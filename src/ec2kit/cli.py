"""Main CLI entrypoint for ec2kit."""

import os
import sys
from pathlib import Path

import typer
from rich.console import Console

from ec2kit import __app_name__, __version__
from ec2kit.aws.session import create_session, get_available_regions, get_caller_identity
from ec2kit.config import Config, get_logger, setup_logging
from ec2kit.exceptions import EC2KitError
from ec2kit.models import InfoResult
from ec2kit.render.tables import print_error, print_json, render_info_panel

app = typer.Typer(
    name=__app_name__,
    help="Developer CLI for discovering, managing, analyzing and understanding AWS EC2 infrastructure.",
    no_args_is_help=True,
    add_completion=False,
)

state: Config = Config()
err_console = Console(stderr=True)


def version_callback(value: bool) -> None:
    """Print the version of ec2kit and exit."""
    if value:
        typer.echo(f"{__app_name__} version {__version__}")
        raise typer.Exit(0)


@app.callback()
def main_callback(
    profile: str | None = typer.Option(
        None,
        "--profile",
        "-p",
        help="AWS named profile to use for credentials and configuration.",
    ),
    region: str | None = typer.Option(
        None,
        "--region",
        "-r",
        help="AWS region to target (overrides profile/environment defaults).",
    ),
    output_json: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output machine-readable JSON to stdout.",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Suppress non-essential output and decorative formatting.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable detailed diagnostic logging to stderr.",
    ),
    _version: bool | None = typer.Option(
        None,
        "--version",
        "-V",
        help="Show ec2kit version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """Global configuration handler for all ec2kit commands."""
    state.profile = profile
    state.region = region
    state.output_json = output_json
    state.quiet = quiet
    state.verbose = verbose

    setup_logging(verbose=verbose)
    logger = get_logger()
    logger.debug(
        "CLI initialized: profile=%s, region=%s, json=%s, quiet=%s, verbose=%s",
        profile,
        region,
        output_json,
        quiet,
        verbose,
    )


@app.command("info")
def info_command() -> None:
    """Display authenticated AWS session details, caller identity, and local environment."""
    logger = get_logger()
    try:
        session = create_session(profile=state.profile, region=state.region)
        identity = get_caller_identity(session)
        regions = get_available_regions(session)

        # Collect active AWS environment variables (names only, never secret values)
        aws_env_keys = [
            "AWS_PROFILE",
            "AWS_DEFAULT_REGION",
            "AWS_REGION",
            "AWS_CONFIG_FILE",
            "AWS_SHARED_CREDENTIALS_FILE",
        ]
        active_env = {k: os.environ[k] for k in aws_env_keys if k in os.environ}

        result = InfoResult(
            identity=identity,
            available_regions=regions,
            config_dir=str(state.config_dir),
            cache_dir=str(state.cache_dir),
            database_path=str(state.db_path),
            environment=active_env,
        )

        if state.output_json:
            print_json(result)
        elif not state.quiet:
            render_info_panel(result.model_dump())
        else:
            # In quiet mode, print minimal essential identifier (Account ID and region)
            typer.echo(f"{identity.account_id} {identity.region}")

    except EC2KitError as exc:
        logger.debug("EC2KitError caught in info_command", exc_info=True)
        if state.output_json:
            print_json({"error": exc.message, "hint": exc.hint})
        else:
            print_error(exc.message, exc.hint)
        raise typer.Exit(code=exc.exit_code) from exc
    except Exception as exc:
        logger.error("Unexpected error occurred: %s", exc, exc_info=state.verbose)
        if state.output_json:
            print_json({"error": str(exc), "hint": "Run with --verbose for more details."})
        else:
            print_error(f"Unexpected error: {exc}", "Run with --verbose for diagnostic trace.")
        raise typer.Exit(code=1) from exc


@app.command("ls")
def ls(
    all_regions: bool = typer.Option(
        False,
        "--all-regions",
        "-a",
        help="Discover instances across all enabled AWS regions.",
    ),
    state_filter: str | None = typer.Option(
        None,
        "--state",
        "-s",
        help="Filter instances by state (e.g. running, stopped, terminated).",
    ),
    type_filter: str | None = typer.Option(
        None,
        "--type",
        "-t",
        help="Filter instances by hardware type (e.g. t3.micro, m5.large).",
    ),
    name_filter: str | None = typer.Option(
        None,
        "--name",
        "-n",
        help="Filter instances by substring match on Name tag.",
    ),
) -> None:
    """List EC2 instances with state, network, and placement details."""
    from ec2kit.commands.ls import ls_command

    ls_command(
        state=state,
        all_regions=all_regions,
        state_filter=state_filter,
        type_filter=type_filter,
        name_filter=name_filter,
    )


@app.command("cost")
def cost(
    all_regions: bool = typer.Option(
        False,
        "--all-regions",
        "-a",
        help="Analyze cost and utilization across all enabled AWS regions.",
    ),
    idle_only: bool = typer.Option(
        False,
        "--idle",
        help="Filter analysis to show only idle instances.",
    ),
    rightsize_only: bool = typer.Option(
        False,
        "--rightsize",
        help="Filter analysis to show only right-sizing recommendations.",
    ),
    orphaned_only: bool = typer.Option(
        False,
        "--orphaned",
        help="Filter analysis to show only orphaned resources (unattached EBS / idle EIPs).",
    ),
    days: int = typer.Option(
        7,
        "--days",
        "-d",
        help="CloudWatch metrics observation window in days (default: 7).",
    ),
    refresh_pricing: bool = typer.Option(
        False,
        "--refresh-pricing",
        help="Bypass local cache and query fresh on-demand rates from AWS Pricing API.",
    ),
) -> None:
    """Analyze EC2 running costs, detect idle instances, right-sizing opportunities, and orphaned resources."""
    from ec2kit.commands.cost import cost_command

    cost_command(
        state=state,
        all_regions=all_regions,
        idle_only=idle_only,
        rightsize_only=rightsize_only,
        orphaned_only=orphaned_only,
        days=days,
        refresh_pricing=refresh_pricing,
    )


@app.command("scan")
def scan(
    vpc_id: str | None = typer.Option(
        None,
        "--vpc",
        help="Target a specific VPC by ID (e.g. vpc-0123456789abcdef0).",
    ),
    all_vpcs: bool = typer.Option(
        False,
        "--all-vpcs",
        help="Scan all VPCs in the target region.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="File path to save the generated Mermaid architecture diagram (.mmd).",
    ),
) -> None:
    """Discover VPC network topology and generate Mermaid architecture diagrams."""
    from ec2kit.commands.scan import scan_command

    scan_command(
        state=state,
        vpc_id=vpc_id,
        all_vpcs=all_vpcs,
        output_path=output,
    )


@app.command("security")
def security(
    severity: str | None = typer.Option(
        None,
        "--severity",
        "-s",
        help="Filter findings by minimum severity threshold: CRITICAL, HIGH, MEDIUM, LOW, INFO.",
    ),
    all_regions: bool = typer.Option(
        False,
        "--all-regions",
        "-a",
        help="Audit security across all enabled AWS regions.",
    ),
) -> None:
    """Scan EC2 instances, Security Groups, EBS encryption, and IMDS configurations for vulnerabilities."""
    from ec2kit.commands.security import security_command

    security_command(
        state=state,
        severity=severity,
        all_regions=all_regions,
    )


@app.command("drift")
def drift(
    state_file: Path = typer.Option(
        ...,
        "--state",
        "-s",
        help="Path to terraform.tfstate or `terraform show -json` output file.",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
) -> None:
    """Detect configuration drift between Terraform state and live AWS infrastructure."""
    from ec2kit.commands.drift import drift_command

    drift_command(state=state, state_file=state_file)


export_app = typer.Typer(
    name="export",
    help="Export discovered infrastructure to external configuration formats (Terraform HCL).",
    no_args_is_help=True,
)
app.add_typer(export_app, name="export")


@export_app.command("terraform")
def export_terraform(
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Target directory to write Terraform HCL files (default: ./terraform).",
    ),
    vpc_id: str | None = typer.Option(
        None,
        "--vpc",
        help="Target a specific VPC by ID (e.g. vpc-0123456789abcdef0).",
    ),
    to_stdout: bool = typer.Option(
        False,
        "--stdout",
        help="Print generated main.tf HCL directly to stdout without writing files.",
    ),
) -> None:
    """Export AWS infrastructure to reviewable Terraform HCL configuration."""
    from ec2kit.commands.export import export_terraform_command

    export_terraform_command(
        state=state,
        output_dir=output_dir,
        vpc_id=vpc_id,
        to_stdout=to_stdout,
    )


@app.command("start")
def start_instance(
    instance_id: str = typer.Argument(..., help="EC2 Instance ID (e.g. i-1234567890abcdef0)."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Validate permissions via AWS DryRun without modifying instance."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip confirmation prompt and immediately start instance."
    ),
) -> None:
    """Start a stopped EC2 instance with blast-radius preview."""
    from ec2kit.commands.ops import start_instance_command

    start_instance_command(state=state, instance_id=instance_id, dry_run=dry_run, yes=yes)


@app.command("stop")
def stop_instance(
    instance_id: str = typer.Argument(..., help="EC2 Instance ID (e.g. i-1234567890abcdef0)."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Validate permissions via AWS DryRun without modifying instance."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip confirmation prompt and immediately stop instance."
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Force stopping instance without waiting for clean OS flush."
    ),
) -> None:
    """Stop a running EC2 instance with blast-radius impact analysis."""
    from ec2kit.commands.ops import stop_instance_command

    stop_instance_command(
        state=state, instance_id=instance_id, dry_run=dry_run, yes=yes, force=force
    )


@app.command("reboot")
def reboot_instance(
    instance_id: str = typer.Argument(..., help="EC2 Instance ID (e.g. i-1234567890abcdef0)."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Validate permissions via AWS DryRun without modifying instance."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip confirmation prompt and immediately reboot instance."
    ),
) -> None:
    """Reboot an EC2 instance with blast-radius preview."""
    from ec2kit.commands.ops import reboot_instance_command

    reboot_instance_command(state=state, instance_id=instance_id, dry_run=dry_run, yes=yes)


@app.command("terminate")
def terminate_instance(
    instance_id: str = typer.Argument(..., help="EC2 Instance ID (e.g. i-1234567890abcdef0)."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Validate permissions via AWS DryRun without modifying instance."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip confirmation prompt and immediately terminate instance."
    ),
) -> None:
    """Permanently terminate an EC2 instance with critical blast-radius warning."""
    from ec2kit.commands.ops import terminate_instance_command

    terminate_instance_command(state=state, instance_id=instance_id, dry_run=dry_run, yes=yes)


policy_app = typer.Typer(
    name="policy",
    help="Evaluate infrastructure resources against declarative governance policies.",
    no_args_is_help=True,
)
app.add_typer(policy_app, name="policy")


@policy_app.command("check")
def policy_check(
    policy_file: Path = typer.Option(
        Path("policy.yaml"),
        "--policy",
        "-p",
        help="Path to YAML policy document defining governance rules.",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
) -> None:
    """Evaluate AWS resources against organizational policy constraints."""
    from ec2kit.commands.policy import policy_check_command

    policy_check_command(state=state, policy_file=policy_file)


def main() -> None:
    """Entry point wrapper with exception safety."""
    try:
        app()
    except SystemExit:
        raise
    except Exception as exc:
        print_error(f"Fatal error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
