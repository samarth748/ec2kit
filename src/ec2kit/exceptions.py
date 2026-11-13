"""Centralized exception hierarchy for ec2kit.

Every custom exception provides human-readable guidance, actionable recommendations,
and avoids exposing sensitive credentials or tokens.
"""


class EC2KitError(Exception):
    """Base exception for all ec2kit errors."""

    def __init__(self, message: str, hint: str | None = None, exit_code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.exit_code = exit_code

    def __str__(self) -> str:
        if self.hint:
            return f"{self.message}\nHint: {self.hint}"
        return self.message


class ConfigError(EC2KitError):
    """Raised when configuration or options are invalid."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(
            message=message,
            hint=hint or "Verify your command-line arguments and local ec2kit settings.",
            exit_code=2,
        )


class AuthError(EC2KitError):
    """Raised when AWS credentials or authentication fail."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(
            message=message,
            hint=hint
            or "Check your ~/.aws/credentials, ~/.aws/config, or run `aws configure` / `aws sso login`.",
            exit_code=1,
        )


class ProfileNotFoundError(AuthError):
    """Raised when a requested AWS profile does not exist."""

    def __init__(self, profile_name: str) -> None:
        super().__init__(
            message=f"AWS profile '{profile_name}' was not found in your AWS configuration.",
            hint="List existing profiles with `aws configure list-profiles` or check ~/.aws/config.",
        )


class RegionError(EC2KitError):
    """Raised when an AWS region is missing or invalid."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(
            message=message,
            hint=hint
            or "Specify a region via --region flag, AWS_DEFAULT_REGION env var, or AWS profile config.",
            exit_code=1,
        )


class PermissionDeniedError(EC2KitError):
    """Raised when an AWS IAM operation fails with AccessDenied or UnauthorizedOperation."""

    def __init__(
        self, action: str, resource: str | None = None, details: str | None = None
    ) -> None:
        res_text = f" on resource '{resource}'" if resource else ""
        msg = f"AWS IAM permission denied for action '{action}'{res_text}."
        if details:
            msg += f" Details: {details}"
        super().__init__(
            message=msg,
            hint=f"Ensure your IAM role or user has permissions for '{action}'. See docs/permissions.md for guidance.",
            exit_code=1,
        )


class ResourceNotFoundError(EC2KitError):
    """Raised when a requested AWS resource cannot be found."""

    def __init__(self, resource_type: str, resource_id: str) -> None:
        super().__init__(
            message=f"The {resource_type} '{resource_id}' was not found.",
            hint="Check that the ID is spelled correctly and exists in the target region.",
            exit_code=1,
        )


class ThrottlingError(EC2KitError):
    """Raised when AWS API requests are throttled (RequestLimitExceeded)."""

    def __init__(self, message: str = "AWS API rate limit exceeded.") -> None:
        super().__init__(
            message=message,
            hint="Requests were throttled by AWS. Retrying with exponential backoff may resolve this.",
            exit_code=1,
        )


class AWSClientError(EC2KitError):
    """Generic wrapper for AWS client communication errors."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(
            message=message,
            hint=hint or "Check your internet connection and AWS service health status.",
            exit_code=1,
        )
