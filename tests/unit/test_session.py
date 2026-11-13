"""Unit tests for AWS session factory and STS caller identity resolution."""

import boto3
import pytest
from moto import mock_aws

from ec2kit.aws.session import (
    create_session,
    get_available_regions,
    get_caller_identity,
    resolve_region,
)
from ec2kit.exceptions import (
    AuthError,
    ProfileNotFoundError,
    RegionError,
)


def test_create_session_defaults() -> None:
    """Verify session creation with default environment credentials."""
    session = create_session()
    assert isinstance(session, boto3.Session)
    assert session.region_name == "us-east-1"


def test_create_session_explicit_region() -> None:
    """Verify session creation respects explicit region."""
    session = create_session(region="ap-south-1")
    assert session.region_name == "ap-south-1"


def test_create_session_invalid_profile() -> None:
    """Verify requesting a non-existent named profile raises ProfileNotFoundError."""
    with pytest.raises(ProfileNotFoundError) as exc_info:
        create_session(profile="non_existent_profile_xyz")
    assert "non_existent_profile_xyz" in str(exc_info.value)


def test_resolve_region(monkeypatch) -> None:
    """Verify region resolution hierarchy."""
    session = create_session(region="us-west-2")
    # 1. Explicit region has highest precedence
    assert resolve_region(session, explicit_region="sa-east-1") == "sa-east-1"
    # 2. Falls back to session region
    assert resolve_region(session) == "us-west-2"

    # 3. Empty session region raises RegionError
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    empty_session = boto3.Session(region_name=None)
    with pytest.raises(RegionError):
        resolve_region(empty_session)


@mock_aws
def test_get_caller_identity_success() -> None:
    """Verify STS GetCallerIdentity retrieves mocked identity successfully."""
    session = create_session(region="us-east-1")
    identity = get_caller_identity(session)

    assert identity.account_id is not None
    assert len(identity.account_id) == 12
    assert "arn:aws:" in identity.arn
    assert identity.region == "us-east-1"


def test_get_caller_identity_no_credentials(monkeypatch) -> None:
    """Verify clear AuthError when credentials are missing."""
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("AWS_SECURITY_TOKEN", raising=False)

    session = boto3.Session(
        aws_access_key_id=None, aws_secret_access_key=None, region_name="us-east-1"
    )
    with pytest.raises(AuthError) as exc_info:
        get_caller_identity(session)
    assert "credentials" in str(exc_info.value).lower()


@mock_aws
def test_get_available_regions() -> None:
    """Verify available regions discovery returns list of region names."""
    session = create_session(region="us-east-1")
    regions = get_available_regions(session)

    assert isinstance(regions, list)
    assert len(regions) > 0
    assert "us-east-1" in regions
    assert "ap-south-1" in regions
