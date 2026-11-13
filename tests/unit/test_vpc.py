"""Unit tests for AWS VPC discovery and Mermaid architecture generation."""

import boto3
from moto import mock_aws

from ec2kit.aws.vpc import discover_vpc_topologies
from ec2kit.render.mermaid import generate_mermaid_diagram, sanitize_id


def test_sanitize_id() -> None:
    """Verify identifier sanitization for valid Mermaid node syntax."""
    assert sanitize_id("vpc-12345678") == "vpc_12345678"
    assert sanitize_id("subnet-abc-def") == "subnet_abc_def"
    assert sanitize_id("my.custom:node") == "my_custom_node"


def test_mermaid_generation_empty() -> None:
    """Verify empty topologies produce valid Mermaid flowchart without syntax error."""
    diagram = generate_mermaid_diagram([])
    assert "flowchart TD" in diagram
    assert "Empty" in diagram


@mock_aws
def test_vpc_discovery_and_mermaid_generation() -> None:
    """Verify full VPC discovery with public/private subnets, IGW, and EC2 instance."""
    session = boto3.Session(region_name="us-east-1")
    ec2 = session.client("ec2", region_name="us-east-1")

    # 1. Create VPC
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")
    vpc_id = vpc["Vpc"]["VpcId"]
    ec2.create_tags(Resources=[vpc_id], Tags=[{"Key": "Name", "Value": "main-vpc"}])

    # 2. Create Public Subnet and Private Subnet
    pub_sub = ec2.create_subnet(
        VpcId=vpc_id, CidrBlock="10.0.1.0/24", AvailabilityZone="us-east-1a"
    )
    pub_sub_id = pub_sub["Subnet"]["SubnetId"]
    ec2.create_tags(Resources=[pub_sub_id], Tags=[{"Key": "Name", "Value": "public-subnet"}])

    priv_sub = ec2.create_subnet(
        VpcId=vpc_id, CidrBlock="10.0.2.0/24", AvailabilityZone="us-east-1b"
    )
    priv_sub_id = priv_sub["Subnet"]["SubnetId"]
    ec2.create_tags(Resources=[priv_sub_id], Tags=[{"Key": "Name", "Value": "private-subnet"}])

    # 3. Create Internet Gateway and attach to VPC
    igw = ec2.create_internet_gateway()
    igw_id = igw["InternetGateway"]["InternetGatewayId"]
    ec2.attach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)

    # 4. Create Route Table for Public Subnet with 0.0.0.0/0 -> IGW
    rt = ec2.create_route_table(VpcId=vpc_id)
    rt_id = rt["RouteTable"]["RouteTableId"]
    ec2.create_route(RouteTableId=rt_id, DestinationCidrBlock="0.0.0.0/0", GatewayId=igw_id)
    ec2.associate_route_table(SubnetId=pub_sub_id, RouteTableId=rt_id)

    # 5. Create Elastic IP and NAT Gateway in public subnet
    eip = ec2.allocate_address(Domain="vpc")
    nat = ec2.create_nat_gateway(SubnetId=pub_sub_id, AllocationId=eip["AllocationId"])
    nat_id = nat["NatGateway"]["NatGatewayId"]

    # 6. Launch EC2 instance in public subnet and another in private subnet
    ec2.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.micro",
        SubnetId=pub_sub_id,
        TagSpecifications=[
            {"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": "web-server"}]}
        ],
    )
    ec2.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.small",
        SubnetId=priv_sub_id,
        TagSpecifications=[
            {"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": "db-server"}]}
        ],
    )

    topologies = discover_vpc_topologies(session=session, region="us-east-1", target_vpc_id=vpc_id)
    assert len(topologies) == 1
    top = topologies[0]
    assert top.vpc.vpc_id == vpc_id
    assert top.vpc.name == "main-vpc"
    assert len(top.subnets) == 2
    assert len(top.internet_gateways) == 1
    assert len(top.nat_gateways) == 1
    assert len(top.instances) == 2

    # Check public vs private classification
    pub_record = next(s for s in top.subnets if s.subnet_id == pub_sub_id)
    priv_record = next(s for s in top.subnets if s.subnet_id == priv_sub_id)
    assert pub_record.is_public is True
    assert priv_record.is_public is False

    # Check Mermaid diagram generation
    diagram = generate_mermaid_diagram(topologies)
    assert "flowchart TD" in diagram
    assert "Public Internet" in diagram
    assert vpc_id in diagram
    assert pub_sub_id in diagram
    assert priv_sub_id in diagram
    assert igw_id in diagram
    assert nat_id in diagram
    assert "web-server" in diagram
    assert "db-server" in diagram
