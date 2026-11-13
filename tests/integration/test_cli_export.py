"""Integration tests for `ec2kit export terraform` CLI command."""

import json
from pathlib import Path

import boto3
from moto import mock_aws
from typer.testing import CliRunner

from ec2kit.cli import app

runner = CliRunner(env={"COLUMNS": "160"})


@mock_aws
def test_cli_export_terraform_files(tmp_path: Path) -> None:
    """Verify `ec2kit export terraform --output-dir` generates HCL files and import instructions."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    vpc = ec2.create_vpc(CidrBlock="10.20.0.0/16")
    vpc_id = vpc["Vpc"]["VpcId"]

    sub = ec2.create_subnet(VpcId=vpc_id, CidrBlock="10.20.1.0/24", AvailabilityZone="us-east-1a")
    subnet_id = sub["Subnet"]["SubnetId"]

    ec2.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.nano",
        SubnetId=subnet_id,
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [{"Key": "Name", "Value": "api-gateway"}],
            }
        ],
    )

    out_dir = tmp_path / "tf_out"
    result = runner.invoke(
        app,
        ["--region", "us-east-1", "export", "terraform", "--output-dir", str(out_dir)],
    )
    assert result.exit_code == 0
    assert "Successfully generated Terraform configuration!" in result.stdout
    assert "main.tf" in result.stdout

    assert (out_dir / "main.tf").exists()
    assert (out_dir / "variables.tf").exists()
    assert (out_dir / "outputs.tf").exists()

    main_hcl = (out_dir / "main.tf").read_text()
    assert 'resource "aws_vpc"' in main_hcl
    assert 'resource "aws_subnet"' in main_hcl
    assert 'resource "aws_instance" "api_gateway"' in main_hcl
    assert "terraform import" in main_hcl


@mock_aws
def test_cli_export_terraform_stdout() -> None:
    """Verify `ec2kit export terraform --stdout` outputs raw main.tf without rich panels."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    ec2.create_vpc(CidrBlock="172.31.0.0/16")

    result = runner.invoke(app, ["--region", "us-east-1", "export", "terraform", "--stdout"])
    assert result.exit_code == 0
    assert 'resource "aws_vpc"' in result.stdout
    assert "terraform {" in result.stdout
    assert "Successfully generated Terraform" not in result.stdout


@mock_aws
def test_cli_export_terraform_json() -> None:
    """Verify `ec2kit --json export terraform` outputs structured JSON."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    ec2.create_vpc(CidrBlock="192.168.0.0/16")

    result = runner.invoke(app, ["--json", "--region", "us-east-1", "export", "terraform"])
    assert result.exit_code == 0

    data = json.loads(result.stdout)
    assert "files" in data
    assert "main.tf" in data["files"]
    assert "import_commands" in data
    assert data["total_resources"] >= 1
