"""Implementation of `ec2kit scan` command for VPC discovery and Mermaid architecture generation."""

from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.syntax import Syntax

from ec2kit.aws.session import create_session, resolve_region
from ec2kit.aws.vpc import discover_vpc_topologies
from ec2kit.config import Config, get_logger
from ec2kit.exceptions import EC2KitError
from ec2kit.models import ScanResult
from ec2kit.render.mermaid import generate_mermaid_diagram
from ec2kit.render.tables import console, print_error, print_json

logger = get_logger()


def scan_command(
    state: Config,
    vpc_id: Annotated[
        str | None,
        typer.Option(
            "--vpc",
            help="Target a specific VPC by ID (e.g. vpc-0123456789abcdef0).",
        ),
    ] = None,
    all_vpcs: Annotated[
        bool,
        typer.Option(
            "--all-vpcs",
            help="Scan all VPCs in the target region.",
        ),
    ] = False,
    output_path: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="File path to save the generated Mermaid architecture diagram (.mmd).",
        ),
    ] = None,
) -> None:
    """Discover VPC network topology and generate Mermaid architecture diagrams."""
    try:
        session = create_session(profile=state.profile, region=state.region)
        region = resolve_region(session, explicit_region=state.region)

        logger.debug(
            "Executing scan in %s (vpc_id=%s, all_vpcs=%s, output=%s)",
            region,
            vpc_id,
            all_vpcs,
            output_path,
        )

        topologies = discover_vpc_topologies(
            session=session,
            region=region,
            target_vpc_id=vpc_id,
        )

        mermaid_code = generate_mermaid_diagram(topologies)

        total_subnets = sum(len(t.subnets) for t in topologies)
        total_instances = sum(len(t.instances) for t in topologies)

        scan_result = ScanResult(
            region=region,
            topologies=topologies,
            mermaid_diagram=mermaid_code,
            total_vpcs=len(topologies),
            total_subnets=total_subnets,
            total_instances=total_instances,
        )

        # Handle file export if requested
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(mermaid_code)
            if not state.quiet and not state.output_json:
                console.print(
                    f"[bold green]✓[/bold green] Architecture diagram exported to [cyan]{output_path}[/cyan]"
                )

        # Handle output modes
        if state.output_json:
            print_json(scan_result)
        elif state.quiet:
            for top in topologies:
                typer.echo(
                    f"{top.vpc.vpc_id} {top.vpc.cidr_block} subnets={len(top.subnets)} instances={len(top.instances)}"
                )
        else:
            # Interactive output: summary banner + syntax highlighted Mermaid diagram
            console.print(
                Panel(
                    f"Discovered [bold cyan]{len(topologies)}[/bold cyan] VPC(s), "
                    f"[bold cyan]{total_subnets}[/bold cyan] Subnet(s), and "
                    f"[bold cyan]{total_instances}[/bold cyan] EC2 instance(s) in [green]{region}[/green]",
                    title="[bold cyan]VPC Architecture Discovery[/bold cyan]",
                    border_style="cyan",
                )
            )
            console.print()
            syntax = Syntax(mermaid_code, "mermaid", theme="monokai", line_numbers=True)
            console.print(syntax)

    except EC2KitError as exc:
        logger.debug("EC2KitError in scan_command: %s", exc, exc_info=True)
        if state.output_json:
            print_json({"error": exc.message, "hint": exc.hint})
        else:
            print_error(exc.message, exc.hint)
        raise typer.Exit(code=exc.exit_code) from exc
    except Exception as exc:
        logger.error("Unexpected error in scan_command: %s", exc, exc_info=state.verbose)
        if state.output_json:
            print_json({"error": str(exc), "hint": "Run with --verbose for diagnostic details."})
        else:
            print_error(f"Unexpected error: {exc}", "Run with --verbose for diagnostic details.")
        raise typer.Exit(code=1) from exc
