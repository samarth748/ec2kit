"""Terraform state drift detection engine comparing live AWS state with Terraform state files."""

import json
from pathlib import Path
from typing import Any

import boto3

from ec2kit.aws.ec2 import list_instances_in_region
from ec2kit.config import get_logger
from ec2kit.exceptions import ResourceNotFoundError
from ec2kit.models import DriftFinding, DriftReport, EC2Instance

logger = get_logger()


def parse_terraform_state(state_file: Path) -> dict[str, dict[str, Any]]:
    """Parse Terraform state JSON (terraform.tfstate or terraform show -json).

    Returns:
        Mapping of resource_type -> mapping of resource_id -> attributes dict.
    """
    if not state_file.exists():
        raise ResourceNotFoundError(
            resource_type="File",
            resource_id=str(state_file),
        )

    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse Terraform state file as JSON: {exc}") from exc

    resources: dict[str, dict[str, Any]] = {
        "aws_instance": {},
        "aws_security_group": {},
        "aws_vpc": {},
    }

    # Case 1: Standard terraform.tfstate (schema version 4)
    if "resources" in data and isinstance(data["resources"], list):
        for res in data["resources"]:
            r_type = res.get("type")
            if r_type in resources:
                for inst in res.get("instances", []):
                    attrs = inst.get("attributes", {})
                    r_id = attrs.get("id")
                    if r_id:
                        resources[r_type][r_id] = attrs

    # Case 2: `terraform show -json` format
    elif "values" in data and "root_module" in data["values"]:
        root = data["values"]["root_module"]

        def extract_module_resources(mod: dict[str, Any]) -> None:
            for res in mod.get("resources", []):
                r_type = res.get("type")
                if r_type in resources:
                    attrs = res.get("values", {})
                    r_id = attrs.get("id")
                    if r_id:
                        resources[r_type][r_id] = attrs
            for child in mod.get("child_modules", []):
                extract_module_resources(child)

        extract_module_resources(root)

    return resources


def compare_instances(
    tf_instances: dict[str, dict[str, Any]],
    live_instances: list[EC2Instance],
) -> list[DriftFinding]:
    """Compare Terraform state instances against live discovered AWS instances."""
    findings: list[DriftFinding] = []
    live_map = {inst.instance_id: inst for inst in live_instances if inst.state != "terminated"}

    # 1. Check for instances in Terraform state but missing in live AWS
    for tf_id, tf_attrs in tf_instances.items():
        if tf_id not in live_map:
            name_tag = (
                (tf_attrs.get("tags") or {}).get("Name")
                if isinstance(tf_attrs.get("tags"), dict)
                else None
            )
            findings.append(
                DriftFinding(
                    resource_type="aws_instance",
                    resource_id=tf_id,
                    resource_name=name_tag,
                    drift_type="MISSING_IN_AWS",
                    details=f"Instance {tf_id} is defined in Terraform state but does not exist (or is terminated) in AWS.",
                )
            )
        else:
            # 2. Check for attribute modifications
            live_inst = live_map[tf_id]
            # Instance type drift
            tf_type = tf_attrs.get("instance_type")
            if tf_type and live_inst.instance_type and tf_type != live_inst.instance_type:
                findings.append(
                    DriftFinding(
                        resource_type="aws_instance",
                        resource_id=tf_id,
                        resource_name=live_inst.name,
                        drift_type="MODIFIED",
                        attribute="instance_type",
                        expected_value=tf_type,
                        actual_value=live_inst.instance_type,
                        details=(
                            f"Instance type drifted from '{tf_type}' (Terraform) "
                            f"to '{live_inst.instance_type}' (AWS live)."
                        ),
                    )
                )

            # Name tag drift
            tf_tags = tf_attrs.get("tags") or {}
            tf_name = tf_tags.get("Name") if isinstance(tf_tags, dict) else None
            if tf_name and live_inst.name and tf_name != live_inst.name:
                findings.append(
                    DriftFinding(
                        resource_type="aws_instance",
                        resource_id=tf_id,
                        resource_name=live_inst.name,
                        drift_type="MODIFIED",
                        attribute="tags.Name",
                        expected_value=tf_name,
                        actual_value=live_inst.name,
                        details=f"Name tag drifted from '{tf_name}' (Terraform) to '{live_inst.name}' (AWS live).",
                    )
                )

    # 3. Check for unmanaged live AWS instances not tracked in Terraform
    for live_id, live_inst in live_map.items():
        if live_id not in tf_instances:
            findings.append(
                DriftFinding(
                    resource_type="aws_instance",
                    resource_id=live_id,
                    resource_name=live_inst.name,
                    drift_type="UNMANAGED_IN_TF",
                    details=(
                        f"Live instance {live_id} ({live_inst.name or 'unnamed'}, {live_inst.instance_type}) "
                        f"is running in AWS but is unmanaged by Terraform."
                    ),
                )
            )

    return findings


def run_drift_analysis(
    state_file: Path,
    session: boto3.Session,
    region: str,
) -> DriftReport:
    """Execute complete drift detection between Terraform state and live AWS cloud."""
    parsed_resources = parse_terraform_state(state_file)
    tf_instances = parsed_resources.get("aws_instance", {})

    # Discover live instances in target region
    scan_res = list_instances_in_region(session, region=region)
    live_instances = scan_res.instances

    findings = compare_instances(tf_instances=tf_instances, live_instances=live_instances)

    missing_cnt = sum(1 for f in findings if f.drift_type == "MISSING_IN_AWS")
    unmanaged_cnt = sum(1 for f in findings if f.drift_type == "UNMANAGED_IN_TF")
    modified_cnt = sum(1 for f in findings if f.drift_type == "MODIFIED")

    return DriftReport(
        region=region,
        state_file=str(state_file),
        findings=findings,
        missing_in_aws_count=missing_cnt,
        unmanaged_in_tf_count=unmanaged_cnt,
        modified_count=modified_cnt,
        total_drifts=len(findings),
    )
