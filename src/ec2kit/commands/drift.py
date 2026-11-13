"""Implementation of `ec2kit drift` command for Terraform infrastructure drift detection."""

from pathlib import Path
from typing import Annotated

import typer

from ec2kit.analysis.drift_rules import run_drift_analysis
from ec2kit.aws.session import create_session, resolve_region
from ec2kit.config import Config, get_logger
from ec2kit.exceptions import EC2KitError
from ec2kit.render.tables import (
    console,
    print_error,
    print_json,
    render_drift_report,
)

logger = get_logger()


def drift_command(
    state: Config,
    state_file: Annotated[
        Path,
        typer.Option(
            "--state",
            "-s",
            help="Path to terraform.tfstate or `terraform show -json` output file.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ],
) -> None:
    """Detect configuration drift between Terraform state and live AWS infrastructure."""
    try:
        session = create_session(profile=state.profile, region=state.region)
        region = resolve_region(session, explicit_region=state.region)

        logger.debug(
            "Executing drift detection for region=%s against state_file=%s", region, state_file
        )

        if not state.output_json and not state.quiet:
            with console.status(
                "[bold magenta]Analyzing infrastructure drift against Terraform state...[/bold magenta]"
            ):
                report = run_drift_analysis(state_file=state_file, session=session, region=region)
        else:
            report = run_drift_analysis(state_file=state_file, session=session, region=region)

        if state.output_json:
            print_json(report)
        elif not state.quiet:
            render_drift_report(report)
        else:
            typer.echo(
                f"drift_count={report.total_drifts} missing={report.missing_in_aws_count} unmanaged={report.unmanaged_in_tf_count} modified={report.modified_count}"
            )

    except EC2KitError as exc:
        logger.debug("EC2KitError caught in drift_command", exc_info=True)
        if state.output_json:
            print_json({"error": exc.message, "hint": exc.hint})
        else:
            print_error(exc.message, exc.hint)
        raise typer.Exit(code=exc.exit_code) from exc
    except Exception as exc:
        logger.error("Unexpected error occurred in drift_command: %s", exc, exc_info=state.verbose)
        if state.output_json:
            print_json({"error": str(exc)})
        else:
            print_error(f"Unexpected error: {exc}")
        raise typer.Exit(code=1) from exc
