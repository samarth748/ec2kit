"""Integration tests for `ec2kit ls` command."""

import json

import boto3
from moto import mock_aws
from typer.testing import CliRunner

from ec2kit.cli import app

runner = CliRunner(env={"COLUMNS": "160"})


@mock_aws
def test_cli_ls_empty() -> None:
    """Verify `ec2kit ls` on an empty region shows informative empty message."""
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert "No EC2 instances found" in result.stdout


@mock_aws
def test_cli_ls_table_output() -> None:
    """Verify `ec2kit ls` renders Rich table with expected columns and data."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    ec2.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.small",
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [{"Key": "Name", "Value": "production-api"}],
            }
        ],
    )

    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert "Discovered EC2 Instances" in result.stdout
    assert "production-api" in result.stdout
    assert "t3.small" in result.stdout
    assert "running" in result.stdout
    assert "us-east-1" in result.stdout


@mock_aws
def test_cli_ls_json_output() -> None:
    """Verify `ec2kit --json ls` outputs machine-readable JSON matching InstanceListResult."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    ec2.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="t2.micro",
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [{"Key": "Name", "Value": "json-test-worker"}],
            }
        ],
    )

    result = runner.invoke(app, ["--json", "ls"])
    assert result.exit_code == 0

    data = json.loads(result.stdout)
    assert "total_count" in data
    assert data["total_count"] == 1
    assert "instances" in data
    inst = data["instances"][0]
    assert inst["name"] == "json-test-worker"
    assert inst["instance_type"] == "t2.micro"
    assert inst["state"] == "running"
    assert inst["region"] == "us-east-1"


@mock_aws
def test_cli_ls_quiet_output() -> None:
    """Verify `ec2kit --quiet ls` outputs single line per instance with id, region, state."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    res = ec2.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.nano",
    )
    inst_id = res["Instances"][0]["InstanceId"]

    result = runner.invoke(app, ["--quiet", "ls"])
    assert result.exit_code == 0
    lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    assert len(lines) == 1
    parts = lines[0].split()
    assert parts[0] == inst_id
    assert parts[1] == "us-east-1"
    assert parts[2] == "running"


@mock_aws
def test_cli_ls_filters() -> None:
    """Verify state, type, and name filters in CLI."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    ec2.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.micro",
        TagSpecifications=[
            {"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": "frontend"}]}
        ],
    )
    ec2.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="m5.xlarge",
        TagSpecifications=[
            {"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": "database"}]}
        ],
    )

    # Filter by name
    res_name = runner.invoke(app, ["--json", "ls", "--name", "frontend"])
    assert res_name.exit_code == 0
    data_name = json.loads(res_name.stdout)
    assert data_name["total_count"] == 1
    assert data_name["instances"][0]["name"] == "frontend"

    # Filter by type
    res_type = runner.invoke(app, ["--json", "ls", "--type", "m5.xlarge"])
    assert res_type.exit_code == 0
    data_type = json.loads(res_type.stdout)
    assert data_type["total_count"] == 1
    assert data_type["instances"][0]["name"] == "database"


@mock_aws
def test_cli_ls_all_regions(monkeypatch) -> None:
    """Verify `ec2kit ls --all-regions` scans multiple regions."""
    monkeypatch.setattr(
        "ec2kit.commands.ls.get_available_regions",
        lambda *_args, **_kwargs: ["us-east-1", "us-west-2"],
    )

    ec2_east = boto3.client("ec2", region_name="us-east-1")
    ec2_east.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.micro",
    )
    ec2_west = boto3.client("ec2", region_name="us-west-2")
    ec2_west.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.micro",
    )

    result = runner.invoke(app, ["--json", "ls", "--all-regions"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["total_count"] == 2
    regions = {inst["region"] for inst in data["instances"]}
    assert "us-east-1" in regions
    assert "us-west-2" in regions
