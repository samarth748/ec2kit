"""Configuration management and environment resolution for ec2kit."""

import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

LOGGER_NAME = "ec2kit"


def get_default_config_dir() -> Path:
    """Return the user configuration directory for ec2kit (~/.config/ec2kit or XDG_CONFIG_HOME)."""
    xdg_config = os.getenv("XDG_CONFIG_HOME")
    if xdg_config:
        base = Path(xdg_config)
    else:
        base = Path.home() / ".config"
    return base / "ec2kit"


def get_default_cache_dir() -> Path:
    """Return the user cache directory for ec2kit (~/.cache/ec2kit or XDG_CACHE_HOME)."""
    xdg_cache = os.getenv("XDG_CACHE_HOME")
    if xdg_cache:
        base = Path(xdg_cache)
    else:
        base = Path.home() / ".cache"
    return base / "ec2kit"


@dataclass
class Config:
    """Global runtime configuration options."""

    profile: str | None = None
    region: str | None = None
    output_json: bool = False
    quiet: bool = False
    verbose: bool = False
    config_dir: Path = field(default_factory=get_default_config_dir)
    cache_dir: Path = field(default_factory=get_default_cache_dir)

    @property
    def db_path(self) -> Path:
        """Path to SQLite database used for caching and state snapshots."""
        return self.cache_dir / "ec2kit.db"

    def ensure_directories(self) -> None:
        """Ensure necessary configuration and cache directories exist on disk."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure structured logging for ec2kit.

    Diagnostics and logs are sent strictly to stderr to prevent corrupting
    stdout JSON streams.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()

    level = logging.DEBUG if verbose else logging.ERROR
    logger.setLevel(level)

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    formatter = logging.Formatter(
        fmt="[%(levelname)s] %(asctime)s - %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Silence overly verbose external library logs unless in debug mode
    if not verbose:
        logging.getLogger("botocore").setLevel(logging.CRITICAL)
        logging.getLogger("boto3").setLevel(logging.CRITICAL)
        logging.getLogger("urllib3").setLevel(logging.CRITICAL)
        logger.setLevel(logging.CRITICAL)
    else:
        logging.getLogger("botocore").setLevel(logging.INFO)
        logging.getLogger("boto3").setLevel(logging.INFO)

    return logger


def get_logger() -> logging.Logger:
    """Retrieve the main ec2kit logger instance."""
    return logging.getLogger(LOGGER_NAME)
