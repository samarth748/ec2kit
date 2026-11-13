"""Integration tests for `ec2kit drift` command."""

import json
from pathlib import Path

import boto3
from moto import mock_aws
from typer.testing import CliRunner

from ec2kit.cli import app

runner = CliRunner(env={"COLUMNS": "160"})


@mock_aws
def test_cli_drift_detected(tmp_path: Path) -> None:
    """Verify `ec2kit drift` identifies missing, unmanaged, and modified resources."""
    ec2 = boto3.client("ec2", region_name="us-east-1")

    # Create one live instance
    res = ec2.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.small",
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [{"Key": "Name", "Value": "live-app"}],
            }
        ],
    )
    live_id = res["Instances"][0]["InstanceId"]

    # State file references a different ID (missing in AWS) and live_id with modified type
    state_content = {
        "version": 4,
        "resources": [
            {
                "type": "aws_instance",
                "name": "live_app",
                "instances": [
                    {
                        "attributes": {
                            "id": live_id,
                            "instance_type": "t3.nano",  # drifted! (live is t3.small)
                            "tags": {"Name": "live-app"},
                        }
                    }
                ],
            },
            {
                "type": "aws_instance",
                "name": "deleted_app",
                "instances": [
                    {
                        "attributes": {
                            "id": "i-nonexistent999",
                            "instance_type": "t3.micro",
                        }
                    }
                ],
            },
        ],
    }
    state_file = tmp_path / "terraform.tfstate"
    state_file.write_text(json.dumps(state_content))

    result = runner.invoke(app, ["--region", "us-east-1", "drift", "--state", str(state_file)])
    assert result.exit_code == 0
    assert "Terraform Infrastructure Drift Detection" in result.stdout
    assert "MISSING_IN_AWS" in result.stdout
    assert "MODIFIED" in result.stdout
    assert "i-nonexistent999" in result.stdout
    assert live_id in result.stdout


@mock_aws
def test_cli_drift_json(tmp_path: Path) -> None:
    """Verify `ec2kit --json drift` outputs valid machine-readable JSON."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    res = ec2.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.micro",
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [{"Key": "Name", "Value": "in-sync-app"}],
            }
        ],
    )
    live_id = res["Instances"][0]["InstanceId"]

    # Perfectly in sync state
    state_content = {
        "version": 4,
        "resources": [
            {
                "type": "aws_instance",
                "name": "in_sync",
                "instances": [
                    {
                        "attributes": {
                            "id": live_id,
                            "instance_type": "t3.micro",
                            "tags": {"Name": "in-sync-app"},
                        }
                    }
                ],
            }
        ],
    }
    state_file = tmp_path / "terraform.tfstate"
    state_file.write_text(json.dumps(state_content))

    result = runner.invoke(
        app,
        ["--json", "--region", "us-east-1", "drift", "--state", str(state_file)],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert "total_drifts" in data
    assert data["total_drifts"] == 0
    assert data["missing_in_aws_count"] == 0
    assert data["unmanaged_in_tf_count"] == 0
    assert data["modified_count"] == 0


@mock_aws
def test_cli_drift_quiet(tmp_path: Path) -> None:
    """Verify `ec2kit --quiet drift` outputs minimal metric counters."""
    state_content = {"version": 4, "resources": []}
    state_file = tmp_path / "empty.tfstate"
    state_file.write_text(json.dumps(state_content))

    result = runner.invoke(
        app,
        ["--quiet", "--region", "us-east-1", "drift", "--state", str(state_file)],
    )
    assert result.exit_code == 0
    assert "drift_count=" in result.stdout
    assert "Terraform Infrastructure Drift Detection" not in result.stdout
