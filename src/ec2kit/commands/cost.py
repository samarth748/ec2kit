"""Implementation of `ec2kit cost` command for cloud cost intelligence and optimization."""

from typing import Annotated

import typer

from ec2kit.analysis.cost_rules import run_cost_analysis
from ec2kit.aws.ec2 import list_instances_multiregion
from ec2kit.aws.session import create_session, get_available_regions, resolve_region
from ec2kit.config import Config, get_logger
from ec2kit.exceptions import EC2KitError
from ec2kit.render.tables import (
    console,
    print_error,
    print_json,
    render_cost_analysis,
)
from ec2kit.storage.cache import PricingCache

logger = get_logger()


def cost_command(
    state: Config,
    all_regions: Annotated[
        bool,
        typer.Option(
            "--all-regions",
            "-a",
            help="Analyze cost and utilization across all enabled AWS regions.",
        ),
    ] = False,
    idle_only: Annotated[
        bool,
        typer.Option(
            "--idle",
            help="Filter analysis to show only idle instances.",
        ),
    ] = False,
    rightsize_only: Annotated[
        bool,
        typer.Option(
            "--rightsize",
            help="Filter analysis to show only right-sizing recommendations.",
        ),
    ] = False,
    orphaned_only: Annotated[
        bool,
        typer.Option(
            "--orphaned",
            help="Filter analysis to show only orphaned resources (unattached EBS / idle EIPs).",
        ),
    ] = False,
    days: Annotated[
        int,
        typer.Option(
            "--days",
            "-d",
            help="CloudWatch metrics observation window in days (default: 7).",
        ),
    ] = 7,
    refresh_pricing: Annotated[
        bool,
        typer.Option(
            "--refresh-pricing",
            help="Bypass local cache and query fresh on-demand rates from AWS Pricing API.",
        ),
    ] = False,
) -> None:
    """Analyze EC2 running costs, detect idle instances, right-sizing opportunities, and orphaned resources."""
    try:
        session = create_session(profile=state.profile, region=state.region)
        cache = PricingCache(state.db_path)

        if refresh_pricing:
            cache.clear()

        # Determine target regions
        if all_regions:
            regions = get_available_regions(session, service_name="ec2")
            if not regions:
                target_reg = resolve_region(session, explicit_region=state.region)
                regions = [target_reg]
        else:
            target_reg = resolve_region(session, explicit_region=state.region)
            regions = [target_reg]

        logger.debug(
            "Running cost analysis on regions: %s (days=%d, refresh=%s)",
            regions,
            days,
            refresh_pricing,
        )

        # 1. Discover all EC2 instances across target regions
        if not state.output_json and not state.quiet:
            with console.status(
                f"[bold cyan]Scanning instances and CloudWatch telemetry ({days}d window)...[/bold cyan]"
            ):
                instance_res = list_instances_multiregion(session=session, regions=regions)
                analysis = run_cost_analysis(
                    session=session,
                    instances=instance_res.instances,
                    regions=regions,
                    days=days,
                    cache=cache,
                    force_refresh=refresh_pricing,
                )
        else:
            instance_res = list_instances_multiregion(session=session, regions=regions)
            analysis = run_cost_analysis(
                session=session,
                instances=instance_res.instances,
                regions=regions,
                days=days,
                cache=cache,
                force_refresh=refresh_pricing,
            )

        # Determine active view filter
        view_filter: str | None = None
        if idle_only:
            view_filter = "idle"
        elif rightsize_only:
            view_filter = "rightsize"
        elif orphaned_only:
            view_filter = "orphaned"

        # Output formatting
        if state.output_json:
            print_json(analysis)
        elif state.quiet:
            # Minimal output: print total estimated monthly cost and count of recommendations
            opp_count = (
                len(analysis.idle_instances)
                + len(analysis.recommendations)
                + len(analysis.orphaned_resources)
            )
            typer.echo(f"${analysis.summary.total_estimated_monthly:,.2f} {opp_count}")
        else:
            render_cost_analysis(analysis, view_filter=view_filter)

    except EC2KitError as exc:
        logger.debug("EC2KitError in cost_command: %s", exc, exc_info=True)
        if state.output_json:
            print_json({"error": exc.message, "hint": exc.hint})
        else:
            print_error(exc.message, exc.hint)
        raise typer.Exit(code=exc.exit_code) from exc
    except Exception as exc:
        logger.error("Unexpected error in cost_command: %s", exc, exc_info=state.verbose)
        if state.output_json:
            print_json({"error": str(exc), "hint": "Run with --verbose for diagnostic details."})
        else:
            print_error(f"Unexpected error: {exc}", "Run with --verbose for diagnostic details.")
        raise typer.Exit(code=1) from exc
