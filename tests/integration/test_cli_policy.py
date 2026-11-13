"""Integration tests for `ec2kit policy check` command."""

import json
from pathlib import Path

import boto3
from moto import mock_aws
from typer.testing import CliRunner

from ec2kit.cli import app

runner = CliRunner(env={"COLUMNS": "160"})


@mock_aws
def test_cli_policy_check_compliant(tmp_path: Path) -> None:
    """Verify compliant infrastructure exits with code 0."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    ec2.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.micro",
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [
                    {"Key": "Environment", "Value": "prod"},
                    {"Key": "Owner", "Value": "platform-team"},
                ],
            }
        ],
    )

    policy_content = """
version: "1.0"
rules:
  - name: tags
    required_tags:
      - Environment
      - Owner
  - name: types
    allowed_types:
      - "t3.*"
"""
    p_file = tmp_path / "policy.yaml"
    p_file.write_text(policy_content)

    result = runner.invoke(
        app, ["--region", "us-east-1", "policy", "check", "--policy", str(p_file)]
    )
    assert result.exit_code == 0
    assert "100% Compliant" in result.stdout


@mock_aws
def test_cli_policy_check_non_compliant_exits_1(tmp_path: Path) -> None:
    """Verify non-compliant infrastructure exits with code 1 for CI gates."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    # Missing tags
    ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1, InstanceType="t3.micro")

    policy_content = """
version: "1.0"
rules:
  - name: required-tags
    required_tags:
      - MandatoryTag
"""
    p_file = tmp_path / "policy.yaml"
    p_file.write_text(policy_content)

    result = runner.invoke(
        app, ["--region", "us-east-1", "policy", "check", "--policy", str(p_file)]
    )
    assert result.exit_code == 1
    assert "NON-COMPLIANT" in result.stdout
    assert "MandatoryTag" in result.stdout


@mock_aws
def test_cli_policy_check_json(tmp_path: Path) -> None:
    """Verify --json emits structured PolicyEvaluationResult."""
    policy_content = "rules: []"
    p_file = tmp_path / "policy.yaml"
    p_file.write_text(policy_content)

    result = runner.invoke(
        app, ["--json", "--region", "us-east-1", "policy", "check", "--policy", str(p_file)]
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["compliant"] is True
    assert "violations" in data
