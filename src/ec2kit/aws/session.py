"""AWS session factory and credential provider integration.

Adheres strictly to boto3's native credential resolution chain and ensures
credentials are never stored, logged, or printed.
"""

import boto3
from botocore.exceptions import (
    ClientError,
    NoCredentialsError,
    NoRegionError,
    PartialCredentialsError,
    ProfileNotFound,
)

from ec2kit.config import get_logger
from ec2kit.exceptions import (
    AuthError,
    PermissionDeniedError,
    ProfileNotFoundError,
    RegionError,
)
from ec2kit.models import IdentityInfo

logger = get_logger()


def create_session(
    profile: str | None = None,
    region: str | None = None,
) -> boto3.Session:
    """Initialize a boto3 Session with profile and region resolution.

    Relies on boto3's native credential chain:
    1. Explicit parameters
    2. Environment variables (AWS_ACCESS_KEY_ID, AWS_PROFILE, AWS_DEFAULT_REGION, etc.)
    3. ~/.aws/credentials and ~/.aws/config (Named profiles, SSO, AssumeRole)
    4. IAM Instance Roles / ECS Task Roles / Container Metadata
    """
    logger.debug("Initializing AWS session: profile=%s, region=%s", profile, region)

    try:
        session = boto3.Session(
            profile_name=profile,
            region_name=region,
        )
        return session
    except ProfileNotFound as exc:
        logger.error("AWS Profile '%s' not found", profile)
        raise ProfileNotFoundError(profile or "") from exc
    except Exception as exc:
        logger.error("Failed to initialize AWS session: %s", exc)
        raise AuthError(f"Failed to initialize AWS session: {exc}") from exc


def resolve_region(session: boto3.Session, explicit_region: str | None = None) -> str:
    """Resolve active target region, falling back to session region or us-east-1."""
    if explicit_region:
        return explicit_region
    if session.region_name:
        return session.region_name
    raise RegionError(
        message="No AWS region specified or configured.",
        hint="Pass --region (e.g. --region us-east-1) or configure `aws configure set region <region>`.",
    )


def get_caller_identity(session: boto3.Session) -> IdentityInfo:
    """Retrieve AWS STS caller identity securely.

    Validates that credentials are valid and active without exposing secrets.
    """
    logger.debug("Verifying AWS caller identity via STS GetCallerIdentity")
    try:
        sts_client = session.client("sts")
        response = sts_client.get_caller_identity()

        resolved_region = session.region_name or "us-east-1"

        return IdentityInfo(
            account_id=str(response.get("Account")),
            arn=str(response.get("Arn")),
            user_id=str(response.get("UserId")),
            profile=session.profile_name,
            region=resolved_region,
        )
    except ProfileNotFound as exc:
        raise ProfileNotFoundError(session.profile_name or "") from exc
    except (NoCredentialsError, PartialCredentialsError) as exc:
        logger.error("No valid AWS credentials found: %s", exc)
        raise AuthError(
            message="No valid AWS credentials found in your environment or configuration.",
            hint="Run `aws configure` or set AWS_ACCESS_KEY_ID & AWS_SECRET_ACCESS_KEY.",
        ) from exc
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        msg = exc.response.get("Error", {}).get("Message", str(exc))
        logger.error("STS ClientError [%s]: %s", code, msg)

        if code in ("ExpiredToken", "ExpiredTokenException"):
            raise AuthError(
                message="Your AWS temporary credentials or SSO session have expired.",
                hint="Refresh credentials via `aws sso login` or request a new STS session token.",
            ) from exc
        if code in ("AccessDenied", "UnauthorizedOperation"):
            raise PermissionDeniedError(
                action="sts:GetCallerIdentity",
                details=msg,
            ) from exc
        raise AuthError(f"AWS authentication failed: {msg}") from exc
    except NoRegionError as exc:
        raise RegionError("No default AWS region configured.") from exc


def get_available_regions(session: boto3.Session, service_name: str = "ec2") -> list[str]:
    """Retrieve available regions for the specified service.

    Queries EC2 DescribeRegions when possible to return enabled regions for the account,
    falling back to boto3's static partition regions if API call is restricted.
    """
    try:
        ec2_client = session.client("ec2")
        response = ec2_client.describe_regions(AllRegions=False)
        regions = [r["RegionName"] for r in response.get("Regions", []) if "RegionName" in r]
        return sorted(regions)
    except Exception as exc:
        logger.debug(
            "EC2 describe_regions failed (%s), falling back to session partition regions", exc
        )
        fallback = session.get_available_regions(service_name)
        return sorted(fallback)
