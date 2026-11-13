"""Unit tests for ec2kit custom exceptions."""

from ec2kit.exceptions import (
    AuthError,
    ConfigError,
    EC2KitError,
    PermissionDeniedError,
    ProfileNotFoundError,
    ResourceNotFoundError,
    ThrottlingError,
)


def test_base_exception_str() -> None:
    """Verify base exception formatting with and without hint."""
    err_without_hint = EC2KitError("Something failed")
    assert str(err_without_hint) == "Something failed"
    assert err_without_hint.exit_code == 1

    err_with_hint = EC2KitError("Something failed", hint="Do this instead")
    assert "Something failed" in str(err_with_hint)
    assert "Hint: Do this instead" in str(err_with_hint)


def test_profile_not_found_error() -> None:
    """Verify ProfileNotFoundError contains profile name and guidance."""
    err = ProfileNotFoundError("production-us")
    assert "production-us" in err.message
    assert "aws configure list-profiles" in (err.hint or "")
    assert isinstance(err, AuthError)
    assert isinstance(err, EC2KitError)


def test_permission_denied_error() -> None:
    """Verify PermissionDeniedError formats action and resource clearly."""
    err = PermissionDeniedError(
        action="ec2:DescribeInstances", resource="arn:aws:ec2:us-east-1:123:instance/i-1"
    )
    assert "ec2:DescribeInstances" in err.message
    assert "arn:aws:ec2:us-east-1:123:instance/i-1" in err.message
    assert "permissions.md" in (err.hint or "")


def test_resource_not_found_error() -> None:
    """Verify ResourceNotFoundError includes resource type and identifier."""
    err = ResourceNotFoundError(resource_type="VPC", resource_id="vpc-12345678")
    assert "VPC" in err.message
    assert "vpc-12345678" in err.message


def test_throttling_error() -> None:
    """Verify ThrottlingError properties."""
    err = ThrottlingError()
    assert "rate limit" in err.message.lower()
    assert "exponential backoff" in (err.hint or "").lower()


def test_config_error() -> None:
    """Verify ConfigError returns exit code 2."""
    err = ConfigError("Invalid argument")
    assert err.exit_code == 2
