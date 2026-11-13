"""Unit tests for cost intelligence calculations, idle detection, and right-sizing heuristics."""

from pathlib import Path

import boto3
from moto import mock_aws

from ec2kit.analysis.cost_rules import (
    discover_orphaned_resources,
    evaluate_idle_instance,
    evaluate_rightsizing,
)
from ec2kit.aws.pricing import get_ebs_monthly_cost, get_instance_cost_estimate
from ec2kit.models import EC2Instance, InstanceMetrics
from ec2kit.storage.cache import PricingCache


def test_instance_cost_estimate(tmp_path: Path) -> None:
    """Verify on-demand cost estimation for Linux and Windows."""
    session = boto3.Session(region_name="us-east-1")
    cache = PricingCache(tmp_path / "pricing.db")

    linux_est = get_instance_cost_estimate(
        session=session,
        instance_type="t3.micro",
        region="us-east-1",
        operating_system="linux",
        cache=cache,
    )
    assert linux_est.hourly_rate == 0.0104
    assert linux_est.monthly_estimate == round(0.0104 * 730, 2)
    assert linux_est.currency == "USD"

    # Windows licensing premium check
    win_est = get_instance_cost_estimate(
        session=session,
        instance_type="t3.micro",
        region="us-east-1",
        operating_system="windows",
        cache=cache,
    )
    assert win_est.hourly_rate > linux_est.hourly_rate
    assert win_est.monthly_estimate > linux_est.monthly_estimate


def test_ebs_monthly_cost(tmp_path: Path) -> None:
    """Verify EBS storage cost calculations based on size and storage class."""
    cache = PricingCache(tmp_path / "pricing.db")
    # 100 GB gp3 at $0.08/GB = $8.00
    cost_gp3 = get_ebs_monthly_cost(volume_type="gp3", size_gb=100, region="us-east-1", cache=cache)
    assert cost_gp3 == 8.00

    # 500 GB gp2 at $0.10/GB = $50.00
    cost_gp2 = get_ebs_monthly_cost(volume_type="gp2", size_gb=500, region="us-east-1", cache=cache)
    assert cost_gp2 == 50.00


def test_evaluate_idle_instance_heuristics() -> None:
    """Verify multi-dimensional idle instance evaluation."""
    running_inst = EC2Instance(
        instance_id="i-idle123",
        name="unused-dev-server",
        state="running",
        instance_type="t3.small",
        region="us-east-1",
        availability_zone="us-east-1a",
    )

    # 1. Truly idle: low CPU and low Network over 7 days
    idle_metrics = InstanceMetrics(
        cpu_avg=1.5,
        cpu_max=8.0,
        network_in_bytes=5 * 1024 * 1024,
        network_out_bytes=2 * 1024 * 1024,
        observation_days=7,
        insufficient_data=False,
    )
    result = evaluate_idle_instance(running_inst, idle_metrics, monthly_cost=15.18)
    assert result is not None
    assert result.instance_id == "i-idle123"
    assert result.confidence == "HIGH"

    # 2. Insufficient data: should NEVER be labeled idle
    no_data_metrics = InstanceMetrics(
        cpu_avg=0.0,
        cpu_max=0.0,
        observation_days=7,
        insufficient_data=True,
    )
    assert evaluate_idle_instance(running_inst, no_data_metrics, monthly_cost=15.18) is None

    # 3. Low CPU but active Network (e.g. reverse proxy / video streaming): NOT idle
    active_net_metrics = InstanceMetrics(
        cpu_avg=3.0,
        cpu_max=12.0,
        network_in_bytes=500 * 1024 * 1024,  # 500 MB
        network_out_bytes=2000 * 1024 * 1024,  # 2 GB
        observation_days=7,
        insufficient_data=False,
    )
    assert evaluate_idle_instance(running_inst, active_net_metrics, monthly_cost=15.18) is None

    # 4. Stopped instance: NOT idle candidate (already stopped)
    stopped_inst = EC2Instance(
        instance_id="i-stopped123",
        name="stopped-server",
        state="stopped",
        instance_type="t3.small",
        region="us-east-1",
        availability_zone="us-east-1a",
    )
    assert evaluate_idle_instance(stopped_inst, idle_metrics, monthly_cost=15.18) is None


def test_evaluate_rightsizing(tmp_path: Path) -> None:
    """Verify right-sizing down-sizing recommendations and RAM checks."""
    session = boto3.Session(region_name="us-east-1")
    cache = PricingCache(tmp_path / "pricing.db")

    instance = EC2Instance(
        instance_id="i-oversized",
        name="oversized-app",
        state="running",
        instance_type="m5.2xlarge",
        region="us-east-1",
        availability_zone="us-east-1a",
    )

    # Low peak CPU (20%) indicates candidate for downsizing to m5.xlarge
    metrics = InstanceMetrics(
        cpu_avg=8.0,
        cpu_max=20.0,
        observation_days=7,
        insufficient_data=False,
    )

    rec = evaluate_rightsizing(session, instance, metrics, cache=cache)
    assert rec is not None
    assert rec.current_type == "m5.2xlarge"
    assert rec.suggested_type == "m5.xlarge"
    assert rec.estimated_monthly_savings > 0.0
    assert rec.confidence == "MEDIUM"

    # If CloudWatch agent memory data shows RAM is high (85%), do NOT recommend downsizing
    high_ram_metrics = InstanceMetrics(
        cpu_avg=8.0,
        cpu_max=20.0,
        memory_avg=85.0,
        observation_days=7,
        insufficient_data=False,
    )
    assert evaluate_rightsizing(session, instance, high_ram_metrics, cache=cache) is None


@mock_aws
def test_discover_orphaned_resources(tmp_path: Path) -> None:
    """Verify discovery of unattached EBS volumes and unassociated Elastic IPs."""
    session = boto3.Session(region_name="us-east-1")
    ec2 = session.client("ec2", region_name="us-east-1")
    cache = PricingCache(tmp_path / "pricing.db")

    # 1. Create unattached volume
    vol = ec2.create_volume(
        AvailabilityZone="us-east-1a",
        Size=50,
        VolumeType="gp3",
    )
    vol_id = vol["VolumeId"]

    # 2. Allocate unassociated Elastic IP
    eip = ec2.allocate_address(Domain="vpc")
    alloc_id = eip["AllocationId"]

    orphaned = discover_orphaned_resources(session, regions=["us-east-1"], cache=cache)

    res_ids = {r.resource_id for r in orphaned}
    assert vol_id in res_ids
    assert alloc_id in res_ids

    vol_record = next(r for r in orphaned if r.resource_id == vol_id)
    assert vol_record.resource_type == "ebs_volume"
    assert vol_record.estimated_monthly_cost == 4.00  # 50GB * $0.08 = $4.00

    eip_record = next(r for r in orphaned if r.resource_id == alloc_id)
    assert eip_record.resource_type == "elastic_ip"
    assert eip_record.estimated_monthly_cost == 3.65
