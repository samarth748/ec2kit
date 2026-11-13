"""Unit tests for ec2kit configuration and logging."""

import logging
from pathlib import Path

from ec2kit.config import (
    Config,
    get_default_cache_dir,
    get_default_config_dir,
    get_logger,
    setup_logging,
)


def test_default_directories(monkeypatch) -> None:
    """Verify default config and cache directories resolve properly."""
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    config_dir = get_default_config_dir()
    cache_dir = get_default_cache_dir()

    assert config_dir == Path.home() / ".config" / "ec2kit"
    assert cache_dir == Path.home() / ".cache" / "ec2kit"


def test_xdg_directories(monkeypatch, tmp_path: Path) -> None:
    """Verify XDG environment variables are respected."""
    custom_cfg = tmp_path / "custom_cfg"
    custom_cache = tmp_path / "custom_cache"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(custom_cfg))
    monkeypatch.setenv("XDG_CACHE_HOME", str(custom_cache))

    assert get_default_config_dir() == custom_cfg / "ec2kit"
    assert get_default_cache_dir() == custom_cache / "ec2kit"


def test_config_instance(tmp_path: Path) -> None:
    """Verify Config dataclass initializes properly and creates directories."""
    cfg = Config(
        profile="dev",
        region="eu-west-1",
        output_json=True,
        quiet=True,
        verbose=True,
        config_dir=tmp_path / "cfg",
        cache_dir=tmp_path / "cache",
    )
    assert cfg.profile == "dev"
    assert cfg.region == "eu-west-1"
    assert cfg.output_json is True
    assert cfg.quiet is True
    assert cfg.verbose is True
    assert cfg.db_path == tmp_path / "cache" / "ec2kit.db"

    cfg.ensure_directories()
    assert cfg.config_dir.exists()
    assert cfg.cache_dir.exists()


def test_setup_logging() -> None:
    """Verify logging setup behaves correctly for normal and verbose modes."""
    log_quiet = setup_logging(verbose=False)
    assert log_quiet.level == logging.CRITICAL

    log_verbose = setup_logging(verbose=True)
    assert log_verbose.level == logging.DEBUG
    assert get_logger().name == "ec2kit"
