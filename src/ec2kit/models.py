"""Data models and serialization structures for ec2kit."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class IdentityInfo(BaseModel):
    """AWS caller identity and session metadata."""

    account_id: str = Field(..., description="AWS Account ID (12 digits)")
    arn: str = Field(..., description="Full ARN of the authenticated caller")
    user_id: str = Field(..., description="Unique identifier of the calling entity")
    profile: str | None = Field(None, description="Active AWS profile name")
    region: str = Field(..., description="Active AWS target region")


class InfoResult(BaseModel):
    """Aggregated information model for `ec2kit info` command."""

    identity: IdentityInfo
    available_regions: list[str] = Field(
        default_factory=list, description="Enabled/Available EC2 regions"
    )
    config_dir: str = Field(..., description="Path to ec2kit config directory")
    cache_dir: str = Field(..., description="Path to ec2kit cache directory")
    database_path: str = Field(..., description="Path to ec2kit SQLite database")
    environment: dict[str, Any] = Field(
        default_factory=dict, description="Active AWS environment variables"
    )


class EC2Instance(BaseModel):
    """Normalized representation of an AWS EC2 instance."""

    instance_id: str = Field(..., description="EC2 instance ID (e.g. i-1234567890abcdef0)")
    name: str = Field("-", description="Instance name tag if defined")
    state: str = Field(..., description="Current state: running, stopped, terminated, etc.")
    instance_type: str = Field(..., description="Hardware type (e.g. t3.micro)")
    region: str = Field(..., description="AWS region where instance resides")
    availability_zone: str = Field(..., description="Availability Zone (e.g. us-east-1a)")
    public_ip: str | None = Field(None, description="Public IPv4 address if allocated")
    private_ip: str | None = Field(None, description="Primary private IPv4 address")
    vpc_id: str | None = Field(None, description="VPC ID if inside a VPC")
    subnet_id: str | None = Field(None, description="Subnet ID if inside a VPC")
    launch_time: datetime | None = Field(None, description="Timestamp of when instance launched")
    platform: str = Field("linux", description="Operating system platform (e.g. linux, windows)")
    tags: dict[str, str] = Field(
        default_factory=dict, description="Resource tags assigned to instance"
    )


class RegionScanResult(BaseModel):
    """Result of scanning a single AWS region."""

    region: str
    instances: list[EC2Instance] = Field(default_factory=list)
    error: str | None = None


class InstanceListResult(BaseModel):
    """Aggregated output model for `ec2kit ls`."""

    regions_scanned: list[str] = Field(default_factory=list)
    instances: list[EC2Instance] = Field(default_factory=list)
    region_errors: dict[str, str] = Field(
        default_factory=dict, description="Errors encountered per region"
    )
    total_count: int = 0


class CostEstimate(BaseModel):
    """On-demand running cost estimate for a single resource."""

    hourly_rate: float
    monthly_estimate: float
    currency: str = "USD"
    pricing_source: str = "AWS Pricing API"


class InstanceMetrics(BaseModel):
    """CloudWatch utilization metrics over an observation window."""

    cpu_avg: float | None = None
    cpu_max: float | None = None
    network_in_bytes: float | None = None
    network_out_bytes: float | None = None
    memory_avg: float | None = None
    observation_days: int = 7
    insufficient_data: bool = False


class IdleInstance(BaseModel):
    """Instance identified as idle based on multi-dimensional telemetry."""

    instance_id: str
    name: str
    instance_type: str
    region: str
    cpu_avg: float
    cpu_max: float
    network_total_mb: float
    estimated_monthly_cost: float
    confidence: str = "HIGH"
    reason: str


class RightSizingRecommendation(BaseModel):
    """Instance right-sizing advice based on observed workload telemetry."""

    instance_id: str
    name: str
    region: str
    current_type: str
    suggested_type: str
    reason: str
    estimated_monthly_savings: float
    confidence: str
    observation_period: str


class OrphanedResource(BaseModel):
    """Unused, unattached, or dangling cloud resource incurring charges."""

    resource_id: str
    resource_type: str  # ebs_volume, elastic_ip, snapshot
    region: str
    estimated_monthly_cost: float
    details: str
    recommendation: str


class CostSummary(BaseModel):
    """Aggregated monthly infrastructure cost estimate."""

    running_ec2_monthly: float = 0.0
    ebs_storage_monthly: float = 0.0
    elastic_ip_monthly: float = 0.0
    total_estimated_monthly: float = 0.0
    currency: str = "USD"
    pricing_model: str = "On-Demand (730 hrs/month)"


class CostAnalysisResult(BaseModel):
    """Comprehensive output model for `ec2kit cost`."""

    summary: CostSummary
    idle_instances: list[IdleInstance] = Field(default_factory=list)
    recommendations: list[RightSizingRecommendation] = Field(default_factory=list)
    orphaned_resources: list[OrphanedResource] = Field(default_factory=list)
    disclaimers: list[str] = Field(
        default_factory=lambda: [
            "Estimates are based on published AWS On-Demand hourly rates and 730 hours/month.",
            "Estimates do not account for Reserved Instances, Savings Plans, enterprise discounts, taxes, or data transfer fees.",
            "This analysis is strictly an estimate and does not represent an actual AWS invoice.",
        ]
    )


class VPCInfo(BaseModel):
    """Discovered Virtual Private Cloud."""

    vpc_id: str
    name: str = "-"
    cidr_block: str
    is_default: bool = False
    state: str = "available"
    tags: dict[str, str] = Field(default_factory=dict)


class SubnetInfo(BaseModel):
    """Discovered Subnet."""

    subnet_id: str
    name: str = "-"
    vpc_id: str
    cidr_block: str
    availability_zone: str
    is_public: bool = False
    tags: dict[str, str] = Field(default_factory=dict)


class InternetGatewayInfo(BaseModel):
    """Discovered Internet Gateway."""

    igw_id: str
    vpc_id: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class NatGatewayInfo(BaseModel):
    """Discovered NAT Gateway."""

    nat_id: str
    vpc_id: str
    subnet_id: str
    public_ip: str | None = None
    state: str = "available"
    tags: dict[str, str] = Field(default_factory=dict)


class SecurityGroupRule(BaseModel):
    """Parsed ingress/egress security group rule."""

    protocol: str  # tcp, udp, icmp, -1 (all)
    from_port: int | None = None
    to_port: int | None = None
    cidr_ipv4: str | None = None
    cidr_ipv6: str | None = None
    source_sg_id: str | None = None
    description: str | None = None


class SecurityGroupInfo(BaseModel):
    """Discovered Security Group."""

    group_id: str
    group_name: str
    description: str
    vpc_id: str | None = None
    ingress_rules: list[SecurityGroupRule] = Field(default_factory=list)
    egress_rules: list[SecurityGroupRule] = Field(default_factory=list)
    tags: dict[str, str] = Field(default_factory=dict)


class VpcTopology(BaseModel):
    """Comprehensive topology of a single VPC and its constituent components."""

    vpc: VPCInfo
    subnets: list[SubnetInfo] = Field(default_factory=list)
    internet_gateways: list[InternetGatewayInfo] = Field(default_factory=list)
    nat_gateways: list[NatGatewayInfo] = Field(default_factory=list)
    security_groups: list[SecurityGroupInfo] = Field(default_factory=list)
    instances: list[EC2Instance] = Field(default_factory=list)


class ScanResult(BaseModel):
    """Overall discovery output for `ec2kit scan`."""

    region: str
    topologies: list[VpcTopology] = Field(default_factory=list)
    mermaid_diagram: str = ""
    total_vpcs: int = 0
    total_subnets: int = 0
    total_instances: int = 0


class SecurityFinding(BaseModel):
    """Identified security risk or configuration flaw."""

    finding_id: str
    resource_id: str
    resource_type: str  # security_group, ebs_volume, ec2_instance, ebs_snapshot
    region: str
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW, INFO
    title: str
    description: str
    evidence: str
    remediation: str
    suggested_command: str | None = None


class SecurityScanResult(BaseModel):
    """Aggregated output model for `ec2kit security`."""

    region: str
    findings: list[SecurityFinding] = Field(default_factory=list)
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    info_count: int = 0
    total_findings: int = 0


class TerraformExportResult(BaseModel):
    """Result of exporting AWS topology to Terraform HCL configuration."""

    region: str
    output_dir: str | None = None
    files: dict[str, str] = Field(default_factory=dict)
    total_resources: int = 0
    import_commands: list[str] = Field(default_factory=list)


class DriftFinding(BaseModel):
    """Specific drift item comparing Terraform state against live AWS."""

    resource_type: str  # aws_instance, aws_security_group, aws_vpc
    resource_id: str
    resource_name: str | None = None
    drift_type: str  # MISSING_IN_AWS, UNMANAGED_IN_TF, MODIFIED
    attribute: str | None = None
    expected_value: str | None = None
    actual_value: str | None = None
    details: str = ""


class DriftReport(BaseModel):
    """Summary report of all infrastructure drift detected."""

    region: str
    state_file: str
    findings: list[DriftFinding] = Field(default_factory=list)
    missing_in_aws_count: int = 0
    unmanaged_in_tf_count: int = 0
    modified_count: int = 0
    total_drifts: int = 0


class OperationResult(BaseModel):
    """Result of an infrastructure-changing operation."""

    instance_id: str
    action: str  # start, stop, reboot, terminate
    region: str
    previous_state: str
    target_state: str
    dry_run: bool
    success: bool
    message: str
    consequences: list[str] = Field(default_factory=list)


class PolicyViolation(BaseModel):
    """Specific policy violation on an AWS resource."""

    rule_name: str
    resource_id: str
    resource_type: str
    severity: str
    message: str
    remediation: str


class PolicyEvaluationResult(BaseModel):
    """Overall outcome of policy compliance check."""

    policy_file: str
    region: str
    compliant: bool
    violations: list[PolicyViolation] = Field(default_factory=list)
    total_violations: int = 0
