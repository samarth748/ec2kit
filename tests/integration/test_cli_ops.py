"""Integration tests for safe lifecycle operations (start, stop, reboot, terminate)."""

import json

import boto3
from moto import mock_aws
from typer.testing import CliRunner

from ec2kit.cli import app

runner = CliRunner(env={"COLUMNS": "160"})


@mock_aws
def test_cli_ops_dry_run() -> None:
    """Verify --dry-run calls AWS DryRun and reports success without mutating instance."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    res = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1, InstanceType="t3.micro")
    inst_id = res["Instances"][0]["InstanceId"]

    result = runner.invoke(app, ["--region", "us-east-1", "stop", inst_id, "--dry-run"])
    assert result.exit_code == 0
    assert "DryRun validation successful" in result.stdout

    # Verify instance was NOT stopped
    desc = ec2.describe_instances(InstanceIds=[inst_id])
    assert desc["Reservations"][0]["Instances"][0]["State"]["Name"] == "running"


@mock_aws
def test_cli_ops_stop_and_start_with_yes() -> None:
    """Verify stop and start with --yes transitions instance states."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    res = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1, InstanceType="t3.micro")
    inst_id = res["Instances"][0]["InstanceId"]

    # 1. Stop instance
    stop_res = runner.invoke(app, ["--region", "us-east-1", "stop", inst_id, "--yes"])
    assert stop_res.exit_code == 0
    assert "Successfully initiated STOP" in stop_res.stdout

    desc = ec2.describe_instances(InstanceIds=[inst_id])
    assert desc["Reservations"][0]["Instances"][0]["State"]["Name"] in ("stopping", "stopped")

    # 2. Start instance
    start_res = runner.invoke(app, ["--region", "us-east-1", "start", inst_id, "--yes"])
    assert start_res.exit_code == 0
    assert "Successfully initiated START" in start_res.stdout


@mock_aws
def test_cli_ops_json_output() -> None:
    """Verify --json output formats OperationResult correctly."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    res = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1, InstanceType="t3.micro")
    inst_id = res["Instances"][0]["InstanceId"]

    result = runner.invoke(app, ["--json", "--region", "us-east-1", "reboot", inst_id, "--yes"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["instance_id"] == inst_id
    assert data["action"] == "reboot"
    assert data["success"] is True
    assert len(data["consequences"]) >= 1


@mock_aws
def test_cli_ops_terminate_with_yes() -> None:
    """Verify terminate instance transitions to shutting-down."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    res = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1, InstanceType="t3.micro")
    inst_id = res["Instances"][0]["InstanceId"]

    result = runner.invoke(app, ["--region", "us-east-1", "terminate", inst_id, "--yes"])
    assert result.exit_code == 0
    assert "Successfully initiated TERMINATE" in result.stdout

    desc = ec2.describe_instances(InstanceIds=[inst_id])
    assert desc["Reservations"][0]["Instances"][0]["State"]["Name"] in (
        "shutting-down",
        "terminated",
    )


@mock_aws
def test_cli_ops_non_existent_instance() -> None:
    """Verify operation on invalid instance returns ResourceNotFoundError exit code."""
    result = runner.invoke(app, ["--region", "us-east-1", "stop", "i-00000000000000000", "--yes"])
    assert result.exit_code == 1
    assert "not found" in result.stdout.lower() or "not found" in result.stderr.lower()
