"""Integration tests for `ec2kit security` command."""

import json

import boto3
from moto import mock_aws
from typer.testing import CliRunner

from ec2kit.cli import app

runner = CliRunner(env={"COLUMNS": "160"})


@mock_aws
def test_cli_security_table_output() -> None:
    """Verify `ec2kit security` prints security findings in tabular format."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    sg = ec2.create_security_group(
        GroupName="open-ssh-sg",
        Description="SG with open SSH",
    )
    sg_id = sg["GroupId"]
    ec2.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 22,
                "ToPort": 22,
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            }
        ],
    )

    result = runner.invoke(app, ["--region", "us-east-1", "security"])
    assert result.exit_code == 0
    assert "AWS Security Audit Summary" in result.stdout
    assert sg_id in result.stdout
    assert "HIGH" in result.stdout
    assert "0.0.0.0/0" in result.stdout


@mock_aws
def test_cli_security_json_output() -> None:
    """Verify `ec2kit --json security` prints valid machine-readable JSON."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    ec2.create_volume(
        AvailabilityZone="us-east-1a",
        Size=20,
        Encrypted=False,
    )

    result = runner.invoke(app, ["--json", "--region", "us-east-1", "security"])
    assert result.exit_code == 0

    data = json.loads(result.stdout)
    assert "findings" in data
    assert "high_count" in data
    assert data["total_findings"] >= 1
    unenc = [f for f in data["findings"] if "EBS-UNENCRYPTED" in f["finding_id"]]
    assert len(unenc) >= 1
    assert unenc[0]["severity"] == "HIGH"


@mock_aws
def test_cli_security_filter_severity() -> None:
    """Verify `ec2kit security --severity` filters findings appropriately."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    # Creates unencrypted volume (HIGH)
    ec2.create_volume(
        AvailabilityZone="us-east-1a",
        Size=10,
        Encrypted=False,
    )

    # Filter by CRITICAL should not show the HIGH finding
    result = runner.invoke(
        app,
        ["--json", "--region", "us-east-1", "security", "--severity", "CRITICAL"],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    high_findings = [f for f in data["findings"] if f["severity"] == "HIGH"]
    assert len(high_findings) == 0


@mock_aws
def test_cli_security_quiet() -> None:
    """Verify `ec2kit --quiet security` suppresses banner and output table."""
    result = runner.invoke(app, ["--quiet", "--region", "us-east-1", "security"])
    assert result.exit_code == 0
    assert "AWS Security Audit Summary" not in result.stdout
