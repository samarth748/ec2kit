"""Integration tests for ec2kit CLI foundation commands."""

import json
import re

from moto import mock_aws
from typer.testing import CliRunner

from ec2kit import __version__
from ec2kit.cli import app

runner = CliRunner(env={"COLUMNS": "160", "NO_COLOR": "1", "TERM": "dumb"})


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from terminal output."""
    return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)


def test_cli_help() -> None:
    """Verify `ec2kit --help` displays expected overview and options."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    clean = strip_ansi(result.stdout)
    assert "Developer CLI for discovering, managing" in clean
    assert "--profile" in clean
    assert "--region" in clean
    assert "--json" in clean
    assert "--quiet" in clean
    assert "--verbose" in clean
    assert "info" in clean


def test_cli_version() -> None:
    """Verify `ec2kit --version` and `-V` print version string."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"ec2kit version {__version__}" in result.stdout

    result_short = runner.invoke(app, ["-V"])
    assert result_short.exit_code == 0
    assert f"ec2kit version {__version__}" in result_short.stdout


@mock_aws
def test_cli_info_table_output() -> None:
    """Verify `ec2kit info` produces Rich formatted output when credentials are valid."""
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0
    assert "AWS Account ID" in result.stdout
    assert "Caller ARN" in result.stdout
    assert "Target Region" in result.stdout


@mock_aws
def test_cli_info_json_output() -> None:
    """Verify `ec2kit --json info` outputs valid machine-readable JSON."""
    result = runner.invoke(app, ["--json", "info"])
    assert result.exit_code == 0

    # Ensure stdout is valid JSON without extraneous text
    data = json.loads(result.stdout)
    assert "identity" in data
    assert "account_id" in data["identity"]
    assert "arn" in data["identity"]
    assert "available_regions" in data
    assert "database_path" in data
    assert isinstance(data["available_regions"], list)


@mock_aws
def test_cli_info_quiet_output() -> None:
    """Verify `ec2kit --quiet info` outputs only minimal output."""
    result = runner.invoke(app, ["--quiet", "info"])
    assert result.exit_code == 0
    # In quiet mode, should be a single line containing account and region
    lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    assert len(lines) == 1
    parts = lines[0].split()
    assert len(parts) == 2
    assert len(parts[0]) == 12  # 12-digit AWS account ID


def test_cli_info_invalid_profile() -> None:
    """Verify `ec2kit --profile <nonexistent> info` yields exit code 1 with clean error."""
    result = runner.invoke(app, ["--profile", "totally_bogus_profile", "info"])
    assert result.exit_code == 1
    assert "totally_bogus_profile" in result.stderr or "totally_bogus_profile" in result.stdout
    assert "Hint:" in (result.stderr + result.stdout)


def test_cli_info_invalid_profile_json() -> None:
    """Verify `ec2kit --json --profile <nonexistent> info` outputs error JSON."""
    result = runner.invoke(app, ["--json", "--profile", "bogus_profile", "info"])
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert "error" in data
    assert "bogus_profile" in data["error"]
