"""Pytest test configuration and fixtures for ec2kit.

Ensures no real AWS credentials or live environments are contacted during testing.
"""

from collections.abc import Generator

import pytest
from moto import mock_aws


@pytest.fixture(autouse=True)
def aws_credentials_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Mock AWS credentials in the environment so tests never hit real infrastructure."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing_mock_access_key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing_mock_secret_key")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing_mock_security_token")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing_mock_session_token")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    # Point away from user's local ~/.aws files during tests
    monkeypatch.setenv("AWS_CONFIG_FILE", "/dev/null")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/dev/null")
    # Prevent AWS Pricing API network calls during offline tests
    monkeypatch.setattr("ec2kit.aws.pricing.query_aws_pricing_api", lambda *_args, **_kwargs: None)
    yield


@pytest.fixture
def mocked_aws() -> Generator[None, None, None]:
    """Activate moto AWS mocking for the duration of a test."""
    with mock_aws():
        yield
