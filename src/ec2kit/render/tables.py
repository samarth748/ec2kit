"""Rich table formatting and display utilities for ec2kit CLI."""

import json
import sys
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
err_console = Console(stderr=True)


def print_json(data: Any) -> None:
    """Print pure machine-readable JSON to stdout."""
    if hasattr(data, "model_dump_json"):
        sys.stdout.write(data.model_dump_json(indent=2) + "\n")
    elif hasattr(data, "dict"):
        sys.stdout.write(json.dumps(data.dict(), indent=2, default=str) + "\n")
    else:
        sys.stdout.write(json.dumps(data, indent=2, default=str) + "\n")
    sys.stdout.flush()


def print_error(message: str, hint: str | None = None) -> None:
    """Print formatted error to stderr."""
    err_console.print(f"[bold red]Error:[/bold red] {message}")
    if hint:
        err_console.print(f"[yellow]Hint:[/yellow] {hint}")


def render_info_panel(info_dict: dict[str, Any]) -> None:
    """Render a clean Rich table and panel for AWS session and environment information."""
    table = Table(show_header=True, header_style="bold cyan", border_style="dim")
    table.add_column("Property", style="bold white", width=22)
    table.add_column("Value", style="green")

    identity = info_dict.get("identity", {})
    table.add_row("AWS Account ID", identity.get("account_id", "N/A"))
    table.add_row("Caller ARN", identity.get("arn", "N/A"))
    table.add_row("Caller User ID", identity.get("user_id", "N/A"))
    table.add_row("Active Profile", identity.get("profile") or "[dim](default/environment)[/dim]")
    table.add_row("Target Region", identity.get("region", "N/A"))
    table.add_section()

    table.add_row("Config Directory", str(info_dict.get("config_dir", "N/A")))
    table.add_row("Cache Directory", str(info_dict.get("cache_dir", "N/A")))
    table.add_row("SQLite Database", str(info_dict.get("database_path", "N/A")))

    regions = info_dict.get("available_regions", [])
    if regions:
        regions_preview = ", ".join(regions[:6])
        if len(regions) > 6:
            regions_preview += f" ... ({len(regions)} total)"
        table.add_row("Available Regions", regions_preview)

    console.print(
        Panel(
            table,
            title="[bold cyan]ec2kit AWS Session Information[/bold cyan]",
            border_style="cyan",
        )
    )


def state_color(state: str) -> str:
    """Return Rich style color for EC2 instance state."""
    state_lower = state.lower()
    if state_lower == "running":
        return "[bold green]running[/bold green]"
    if state_lower in ("stopped", "stopping"):
        return "[yellow]stopped[/yellow]"
    if state_lower in ("shutting-down", "terminated"):
        return "[bold red]terminated[/bold red]"
    if state_lower == "pending":
        return "[cyan]pending[/cyan]"
    return f"[dim]{state}[/dim]"


def render_instances_table(result: Any) -> None:
    """Render discovered EC2 instances in a formatted Rich table."""
    instances = result.instances if hasattr(result, "instances") else result.get("instances", [])
    region_errors = (
        result.region_errors
        if hasattr(result, "region_errors")
        else result.get("region_errors", {})
    )

    if not instances:
        console.print("[dim]No EC2 instances found matching the specified criteria.[/dim]")
    else:
        table = Table(
            show_header=True,
            header_style="bold cyan",
            border_style="dim",
            title=f"Discovered EC2 Instances ({len(instances)} total)",
        )
        table.add_column("Region", style="cyan", no_wrap=True)
        table.add_column("Instance ID", style="bold white", no_wrap=True)
        table.add_column("Name", style="magenta", overflow="fold")
        table.add_column("Type", style="green", no_wrap=True)
        table.add_column("State", no_wrap=True)
        table.add_column("Private IP", style="dim", no_wrap=True)
        table.add_column("Public IP", style="yellow", no_wrap=True)
        table.add_column("AZ", style="dim", no_wrap=True)
        table.add_column("VPC ID", style="dim", no_wrap=True)

        for inst in instances:
            state_str = inst.state if hasattr(inst, "state") else inst.get("state", "unknown")
            table.add_row(
                inst.region if hasattr(inst, "region") else inst.get("region", "-"),
                inst.instance_id if hasattr(inst, "instance_id") else inst.get("instance_id", "-"),
                inst.name if hasattr(inst, "name") else inst.get("name", "-"),
                inst.instance_type
                if hasattr(inst, "instance_type")
                else inst.get("instance_type", "-"),
                state_color(state_str),
                (inst.private_ip if hasattr(inst, "private_ip") else inst.get("private_ip")) or "-",
                (inst.public_ip if hasattr(inst, "public_ip") else inst.get("public_ip")) or "-",
                inst.availability_zone
                if hasattr(inst, "availability_zone")
                else inst.get("availability_zone", "-"),
                (inst.vpc_id if hasattr(inst, "vpc_id") else inst.get("vpc_id")) or "-",
            )

        console.print(table)

    # Render regional errors if any occurred during multi-region scanning
    if region_errors:
        err_table = Table(
            show_header=True,
            header_style="bold red",
            border_style="red",
            title="[bold red]Region-Level Scan Warnings[/bold red]",
        )
        err_table.add_column("Region", style="bold yellow", width=18)
        err_table.add_column("Error Details", style="red")

        for reg, err in region_errors.items():
            err_table.add_row(reg, err)

        err_console.print(err_table)


def render_cost_analysis(result: Any, view_filter: str | None = None) -> None:
    """Render comprehensive cost intelligence and optimization recommendations."""
    summary = result.summary if hasattr(result, "summary") else result.get("summary", {})
    idle_instances = (
        result.idle_instances
        if hasattr(result, "idle_instances")
        else result.get("idle_instances", [])
    )
    recommendations = (
        result.recommendations
        if hasattr(result, "recommendations")
        else result.get("recommendations", [])
    )
    orphaned_resources = (
        result.orphaned_resources
        if hasattr(result, "orphaned_resources")
        else result.get("orphaned_resources", [])
    )

    # 1. Cost Summary Table (unless filtered specifically to idle/rightsize/orphaned)
    if not view_filter or view_filter == "summary":
        summary_table = Table(
            show_header=True,
            header_style="bold cyan",
            border_style="dim",
            title="COST SUMMARY",
        )
        summary_table.add_column("Resource", style="bold white", width=26)
        summary_table.add_column("Estimated Monthly Cost", style="green", justify="right")

        ec2_cost = (
            summary.running_ec2_monthly
            if hasattr(summary, "running_ec2_monthly")
            else summary.get("running_ec2_monthly", 0.0)
        )
        ebs_cost = (
            summary.ebs_storage_monthly
            if hasattr(summary, "ebs_storage_monthly")
            else summary.get("ebs_storage_monthly", 0.0)
        )
        eip_cost = (
            summary.elastic_ip_monthly
            if hasattr(summary, "elastic_ip_monthly")
            else summary.get("elastic_ip_monthly", 0.0)
        )
        total_cost = (
            summary.total_estimated_monthly
            if hasattr(summary, "total_estimated_monthly")
            else summary.get("total_estimated_monthly", 0.0)
        )

        summary_table.add_row("Running EC2 Instances", f"${ec2_cost:,.2f}")
        summary_table.add_row("Unattached EBS Storage", f"${ebs_cost:,.2f}")
        summary_table.add_row("Unassociated Elastic IPs", f"${eip_cost:,.2f}")
        summary_table.add_section()
        summary_table.add_row(
            "[bold white]Total Estimated Monthly[/bold white]",
            f"[bold green]${total_cost:,.2f}[/bold green]",
        )
        console.print(summary_table)
        console.print()

    # 2. Optimization Opportunities Table
    has_opps = bool(idle_instances or recommendations or orphaned_resources)
    if not has_opps:
        console.print(
            "[dim]No optimization opportunities detected for the selected criteria.[/dim]"
        )
    else:
        opp_table = Table(
            show_header=True,
            header_style="bold yellow",
            border_style="dim",
            title="OPTIMIZATION OPPORTUNITIES",
        )
        opp_table.add_column("Resource ID", style="bold white", no_wrap=True)
        opp_table.add_column("Category", style="cyan", no_wrap=True)
        opp_table.add_column("Region", style="dim", no_wrap=True)
        opp_table.add_column("Recommendation", style="white")
        opp_table.add_column("Est. Monthly Savings", style="bold green", justify="right")
        opp_table.add_column("Confidence", no_wrap=True)

        # Right-Sizing
        if not view_filter or view_filter == "rightsize":
            for rec in recommendations:
                r_id = rec.instance_id if hasattr(rec, "instance_id") else rec.get("instance_id")
                curr = rec.current_type if hasattr(rec, "current_type") else rec.get("current_type")
                sugg = (
                    rec.suggested_type
                    if hasattr(rec, "suggested_type")
                    else rec.get("suggested_type")
                )
                reg = rec.region if hasattr(rec, "region") else rec.get("region")
                sav = (
                    rec.estimated_monthly_savings
                    if hasattr(rec, "estimated_monthly_savings")
                    else rec.get("estimated_monthly_savings", 0.0)
                )
                conf = (
                    rec.confidence
                    if hasattr(rec, "confidence")
                    else rec.get("confidence", "MEDIUM")
                )
                opp_table.add_row(
                    r_id,
                    "Right-Size",
                    reg,
                    f"Downsize from {curr} to {sugg}",
                    f"${sav:,.2f}",
                    f"[green]{conf}[/green]" if conf == "HIGH" else f"[yellow]{conf}[/yellow]",
                )

        # Idle Instances
        if not view_filter or view_filter == "idle":
            for idle in idle_instances:
                i_id = idle.instance_id if hasattr(idle, "instance_id") else idle.get("instance_id")
                reg = idle.region if hasattr(idle, "region") else idle.get("region")
                cost = (
                    idle.estimated_monthly_cost
                    if hasattr(idle, "estimated_monthly_cost")
                    else idle.get("estimated_monthly_cost", 0.0)
                )
                conf = (
                    idle.confidence
                    if hasattr(idle, "confidence")
                    else idle.get("confidence", "HIGH")
                )
                opp_table.add_row(
                    i_id,
                    "Idle Instance",
                    reg,
                    "Stop or terminate idle instance (minimal CPU/network traffic)",
                    f"${cost:,.2f}",
                    f"[green]{conf}[/green]",
                )

        # Orphaned Resources
        if not view_filter or view_filter == "orphaned":
            for orph in orphaned_resources:
                res_id = (
                    orph.resource_id if hasattr(orph, "resource_id") else orph.get("resource_id")
                )
                r_type = (
                    orph.resource_type
                    if hasattr(orph, "resource_type")
                    else orph.get("resource_type")
                )
                reg = orph.region if hasattr(orph, "region") else orph.get("region")
                cost = (
                    orph.estimated_monthly_cost
                    if hasattr(orph, "estimated_monthly_cost")
                    else orph.get("estimated_monthly_cost", 0.0)
                )
                opp_table.add_row(
                    res_id,
                    "Orphaned " + ("Volume" if "volume" in r_type else "EIP"),
                    reg,
                    orph.recommendation
                    if hasattr(orph, "recommendation")
                    else orph.get("recommendation"),
                    f"${cost:,.2f}",
                    "[green]HIGH[/green]",
                )

        console.print(opp_table)
        console.print()

    # 3. Disclaimers & Pricing Model Panel
    disclaimers = (
        result.disclaimers if hasattr(result, "disclaimers") else result.get("disclaimers", [])
    )
    if disclaimers and not view_filter:
        disc_text = "\n".join(f"• {d}" for d in disclaimers)
        console.print(
            Panel(
                disc_text,
                title="[bold yellow]Cost Estimation Assumptions & Disclaimers[/bold yellow]",
                border_style="yellow",
            )
        )


def severity_badge(severity: str) -> str:
    """Format severity level with standardized Rich color styles."""
    sev = severity.upper()
    if sev == "CRITICAL":
        return "[bold white on red] CRITICAL [/bold white on red]"
    if sev == "HIGH":
        return "[bold red]HIGH[/bold red]"
    if sev == "MEDIUM":
        return "[bold yellow]MEDIUM[/bold yellow]"
    if sev == "LOW":
        return "[cyan]LOW[/cyan]"
    return f"[blue]{severity}[/blue]"


def render_security_findings(result: Any) -> None:
    """Render structured security vulnerability findings and remediation guidance."""
    findings = result.findings if hasattr(result, "findings") else result.get("findings", [])

    if not findings:
        console.print(
            "[bold green]✓ No security vulnerabilities or configuration risks detected.[/bold green]"
        )
        return

    # Summary header
    crit = (
        result.critical_count
        if hasattr(result, "critical_count")
        else result.get("critical_count", 0)
    )
    high = result.high_count if hasattr(result, "high_count") else result.get("high_count", 0)
    med = result.medium_count if hasattr(result, "medium_count") else result.get("medium_count", 0)
    low = result.low_count if hasattr(result, "low_count") else result.get("low_count", 0)

    summary_text = (
        f"Security Posture Findings: [bold red]{crit} Critical[/bold red], "
        f"[bold red]{high} High[/bold red], [yellow]{med} Medium[/yellow], [cyan]{low} Low[/cyan] "
        f"({len(findings)} total)"
    )
    console.print(
        Panel(
            summary_text,
            title="[bold red]AWS Security Audit Summary[/bold red]",
            border_style="red",
        )
    )
    console.print()

    for f in findings:
        f_id = f.finding_id if hasattr(f, "finding_id") else f.get("finding_id")
        sev = f.severity if hasattr(f, "severity") else f.get("severity")
        title = f.title if hasattr(f, "title") else f.get("title")
        res_id = f.resource_id if hasattr(f, "resource_id") else f.get("resource_id")
        r_type = f.resource_type if hasattr(f, "resource_type") else f.get("resource_type")
        reg = f.region if hasattr(f, "region") else f.get("region")
        desc = f.description if hasattr(f, "description") else f.get("description")
        evidence = f.evidence if hasattr(f, "evidence") else f.get("evidence")
        remediation = f.remediation if hasattr(f, "remediation") else f.get("remediation")
        cmd = f.suggested_command if hasattr(f, "suggested_command") else f.get("suggested_command")

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Key", style="bold white", width=18)
        table.add_column("Value")

        table.add_row("Finding ID:", f_id)
        table.add_row("Resource:", f"[bold cyan]{res_id}[/bold cyan] ({r_type}) in {reg}")
        table.add_row("Evidence:", f"[dim]{evidence}[/dim]")
        table.add_row("Description:", desc)
        table.add_row("Recommendation:", f"[green]{remediation}[/green]")
        if cmd:
            table.add_row("Remediation Command:", f"[bold yellow]{cmd}[/bold yellow]")

        border_color = (
            "red" if sev in ("CRITICAL", "HIGH") else ("yellow" if sev == "MEDIUM" else "cyan")
        )
        console.print(
            Panel(
                table,
                title=f"{severity_badge(sev)}  [bold white]{title}[/bold white]",
                border_style=border_color,
            )
        )


def render_drift_report(report: Any) -> None:
    """Render structured drift detection report."""
    findings = report.findings if hasattr(report, "findings") else report.get("findings", [])

    if not findings:
        console.print(
            "[bold green]✓ Infrastructure is completely in sync with Terraform state (zero drift detected).[/bold green]"
        )
        return

    missing = (
        report.missing_in_aws_count
        if hasattr(report, "missing_in_aws_count")
        else report.get("missing_in_aws_count", 0)
    )
    unmanaged = (
        report.unmanaged_in_tf_count
        if hasattr(report, "unmanaged_in_tf_count")
        else report.get("unmanaged_in_tf_count", 0)
    )
    modified = (
        report.modified_count
        if hasattr(report, "modified_count")
        else report.get("modified_count", 0)
    )

    summary = (
        f"Drift Summary: [bold red]{missing} Missing in AWS[/bold red], "
        f"[bold yellow]{unmanaged} Unmanaged in TF[/bold yellow], "
        f"[bold cyan]{modified} Modified Attributes[/bold cyan] "
        f"({len(findings)} total drifts)"
    )
    console.print(
        Panel(
            summary,
            title="[bold magenta]Terraform Infrastructure Drift Detection[/bold magenta]",
            border_style="magenta",
        )
    )
    console.print()

    table = Table(
        title="Detected Infrastructure Drift Items",
        box=box.ROUNDED,
        header_style="bold magenta",
        title_justify="left",
    )
    table.add_column("Resource ID", style="bold cyan")
    table.add_column("Type", style="dim")
    table.add_column("Drift Type")
    table.add_column("Attribute", style="bold")
    table.add_column("Expected (TF)", style="yellow")
    table.add_column("Actual (AWS)", style="green")
    table.add_column("Details")

    for f in findings:
        r_id = f.resource_id if hasattr(f, "resource_id") else f.get("resource_id")
        r_type = f.resource_type if hasattr(f, "resource_type") else f.get("resource_type")
        d_type = f.drift_type if hasattr(f, "drift_type") else f.get("drift_type")
        attr = f.attribute if hasattr(f, "attribute") else f.get("attribute", "-")
        exp = f.expected_value if hasattr(f, "expected_value") else f.get("expected_value", "-")
        act = f.actual_value if hasattr(f, "actual_value") else f.get("actual_value", "-")
        details = f.details if hasattr(f, "details") else f.get("details", "")

        if d_type == "MISSING_IN_AWS":
            styled_drift = "[bold red]MISSING_IN_AWS[/bold red]"
        elif d_type == "UNMANAGED_IN_TF":
            styled_drift = "[bold yellow]UNMANAGED_IN_TF[/bold yellow]"
        else:
            styled_drift = "[bold cyan]MODIFIED[/bold cyan]"

        table.add_row(
            r_id,
            r_type,
            styled_drift,
            attr or "-",
            exp or "-",
            act or "-",
            details,
        )

    console.print(table)
    console.print()


def render_policy_evaluation(result: Any) -> None:
    """Render rich policy evaluation compliance report."""
    is_compliant = (
        result.compliant if hasattr(result, "compliant") else result.get("compliant", False)
    )
    policy_file = (
        result.policy_file
        if hasattr(result, "policy_file")
        else result.get("policy_file", "policy.yaml")
    )
    violations = (
        result.violations if hasattr(result, "violations") else result.get("violations", [])
    )

    if is_compliant:
        console.print(
            Panel(
                f"[bold green]✓ 100% Compliant: All AWS resources adhere to rules in '{policy_file}'.[/bold green]",
                title="[bold green]Infrastructure Policy Compliance Passed[/bold green]",
                border_style="green",
            )
        )
        return

    summary_text = (
        f"[bold red]NON-COMPLIANT:[/bold red] Detected [bold]{len(violations)}[/bold] policy violations "
        f"against declared rules in [bold cyan]{policy_file}[/bold cyan]."
    )
    console.print(
        Panel(
            summary_text,
            title="[bold red]Infrastructure Policy Violations Detected[/bold red]",
            border_style="red",
        )
    )
    console.print()

    table = Table(
        title="Non-Compliant Infrastructure Items",
        box=box.ROUNDED,
        header_style="bold red",
        title_justify="left",
    )
    table.add_column("Rule Name", style="bold cyan")
    table.add_column("Severity")
    table.add_column("Resource ID", style="bold white")
    table.add_column("Type", style="dim")
    table.add_column("Violation Message")
    table.add_column("Remediation", style="green")

    for v in violations:
        rule_name = v.rule_name if hasattr(v, "rule_name") else v.get("rule_name")
        sev = v.severity if hasattr(v, "severity") else v.get("severity", "MEDIUM")
        r_id = v.resource_id if hasattr(v, "resource_id") else v.get("resource_id")
        r_type = v.resource_type if hasattr(v, "resource_type") else v.get("resource_type")
        msg = v.message if hasattr(v, "message") else v.get("message")
        rem = v.remediation if hasattr(v, "remediation") else v.get("remediation")

        table.add_row(
            rule_name,
            severity_badge(sev),
            r_id,
            r_type,
            msg,
            rem,
        )

    console.print(table)
    console.print()
