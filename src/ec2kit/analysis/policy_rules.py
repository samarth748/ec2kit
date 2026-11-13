"""Policy evaluation engine for declarative cloud governance checks (policy.yaml)."""

from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import boto3
import yaml

from ec2kit.aws.ec2 import list_instances_in_region
from ec2kit.config import get_logger
from ec2kit.exceptions import ResourceNotFoundError
from ec2kit.models import PolicyEvaluationResult, PolicyViolation

logger = get_logger()


def load_policy_file(policy_file: Path) -> dict[str, Any]:
    """Parse and validate YAML policy document."""
    if not policy_file.exists():
        raise ResourceNotFoundError(resource_type="Policy file", resource_id=str(policy_file))

    try:
        content = yaml.safe_load(policy_file.read_text(encoding="utf-8"))
        if not isinstance(content, dict):
            raise ValueError("Policy file must contain a top-level YAML mapping/dictionary.")
        return content
    except Exception as exc:
        raise ValueError(f"Failed to parse policy YAML file '{policy_file}': {exc}") from exc


def evaluate_policies(
    session: boto3.Session,
    region: str,
    policy_file: Path,
) -> PolicyEvaluationResult:
    """Evaluate live AWS resources in target region against declared governance policies."""
    policy_data = load_policy_file(policy_file)
    rules = policy_data.get("rules", [])
    violations: list[PolicyViolation] = []

    ec2_client = session.client("ec2", region_name=region)
    scan_res = list_instances_in_region(session, region=region)
    live_instances = [inst for inst in scan_res.instances if inst.state != "terminated"]

    for rule in rules:
        rule_name = rule.get("name", "unnamed-rule")

        # 1. Required tags rule
        req_tags = rule.get("required_tags")
        if req_tags and isinstance(req_tags, list):
            for inst in live_instances:
                missing = [t for t in req_tags if t not in inst.tags or not inst.tags[t]]
                if missing:
                    violations.append(
                        PolicyViolation(
                            rule_name=rule_name,
                            resource_id=inst.instance_id,
                            resource_type="ec2_instance",
                            severity="MEDIUM",
                            message=f"Instance is missing mandatory tags: {', '.join(missing)}",
                            remediation=f"Apply required tags ({', '.join(missing)}) to instance {inst.instance_id}.",
                        )
                    )

        # 2. Allowed instance types rule
        allowed_types = rule.get("allowed_types")
        if allowed_types and isinstance(allowed_types, list):
            for inst in live_instances:
                matched = any(fnmatch(inst.instance_type, pattern) for pattern in allowed_types)
                if not matched:
                    violations.append(
                        PolicyViolation(
                            rule_name=rule_name,
                            resource_id=inst.instance_id,
                            resource_type="ec2_instance",
                            severity="HIGH",
                            message=(
                                f"Instance type '{inst.instance_type}' is not allowed by policy. "
                                f"Allowed patterns: {', '.join(allowed_types)}"
                            ),
                            remediation=f"Resize instance {inst.instance_id} to an approved family: {', '.join(allowed_types)}.",
                        )
                    )

        # 3. Maximum running instances limit
        max_count = rule.get("max_count")
        if max_count is not None and isinstance(max_count, int):
            running_instances = [i for i in live_instances if i.state == "running"]
            if len(running_instances) > max_count:
                violations.append(
                    PolicyViolation(
                        rule_name=rule_name,
                        resource_id=region,
                        resource_type="region_quota",
                        severity="HIGH",
                        message=(
                            f"Region {region} exceeds max running instances limit ({len(running_instances)} > {max_count})."
                        ),
                        remediation="Stop or terminate non-essential instances to stay within organizational limits.",
                    )
                )

        # 4. Mandatory EBS encryption rule
        if rule.get("require_encryption") is True:
            try:
                vols = ec2_client.describe_volumes()
                for vol in vols.get("Volumes", []):
                    if not vol.get("Encrypted", False):
                        vol_id = vol["VolumeId"]
                        violations.append(
                            PolicyViolation(
                                rule_name=rule_name,
                                resource_id=vol_id,
                                resource_type="ebs_volume",
                                severity="HIGH",
                                message="EBS volume is not encrypted at rest.",
                                remediation=f"Enable encryption for volume {vol_id} by migrating to an encrypted snapshot.",
                            )
                        )
            except Exception as exc:
                logger.debug("Failed to evaluate EBS encryption rule: %s", exc)

    return PolicyEvaluationResult(
        policy_file=str(policy_file),
        region=region,
        compliant=len(violations) == 0,
        violations=violations,
        total_violations=len(violations),
    )
