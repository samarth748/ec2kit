"""Unit tests for declarative policy governance checks."""

from pathlib import Path

import boto3
from moto import mock_aws

from ec2kit.analysis.policy_rules import evaluate_policies, load_policy_file


def test_load_policy_file(tmp_path: Path) -> None:
    """Verify loading and parsing of YAML policy document."""
    yaml_content = """
version: "1.0"
rules:
  - name: tag-governance
    required_tags:
      - Environment
      - Owner
"""
    p_file = tmp_path / "policy.yaml"
    p_file.write_text(yaml_content)

    data = load_policy_file(p_file)
    assert data["version"] == "1.0"
    assert len(data["rules"]) == 1
    assert data["rules"][0]["name"] == "tag-governance"


@mock_aws
def test_evaluate_policies_tag_and_type_violations(tmp_path: Path) -> None:
    """Verify violation detection for disallowed instance type and missing tags."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    # Launch instance with non-allowed type c5.2xlarge and missing Owner tag
    ec2.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="c5.2xlarge",
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [{"Key": "Environment", "Value": "staging"}],
            }
        ],
    )

    yaml_content = """
version: "1.0"
rules:
  - name: required-tags
    required_tags:
      - Environment
      - Owner
  - name: allowed-types
    allowed_types:
      - "t3.*"
      - "t4g.*"
"""
    p_file = tmp_path / "policy.yaml"
    p_file.write_text(yaml_content)

    session = boto3.Session(region_name="us-east-1")
    result = evaluate_policies(session=session, region="us-east-1", policy_file=p_file)

    assert result.compliant is False
    assert result.total_violations == 2
    rule_names = {v.rule_name for v in result.violations}
    assert "required-tags" in rule_names
    assert "allowed-types" in rule_names
