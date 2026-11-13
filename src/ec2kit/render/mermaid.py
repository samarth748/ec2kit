"""Mermaid architecture diagram generator for AWS VPC and EC2 topologies."""

import re

from ec2kit.models import VpcTopology


def sanitize_id(raw_id: str) -> str:
    """Sanitize resource ID for valid Mermaid node syntax."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", raw_id)


def generate_mermaid_diagram(topologies: list[VpcTopology]) -> str:
    """Generate a structured Mermaid flowchart reflecting true discovered network topology."""
    if not topologies:
        return "flowchart TD\n    Empty([No VPC Topologies Discovered])\n"

    lines: list[str] = ["flowchart TD"]
    has_any_igw = any(len(t.internet_gateways) > 0 for t in topologies)

    if has_any_igw:
        lines.append('    Internet["🌐 Public Internet"]')

    for top in topologies:
        vpc = top.vpc
        v_node = sanitize_id(vpc.vpc_id)
        vpc_label = f"VPC: {vpc.vpc_id}"
        if vpc.name and vpc.name != "-":
            vpc_label += f" ({vpc.name})"
        vpc_label += f" [{vpc.cidr_block}]"

        lines.append(f'    subgraph SG_{v_node} ["{vpc_label}"]')

        # 1. Internet Gateways
        for igw in top.internet_gateways:
            igw_node = sanitize_id(igw.igw_id)
            lines.append(f'        {igw_node}["🚪 IGW: {igw.igw_id}"]')
            if has_any_igw:
                lines.append(f"        Internet --> {igw_node}")

        # 2. Public vs Private Subnets
        public_subnets = [s for s in top.subnets if s.is_public]
        private_subnets = [s for s in top.subnets if not s.is_public]

        # Public Subnets
        if public_subnets:
            lines.append('        subgraph SG_Public ["Public Subnets"]')
            for pub_sub in public_subnets:
                sub_node = sanitize_id(pub_sub.subnet_id)
                sub_label = f"Subnet: {pub_sub.subnet_id} ({pub_sub.availability_zone}) [{pub_sub.cidr_block}]"
                lines.append(f'            subgraph SG_SUB_{sub_node} ["{sub_label}"]')

                # NAT Gateways in this subnet
                for nat in top.nat_gateways:
                    if nat.subnet_id == pub_sub.subnet_id:
                        nat_node = sanitize_id(nat.nat_id)
                        lines.append(f'                {nat_node}["⚡ NAT Gateway: {nat.nat_id}"]')

                # Instances in this public subnet
                for inst in top.instances:
                    if inst.subnet_id == pub_sub.subnet_id:
                        inst_node = sanitize_id(inst.instance_id)
                        inst_label = f"🖥️ {inst.name} ({inst.instance_type})\\n{inst.instance_id}"
                        lines.append(f'                {inst_node}["{inst_label}"]')

                lines.append("            end")

                # Connect IGW to public subnet
                for igw in top.internet_gateways:
                    igw_node = sanitize_id(igw.igw_id)
                    lines.append(f"            {igw_node} --> SG_SUB_{sub_node}")

            lines.append("        end")

        # Private Subnets
        if private_subnets:
            lines.append('        subgraph SG_Private ["Private Subnets"]')
            for priv_sub in private_subnets:
                sub_node = sanitize_id(priv_sub.subnet_id)
                sub_label = f"Subnet: {priv_sub.subnet_id} ({priv_sub.availability_zone}) [{priv_sub.cidr_block}]"
                lines.append(f'            subgraph SG_SUB_{sub_node} ["{sub_label}"]')

                # Instances in this private subnet
                for inst in top.instances:
                    if inst.subnet_id == priv_sub.subnet_id:
                        inst_node = sanitize_id(inst.instance_id)
                        inst_label = f"🖥️ {inst.name} ({inst.instance_type})\\n{inst.instance_id}"
                        lines.append(f'                {inst_node}["{inst_label}"]')

                lines.append("            end")

                # Connect NAT Gateways to private subnet if present
                for nat in top.nat_gateways:
                    nat_node = sanitize_id(nat.nat_id)
                    lines.append(f"            SG_SUB_{sub_node} -. egress .-> {nat_node}")

            lines.append("        end")

        lines.append("    end")

    return "\n".join(lines) + "\n"
