"""AWS EC2 client interactions, multi-region discovery, and pagination handling.

Implements resilient multi-region scanning with bounded concurrency and region-level
error isolation so that failure in one region does not abort the entire scan.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import boto3
from botocore.exceptions import ClientError

from ec2kit.config import get_logger
from ec2kit.models import EC2Instance, InstanceListResult, RegionScanResult

logger = get_logger()


def parse_instance(raw: dict[str, Any], region: str) -> EC2Instance:
    """Normalize raw EC2 API instance dictionary into a typed EC2Instance model."""
    tags = {
        tag["Key"]: tag.get("Value", "")
        for tag in raw.get("Tags", [])
        if "Key" in tag and tag["Key"] is not None
    }
    name = tags.get("Name", "-")

    platform_detail = raw.get("PlatformDetails") or raw.get("Platform")
    if not platform_detail:
        platform = "linux"
    elif "windows" in str(platform_detail).lower():
        platform = "windows"
    else:
        platform = str(platform_detail).lower()

    return EC2Instance(
        instance_id=raw.get("InstanceId", "unknown"),
        name=name,
        state=raw.get("State", {}).get("Name", "unknown"),
        instance_type=raw.get("InstanceType", "unknown"),
        region=region,
        availability_zone=raw.get("Placement", {}).get("AvailabilityZone", ""),
        public_ip=raw.get("PublicIpAddress"),
        private_ip=raw.get("PrivateIpAddress"),
        vpc_id=raw.get("VpcId"),
        subnet_id=raw.get("SubnetId"),
        launch_time=raw.get("LaunchTime"),
        platform=platform,
        tags=tags,
    )


def list_instances_in_region(
    session: boto3.Session,
    region: str,
    state_filter: str | None = None,
    type_filter: str | None = None,
    name_filter: str | None = None,
) -> RegionScanResult:
    """Discover EC2 instances in a single region using AWS API paginators.

    Catches region-specific client errors (such as UnauthorizedOperation or OptInRequired)
    and returns a structured RegionScanResult without failing other regions.
    """
    logger.debug("Scanning EC2 instances in region: %s", region)
    instances: list[EC2Instance] = []

    filters: list[dict[str, Any]] = []
    if state_filter:
        filters.append({"Name": "instance-state-name", "Values": [state_filter.strip().lower()]})
    if type_filter:
        filters.append({"Name": "instance-type", "Values": [type_filter.strip()]})
    if name_filter:
        pattern = f"*{name_filter.strip()}*" if "*" not in name_filter else name_filter.strip()
        filters.append({"Name": "tag:Name", "Values": [pattern]})

    try:
        ec2_client = session.client("ec2", region_name=region)
        paginator = ec2_client.get_paginator("describe_instances")

        paginate_kwargs: dict[str, Any] = {}
        if filters:
            paginate_kwargs["Filters"] = filters

        for page in paginator.paginate(**paginate_kwargs):
            for reservation in page.get("Reservations", []):
                for raw_instance in reservation.get("Instances", []):
                    instance = parse_instance(raw_instance, region=region)
                    instances.append(instance)

        return RegionScanResult(region=region, instances=instances)

    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "UnknownError")
        msg = exc.response.get("Error", {}).get("Message", str(exc))
        logger.warning("Region %s failed with [%s]: %s", region, code, msg)
        return RegionScanResult(region=region, instances=[], error=f"[{code}] {msg}")
    except Exception as exc:
        logger.warning("Unexpected error scanning region %s: %s", region, exc)
        return RegionScanResult(region=region, instances=[], error=str(exc))


def list_instances_multiregion(
    session: boto3.Session,
    regions: list[str],
    state_filter: str | None = None,
    type_filter: str | None = None,
    name_filter: str | None = None,
    max_workers: int = 8,
) -> InstanceListResult:
    """Scan multiple AWS regions concurrently with bounded parallelism.

    Ensures that partial regional failures (e.g. lack of permissions or disabled regions)
    are captured in `region_errors` while successfully returning instances from healthy regions.
    """
    if not regions:
        return InstanceListResult()

    all_instances: list[EC2Instance] = []
    region_errors: dict[str, str] = {}

    workers = min(max_workers, len(regions))
    logger.debug(
        "Beginning multi-region scan across %d regions with %d worker threads",
        len(regions),
        workers,
    )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_region = {
            executor.submit(
                list_instances_in_region,
                session=session,
                region=r,
                state_filter=state_filter,
                type_filter=type_filter,
                name_filter=name_filter,
            ): r
            for r in regions
        }

        for future in as_completed(future_to_region):
            scan_result: RegionScanResult = future.result()
            if scan_result.error:
                region_errors[scan_result.region] = scan_result.error
            else:
                all_instances.extend(scan_result.instances)

    # Deterministic sorting: by region first, then by instance_id
    all_instances.sort(key=lambda x: (x.region, x.name, x.instance_id))

    return InstanceListResult(
        regions_scanned=sorted(regions),
        instances=all_instances,
        region_errors=region_errors,
        total_count=len(all_instances),
    )
