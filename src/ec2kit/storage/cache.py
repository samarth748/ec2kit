"""Cache repository for AWS pricing data with configurable TTL and invalidation."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ec2kit.config import get_logger
from ec2kit.storage.database import Database

logger = get_logger()


class PricingCache:
    """Manages cached AWS EC2 and EBS pricing in SQLite."""

    def __init__(self, db_path: Path) -> None:
        self.db = Database(db_path)

    def get_instance_price(
        self,
        instance_type: str,
        region: str,
        operating_system: str = "linux",
        max_age_days: int = 7,
    ) -> dict[str, Any] | None:
        """Fetch cached hourly price if present and within max_age_days."""
        os_normalized = operating_system.lower()
        if "windows" in os_normalized:
            os_key = "windows"
        else:
            os_key = "linux"

        cutoff = (datetime.now(UTC) - timedelta(days=max_age_days)).strftime("%Y-%m-%d %H:%M:%S")
        sql = """
            SELECT instance_type, region, operating_system, hourly_price, currency, source, updated_at
            FROM pricing_cache
            WHERE instance_type = ? AND region = ? AND operating_system = ?
              AND updated_at >= ?
        """
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (instance_type, region, os_key, cutoff))
            row = cursor.fetchone()
            if row:
                return {
                    "instance_type": row["instance_type"],
                    "region": row["region"],
                    "operating_system": row["operating_system"],
                    "hourly_price": float(row["hourly_price"]),
                    "currency": row["currency"],
                    "source": row["source"],
                    "updated_at": row["updated_at"],
                }
        return None

    def set_instance_price(
        self,
        instance_type: str,
        region: str,
        operating_system: str,
        hourly_price: float,
        source: str = "AWS Pricing API",
        currency: str = "USD",
    ) -> None:
        """Store or update on-demand hourly price in cache."""
        os_key = "windows" if "windows" in operating_system.lower() else "linux"
        sql = """
            INSERT INTO pricing_cache
            (instance_type, region, operating_system, hourly_price, currency, source, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(instance_type, region, operating_system) DO UPDATE SET
                hourly_price = excluded.hourly_price,
                currency = excluded.currency,
                source = excluded.source,
                updated_at = CURRENT_TIMESTAMP
        """
        with self.db.connection() as conn:
            conn.execute(
                sql,
                (instance_type, region, os_key, float(hourly_price), currency, source),
            )

    def get_ebs_price(
        self,
        volume_type: str,
        region: str,
        max_age_days: int = 7,
    ) -> float | None:
        """Fetch cached EBS monthly price per GB."""
        cutoff = (datetime.now(UTC) - timedelta(days=max_age_days)).strftime("%Y-%m-%d %H:%M:%S")
        sql = """
            SELECT price_per_gb_month
            FROM ebs_pricing_cache
            WHERE volume_type = ? AND region = ? AND updated_at >= ?
        """
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (volume_type.lower(), region, cutoff))
            row = cursor.fetchone()
            if row:
                return float(row["price_per_gb_month"])
        return None

    def set_ebs_price(
        self,
        volume_type: str,
        region: str,
        price_per_gb_month: float,
        currency: str = "USD",
    ) -> None:
        """Store or update EBS monthly price per GB."""
        sql = """
            INSERT INTO ebs_pricing_cache
            (volume_type, region, price_per_gb_month, currency, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(volume_type, region) DO UPDATE SET
                price_per_gb_month = excluded.price_per_gb_month,
                currency = excluded.currency,
                updated_at = CURRENT_TIMESTAMP
        """
        with self.db.connection() as conn:
            conn.execute(
                sql,
                (volume_type.lower(), region, float(price_per_gb_month), currency),
            )

    def clear(self) -> None:
        """Clear all cached pricing entries."""
        with self.db.connection() as conn:
            conn.execute("DELETE FROM pricing_cache")
            conn.execute("DELETE FROM ebs_pricing_cache")
        logger.info("Pricing cache cleared.")
