"""Unit tests for Terraform drift detection rules."""

import json
from pathlib import Path

import pytest

from ec2kit.analysis.drift_rules import compare_instances, parse_terraform_state
from ec2kit.exceptions import ResourceNotFoundError
from ec2kit.models import EC2Instance


def test_parse_terraform_state_standard(tmp_path: Path) -> None:
    """Verify parsing standard terraform.tfstate JSON format."""
    state_content = {
        "version": 4,
        "terraform_version": "1.5.0",
        "resources": [
            {
                "type": "aws_instance",
                "name": "web",
                "instances": [
                    {
                        "attributes": {
                            "id": "i-00001111222233334",
                            "instance_type": "t3.micro",
                            "tags": {"Name": "web-frontend"},
                        }
                    }
                ],
            }
        ],
    }
    tfstate = tmp_path / "terraform.tfstate"
    tfstate.write_text(json.dumps(state_content))

    parsed = parse_terraform_state(tfstate)
    assert "aws_instance" in parsed
    assert "i-00001111222233334" in parsed["aws_instance"]
    assert parsed["aws_instance"]["i-00001111222233334"]["instance_type"] == "t3.micro"


def test_parse_terraform_state_show_json(tmp_path: Path) -> None:
    """Verify parsing `terraform show -json` format."""
    show_content = {
        "format_version": "1.0",
        "values": {
            "root_module": {
                "resources": [
                    {
                        "type": "aws_instance",
                        "values": {
                            "id": "i-99998888777766665",
                            "instance_type": "m5.large",
                            "tags": {"Name": "db-server"},
                        },
                    }
                ]
            }
        },
    }
    tf_json = tmp_path / "tf_show.json"
    tf_json.write_text(json.dumps(show_content))

    parsed = parse_terraform_state(tf_json)
    assert "i-99998888777766665" in parsed["aws_instance"]
    assert parsed["aws_instance"]["i-99998888777766665"]["instance_type"] == "m5.large"


def test_parse_terraform_state_not_found(tmp_path: Path) -> None:
    """Verify non-existent file raises ResourceNotFoundError."""
    with pytest.raises(ResourceNotFoundError):
        parse_terraform_state(tmp_path / "non_existent.tfstate")


def test_compare_instances_drifts() -> None:
    """Verify detection of missing, unmanaged, and modified instances."""
    tf_instances = {
        # 1. Missing in live AWS
        "i-missing123": {
            "id": "i-missing123",
            "instance_type": "t3.micro",
            "tags": {"Name": "legacy-worker"},
        },
        # 2. Modified instance (drifted type and tag)
        "i-modified456": {
            "id": "i-modified456",
            "instance_type": "t3.micro",
            "tags": {"Name": "prod-api"},
        },
        # 3. Exactly in sync
        "i-sync789": {
            "id": "i-sync789",
            "instance_type": "c5.xlarge",
            "tags": {"Name": "analytics-job"},
        },
    }

    live_instances = [
        # i-modified456 is actually t3.large and Name is "prod-api-v2"
        EC2Instance(
            instance_id="i-modified456",
            name="prod-api-v2",
            instance_type="t3.large",
            state="running",
            region="us-east-1",
            availability_zone="us-east-1a",
        ),
        # i-sync789 is in sync
        EC2Instance(
            instance_id="i-sync789",
            name="analytics-job",
            instance_type="c5.xlarge",
            state="running",
            region="us-east-1",
            availability_zone="us-east-1a",
        ),
        # 4. Unmanaged instance in AWS
        EC2Instance(
            instance_id="i-unmanaged999",
            name="rogue-bastion",
            instance_type="t2.micro",
            state="running",
            region="us-east-1",
            availability_zone="us-east-1a",
        ),
    ]

    findings = compare_instances(tf_instances=tf_instances, live_instances=live_instances)

    types = {f.drift_type for f in findings}
    assert "MISSING_IN_AWS" in types
    assert "UNMANAGED_IN_TF" in types
    assert "MODIFIED" in types

    missing = [f for f in findings if f.drift_type == "MISSING_IN_AWS"]
    assert len(missing) == 1
    assert missing[0].resource_id == "i-missing123"

    unmanaged = [f for f in findings if f.drift_type == "UNMANAGED_IN_TF"]
    assert len(unmanaged) == 1
    assert unmanaged[0].resource_id == "i-unmanaged999"

    modified = [f for f in findings if f.drift_type == "MODIFIED"]
    assert len(modified) == 2  # instance_type and tags.Name
    mod_attrs = {f.attribute for f in modified}
    assert "instance_type" in mod_attrs
    assert "tags.Name" in mod_attrs
