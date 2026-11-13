"""Implementation of `ec2kit ls` command for multi-region EC2 discovery."""

from typing import Annotated

import typer

from ec2kit.aws.ec2 import list_instances_multiregion
from ec2kit.aws.session import create_session, get_available_regions, resolve_region
from ec2kit.config import Config, get_logger
from ec2kit.exceptions import EC2KitError
from ec2kit.render.tables import (
    console,
    print_error,
    print_json,
    render_instances_table,
)

logger = get_logger()


def ls_command(
    state: Config,
    all_regions: Annotated[
        bool,
        typer.Option(
            "--all-regions",
            "-a",
            help="Discover instances across all enabled AWS regions.",
        ),
    ] = False,
    state_filter: Annotated[
        str | None,
        typer.Option(
            "--state",
            "-s",
            help="Filter instances by state (e.g. running, stopped, terminated).",
        ),
    ] = None,
    type_filter: Annotated[
        str | None,
        typer.Option(
            "--type",
            "-t",
            help="Filter instances by hardware type (e.g. t3.micro, m5.large).",
        ),
    ] = None,
    name_filter: Annotated[
        str | None,
        typer.Option(
            "--name",
            "-n",
            help="Filter instances by substring match on Name tag.",
        ),
    ] = None,
) -> None:
    """List and inspect AWS EC2 instances across one or all regions."""
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
            "Target regions for ls: %s (all_regions=%s, state=%s, type=%s, name=%s)",
            regions,
            all_regions,
            state_filter,
            type_filter,
            name_filter,
        )

        # Execute scan with optional spinner in interactive mode
        if not state.output_json and not state.quiet:
            with console.status(
                f"[bold cyan]Scanning EC2 instances across {len(regions)} region(s)...[/bold cyan]"
            ):
                result = list_instances_multiregion(
                    session=session,
                    regions=regions,
                    state_filter=state_filter,
                    type_filter=type_filter,
                    name_filter=name_filter,
                )
        else:
            result = list_instances_multiregion(
                session=session,
                regions=regions,
                state_filter=state_filter,
                type_filter=type_filter,
                name_filter=name_filter,
            )

        # Output formatting
        if state.output_json:
            print_json(result)
        elif state.quiet:
            for inst in result.instances:
                typer.echo(f"{inst.instance_id} {inst.region} {inst.state}")
        else:
            render_instances_table(result)

    except EC2KitError as exc:
        logger.debug("EC2KitError in ls_command: %s", exc, exc_info=True)
        if state.output_json:
            print_json({"error": exc.message, "hint": exc.hint})
        else:
            print_error(exc.message, exc.hint)
        raise typer.Exit(code=exc.exit_code) from exc
    except Exception as exc:
        logger.error("Unexpected error in ls_command: %s", exc, exc_info=state.verbose)
        if state.output_json:
            print_json({"error": str(exc), "hint": "Run with --verbose for diagnostic details."})
        else:
            print_error(f"Unexpected error: {exc}", "Run with --verbose for diagnostic details.")
        raise typer.Exit(code=1) from exc
