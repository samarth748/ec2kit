"""CloudWatch metrics retriever for EC2 telemetry and utilization analysis.

Handles observation windows, distinguishes missing metrics from zero utilization,
and queries CloudWatch Agent memory data only when available without fabricating telemetry.
"""

from datetime import UTC, datetime, timedelta

import boto3
from botocore.exceptions import ClientError

from ec2kit.config import get_logger
from ec2kit.models import InstanceMetrics

logger = get_logger()


def get_instance_metrics(
    session: boto3.Session,
    instance_id: str,
    region: str,
    days: int = 7,
) -> InstanceMetrics:
    """Fetch CloudWatch telemetry for an instance over a configurable observation window.

    Distinguishes missing CloudWatch data from zero utilization: if no datapoints are
    returned, `insufficient_data` is marked True rather than assuming the instance is idle.
    """
    logger.debug(
        "Querying CloudWatch metrics for %s in %s over %d days",
        instance_id,
        region,
        days,
    )
    end_time = datetime.now(UTC)
    start_time = end_time - timedelta(days=days)
    period = 3600  # 1 hour granularity

    try:
        cw_client = session.client("cloudwatch", region_name=region)

        # 1. CPU Utilization
        cpu_response = cw_client.get_metric_statistics(
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=period,
            Statistics=["Average", "Maximum"],
        )
        cpu_datapoints = cpu_response.get("Datapoints", [])

        if not cpu_datapoints:
            # Handle missing data as lack of evidence rather than 0% CPU
            logger.debug("No CloudWatch CPU datapoints found for %s", instance_id)
            return InstanceMetrics(observation_days=days, insufficient_data=True)

        avg_cpu = sum(dp["Average"] for dp in cpu_datapoints) / len(cpu_datapoints)
        max_cpu = max(dp["Maximum"] for dp in cpu_datapoints)

        # 2. Network In / Out
        net_in_response = cw_client.get_metric_statistics(
            Namespace="AWS/EC2",
            MetricName="NetworkIn",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=period,
            Statistics=["Sum"],
        )
        net_in_bytes = sum(dp["Sum"] for dp in net_in_response.get("Datapoints", []))

        net_out_response = cw_client.get_metric_statistics(
            Namespace="AWS/EC2",
            MetricName="NetworkOut",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=period,
            Statistics=["Sum"],
        )
        net_out_bytes = sum(dp["Sum"] for dp in net_out_response.get("Datapoints", []))

        # 3. Optional CloudWatch Agent memory metric (CWAgent)
        mem_avg: float | None = None
        try:
            mem_response = cw_client.get_metric_statistics(
                Namespace="CWAgent",
                MetricName="mem_used_percent",
                Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=["Average"],
            )
            mem_dps = mem_response.get("Datapoints", [])
            if mem_dps:
                mem_avg = sum(dp["Average"] for dp in mem_dps) / len(mem_dps)
        except ClientError:
            pass  # CWAgent metrics are optional and not published by standard basic monitoring

        return InstanceMetrics(
            cpu_avg=round(avg_cpu, 2),
            cpu_max=round(max_cpu, 2),
            network_in_bytes=round(net_in_bytes, 2),
            network_out_bytes=round(net_out_bytes, 2),
            memory_avg=round(mem_avg, 2) if mem_avg is not None else None,
            observation_days=days,
            insufficient_data=False,
        )

    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        logger.debug("CloudWatch query for %s failed [%s]: %s", instance_id, code, exc)
        return InstanceMetrics(observation_days=days, insufficient_data=True)
    except Exception as exc:
        logger.debug("Unexpected error fetching CloudWatch metrics for %s: %s", instance_id, exc)
        return InstanceMetrics(observation_days=days, insufficient_data=True)
