"""Implementation of `ec2kit security` command for AWS infrastructure security posture scanning."""

from typing import Annotated

import typer

from ec2kit.analysis.security_rules import run_security_scan
from ec2kit.aws.session import create_session, get_available_regions, resolve_region
from ec2kit.config import Config, get_logger
from ec2kit.exceptions import EC2KitError
from ec2kit.render.tables import (
    console,
    print_error,
    print_json,
    render_security_findings,
)

logger = get_logger()


def security_command(
    state: Config,
    severity: Annotated[
        str | None,
        typer.Option(
            "--severity",
            "-s",
            help="Filter findings by minimum severity threshold: CRITICAL, HIGH, MEDIUM, LOW, INFO.",
        ),
    ] = None,
    all_regions: Annotated[
        bool,
        typer.Option(
            "--all-regions",
            "-a",
            help="Audit security across all enabled AWS regions.",
        ),
    ] = False,
) -> None:
    """Scan EC2 instances, Security Groups, EBS encryption, and IMDS configurations for vulnerabilities."""
    try:
        session = create_session(profile=state.profile, region=state.region)

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
            "Executing security audit across regions: %s (min_severity=%s)",
            regions,
            severity,
        )

        if not state.output_json and not state.quiet:
            with console.status("[bold red]Auditing infrastructure security posture...[/bold red]"):
                scan_result = run_security_scan(
                    session=session,
                    regions=regions,
                    min_severity=severity,
                )
        else:
            scan_result = run_security_scan(
                session=session,
                regions=regions,
                min_severity=severity,
            )

        # Output modes
        if state.output_json:
            print_json(scan_result)
        elif state.quiet:
            for f in scan_result.findings:
                typer.echo(f"{f.severity} {f.finding_id} {f.resource_id}")
        else:
            render_security_findings(scan_result)

    except EC2KitError as exc:
        logger.debug("EC2KitError in security_command: %s", exc, exc_info=True)
        if state.output_json:
            print_json({"error": exc.message, "hint": exc.hint})
        else:
            print_error(exc.message, exc.hint)
        raise typer.Exit(code=exc.exit_code) from exc
    except Exception as exc:
        logger.error("Unexpected error in security_command: %s", exc, exc_info=state.verbose)
        if state.output_json:
            print_json({"error": str(exc), "hint": "Run with --verbose for diagnostic details."})
        else:
            print_error(f"Unexpected error: {exc}", "Run with --verbose for diagnostic details.")
        raise typer.Exit(code=1) from exc
