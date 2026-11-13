"""Cost intelligence analysis rules: idle detection, right-sizing, and orphaned resource identification.

Follows strict heuristics to avoid premature or inaccurate classification:
- Distinguishes missing metrics from zero utilization.
- Evaluates CPU and Network together rather than CPU alone.
- Explicitly accounts for absence of memory metrics without fabricating data.
- Never automatically mutates or resizes cloud infrastructure.
"""

import boto3
from botocore.exceptions import ClientError

from ec2kit.aws.cloudwatch import get_instance_metrics
from ec2kit.aws.pricing import get_ebs_monthly_cost, get_instance_cost_estimate
from ec2kit.config import get_logger
from ec2kit.models import (
    CostAnalysisResult,
    CostSummary,
    EC2Instance,
    IdleInstance,
    InstanceMetrics,
    OrphanedResource,
    RightSizingRecommendation,
)
from ec2kit.storage.cache import PricingCache

logger = get_logger()

# Standard family size step-downs for right-sizing recommendations
FAMILY_DOWNSIZING_MAP: dict[str, str] = {
    # T3 family
    "t3.2xlarge": "t3.xlarge",
    "t3.xlarge": "t3.large",
    "t3.large": "t3.medium",
    "t3.medium": "t3.small",
    "t3.small": "t3.micro",
    # T2 family
    "t2.2xlarge": "t2.xlarge",
    "t2.xlarge": "t2.large",
    "t2.large": "t2.medium",
    "t2.medium": "t2.small",
    "t2.small": "t2.micro",
    # M5 family
    "m5.4xlarge": "m5.2xlarge",
    "m5.2xlarge": "m5.xlarge",
    "m5.xlarge": "m5.large",
    # C5 family
    "c5.4xlarge": "c5.2xlarge",
    "c5.2xlarge": "c5.xlarge",
    "c5.xlarge": "c5.large",
    # R5 family
    "r5.4xlarge": "r5.2xlarge",
    "r5.2xlarge": "r5.xlarge",
    "r5.xlarge": "r5.large",
}

IDLE_EIP_MONTHLY_RATE = 3.65  # $0.005/hr * 730 hrs/month for idle unassociated IPv4


def evaluate_idle_instance(
    instance: EC2Instance,
    metrics: InstanceMetrics,
    monthly_cost: float,
) -> IdleInstance | None:
    """Evaluate whether an instance is idle based on multi-dimensional telemetry.

    Requirement: Do not label an instance idle based on CPU alone or missing data.
    """
    if instance.state.lower() != "running":
        return None

    if metrics.insufficient_data:
        logger.debug(
            "Skipping idle evaluation for %s due to insufficient CloudWatch data",
            instance.instance_id,
        )
        return None

    cpu_avg = metrics.cpu_avg if metrics.cpu_avg is not None else 100.0
    cpu_max = metrics.cpu_max if metrics.cpu_max is not None else 100.0
    net_in = metrics.network_in_bytes or 0.0
    net_out = metrics.network_out_bytes or 0.0
    total_net_mb = round((net_in + net_out) / (1024 * 1024), 2)

    # Heuristic: Average CPU < 5%, Peak CPU < 20%, and Total Network < 25 MB across observation window
    if cpu_avg < 5.0 and cpu_max < 20.0 and total_net_mb < 25.0:
        confidence = "HIGH" if metrics.observation_days >= 7 else "MEDIUM"
        reason = (
            f"Avg CPU was {cpu_avg}% (peak {cpu_max}%) and total network traffic was "
            f"{total_net_mb} MB over {metrics.observation_days} days."
        )
        return IdleInstance(
            instance_id=instance.instance_id,
            name=instance.name,
            instance_type=instance.instance_type,
            region=instance.region,
            cpu_avg=cpu_avg,
            cpu_max=cpu_max,
            network_total_mb=total_net_mb,
            estimated_monthly_cost=monthly_cost,
            confidence=confidence,
            reason=reason,
        )

    return None


def evaluate_rightsizing(
    session: boto3.Session,
    instance: EC2Instance,
    metrics: InstanceMetrics,
    cache: PricingCache | None = None,
) -> RightSizingRecommendation | None:
    """Analyze instance utilization and suggest down-sizing if over-provisioned."""
    if instance.state.lower() != "running" or metrics.insufficient_data:
        return None

    current_type = instance.instance_type.lower()
    suggested_type = FAMILY_DOWNSIZING_MAP.get(current_type)
    if not suggested_type:
        return None

    cpu_avg = metrics.cpu_avg or 0.0
    cpu_max = metrics.cpu_max or 0.0

    # Right-sizing candidate heuristic: peak CPU under 35% and average CPU under 15%
    if cpu_max < 35.0 and cpu_avg < 15.0:
        curr_cost = get_instance_cost_estimate(
            session=session,
            instance_type=current_type,
            region=instance.region,
            operating_system=instance.platform,
            cache=cache,
        ).monthly_estimate

        suggested_cost = get_instance_cost_estimate(
            session=session,
            instance_type=suggested_type,
            region=instance.region,
            operating_system=instance.platform,
            cache=cache,
        ).monthly_estimate

        savings = max(0.0, round(curr_cost - suggested_cost, 2))

        # Memory evaluation note
        if metrics.memory_avg is not None:
            if metrics.memory_avg > 70.0:
                # Memory usage is high; downsizing CPU family might starve RAM
                return None
            confidence = "HIGH"
            reason = (
                f"Peak CPU {cpu_max}% and RAM utilization {metrics.memory_avg}% over "
                f"{metrics.observation_days} days indicate over-provisioned compute capacity."
            )
        else:
            confidence = "MEDIUM"
            reason = (
                f"Peak CPU was {cpu_max}% over {metrics.observation_days} days. "
                "Memory telemetry is unavailable via standard CloudWatch; inspect RAM before downsizing."
            )

        return RightSizingRecommendation(
            instance_id=instance.instance_id,
            name=instance.name,
            region=instance.region,
            current_type=current_type,
            suggested_type=suggested_type,
            reason=reason,
            estimated_monthly_savings=savings,
            confidence=confidence,
            observation_period=f"{metrics.observation_days} days",
        )

    return None


def discover_orphaned_resources(
    session: boto3.Session,
    regions: list[str],
    cache: PricingCache | None = None,
) -> list[OrphanedResource]:
    """Identify unattached EBS volumes and unassociated Elastic IP addresses."""
    orphaned: list[OrphanedResource] = []

    for reg in regions:
        try:
            ec2 = session.client("ec2", region_name=reg)

            # 1. Unattached EBS Volumes (status = available)
            vol_resp = ec2.describe_volumes(Filters=[{"Name": "status", "Values": ["available"]}])
            for vol in vol_resp.get("Volumes", []):
                vol_id = vol.get("VolumeId", "unknown")
                vol_type = vol.get("VolumeType", "gp3")
                size = vol.get("Size", 0)
                monthly = get_ebs_monthly_cost(vol_type, size, reg, cache=cache)
                orphaned.append(
                    OrphanedResource(
                        resource_id=vol_id,
                        resource_type="ebs_volume",
                        region=reg,
                        estimated_monthly_cost=monthly,
                        details=f"{size} GB {vol_type} volume created {vol.get('CreateTime')}",
                        recommendation="Volume is unattached. Snapshot and delete if data is no longer needed.",
                    )
                )

            # 2. Unassociated Elastic IP Addresses
            eip_resp = ec2.describe_addresses()
            for addr in eip_resp.get("Addresses", []):
                alloc_id = addr.get("AllocationId", addr.get("PublicIp", "unknown"))
                # An EIP is unassociated if AssociationId or InstanceId is not set
                if not addr.get("AssociationId") and not addr.get("InstanceId"):
                    orphaned.append(
                        OrphanedResource(
                            resource_id=alloc_id,
                            resource_type="elastic_ip",
                            region=reg,
                            estimated_monthly_cost=IDLE_EIP_MONTHLY_RATE,
                            details=f"Public IPv4 address {addr.get('PublicIp', 'N/A')} with no attached instance or ENI",
                            recommendation="Release unassociated Elastic IP to eliminate idle hourly billing charges.",
                        )
                    )

        except ClientError as exc:
            logger.warning("Failed scanning orphaned resources in region %s: %s", reg, exc)
        except Exception as exc:
            logger.warning("Unexpected error in region %s during orphaned scan: %s", reg, exc)

    return orphaned


def run_cost_analysis(
    session: boto3.Session,
    instances: list[EC2Instance],
    regions: list[str],
    days: int = 7,
    cache: PricingCache | None = None,
    force_refresh: bool = False,
) -> CostAnalysisResult:
    """Execute end-to-end cost intelligence analysis across discovered infrastructure."""
    running_ec2_monthly = 0.0
    idle_instances: list[IdleInstance] = []
    recommendations: list[RightSizingRecommendation] = []

    # 1. Evaluate Running EC2 Costs, Telemetry, and Recommendations
    for inst in instances:
        cost_est = get_instance_cost_estimate(
            session=session,
            instance_type=inst.instance_type,
            region=inst.region,
            operating_system=inst.platform,
            cache=cache,
            force_refresh=force_refresh,
        )

        if inst.state.lower() == "running":
            running_ec2_monthly += cost_est.monthly_estimate

            # Fetch CloudWatch telemetry
            metrics = get_instance_metrics(
                session=session,
                instance_id=inst.instance_id,
                region=inst.region,
                days=days,
            )

            # Check idle heuristic
            idle = evaluate_idle_instance(inst, metrics, cost_est.monthly_estimate)
            if idle:
                idle_instances.append(idle)

            # Check right-sizing heuristic
            rec = evaluate_rightsizing(session, inst, metrics, cache=cache)
            if rec:
                recommendations.append(rec)

    # 2. Discover Orphaned Resources
    orphaned = discover_orphaned_resources(session, regions=regions, cache=cache)

    ebs_orphaned_cost = sum(
        r.estimated_monthly_cost for r in orphaned if r.resource_type == "ebs_volume"
    )
    eip_orphaned_cost = sum(
        r.estimated_monthly_cost for r in orphaned if r.resource_type == "elastic_ip"
    )

    total_monthly = round(running_ec2_monthly + ebs_orphaned_cost + eip_orphaned_cost, 2)

    summary = CostSummary(
        running_ec2_monthly=round(running_ec2_monthly, 2),
        ebs_storage_monthly=round(ebs_orphaned_cost, 2),
        elastic_ip_monthly=round(eip_orphaned_cost, 2),
        total_estimated_monthly=total_monthly,
        currency="USD",
        pricing_model="On-Demand (730 hrs/month)",
    )

    return CostAnalysisResult(
        summary=summary,
        idle_instances=idle_instances,
        recommendations=recommendations,
        orphaned_resources=orphaned,
    )
