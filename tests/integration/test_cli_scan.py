"""Integration tests for `ec2kit scan` command."""

import json
from pathlib import Path

import boto3
from moto import mock_aws
from typer.testing import CliRunner

from ec2kit.cli import app

runner = CliRunner(env={"COLUMNS": "160"})


@mock_aws
def test_cli_scan_with_vpc_and_export(tmp_path: Path) -> None:
    """Verify `ec2kit scan` discovers network topology and exports diagram to file."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    vpc = ec2.create_vpc(CidrBlock="172.16.0.0/16")
    vpc_id = vpc["Vpc"]["VpcId"]

    export_file = tmp_path / "output_arch.mmd"

    result = runner.invoke(app, ["scan", "--output", str(export_file)])
    assert result.exit_code == 0
    assert "VPC Architecture Discovery" in result.stdout
    assert "Discovered" in result.stdout
    assert "flowchart TD" in result.stdout
    assert export_file.exists()
    content = export_file.read_text()
    assert "flowchart TD" in content
    assert vpc_id in content


@mock_aws
def test_cli_scan_json() -> None:
    """Verify `ec2kit --json scan` emits valid machine-readable JSON matching ScanResult."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    vpc = ec2.create_vpc(CidrBlock="10.100.0.0/16")
    vpc_id = vpc["Vpc"]["VpcId"]

    result = runner.invoke(app, ["--json", "scan", "--vpc", vpc_id])
    assert result.exit_code == 0

    data = json.loads(result.stdout)
    assert "topologies" in data
    assert data["total_vpcs"] == 1
    top = data["topologies"][0]
    assert top["vpc"]["vpc_id"] == vpc_id
    assert "mermaid_diagram" in data
    assert "flowchart TD" in data["mermaid_diagram"]


@mock_aws
def test_cli_scan_quiet() -> None:
    """Verify `ec2kit --quiet scan` outputs minimal single line per VPC."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    vpc = ec2.create_vpc(CidrBlock="10.200.0.0/16")
    vpc_id = vpc["Vpc"]["VpcId"]

    result = runner.invoke(app, ["--quiet", "scan"])
    assert result.exit_code == 0
    assert vpc_id in result.stdout
    assert "10.200.0.0/16" in result.stdout
