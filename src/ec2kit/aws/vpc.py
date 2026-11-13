"""AWS VPC and network architecture topology discovery engine."""

from typing import Any

import boto3
from botocore.exceptions import ClientError

from ec2kit.aws.ec2 import parse_instance
from ec2kit.config import get_logger
from ec2kit.models import (
    InternetGatewayInfo,
    NatGatewayInfo,
    SecurityGroupInfo,
    SecurityGroupRule,
    SubnetInfo,
    VPCInfo,
    VpcTopology,
)

logger = get_logger()


def parse_tags(raw_tags: list[dict[str, Any]]) -> dict[str, str]:
    """Extract key-value pairs from AWS tags list."""
    return {
        tag["Key"]: tag.get("Value", "")
        for tag in raw_tags
        if "Key" in tag and tag["Key"] is not None
    }


def parse_security_group_rules(ip_permissions: list[dict[str, Any]]) -> list[SecurityGroupRule]:
    """Parse raw security group permission structures into typed rules."""
    rules: list[SecurityGroupRule] = []
    for perm in ip_permissions:
        protocol = perm.get("IpProtocol", "-1")
        from_port = perm.get("FromPort")
        to_port = perm.get("ToPort")

        # IPv4 ranges
        for ip_range in perm.get("IpRanges", []):
            rules.append(
                SecurityGroupRule(
                    protocol=protocol,
                    from_port=from_port,
                    to_port=to_port,
                    cidr_ipv4=ip_range.get("CidrIp"),
                    description=ip_range.get("Description"),
                )
            )

        # IPv6 ranges
        for ipv6_range in perm.get("Ipv6Ranges", []):
            rules.append(
                SecurityGroupRule(
                    protocol=protocol,
                    from_port=from_port,
                    to_port=to_port,
                    cidr_ipv6=ipv6_range.get("CidrIpv6"),
                    description=ipv6_range.get("Description"),
                )
            )

        # Security group references
        for user_id_pair in perm.get("UserIdGroupPairs", []):
            rules.append(
                SecurityGroupRule(
                    protocol=protocol,
                    from_port=from_port,
                    to_port=to_port,
                    source_sg_id=user_id_pair.get("GroupId"),
                    description=user_id_pair.get("Description"),
                )
            )
    return rules


def discover_vpc_topologies(
    session: boto3.Session,
    region: str,
    target_vpc_id: str | None = None,
) -> list[VpcTopology]:
    """Discover VPCs, subnets, gateways, and security groups in a region."""
    logger.debug("Discovering VPC topologies in %s (vpc_id=%s)", region, target_vpc_id)
    ec2 = session.client("ec2", region_name=region)

    vpc_filter: list[dict[str, Any]] = []
    if target_vpc_id:
        vpc_filter.append({"Name": "vpc-id", "Values": [target_vpc_id]})

    try:
        vpc_resp = ec2.describe_vpcs(Filters=vpc_filter)
    except ClientError as exc:
        logger.error("Failed to describe VPCs in %s: %s", region, exc)
        return []

    topologies: list[VpcTopology] = []

    for vpc_raw in vpc_resp.get("Vpcs", []):
        vpc_id = vpc_raw["VpcId"]
        tags = parse_tags(vpc_raw.get("Tags", []))
        vpc_info = VPCInfo(
            vpc_id=vpc_id,
            name=tags.get("Name", "-"),
            cidr_block=vpc_raw.get("CidrBlock", "0.0.0.0/0"),
            is_default=vpc_raw.get("IsDefault", False),
            state=vpc_raw.get("State", "available"),
            tags=tags,
        )

        # 1. Discover Route Tables to identify public vs private subnets
        rt_resp = ec2.describe_route_tables(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
        public_subnet_ids: set[str] = set()

        for rt in rt_resp.get("RouteTables", []):
            has_igw = any(
                r.get("GatewayId", "").startswith("igw-")
                for r in rt.get("Routes", [])
                if r.get("DestinationCidrBlock") == "0.0.0.0/0"
            )
            if has_igw:
                for assoc in rt.get("Associations", []):
                    s_id = assoc.get("SubnetId")
                    if s_id:
                        public_subnet_ids.add(s_id)

        # 2. Discover Subnets
        sub_resp = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
        subnets: list[SubnetInfo] = []
        for s_raw in sub_resp.get("Subnets", []):
            s_id = s_raw["SubnetId"]
            s_tags = parse_tags(s_raw.get("Tags", []))
            is_pub = (
                s_id in public_subnet_ids
                or s_raw.get("MapPublicIpOnLaunch", False)
                or "public" in s_tags.get("Name", "").lower()
            )
            subnets.append(
                SubnetInfo(
                    subnet_id=s_id,
                    name=s_tags.get("Name", "-"),
                    vpc_id=vpc_id,
                    cidr_block=s_raw.get("CidrBlock", ""),
                    availability_zone=s_raw.get("AvailabilityZone", ""),
                    is_public=is_pub,
                    tags=s_tags,
                )
            )

        # 3. Discover Internet Gateways
        igw_resp = ec2.describe_internet_gateways(
            Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]
        )
        igws: list[InternetGatewayInfo] = []
        for igw_raw in igw_resp.get("InternetGateways", []):
            igw_tags = parse_tags(igw_raw.get("Tags", []))
            igws.append(
                InternetGatewayInfo(
                    igw_id=igw_raw["InternetGatewayId"],
                    vpc_id=vpc_id,
                    tags=igw_tags,
                )
            )

        # 4. Discover NAT Gateways
        nat_resp = ec2.describe_nat_gateways(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
        nats: list[NatGatewayInfo] = []
        for nat_raw in nat_resp.get("NatGateways", []):
            if nat_raw.get("State") != "deleted":
                nat_tags = parse_tags(nat_raw.get("Tags", []))
                pub_ip: str | None = None
                for addr in nat_raw.get("NatGatewayAddresses", []):
                    if addr.get("PublicIp"):
                        pub_ip = addr.get("PublicIp")
                        break
                nats.append(
                    NatGatewayInfo(
                        nat_id=nat_raw["NatGatewayId"],
                        vpc_id=vpc_id,
                        subnet_id=nat_raw.get("SubnetId", ""),
                        public_ip=pub_ip,
                        state=nat_raw.get("State", "available"),
                        tags=nat_tags,
                    )
                )

        # 5. Discover Security Groups
        sg_resp = ec2.describe_security_groups(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
        sgs: list[SecurityGroupInfo] = []
        for sg_raw in sg_resp.get("SecurityGroups", []):
            sg_tags = parse_tags(sg_raw.get("Tags", []))
            sgs.append(
                SecurityGroupInfo(
                    group_id=sg_raw["GroupId"],
                    group_name=sg_raw.get("GroupName", ""),
                    description=sg_raw.get("Description", ""),
                    vpc_id=vpc_id,
                    ingress_rules=parse_security_group_rules(sg_raw.get("IpPermissions", [])),
                    egress_rules=parse_security_group_rules(sg_raw.get("IpPermissionsEgress", [])),
                    tags=sg_tags,
                )
            )

        # 6. Discover EC2 Instances in this VPC
        inst_resp = ec2.describe_instances(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
        instances = []
        for resv in inst_resp.get("Reservations", []):
            for inst_raw in resv.get("Instances", []):
                instances.append(parse_instance(inst_raw, region=region))

        topologies.append(
            VpcTopology(
                vpc=vpc_info,
                subnets=subnets,
                internet_gateways=igws,
                nat_gateways=nats,
                security_groups=sgs,
                instances=instances,
            )
        )

    return topologies
