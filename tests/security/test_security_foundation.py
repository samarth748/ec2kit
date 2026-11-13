"""Security tests ensuring credentials are never leaked, stored, or exposed."""

from moto import mock_aws
from typer.testing import CliRunner

from ec2kit.cli import app

runner = CliRunner()


@mock_aws
def test_no_credentials_in_stdout_or_stderr(monkeypatch) -> None:
    """Verify secret keys and session tokens never appear in CLI output."""
    secret_key = "SuperSecretAWSKeyDoNotLeak"
    session_token = "SuperSecretSessionTokenDoNotLeak"

    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", secret_key)
    monkeypatch.setenv("AWS_SESSION_TOKEN", session_token)

    # 1. Standard info command
    result = runner.invoke(app, ["info"])
    assert secret_key not in result.stdout
    assert secret_key not in result.stderr
    assert session_token not in result.stdout
    assert session_token not in result.stderr

    # 2. JSON info command
    result_json = runner.invoke(app, ["--json", "info"])
    assert secret_key not in result_json.stdout
    assert session_token not in result_json.stdout

    # 3. Verbose debug mode
    result_verbose = runner.invoke(app, ["--verbose", "info"])
    assert secret_key not in result_verbose.stdout
    assert secret_key not in result_verbose.stderr
    assert session_token not in result_verbose.stdout
    assert session_token not in result_verbose.stderr
