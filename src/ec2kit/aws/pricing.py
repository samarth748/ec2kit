"""AWS Pricing client and on-demand cost resolution engine.

Queries the AWS Pricing API with local SQLite caching. Fallbacks to published
on-demand reference rates when the Pricing API is unavailable or IAM-restricted.
All estimates identify currency, pricing assumptions, and estimation period.
"""

import json
from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from ec2kit.config import get_logger
from ec2kit.models import CostEstimate
from ec2kit.storage.cache import PricingCache

logger = get_logger()

# AWS Region to Pricing API Location Description mapping
REGION_LOCATION_MAP: dict[str, str] = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "eu-west-1": "EU (Ireland)",
    "eu-west-2": "EU (London)",
    "eu-central-1": "EU (Frankfurt)",
    "ap-south-1": "Asia Pacific (Mumbai)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-northeast-2": "Asia Pacific (Seoul)",
    "sa-east-1": "South America (Sao Paulo)",
    "ca-central-1": "Canada (Central)",
}

# Standard baseline published on-demand hourly rates (USD, Linux, us-east-1 base)
REFERENCE_HOURLY_RATES: dict[str, float] = {
    "t3.nano": 0.0052,
    "t3.micro": 0.0104,
    "t3.small": 0.0208,
    "t3.medium": 0.0416,
    "t3.large": 0.0832,
    "t3.xlarge": 0.1664,
    "t3.2xlarge": 0.3328,
    "t2.nano": 0.0058,
    "t2.micro": 0.0116,
    "t2.small": 0.023,
    "t2.medium": 0.0464,
    "t2.large": 0.0928,
    "t4g.nano": 0.0042,
    "t4g.micro": 0.0084,
    "t4g.small": 0.0168,
    "t4g.medium": 0.0336,
    "t4g.large": 0.0672,
    "m5.large": 0.096,
    "m5.xlarge": 0.192,
    "m5.2xlarge": 0.384,
    "m5.4xlarge": 0.768,
    "c5.large": 0.085,
    "c5.xlarge": 0.17,
    "c5.2xlarge": 0.34,
    "c5.4xlarge": 0.68,
    "r5.large": 0.126,
    "r5.xlarge": 0.252,
    "r5.2xlarge": 0.504,
    "m6i.large": 0.096,
    "m6i.xlarge": 0.192,
    "c6i.large": 0.085,
    "c6i.xlarge": 0.17,
}

# Standard baseline EBS monthly pricing per GB (USD)
REFERENCE_EBS_RATES_PER_GB: dict[str, float] = {
    "gp3": 0.08,
    "gp2": 0.10,
    "io1": 0.125,
    "io2": 0.125,
    "st1": 0.045,
    "sc1": 0.015,
    "standard": 0.05,
}

HOURS_PER_MONTH = 730.0


def query_aws_pricing_api(
    session: boto3.Session,
    instance_type: str,
    region: str,
    operating_system: str = "linux",
) -> float | None:
    """Query the AWS Pricing API for on-demand hourly rate.

    The Pricing API is only hosted in us-east-1 and ap-south-1.
    """
    location = REGION_LOCATION_MAP.get(region)
    if not location:
        return None

    os_filter = "Windows" if "windows" in operating_system.lower() else "Linux"

    try:
        # AWS Pricing API endpoint is in us-east-1 with tight timeouts for resilient fallback
        fast_boto_cfg = BotoConfig(
            connect_timeout=1,
            read_timeout=1,
            retries={"max_attempts": 1},
        )
        pricing_client = session.client("pricing", region_name="us-east-1", config=fast_boto_cfg)
        filters = [
            {"Type": "TERM_MATCH", "Field": "ServiceCode", "Value": "AmazonEC2"},
            {"Type": "TERM_MATCH", "Field": "location", "Value": location},
            {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type},
            {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": os_filter},
            {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
            {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
            {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
        ]

        response = pricing_client.get_products(
            ServiceCode="AmazonEC2",
            Filters=filters,
            MaxResults=1,
        )

        price_list = response.get("PriceList", [])
        if not price_list:
            return None

        product_raw = price_list[0]
        data: dict[str, Any] = (
            json.loads(product_raw) if isinstance(product_raw, str) else product_raw
        )

        terms_on_demand = data.get("terms", {}).get("OnDemand", {})
        for _, term_data in terms_on_demand.items():
            dimensions = term_data.get("priceDimensions", {})
            for _, dim in dimensions.items():
                unit = dim.get("unit", "")
                usd_rate = dim.get("pricePerUnit", {}).get("USD")
                if unit == "Hrs" and usd_rate is not None:
                    return float(usd_rate)
        return None

    except ClientError as exc:
        logger.debug("AWS Pricing API call failed: %s", exc)
        return None
    except Exception as exc:
        logger.debug("Error parsing AWS Pricing API response: %s", exc)
        return None


def get_instance_cost_estimate(
    session: boto3.Session,
    instance_type: str,
    region: str,
    operating_system: str = "linux",
    cache: PricingCache | None = None,
    force_refresh: bool = False,
) -> CostEstimate:
    """Retrieve on-demand cost estimate for an EC2 instance with cache support."""
    # 1. Check local SQLite cache unless force_refresh is requested
    if cache and not force_refresh:
        cached = cache.get_instance_price(instance_type, region, operating_system)
        if cached:
            hourly = cached["hourly_price"]
            return CostEstimate(
                hourly_rate=hourly,
                monthly_estimate=round(hourly * HOURS_PER_MONTH, 2),
                currency=cached["currency"],
                pricing_source=f"{cached['source']} (cached)",
            )

    # 2. Attempt query to AWS Pricing API
    api_rate = query_aws_pricing_api(session, instance_type, region, operating_system)
    if api_rate is not None:
        if cache:
            cache.set_instance_price(
                instance_type=instance_type,
                region=region,
                operating_system=operating_system,
                hourly_price=api_rate,
                source="AWS Pricing API",
            )
        return CostEstimate(
            hourly_rate=api_rate,
            monthly_estimate=round(api_rate * HOURS_PER_MONTH, 2),
            currency="USD",
            pricing_source="AWS Pricing API",
        )

    # 3. Fallback to reference on-demand catalog
    base_rate = REFERENCE_HOURLY_RATES.get(instance_type, 0.05)
    # Windows typically incurs a ~40% licensing premium over Linux on-demand rates
    if "windows" in operating_system.lower():
        base_rate = base_rate * 1.4

    if cache:
        cache.set_instance_price(
            instance_type=instance_type,
            region=region,
            operating_system=operating_system,
            hourly_price=base_rate,
            source="Published Reference On-Demand",
        )

    return CostEstimate(
        hourly_rate=base_rate,
        monthly_estimate=round(base_rate * HOURS_PER_MONTH, 2),
        currency="USD",
        pricing_source="Published Reference On-Demand",
    )


def get_ebs_monthly_cost(
    volume_type: str,
    size_gb: int,
    region: str,
    cache: PricingCache | None = None,
) -> float:
    """Estimate monthly cost for an EBS volume based on volume type and storage size."""
    rate_per_gb: float | None = None
    if cache:
        rate_per_gb = cache.get_ebs_price(volume_type, region)

    if rate_per_gb is None:
        rate_per_gb = REFERENCE_EBS_RATES_PER_GB.get(volume_type.lower(), 0.08)
        if cache:
            cache.set_ebs_price(volume_type, region, rate_per_gb)

    return round(rate_per_gb * size_gb, 2)
