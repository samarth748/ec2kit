"""SQLite database manager for caching and local metadata storage.

Uses versioned schemas, atomic transactions, and corruption recovery.
Strictly prohibited from storing AWS credentials or access tokens.
"""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from ec2kit.config import get_logger

logger = get_logger()

CURRENT_SCHEMA_VERSION = 1

INIT_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pricing_cache (
    instance_type TEXT NOT NULL,
    region TEXT NOT NULL,
    operating_system TEXT NOT NULL,
    hourly_price REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    source TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (instance_type, region, operating_system)
);

CREATE TABLE IF NOT EXISTS ebs_pricing_cache (
    volume_type TEXT NOT NULL,
    region TEXT NOT NULL,
    price_per_gb_month REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (volume_type, region)
);

CREATE INDEX IF NOT EXISTS idx_pricing_lookup
ON pricing_cache (instance_type, region, operating_system);
"""


class Database:
    """SQLite database manager with migration tracking and corruption handling."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._ensure_initialized()

    def _ensure_initialized(self) -> None:
        """Ensure parent directory exists and schema is migrated."""
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self.connection() as conn:
                conn.executescript(INIT_SQL)
                cursor = conn.cursor()
                cursor.execute("SELECT MAX(version) FROM schema_version")
                row = cursor.fetchone()
                current_ver = row[0] if row and row[0] is not None else 0
                if current_ver < CURRENT_SCHEMA_VERSION:
                    cursor.execute(
                        "INSERT INTO schema_version (version) VALUES (?)",
                        (CURRENT_SCHEMA_VERSION,),
                    )
        except sqlite3.DatabaseError as exc:
            logger.error("Database corruption detected at %s: %s", self.db_path, exc)
            self._handle_corruption()

    def _handle_corruption(self) -> None:
        """Handle corrupted database file by renaming it and recreating clean DB."""
        if self.db_path.exists():
            backup_path = self.db_path.with_suffix(".corrupt.bak")
            logger.warning("Backing up corrupted DB to %s and reinitializing", backup_path)
            try:
                self.db_path.rename(backup_path)
            except OSError as err:
                logger.error("Failed to rename corrupted DB: %s", err)
        with self.connection() as conn:
            conn.executescript(INIT_SQL)
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (CURRENT_SCHEMA_VERSION,),
            )

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Provide a transactional SQLite connection."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=10.0,
        )
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
