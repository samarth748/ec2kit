"""Safe, blast-radius-aware EC2 instance lifecycle operations.

Implements strict read-only safety guardrails:
- Displays complete impact analysis and blast radius before modification
- Supports AWS native `--dry-run` validation
- Requires explicit `--yes` flag or interactive confirmation
- Never performs silent or unprompted state modifications
"""

import typer
from botocore.exceptions import ClientError
from rich.panel import Panel

from ec2kit.aws.session import create_session, resolve_region
from ec2kit.config import Config, get_logger
from ec2kit.exceptions import EC2KitError, PermissionDeniedError, ResourceNotFoundError
from ec2kit.models import OperationResult
from ec2kit.render.tables import console, print_error, print_json

logger = get_logger()


def get_instance_details(ec2_client: object, instance_id: str) -> dict:
    """Fetch current instance state and metadata with error handling."""
    try:
        resp = ec2_client.describe_instances(InstanceIds=[instance_id])
        reservations = resp.get("Reservations", [])
        if not reservations or not reservations[0].get("Instances"):
            raise ResourceNotFoundError(resource_type="EC2 Instance", resource_id=instance_id)
        return reservations[0]["Instances"][0]
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if "InvalidInstanceID" in code or code == "InvalidParameterValue":
            raise ResourceNotFoundError(
                resource_type="EC2 Instance", resource_id=instance_id
            ) from exc
        raise


def evaluate_consequences(action: str, inst_data: dict) -> list[str]:
    """Calculate blast radius and operational consequences of an action."""
    consequences: list[str] = []
    pub_ip = inst_data.get("PublicIpAddress")

    if action == "stop":
        if pub_ip:
            consequences.append(
                f"Dynamic public IP {pub_ip} will be released back to AWS pool unless backed by an Elastic IP."
            )
        consequences.append(
            "EC2 compute billing halts; attached EBS storage volumes continue to incur charges."
        )
        consequences.append("Any data stored on ephemeral instance store volumes will be lost.")

    elif action == "reboot":
        consequences.append("In-flight network connections will be terminated.")
        consequences.append(
            "Operating system will restart; cached memory and volatile state will be cleared."
        )

    elif action == "terminate":
        consequences.append(
            "[bold red]PERMANENT DESTRUCTION:[/bold red] The virtual machine will be permanently deleted."
        )
        if pub_ip:
            consequences.append(f"Public IP {pub_ip} will be detached and released.")
        consequences.append(
            "All attached EBS volumes with DeleteOnTermination=true will be destroyed."
        )
        consequences.append("All ephemeral instance store data will be permanently lost.")

    elif action == "start":
        consequences.append("Compute charges will resume.")
        if not pub_ip:
            consequences.append(
                "A new dynamic public IPv4 address will be assigned if launched in a public subnet."
            )

    return consequences


def execute_lifecycle_op(
    state: Config,
    action: str,
    instance_id: str,
    dry_run: bool = False,
    yes: bool = False,
    force: bool = False,
) -> None:
    """Execute lifecycle action with blast-radius preview, dry-run, and confirmation."""
    try:
        session = create_session(profile=state.profile, region=state.region)
        region = resolve_region(session, explicit_region=state.region)
        ec2 = session.client("ec2", region_name=region)

        inst_data = get_instance_details(ec2, instance_id)
        current_state = inst_data.get("State", {}).get("Name", "unknown")
        tags = {t["Key"]: t.get("Value", "") for t in inst_data.get("Tags", []) if "Key" in t}
        inst_name = tags.get("Name", "unnamed")
        inst_type = inst_data.get("InstanceType", "")

        consequences = evaluate_consequences(action, inst_data)

        # 1. Display Blast-Radius Preview Panel
        if not state.output_json and not state.quiet:
            impact_text = (
                f"[bold]Target Instance:[/bold] [bold cyan]{instance_id}[/bold cyan] ({inst_name})\n"
                f"[bold]Instance Type:[/bold] {inst_type} in {region}\n"
                f"[bold]State Transition:[/bold] [yellow]{current_state}[/yellow] ➔ [bold green]{action.upper()}ING[/bold green]\n\n"
                f"[bold red]Operational Blast Radius & Consequences:[/bold red]\n"
            )
            for c in consequences:
                impact_text += f" • {c}\n"

            if dry_run:
                impact_text += "\n[bold yellow]Mode: AWS Dry-Run only (no changes will be applied).[/bold yellow]"

            console.print(
                Panel(
                    impact_text,
                    title=f"[bold red]Blast Radius Safety Check — {action.upper()} {instance_id}[/bold red]",
                    border_style="red" if action == "terminate" else "yellow",
                )
            )

        # 2. Dry-Run Execution
        if dry_run:
            try:
                if action == "start":
                    ec2.start_instances(InstanceIds=[instance_id], DryRun=True)
                elif action == "stop":
                    ec2.stop_instances(InstanceIds=[instance_id], Force=force, DryRun=True)
                elif action == "reboot":
                    ec2.reboot_instances(InstanceIds=[instance_id], DryRun=True)
                elif action == "terminate":
                    ec2.terminate_instances(InstanceIds=[instance_id], DryRun=True)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code == "DryRunOperation":
                    msg = "AWS DryRun validation successful. IAM permissions and parameters are valid."
                    if state.output_json:
                        print_json(
                            OperationResult(
                                instance_id=instance_id,
                                action=action,
                                region=region,
                                previous_state=current_state,
                                target_state=action + "ing",
                                dry_run=True,
                                success=True,
                                message=msg,
                                consequences=consequences,
                            )
                        )
                    elif not state.quiet:
                        console.print(f"[bold green]✓ {msg}[/bold green]")
                    return
                elif code == "UnauthorizedOperation":
                    raise PermissionDeniedError(
                        action=f"ec2:{action.capitalize()}Instances",
                        resource=instance_id,
                    ) from exc
                raise

        # 3. Explicit Confirmation Guardrail
        if not yes:
            if state.quiet:
                print_error(
                    "Modification commands require '--yes' when running in quiet or automated mode."
                )
                raise typer.Exit(code=1)

            confirm = typer.confirm(
                f"Do you want to proceed with {action.upper()} on {instance_id}?", default=False
            )
            if not confirm:
                console.print("[yellow]Operation aborted by user.[/yellow]")
                raise typer.Exit(code=0)

        # 4. Perform Live AWS Mutation
        if action == "start":
            ec2.start_instances(InstanceIds=[instance_id])
            target_state = "starting"
        elif action == "stop":
            ec2.stop_instances(InstanceIds=[instance_id], Force=force)
            target_state = "stopping"
        elif action == "reboot":
            ec2.reboot_instances(InstanceIds=[instance_id])
            target_state = "rebooting"
        elif action == "terminate":
            ec2.terminate_instances(InstanceIds=[instance_id])
            target_state = "shutting-down"
        else:
            raise ValueError(f"Unsupported action: {action}")

        success_msg = f"Successfully initiated {action.upper()} for instance {instance_id}."

        if state.output_json:
            print_json(
                OperationResult(
                    instance_id=instance_id,
                    action=action,
                    region=region,
                    previous_state=current_state,
                    target_state=target_state,
                    dry_run=False,
                    success=True,
                    message=success_msg,
                    consequences=consequences,
                )
            )
        elif not state.quiet:
            console.print(
                f"[bold green]✓ {success_msg}[/bold green] (State: {current_state} ➔ {target_state})"
            )

    except EC2KitError as exc:
        logger.debug("EC2KitError caught in ops command", exc_info=True)
        if state.output_json:
            print_json({"error": exc.message, "hint": exc.hint})
        else:
            print_error(exc.message, exc.hint)
        raise typer.Exit(code=exc.exit_code) from exc
    except typer.Exit:
        raise
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "UnauthorizedOperation":
            if state.output_json:
                print_json(
                    {
                        "error": "AWS IAM permission denied",
                        "hint": "Ensure required IAM permissions.",
                    }
                )
            else:
                print_error("AWS IAM permission denied", "Ensure required IAM permissions.")
            raise typer.Exit(code=1) from exc
        raise


def start_instance_command(
    state: Config, instance_id: str, dry_run: bool = False, yes: bool = False
) -> None:
    """Start a stopped EC2 instance."""
    execute_lifecycle_op(
        state=state, action="start", instance_id=instance_id, dry_run=dry_run, yes=yes
    )


def stop_instance_command(
    state: Config, instance_id: str, dry_run: bool = False, yes: bool = False, force: bool = False
) -> None:
    """Stop a running EC2 instance."""
    execute_lifecycle_op(
        state=state, action="stop", instance_id=instance_id, dry_run=dry_run, yes=yes, force=force
    )


def reboot_instance_command(
    state: Config, instance_id: str, dry_run: bool = False, yes: bool = False
) -> None:
    """Reboot an EC2 instance."""
    execute_lifecycle_op(
        state=state, action="reboot", instance_id=instance_id, dry_run=dry_run, yes=yes
    )


def terminate_instance_command(
    state: Config, instance_id: str, dry_run: bool = False, yes: bool = False
) -> None:
    """Permanently terminate and delete an EC2 instance."""
    execute_lifecycle_op(
        state=state, action="terminate", instance_id=instance_id, dry_run=dry_run, yes=yes
    )
