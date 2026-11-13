# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-11-13
### Added
- **Tier 2 — Safe Operations & Policy Guardrails**:
  - Safe lifecycle mutations: `ec2kit start`, `ec2kit stop`, `ec2kit reboot`, `ec2kit terminate`.
  - Blast-radius impact analysis displaying affected resources, IP release consequences, and storage persistence before modification.
  - AWS native `--dry-run` validation verifying IAM permissions and parameters without altering state.
  - Mandatory confirmation prompt or `--yes` (`-y`) safety guardrail for CI/CD automation.
  - Policy Guardrails engine (`ec2kit policy check --policy policy.yaml`): evaluates live AWS infrastructure against declarative YAML governance rules (required tags, approved instance families, volume encryption, instance quotas).
  - Clean exit code `0` for compliance, `1` for policy violations to act as deployment quality gates.

## [0.7.0] - 2026-11-13
### Added
- **Milestone 7 — Drift Detection (`ec2kit drift`)**:
  - Discovers drift between Terraform state (`terraform.tfstate` or `terraform show -json`) and live AWS infrastructure.
  - Identifies `MISSING_IN_AWS` resources (deleted or terminated outside of Terraform).
  - Identifies `UNMANAGED_IN_TF` resources (rogue cloud resources launched outside of code).
  - Identifies `MODIFIED` attributes (instance hardware type changed, tags drifted).
  - Tabular Rich report and machine-readable JSON output for automated audit runs.

## [0.6.0] - 2026-11-13
### Added
- **Milestone 6 — Terraform Export (`ec2kit export terraform`)**:
  - Exports discovered AWS network and instance topology into clean, reviewable Terraform 1.5+ HCL.
  - Generates `main.tf`, `variables.tf`, and `outputs.tf` with Jinja2 templates.
  - Generates resource blocks: `aws_vpc`, `aws_subnet`, `aws_internet_gateway`, `aws_security_group`, `aws_instance`.
  - Enriches every generated resource block with exact `terraform import` command guidance.
  - Strictly read-only: never modifies state or executes `terraform apply`.

## [0.5.0] - 2026-11-13
### Added
- **Milestone 5 — Security Scanner (`ec2kit security`)**:
  - Posture audit scanning for CIS AWS Foundations benchmarks.
  - Ingress security group rule analysis: flags open SSH (22), RDP (3389), database ports (3306, 5432, etc.), and unrestricted (`-1`) rules.
  - EBS volume encryption detection.
  - Instance Metadata Service v1 vulnerability detection (`HttpTokens != 'required'`).
  - Missing governance tags detection.
  - Exact CLI remediation commands for every identified risk.

## [0.4.0] - 2026-11-13
### Added
- **Milestone 4 — VPC Discovery & Architecture Diagrams (`ec2kit scan`)**:
  - Implemented VPC topology discovery: subnets, route tables, internet gateways, NAT gateways, security groups, and EC2 instance associations.
  - Public vs. private subnet detection based on default route table associations and `0.0.0.0/0` Internet Gateway routing.
  - Automated Mermaid architecture diagram generator (`flowchart TD`) modeling true network topology.
  - File export support (`--output` / `-o <file.mmd>`).
  - Terminal preview with Rich syntax highlighting.
  - Machine-readable JSON output matching `ScanResult`.

## [0.3.0] - 2026-11-13
### Added
- **Milestone 3 — Cost Intelligence (`ec2kit cost`)**:
  - Implemented on-demand running cost estimation using AWS Pricing API with fallback to published reference rates.
  - Added SQLite database management (`~/.cache/ec2kit/ec2kit.db`) with versioned schema migrations and corruption recovery.
  - Implemented local pricing caching (`PricingCache`) with TTL expiration and `--refresh-pricing` cache bypass.
  - Multi-dimensional idle instance detection evaluating both CPU utilization and network activity over configurable observation windows (`--days`).
  - Safe telemetry handling: missing CloudWatch metrics are treated as insufficient evidence rather than 0% utilization.
  - Right-sizing recommendations with down-sizing mapping, estimated monthly savings, confidence scoring, and explicit awareness of memory metrics.
  - Orphaned cloud resource discovery: identifies unattached EBS storage volumes and unassociated Elastic IP addresses incurring hourly charges.
  - Added filter flags: `--idle`, `--rightsize`, `--orphaned`.
  - Machine-readable JSON output (`--json`) and quiet output (`--quiet`).

## [0.2.0] - 2026-11-13
### Added
- **Milestone 2 — EC2 Instance Discovery (`ec2kit ls`)**:
  - Implemented `ec2kit ls` with support for single-region and multi-region (`--all-regions`) discovery.
  - Added filtering options: `--state`, `--type`, and `--name` substring filtering.
  - Multi-region bounded concurrency using thread pooling.
  - Resilient partial failure handling: regional API errors are isolated without terminating healthy regions.
  - Normalized `EC2Instance` model.
  - Formatted Rich table output and JSON output.

## [0.1.0] - 2026-11-13
### Added
- **Milestone 1 — Project Foundation**:
  - Python packaging with `pyproject.toml` supporting Python 3.11+.
  - Typer CLI with global options: `--profile`, `--region`, `--json`, `--quiet`, `--verbose`, `--version`.
  - Native boto3 session integration supporting SSO, assume-role, and environment credentials.
  - Centralized exception hierarchy with actionable user hints.
  - Diagnostic logging routed strictly to `stderr`.
  - `ec2kit info` command.
