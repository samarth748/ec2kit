"""Unit tests for Terraform renderer and HCL generation."""

from pathlib import Path

from ec2kit.models import (
    EC2Instance,
    InternetGatewayInfo,
    SecurityGroupInfo,
    SecurityGroupRule,
    SubnetInfo,
    VPCInfo,
    VpcTopology,
)
from ec2kit.render.terraform import (
    TerraformRenderer,
    sanitize_tf_name,
)


def test_sanitize_tf_name() -> None:
    """Verify Terraform identifier sanitization rules."""
    assert sanitize_tf_name("web-server-01") == "web_server_01"
    assert sanitize_tf_name("123-leading-digit") == "resource_123_leading_digit"
    assert sanitize_tf_name("my.app/prod") == "my_app_prod"
    assert sanitize_tf_name(None, fallback="default_res") == "default_res"
    assert sanitize_tf_name("___already_underscored___") == "already_underscored"


def test_prepare_topology_and_render(tmp_path: Path) -> None:
    """Verify rendering of main.tf, variables.tf, and outputs.tf."""
    vpc = VPCInfo(
        vpc_id="vpc-12345678",
        cidr_block="10.0.0.0/16",
        state="available",
        name="production-vpc",
        is_default=False,
    )
    subnet = SubnetInfo(
        subnet_id="subnet-11112222",
        vpc_id="vpc-12345678",
        cidr_block="10.0.1.0/24",
        availability_zone="us-east-1a",
        is_public=True,
        name="public-subnet-1",
    )
    igw = InternetGatewayInfo(
        igw_id="igw-33334444",
        vpc_id="vpc-12345678",
        state="available",
    )
    sg = SecurityGroupInfo(
        group_id="sg-55556666",
        group_name="web-sg",
        description="Web security group",
        vpc_id="vpc-12345678",
        ingress_rules=[
            SecurityGroupRule(
                protocol="tcp",
                from_port=443,
                to_port=443,
                cidr_ipv4="0.0.0.0/0",
                description="HTTPS",
            )
        ],
    )
    instance = EC2Instance(
        instance_id="i-77778888",
        name="web-server",
        instance_type="t3.medium",
        state="running",
        region="us-east-1",
        availability_zone="us-east-1a",
        ami_id="ami-99990000",
        subnet_id="subnet-11112222",
        vpc_id="vpc-12345678",
    )

    topology = VpcTopology(
        vpc=vpc,
        subnets=[subnet],
        internet_gateways=[igw],
        security_groups=[sg],
        instances=[instance],
    )

    renderer = TerraformRenderer()
    rendered = renderer.render_all(topologies=[topology], region="us-east-1")

    assert "main.tf" in rendered
    assert "variables.tf" in rendered
    assert "outputs.tf" in rendered

    main_tf = rendered["main.tf"]
    assert 'resource "aws_vpc" "production_vpc"' in main_tf
    assert "terraform import aws_vpc.production_vpc vpc-12345678" in main_tf
    assert 'resource "aws_subnet" "public_subnet_1"' in main_tf
    assert "terraform import aws_subnet.public_subnet_1 subnet-11112222" in main_tf
    assert 'resource "aws_instance" "web_server"' in main_tf
    assert "terraform import aws_instance.web_server i-77778888" in main_tf

    # Test writing to directory
    written = renderer.write_to_directory(
        topologies=[topology], region="us-east-1", output_dir=tmp_path
    )
    assert len(written) == 3
    assert (tmp_path / "main.tf").exists()
    assert (tmp_path / "variables.tf").exists()
    assert (tmp_path / "outputs.tf").exists()
