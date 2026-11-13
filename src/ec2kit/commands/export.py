"""Implementation of `ec2kit export terraform` command."""

import re
from pathlib import Path

import typer

from ec2kit.aws.session import create_session, resolve_region
from ec2kit.aws.vpc import discover_vpc_topologies
from ec2kit.config import Config, get_logger
from ec2kit.exceptions import EC2KitError
from ec2kit.models import TerraformExportResult
from ec2kit.render.tables import (
    console,
    print_error,
    print_json,
)
from ec2kit.render.terraform import TerraformRenderer

logger = get_logger()


def export_terraform_command(
    state: Config,
    output_dir: Path | None = None,
    vpc_id: str | None = None,
    to_stdout: bool = False,
) -> None:
    """Generate reviewable Terraform HCL configuration from live AWS topology."""
    try:
        session = create_session(profile=state.profile, region=state.region)
        region = resolve_region(session, explicit_region=state.region)

        logger.debug(
            "Exporting Terraform for region=%s, vpc_id=%s, output_dir=%s",
            region,
            vpc_id,
            output_dir,
        )

        if not state.output_json and not state.quiet and not to_stdout:
            with console.status(
                "[bold cyan]Discovering AWS topology for Terraform export...[/bold cyan]"
            ):
                topologies = discover_vpc_topologies(session, region=region, target_vpc_id=vpc_id)
        else:
            topologies = discover_vpc_topologies(session, region=region, target_vpc_id=vpc_id)

        if not topologies:
            if state.output_json:
                print_json(
                    TerraformExportResult(
                        region=region,
                        output_dir=str(output_dir) if output_dir else None,
                        files={},
                        total_resources=0,
                        import_commands=[],
                    )
                )
            elif not state.quiet:
                console.print(
                    f"[yellow]No VPC infrastructure found to export in region {region}.[/yellow]"
                )
            return

        renderer = TerraformRenderer()
        rendered_files = renderer.render_all(topologies=topologies, region=region)

        # Extract import commands
        main_content = rendered_files.get("main.tf", "")
        import_cmds = re.findall(r"# Import:\s*(terraform import [^\n]+)", main_content)

        # Count exported resources
        total_resources = sum(
            1
            + len(t.subnets)
            + len(t.internet_gateways)
            + len(t.security_groups)
            + len(t.instances)
            for t in topologies
        )

        target_dir = output_dir or Path("./terraform")

        if to_stdout:
            typer.echo(main_content)
            return

        if state.output_json:
            result = TerraformExportResult(
                region=region,
                output_dir=str(target_dir),
                files=rendered_files,
                total_resources=total_resources,
                import_commands=import_cmds,
            )
            print_json(result)
            return

        # Write to files
        written_files = renderer.write_to_directory(
            topologies=topologies,
            region=region,
            output_dir=target_dir,
        )

        if not state.quiet:
            from rich.panel import Panel

            summary = (
                f"[bold green]Successfully generated Terraform configuration![/bold green]\n\n"
                f"• Target Directory: [bold cyan]{target_dir.resolve()}[/bold cyan]\n"
                f"• Resources Exported: [bold]{total_resources}[/bold]\n"
                f"• Importable Resources: [bold]{len(import_cmds)}[/bold]\n"
                f"• Files Created:\n"
            )
            for f in written_files:
                summary += f"   - [bold]{f.name}[/bold] ({f.stat().st_size} bytes)\n"

            summary += (
                f"\n[dim]Next steps:\n"
                f"  1. Review generated HCL in {target_dir}/\n"
                f"  2. Initialize Terraform: cd {target_dir} && terraform init\n"
                f"  3. Import live resources: run import commands annotated in main.tf[/dim]"
            )

            console.print(
                Panel(
                    summary,
                    title="[bold cyan]Terraform Infrastructure Export[/bold cyan]",
                    border_style="cyan",
                )
            )

    except EC2KitError as exc:
        logger.debug("EC2KitError caught in export_terraform_command", exc_info=True)
        if state.output_json:
            print_json({"error": exc.message, "hint": exc.hint})
        else:
            print_error(exc.message, exc.hint)
        raise typer.Exit(code=exc.exit_code) from exc
    except Exception as exc:
        logger.error("Unexpected error occurred: %s", exc, exc_info=state.verbose)
        if state.output_json:
            print_json({"error": str(exc)})
        else:
            print_error(f"Unexpected error: {exc}")
        raise typer.Exit(code=1) from exc
