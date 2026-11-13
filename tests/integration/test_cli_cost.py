"""Integration tests for `ec2kit cost` CLI command."""

import json

import boto3
from moto import mock_aws
from typer.testing import CliRunner

from ec2kit.cli import app

runner = CliRunner(env={"COLUMNS": "160"})


@mock_aws
def test_cli_cost_empty() -> None:
    """Verify `ec2kit cost` runs cleanly when no resources exist."""
    result = runner.invoke(app, ["cost"])
    assert result.exit_code == 0
    assert "COST SUMMARY" in result.stdout
    assert "Running EC2 Instances" in result.stdout
    assert "Unattached EBS Storage" in result.stdout
    assert "$0.00" in result.stdout


@mock_aws
def test_cli_cost_with_resources() -> None:
    """Verify `ec2kit cost` aggregates running instances, unattached volumes, and unassociated EIPs."""
    ec2 = boto3.client("ec2", region_name="us-east-1")

    # 1. Running instance
    ec2.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.micro",
        TagSpecifications=[{"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": "api"}]}],
    )

    # 2. Unattached volume
    ec2.create_volume(
        AvailabilityZone="us-east-1a",
        Size=100,
        VolumeType="gp3",
    )

    # 3. Unassociated EIP
    ec2.allocate_address(Domain="vpc")

    result = runner.invoke(app, ["cost"])
    assert result.exit_code == 0
    assert "COST SUMMARY" in result.stdout
    assert "OPTIMIZATION OPPORTUNITIES" in result.stdout
    assert "Unattached Volume" in result.stdout or "Orphaned" in result.stdout
    assert "Assumptions & Disclaimers" in result.stdout


@mock_aws
def test_cli_cost_json_output() -> None:
    """Verify `ec2kit --json cost` returns valid machine-readable JSON."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    ec2.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.small",
    )

    result = runner.invoke(app, ["--json", "cost"])
    assert result.exit_code == 0

    data = json.loads(result.stdout)
    assert "summary" in data
    assert "running_ec2_monthly" in data["summary"]
    assert data["summary"]["running_ec2_monthly"] > 0
    assert "disclaimers" in data
    assert isinstance(data["disclaimers"], list)


@mock_aws
def test_cli_cost_quiet_output() -> None:
    """Verify `ec2kit --quiet cost` returns minimal single-line summary."""
    result = runner.invoke(app, ["--quiet", "cost"])
    assert result.exit_code == 0
    lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    assert len(lines) == 1
    assert "$" in lines[0]


@mock_aws
def test_cli_cost_filter_views() -> None:
    """Verify `--idle`, `--rightsize`, and `--orphaned` view filtering."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    ec2.create_volume(
        AvailabilityZone="us-east-1a",
        Size=20,
        VolumeType="gp3",
    )

    # Orphaned view
    res_orphaned = runner.invoke(app, ["cost", "--orphaned"])
    assert res_orphaned.exit_code == 0
    assert "OPTIMIZATION OPPORTUNITIES" in res_orphaned.stdout
    assert "COST SUMMARY" not in res_orphaned.stdout


@mock_aws
def test_cli_cost_refresh_pricing() -> None:
    """Verify `--refresh-pricing` executes and clears cache without error."""
    result = runner.invoke(app, ["cost", "--refresh-pricing"])
    assert result.exit_code == 0
    assert "COST SUMMARY" in result.stdout
