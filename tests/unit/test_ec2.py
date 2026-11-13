"""Unit tests for AWS EC2 instance parsing and multi-region discovery."""

from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError
from moto import mock_aws

from ec2kit.aws.ec2 import (
    list_instances_in_region,
    list_instances_multiregion,
    parse_instance,
)
from ec2kit.models import EC2Instance


def test_parse_instance() -> None:
    """Verify parsing raw EC2 describe_instances dictionaries into EC2Instance."""
    raw = {
        "InstanceId": "i-0123456789abcdef0",
        "InstanceType": "t3.medium",
        "State": {"Name": "running"},
        "Placement": {"AvailabilityZone": "us-east-1a"},
        "PublicIpAddress": "54.210.1.2",
        "PrivateIpAddress": "10.0.1.5",
        "VpcId": "vpc-012345",
        "SubnetId": "subnet-012345",
        "LaunchTime": datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        "PlatformDetails": "Linux/UNIX",
        "Tags": [
            {"Key": "Name", "Value": "api-gateway"},
            {"Key": "Environment", "Value": "production"},
        ],
    }

    parsed = parse_instance(raw, region="us-east-1")
    assert isinstance(parsed, EC2Instance)
    assert parsed.instance_id == "i-0123456789abcdef0"
    assert parsed.name == "api-gateway"
    assert parsed.instance_type == "t3.medium"
    assert parsed.state == "running"
    assert parsed.region == "us-east-1"
    assert parsed.availability_zone == "us-east-1a"
    assert parsed.public_ip == "54.210.1.2"
    assert parsed.private_ip == "10.0.1.5"
    assert parsed.vpc_id == "vpc-012345"
    assert parsed.subnet_id == "subnet-012345"
    assert parsed.platform == "linux/unix"
    assert parsed.tags["Environment"] == "production"


def test_parse_instance_windows_and_no_name() -> None:
    """Verify platform fallback to windows and missing Name tag defaults to '-'."""
    raw = {
        "InstanceId": "i-windows123",
        "InstanceType": "m5.large",
        "State": {"Name": "stopped"},
        "Placement": {"AvailabilityZone": "eu-west-1b"},
        "Platform": "windows",
        "Tags": [],
    }

    parsed = parse_instance(raw, region="eu-west-1")
    assert parsed.name == "-"
    assert parsed.platform == "windows"
    assert parsed.public_ip is None
    assert parsed.private_ip is None


@mock_aws
def test_list_instances_in_region_empty() -> None:
    """Verify scanning an empty region returns 0 instances and no error."""
    session = boto3.Session(region_name="us-east-1")
    result = list_instances_in_region(session, region="us-east-1")

    assert result.region == "us-east-1"
    assert len(result.instances) == 0
    assert result.error is None


@mock_aws
def test_list_instances_in_region_with_instances() -> None:
    """Verify discovering created EC2 instances with tags and states."""
    session = boto3.Session(region_name="us-east-1")
    ec2 = session.client("ec2", region_name="us-east-1")

    ec2.run_instances(
        ImageId="ami-12345678",
        MinCount=2,
        MaxCount=2,
        InstanceType="t3.micro",
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [{"Key": "Name", "Value": "worker-node"}],
            }
        ],
    )

    result = list_instances_in_region(session, region="us-east-1")
    assert result.error is None
    assert len(result.instances) == 2
    for inst in result.instances:
        assert inst.instance_type == "t3.micro"
        assert inst.name == "worker-node"
        assert inst.state == "running"
        assert inst.region == "us-east-1"


@mock_aws
def test_list_instances_with_filters() -> None:
    """Verify filtering by state, instance type, and name."""
    session = boto3.Session(region_name="us-east-1")
    ec2 = session.client("ec2", region_name="us-east-1")

    res1 = ec2.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.micro",
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [{"Key": "Name", "Value": "frontend-web"}],
            }
        ],
    )
    inst_id1 = res1["Instances"][0]["InstanceId"]

    ec2.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="m5.large",
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [{"Key": "Name", "Value": "backend-db"}],
            }
        ],
    )

    # Stop inst_id1
    ec2.stop_instances(InstanceIds=[inst_id1])

    # Filter by state stopped
    stopped_result = list_instances_in_region(session, region="us-east-1", state_filter="stopped")
    assert len(stopped_result.instances) == 1
    assert stopped_result.instances[0].instance_id == inst_id1

    # Filter by type m5.large
    type_result = list_instances_in_region(session, region="us-east-1", type_filter="m5.large")
    assert len(type_result.instances) == 1
    assert type_result.instances[0].name == "backend-db"

    # Filter by name wildcard
    name_result = list_instances_in_region(session, region="us-east-1", name_filter="frontend")
    assert len(name_result.instances) == 1
    assert name_result.instances[0].name == "frontend-web"


def test_list_instances_client_error(monkeypatch) -> None:
    """Verify ClientError in a region is caught and surfaced in result.error without crashing."""
    session = boto3.Session(region_name="us-east-1")

    def mock_client(_service_name, region_name=None, **_kwargs):
        _ = region_name
        error_response = {
            "Error": {
                "Code": "UnauthorizedOperation",
                "Message": "You are not authorized to perform this operation.",
            }
        }
        raise ClientError(error_response, "DescribeInstances")

    monkeypatch.setattr(session, "client", mock_client)

    result = list_instances_in_region(session, region="us-east-1")
    assert result.region == "us-east-1"
    assert len(result.instances) == 0
    assert result.error is not None
    assert "UnauthorizedOperation" in result.error


@mock_aws
def test_list_instances_multiregion() -> None:
    """Verify multi-region scanning aggregates instances from multiple regions."""
    session = boto3.Session()

    # Launch instance in us-east-1
    ec2_east = session.client("ec2", region_name="us-east-1")
    ec2_east.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.nano",
        TagSpecifications=[
            {"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": "east-node"}]}
        ],
    )

    # Launch instance in ap-south-1
    ec2_south = session.client("ec2", region_name="ap-south-1")
    ec2_south.run_instances(
        ImageId="ami-87654321",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.small",
        TagSpecifications=[
            {"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": "south-node"}]}
        ],
    )

    res = list_instances_multiregion(
        session=session,
        regions=["us-east-1", "ap-south-1"],
    )

    assert res.total_count == 2
    assert len(res.instances) == 2
    assert len(res.region_errors) == 0
    regions_found = {inst.region for inst in res.instances}
    assert regions_found == {"us-east-1", "ap-south-1"}


@mock_aws
def test_list_instances_multiregion_partial_failure(monkeypatch) -> None:
    """Verify multi-region scan resilience when one region encounters a permission failure."""
    session = boto3.Session()

    # Launch instance in ap-south-1
    ec2_south = session.client("ec2", region_name="ap-south-1")
    ec2_south.run_instances(
        ImageId="ami-87654321",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.micro",
    )

    real_client_fn = session.client

    def resilient_client(service_name, region_name=None, **kwargs):
        if region_name == "us-east-1":
            error_response = {
                "Error": {
                    "Code": "UnauthorizedOperation",
                    "Message": "Access denied in us-east-1.",
                }
            }
            raise ClientError(error_response, "DescribeInstances")
        return real_client_fn(service_name, region_name=region_name, **kwargs)

    monkeypatch.setattr(session, "client", resilient_client)

    res = list_instances_multiregion(
        session=session,
        regions=["us-east-1", "ap-south-1"],
    )

    # ap-south-1 succeeded
    assert res.total_count == 1
    assert res.instances[0].region == "ap-south-1"
    # us-east-1 failed cleanly and recorded in region_errors
    assert "us-east-1" in res.region_errors
    assert "UnauthorizedOperation" in res.region_errors["us-east-1"]
