"""Unit tests for static security scanning rules and remediation suggestions."""

import boto3
from moto import mock_aws

from ec2kit.analysis.security_rules import (
    check_ebs_volumes,
    check_ec2_instances,
    check_security_groups,
    run_security_scan,
)


@mock_aws
def test_check_security_groups_vulnerabilities() -> None:
    """Verify detection of SSH, RDP, and unrestricted ingress rules."""
    session = boto3.Session(region_name="us-east-1")
    ec2 = session.client("ec2", region_name="us-east-1")

    # 1. Group with SSH open to 0.0.0.0/0
    sg_ssh = ec2.create_security_group(GroupName="ssh-open-sg", Description="SSH open group")
    sg_ssh_id = sg_ssh["GroupId"]
    ec2.authorize_security_group_ingress(
        GroupId=sg_ssh_id,
        IpProtocol="tcp",
        FromPort=22,
        ToPort=22,
        CidrIp="0.0.0.0/0",
    )

    # 2. Group with RDP open to 0.0.0.0/0
    sg_rdp = ec2.create_security_group(GroupName="rdp-open-sg", Description="RDP open group")
    sg_rdp_id = sg_rdp["GroupId"]
    ec2.authorize_security_group_ingress(
        GroupId=sg_rdp_id,
        IpProtocol="tcp",
        FromPort=3389,
        ToPort=3389,
        CidrIp="0.0.0.0/0",
    )

    # 3. Group with All Traffic open (-1)
    sg_all = ec2.create_security_group(GroupName="all-traffic-sg", Description="All traffic group")
    sg_all_id = sg_all["GroupId"]
    ec2.authorize_security_group_ingress(
        GroupId=sg_all_id,
        IpProtocol="-1",
        CidrIp="0.0.0.0/0",
    )

    findings = check_security_groups(ec2, region="us-east-1")
    f_ids = {f.finding_id for f in findings}

    assert f"SG-SSH-EXPOSED-IPV4-{sg_ssh_id}" in f_ids
    assert f"SG-RDP-EXPOSED-{sg_rdp_id}" in f_ids
    assert f"SG-UNRESTRICTED-ALL-{sg_all_id}" in f_ids

    rdp_finding = next(f for f in findings if f.resource_id == sg_rdp_id)
    assert rdp_finding.severity == "CRITICAL"
    assert "revoke-security-group-ingress" in rdp_finding.suggested_command


@mock_aws
def test_check_ebs_unencrypted_volumes() -> None:
    """Verify unencrypted EBS volume detection."""
    session = boto3.Session(region_name="us-east-1")
    ec2 = session.client("ec2", region_name="us-east-1")

    # Create unencrypted volume
    vol = ec2.create_volume(
        AvailabilityZone="us-east-1a",
        Size=20,
        Encrypted=False,
    )
    vol_id = vol["VolumeId"]

    findings = check_ebs_volumes(ec2, region="us-east-1")
    f_ids = {f.finding_id for f in findings}
    assert f"EBS-UNENCRYPTED-{vol_id}" in f_ids
    vol_finding = next(f for f in findings if f.resource_id == vol_id)
    assert vol_finding.severity == "HIGH"


@mock_aws
def test_check_ec2_imds_and_tags() -> None:
    """Verify detection of IMDSv1 allowed instances and missing governance tags."""
    session = boto3.Session(region_name="us-east-1")
    ec2 = session.client("ec2", region_name="us-east-1")

    # Instance launched without enforcing IMDSv2
    res = ec2.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.micro",
        MetadataOptions={"HttpTokens": "optional"},
    )
    inst_id = res["Instances"][0]["InstanceId"]

    findings = check_ec2_instances(ec2, region="us-east-1")
    f_ids = {f.finding_id for f in findings}

    assert f"EC2-IMDSV1-ENABLED-{inst_id}" in f_ids
    assert f"EC2-TAGS-MISSING-{inst_id}" in f_ids

    imds_finding = next(f for f in findings if f.finding_id == f"EC2-IMDSV1-ENABLED-{inst_id}")
    assert imds_finding.severity == "HIGH"
    assert "modify-instance-metadata-options" in imds_finding.suggested_command


@mock_aws
def test_run_security_scan_filtering() -> None:
    """Verify security scan severity threshold filtering and sorting."""
    session = boto3.Session(region_name="us-east-1")
    ec2 = session.client("ec2", region_name="us-east-1")

    # Create RDP (CRITICAL) and unencrypted volume (HIGH)
    sg = ec2.create_security_group(GroupName="rdp-sg", Description="RDP")
    ec2.authorize_security_group_ingress(
        GroupId=sg["GroupId"],
        IpProtocol="tcp",
        FromPort=3389,
        ToPort=3389,
        CidrIp="0.0.0.0/0",
    )
    ec2.create_volume(AvailabilityZone="us-east-1a", Size=10, Encrypted=False)

    # Scan with CRITICAL threshold
    crit_scan = run_security_scan(session, regions=["us-east-1"], min_severity="CRITICAL")
    assert crit_scan.critical_count == 1
    assert len(crit_scan.findings) == 1
    assert crit_scan.findings[0].severity == "CRITICAL"
