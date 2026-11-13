"""Terraform HCL generator for discovered AWS infrastructure topologies.

Renders reviewable, syntactically valid Terraform 1.5+ configurations with:
- Strict sanitization of Terraform resource identifiers
- Provider configurations and input variables
- Exact `terraform import` commands in code comments for every resource
- Outputs for critical identifiers (VPC IDs, Instance IDs, IPs)
"""

import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from ec2kit.models import VpcTopology


def sanitize_tf_name(name: str | None, fallback: str = "resource") -> str:
    """Sanitize arbitrary strings into valid Terraform HCL identifiers ([a-zA-Z0-9_]+)."""
    if not name:
        return fallback

    # Replace hyphens, dots, slashes, and spaces with underscores
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", name.strip())
    # Collapse consecutive underscores
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.strip("_")

    # Terraform identifiers cannot begin with a number
    if cleaned and cleaned[0].isdigit():
        cleaned = f"{fallback}_{cleaned}"

    return cleaned or fallback


def prepare_topology_for_terraform(topology: VpcTopology) -> dict[str, Any]:
    """Prepare and enrich topology data with unique Terraform resource names."""
    top_dict = topology.model_dump()

    # Assign terraform-safe resource identifier
    vpc_name = topology.vpc.name or topology.vpc.vpc_id
    top_dict["tf_name"] = sanitize_tf_name(vpc_name, fallback=f"vpc_{topology.vpc.vpc_id[-8:]}")

    # Subnets
    seen_subnet_names: set[str] = set()
    for sub in top_dict.get("subnets", []):
        sub_id = sub.get("subnet_id", "subnet")
        raw_name = sub.get("name") or sub_id
        base_tf = sanitize_tf_name(raw_name, fallback=f"sub_{sub_id[-8:]}")
        tf_name = base_tf
        counter = 1
        while tf_name in seen_subnet_names:
            tf_name = f"{base_tf}_{counter}"
            counter += 1
        seen_subnet_names.add(tf_name)
        sub["tf_name"] = tf_name

    # Internet Gateways
    for igw in top_dict.get("internet_gateways", []):
        igw_id = igw.get("igw_id", "igw")
        igw["tf_name"] = sanitize_tf_name(igw_id, fallback=f"igw_{igw_id[-8:]}")

    # Security Groups
    seen_sg_names: set[str] = set()
    for sg in top_dict.get("security_groups", []):
        sg_id = sg.get("group_id", "sg")
        sg_name = sg.get("group_name") or sg_id
        base_tf = sanitize_tf_name(sg_name, fallback=f"sg_{sg_id[-8:]}")
        tf_name = base_tf
        counter = 1
        while tf_name in seen_sg_names:
            tf_name = f"{base_tf}_{counter}"
            counter += 1
        seen_sg_names.add(tf_name)
        sg["tf_name"] = tf_name

    # Instances
    seen_inst_names: set[str] = set()
    for inst in top_dict.get("instances", []):
        inst_id = inst.get("instance_id", "inst")
        inst_name = inst.get("name") or inst_id
        base_tf = sanitize_tf_name(inst_name, fallback=f"inst_{inst_id[-8:]}")
        tf_name = base_tf
        counter = 1
        while tf_name in seen_inst_names:
            tf_name = f"{base_tf}_{counter}"
            counter += 1
        seen_inst_names.add(tf_name)
        inst["tf_name"] = tf_name

    return top_dict


class TerraformRenderer:
    """Renders Terraform HCL configuration files from discovered AWS topologies."""

    def __init__(self) -> None:
        template_dir = Path(__file__).resolve().parent.parent / "templates"
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render_all(
        self,
        topologies: list[VpcTopology],
        region: str,
    ) -> dict[str, str]:
        """Render all Terraform files (main.tf, variables.tf, outputs.tf).

        Returns:
            Dict mapping filename to rendered HCL text.
        """
        prepared_topologies = [prepare_topology_for_terraform(t) for t in topologies]

        context = {
            "topologies": prepared_topologies,
            "region": region,
        }

        main_tf = self.env.get_template("main.tf.j2").render(context)
        variables_tf = self.env.get_template("variables.tf.j2").render(context)
        outputs_tf = self.env.get_template("outputs.tf.j2").render(context)

        return {
            "main.tf": main_tf,
            "variables.tf": variables_tf,
            "outputs.tf": outputs_tf,
        }

    def write_to_directory(
        self,
        topologies: list[VpcTopology],
        region: str,
        output_dir: Path,
    ) -> list[Path]:
        """Render and write all Terraform files into the specified directory."""
        rendered = self.render_all(topologies=topologies, region=region)
        output_dir.mkdir(parents=True, exist_ok=True)

        written_files: list[Path] = []
        for filename, content in rendered.items():
            dest = output_dir / filename
            dest.write_text(content.strip() + "\n", encoding="utf-8")
            written_files.append(dest)

        return written_files
