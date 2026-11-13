"""Unit tests for SQLite database manager and PricingCache."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from ec2kit.storage.cache import PricingCache
from ec2kit.storage.database import Database


def test_database_initialization(tmp_path: Path) -> None:
    """Verify database initialization, directory creation, and schema versioning."""
    db_file = tmp_path / "sub" / "test.db"
    db = Database(db_file)
    assert db_file.exists()

    with db.connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT version FROM schema_version")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == 1


def test_database_corruption_recovery(tmp_path: Path) -> None:
    """Verify corrupted database file is safely backed up and recreated."""
    db_file = tmp_path / "corrupt.db"
    # Write garbage bytes into db file to simulate corruption
    db_file.write_text("NOT A VALID SQLITE DATABASE FILE")

    db = Database(db_file)
    assert db_file.exists()

    # Verify corrupt backup was made
    backup_file = db_file.with_suffix(".corrupt.bak")
    assert backup_file.exists()
    assert backup_file.read_text() == "NOT A VALID SQLITE DATABASE FILE"

    # Verify newly created database is functional
    with db.connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT version FROM schema_version")
        row = cursor.fetchone()
        assert row[0] == 1


def test_pricing_cache_crud(tmp_path: Path) -> None:
    """Verify storing, retrieving, and clearing pricing entries."""
    db_file = tmp_path / "cache_test.db"
    cache = PricingCache(db_file)

    # 1. Miss
    assert cache.get_instance_price("t3.micro", "us-east-1", "linux") is None

    # 2. Store & Hit
    cache.set_instance_price(
        instance_type="t3.micro",
        region="us-east-1",
        operating_system="linux",
        hourly_price=0.0104,
        source="AWS Pricing API",
    )
    hit = cache.get_instance_price("t3.micro", "us-east-1", "linux")
    assert hit is not None
    assert hit["hourly_price"] == 0.0104
    assert hit["source"] == "AWS Pricing API"

    # 3. EBS Price
    assert cache.get_ebs_price("gp3", "us-east-1") is None
    cache.set_ebs_price("gp3", "us-east-1", 0.08)
    assert cache.get_ebs_price("gp3", "us-east-1") == 0.08

    # 4. Clear
    cache.clear()
    assert cache.get_instance_price("t3.micro", "us-east-1", "linux") is None
    assert cache.get_ebs_price("gp3", "us-east-1") is None


def test_pricing_cache_ttl_expiration(tmp_path: Path) -> None:
    """Verify cached entries older than max_age_days are not returned."""
    db_file = tmp_path / "ttl_test.db"
    cache = PricingCache(db_file)

    cache.set_instance_price(
        instance_type="t3.nano",
        region="us-east-1",
        operating_system="linux",
        hourly_price=0.0052,
    )

    # Manually backdate the updated_at timestamp in SQLite
    old_time = (datetime.now(UTC) - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
    with cache.db.connection() as conn:
        conn.execute(
            "UPDATE pricing_cache SET updated_at = ? WHERE instance_type = ?",
            (old_time, "t3.nano"),
        )

    # Within 7 days should miss because it is 10 days old
    assert cache.get_instance_price("t3.nano", "us-east-1", max_age_days=7) is None
    # Within 15 days should hit
    hit = cache.get_instance_price("t3.nano", "us-east-1", max_age_days=15)
    assert hit is not None
    assert hit["hourly_price"] == 0.0052
