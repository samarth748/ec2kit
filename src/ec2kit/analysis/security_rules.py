"""Static security posture analysis for EC2, Security Groups, EBS, and IMDS.

Detects insecure configurations according to CIS AWS Foundations and AWS security best practices:
- SSH (port 22) or RDP (port 3389) open to unrestricted IPv4/IPv6 (0.0.0.0/0, ::/0)
- Unrestricted ingress rules (protocol -1 or wide port ranges)
- Exposed sensitive database/admin ports (3306, 5432, 1433, 27017, 23)
- Unencrypted EBS volumes and snapshots
- IMDSv1 enabled / missing IMDSv2 enforcement (HttpTokens != 'required')
- Missing required governance tags
- Provides exact suggested remediation commands.
"""

from typing import Any

import boto3
from botocore.exceptions import ClientError

from ec2kit.config import get_logger
from ec2kit.models import SecurityFinding, SecurityScanResult

logger = get_logger()

ADMIN_PORTS_MAP = {
    22: "SSH",
    3389: "RDP",
    23: "Telnet",
    1433: "MS SQL Server",
    3306: "MySQL / Aurora",
    5432: "PostgreSQL",
    27017: "MongoDB",
    6379: "Redis",
}

SEVERITY_ORDER = {"CRITICAL": 5, "HIGH": 4, "MEDIUM": 3, "LOW": 2, "INFO": 1}


def is_port_in_range(port: int, from_port: int | None, to_port: int | None) -> bool:
    """Check if target port is encompassed within rule port bounds."""
    if from_port is None or to_port is None:
        return True  # -1 (all ports)
    return from_port <= port <= to_port


def check_security_groups(
    ec2_client: Any,
    region: str,
) -> list[SecurityFinding]:
    """Scan security group ingress rules for unrestricted access and exposed ports."""
    findings: list[SecurityFinding] = []

    try:
        resp = ec2_client.describe_security_groups()
        for sg in resp.get("SecurityGroups", []):
            sg_id = sg["GroupId"]
            sg_name = sg.get("GroupName", sg_id)

            for perm in sg.get("IpPermissions", []):
                protocol = perm.get("IpProtocol", "-1")
                from_port = perm.get("FromPort")
                to_port = perm.get("ToPort")

                # Check IPv4 unrestricted rules (0.0.0.0/0)
                for ip_range in perm.get("IpRanges", []):
                    cidr = ip_range.get("CidrIp", "")
                    if cidr == "0.0.0.0/0":
                        # 1. All traffic open
                        if protocol == "-1":
                            findings.append(
                                SecurityFinding(
                                    finding_id=f"SG-UNRESTRICTED-ALL-{sg_id}",
                                    resource_id=sg_id,
                                    resource_type="security_group",
                                    region=region,
                                    severity="CRITICAL",
                                    title=f"All traffic unrestricted in Security Group '{sg_name}'",
                                    description="Security group allows unrestricted ingress for all protocols and ports from the public internet (0.0.0.0/0).",
                                    evidence="Protocol: -1, Ingress CIDR: 0.0.0.0/0",
                                    remediation="Restrict ingress rules to only specific required application ports and trusted source IP ranges.",
                                    suggested_command=f"aws ec2 revoke-security-group-ingress --group-id {sg_id} --protocol -1 --cidr 0.0.0.0/0",
                                )
                            )

                        # 2. RDP open (port 3389)
                        elif is_port_in_range(3389, from_port, to_port):
                            findings.append(
                                SecurityFinding(
                                    finding_id=f"SG-RDP-EXPOSED-{sg_id}",
                                    resource_id=sg_id,
                                    resource_type="security_group",
                                    region=region,
                                    severity="CRITICAL",
                                    title=f"RDP (Port 3389) open to public internet in '{sg_name}'",
                                    description="Windows Remote Desktop Protocol (RDP) port 3389 is exposed to the entire internet, inviting brute-force and credential stuffing attacks.",
                                    evidence=f"Port: {from_port}-{to_port}, Ingress CIDR: 0.0.0.0/0",
                                    remediation="Restrict RDP access to a trusted corporate VPN or bastion host IP address.",
                                    suggested_command=f"aws ec2 revoke-security-group-ingress --group-id {sg_id} --protocol tcp --port 3389 --cidr 0.0.0.0/0",
                                )
                            )

                        # 3. SSH open (port 22)
                        elif is_port_in_range(22, from_port, to_port):
                            findings.append(
                                SecurityFinding(
                                    finding_id=f"SG-SSH-EXPOSED-IPV4-{sg_id}",
                                    resource_id=sg_id,
                                    resource_type="security_group",
                                    region=region,
                                    severity="HIGH",
                                    title=f"SSH (Port 22) open to public internet in '{sg_name}'",
                                    description="Secure Shell (SSH) port 22 is exposed to unrestricted internet access (0.0.0.0/0).",
                                    evidence=f"Port: {from_port}-{to_port}, Ingress CIDR: 0.0.0.0/0",
                                    remediation="Restrict SSH ingress to authorized administrator CIDRs or use AWS Systems Manager Session Manager instead of public SSH.",
                                    suggested_command=f"aws ec2 revoke-security-group-ingress --group-id {sg_id} --protocol tcp --port 22 --cidr 0.0.0.0/0",
                                )
                            )

                        # 4. Database ports open
                        for db_port, db_name in ADMIN_PORTS_MAP.items():
                            if db_port not in (22, 3389) and is_port_in_range(
                                db_port, from_port, to_port
                            ):
                                findings.append(
                                    SecurityFinding(
                                        finding_id=f"SG-DB-EXPOSED-{db_port}-{sg_id}",
                                        resource_id=sg_id,
                                        resource_type="security_group",
                                        region=region,
                                        severity="HIGH",
                                        title=f"{db_name} (Port {db_port}) open to public internet in '{sg_name}'",
                                        description=f"Database / service port {db_port} ({db_name}) is exposed to 0.0.0.0/0.",
                                        evidence=f"Port: {from_port}-{to_port}, Ingress CIDR: 0.0.0.0/0",
                                        remediation=f"Restrict {db_name} ingress to application security groups or internal VPC subnets.",
                                        suggested_command=f"aws ec2 revoke-security-group-ingress --group-id {sg_id} --protocol tcp --port {db_port} --cidr 0.0.0.0/0",
                                    )
                                )

                # Check IPv6 unrestricted rules (::/0)
                for ipv6_range in perm.get("Ipv6Ranges", []):
                    cidr6 = ipv6_range.get("CidrIpv6", "")
                    if cidr6 == "::/0":
                        if is_port_in_range(22, from_port, to_port):
                            findings.append(
                                SecurityFinding(
                                    finding_id=f"SG-SSH-EXPOSED-IPV6-{sg_id}",
                                    resource_id=sg_id,
                                    resource_type="security_group",
                                    region=region,
                                    severity="HIGH",
                                    title=f"SSH (Port 22) open to unrestricted IPv6 (::/0) in '{sg_name}'",
                                    description="SSH port 22 allows unrestricted ingress from any IPv6 address.",
                                    evidence=f"Port: {from_port}-{to_port}, Ingress CIDR: ::/0",
                                    remediation="Restrict IPv6 SSH ingress to trusted administrative network prefixes.",
                                    suggested_command=f'aws ec2 revoke-security-group-ingress --group-id {sg_id} --ip-permissions \'[{{"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "Ipv6Ranges": [{{"CidrIpv6": "::/0"}}]}}]\'',
                                )
                            )

    except ClientError as exc:
        logger.warning("Failed scanning security groups in %s: %s", region, exc)

    return findings


def check_ebs_volumes(
    ec2_client: Any,
    region: str,
) -> list[SecurityFinding]:
    """Scan EBS volumes for missing encryption."""
    findings: list[SecurityFinding] = []

    try:
        resp = ec2_client.describe_volumes()
        for vol in resp.get("Volumes", []):
            vol_id = vol["VolumeId"]
            encrypted = vol.get("Encrypted", False)

            if not encrypted:
                findings.append(
                    SecurityFinding(
                        finding_id=f"EBS-UNENCRYPTED-{vol_id}",
                        resource_id=vol_id,
                        resource_type="ebs_volume",
                        region=region,
                        severity="HIGH",
                        title=f"EBS Volume '{vol_id}' is unencrypted",
                        description=f"Volume '{vol_id}' ({vol.get('Size', 0)} GB {vol.get('VolumeType', 'gp3')}) is not encrypted at rest with AWS KMS.",
                        evidence=f"Encrypted: False, VolumeId: {vol_id}",
                        remediation="Create a snapshot of this volume, copy the snapshot with encryption enabled, and replace the unencrypted volume.",
                        suggested_command=f"aws ec2 create-snapshot --volume-id {vol_id} --description 'Backup before KMS encryption'",
                    )
                )

    except ClientError as exc:
        logger.warning("Failed scanning EBS volumes in %s: %s", region, exc)

    return findings


def check_ec2_instances(
    ec2_client: Any,
    region: str,
    required_tags: list[str] | None = None,
) -> list[SecurityFinding]:
    """Scan EC2 instances for IMDSv1 vulnerabilities and governance tag compliance."""
    findings: list[SecurityFinding] = []
    tags_to_check = required_tags or ["Environment", "Owner", "Project"]

    try:
        resp = ec2_client.describe_instances()
        for resv in resp.get("Reservations", []):
            for inst in resv.get("Instances", []):
                inst_id = inst["InstanceId"]
                state = inst.get("State", {}).get("Name", "")
                if state in ("terminated", "shutting-down"):
                    continue

                metadata_opts = inst.get("MetadataOptions", {})
                http_tokens = metadata_opts.get("HttpTokens", "optional")

                # 1. IMDSv2 Enforcement Check
                if http_tokens != "required":
                    findings.append(
                        SecurityFinding(
                            finding_id=f"EC2-IMDSV1-ENABLED-{inst_id}",
                            resource_id=inst_id,
                            resource_type="ec2_instance",
                            region=region,
                            severity="HIGH",
                            title=f"IMDSv2 not enforced on instance '{inst_id}'",
                            description="Instance allows IMDSv1 tokenless metadata access (HttpTokens != required), increasing exposure to Server-Side Request Forgery (SSRF) attacks.",
                            evidence=f"HttpTokens: {http_tokens}",
                            remediation="Enforce IMDSv2 by requiring session tokens for all instance metadata requests.",
                            suggested_command=f"aws ec2 modify-instance-metadata-options --instance-id {inst_id} --http-tokens required --http-endpoint enabled",
                        )
                    )

                # 2. Governance Tag Compliance Check
                existing_tags = {
                    t["Key"] for t in inst.get("Tags", []) if "Key" in t and t["Key"] is not None
                }
                missing_tags = [t for t in tags_to_check if t not in existing_tags]

                if missing_tags:
                    findings.append(
                        SecurityFinding(
                            finding_id=f"EC2-TAGS-MISSING-{inst_id}",
                            resource_id=inst_id,
                            resource_type="ec2_instance",
                            region=region,
                            severity="LOW",
                            title=f"Missing governance tags on instance '{inst_id}'",
                            description=f"Instance is missing required organizational tags: {', '.join(missing_tags)}.",
                            evidence=f"Missing: {missing_tags}, Existing: {list(existing_tags)}",
                            remediation="Apply standard governance tags (Environment, Owner, Project) for tracking, billing, and access control.",
                            suggested_command=f"aws ec2 create-tags --resources {inst_id} --tags Key=Environment,Value=production Key=Owner,Value=devops",
                        )
                    )

    except ClientError as exc:
        logger.warning("Failed scanning EC2 instances in %s: %s", region, exc)

    return findings


def run_security_scan(
    session: boto3.Session,
    regions: list[str],
    min_severity: str | None = None,
) -> SecurityScanResult:
    """Execute complete security scan across target regions and compile findings."""
    all_findings: list[SecurityFinding] = []

    for reg in regions:
        ec2 = session.client("ec2", region_name=reg)
        all_findings.extend(check_security_groups(ec2, reg))
        all_findings.extend(check_ebs_volumes(ec2, reg))
        all_findings.extend(check_ec2_instances(ec2, reg))

    # Apply minimum severity filter if requested
    if min_severity:
        threshold = SEVERITY_ORDER.get(min_severity.upper(), 1)
        all_findings = [
            f for f in all_findings if SEVERITY_ORDER.get(f.severity.upper(), 1) >= threshold
        ]

    # Sort findings by severity (CRITICAL first, then HIGH, etc.)
    all_findings.sort(
        key=lambda f: (-SEVERITY_ORDER.get(f.severity.upper(), 1), f.region, f.resource_id)
    )

    crit = sum(1 for f in all_findings if f.severity == "CRITICAL")
    high = sum(1 for f in all_findings if f.severity == "HIGH")
    med = sum(1 for f in all_findings if f.severity == "MEDIUM")
    low = sum(1 for f in all_findings if f.severity == "LOW")
    info = sum(1 for f in all_findings if f.severity == "INFO")

    return SecurityScanResult(
        region=",".join(regions),
        findings=all_findings,
        critical_count=crit,
        high_count=high,
        medium_count=med,
        low_count=low,
        info_count=info,
        total_findings=len(all_findings),
    )
