"""Implementation of `ec2kit policy check` command for infrastructure governance validation."""

from pathlib import Path
from typing import Annotated

import typer

from ec2kit.analysis.policy_rules import evaluate_policies
from ec2kit.aws.session import create_session, resolve_region
from ec2kit.config import Config, get_logger
from ec2kit.exceptions import EC2KitError
from ec2kit.render.tables import (
    console,
    print_error,
    print_json,
    render_policy_evaluation,
)

logger = get_logger()


def policy_check_command(
    state: Config,
    policy_file: Annotated[
        Path,
        typer.Option(
            "--policy",
            "-p",
            help="Path to YAML policy document defining governance rules.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ] = Path("policy.yaml"),
) -> None:
    """Validate AWS resources against organizational policy constraints (policy.yaml)."""
    try:
        session = create_session(profile=state.profile, region=state.region)
        region = resolve_region(session, explicit_region=state.region)

        logger.debug("Checking policies from '%s' against region '%s'", policy_file, region)

        if not state.output_json and not state.quiet:
            with console.status(
                "[bold blue]Evaluating cloud resources against governance policies...[/bold blue]"
            ):
                result = evaluate_policies(session=session, region=region, policy_file=policy_file)
        else:
            result = evaluate_policies(session=session, region=region, policy_file=policy_file)

        if state.output_json:
            print_json(result)
        elif not state.quiet:
            render_policy_evaluation(result)
        else:
            status = (
                "compliant"
                if result.compliant
                else f"non_compliant violations={result.total_violations}"
            )
            typer.echo(status)

        if not result.compliant:
            raise typer.Exit(code=1)

    except EC2KitError as exc:
        logger.debug("EC2KitError caught in policy_check_command", exc_info=True)
        if state.output_json:
            print_json({"error": exc.message, "hint": exc.hint})
        else:
            print_error(exc.message, exc.hint)
        raise typer.Exit(code=exc.exit_code) from exc
    except typer.Exit:
        raise
    except Exception as exc:
        logger.error("Unexpected error in policy_check_command: %s", exc, exc_info=state.verbose)
        if state.output_json:
            print_json({"error": str(exc)})
        else:
            print_error(f"Unexpected error: {exc}")
        raise typer.Exit(code=1) from exc
