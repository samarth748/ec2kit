# CLI Command Reference

`ec2kit` provides a unified set of options across all commands.

## Global Options

| Option | Flag | Description |
|---|---|---|
| `--profile` | `-p` | Named AWS profile from `~/.aws/config` or credentials |
| `--region` | `-r` | Target AWS region (e.g. `us-east-1`, `ap-south-1`) |
| `--json` | `-j` | Output strictly machine-readable JSON to `stdout` |
| `--quiet` | `-q` | Suppress non-essential decorative banners and progress indicators |
| `--verbose` | `-v` | Enable diagnostic and debug logging to `stderr` |
| `--version` | `-V` | Display version and exit |
| `--help` | | Display help message and options |

## Commands

### `ec2kit info`
Inspects active AWS authentication, caller identity (Account ID, ARN, User ID), target region, available regions, and local cache paths.

**Examples:**
```bash
# Pretty terminal output with Rich table
ec2kit info

# Machine-readable JSON output for scripting and CI
ec2kit --json info

# Quiet mode outputting only essential identifiers
ec2kit --quiet info

# Inspecting with explicit profile and region
ec2kit -p development -r eu-central-1 info
```

### `ec2kit ls`
Discover and list EC2 instances with state, network, and placement details across a single region or all enabled AWS regions.

**Options:**
- `-a`, `--all-regions`: Scan all enabled AWS regions concurrently.
- `-s`, `--state <state>`: Filter instances by state (`running`, `stopped`, `terminated`, etc.).
- `-t`, `--type <type>`: Filter instances by hardware instance type (e.g. `t3.micro`, `m5.large`).
- `-n`, `--name <pattern>`: Substring match on the instance `Name` tag.

**Examples:**
```bash
# List instances in the default/active region
ec2kit ls

# Discover instances across all enabled regions in the account
ec2kit ls --all-regions

# Filter for running t3.micro instances
ec2kit ls --state running --type t3.micro

# Search for instances by name substring
ec2kit ls --name backend

# Output structured JSON for automation or scripting
ec2kit --json ls --all-regions

# Quiet output printing instance IDs, regions, and states
ec2kit --quiet ls
```

### `ec2kit cost`
Analyzes running EC2 on-demand costs, identifies idle instances via CloudWatch telemetry, generates right-sizing recommendations, and detects orphaned storage and IP resources.

**Options:**
- `--idle`: Filter analysis to display only idle instances.
- `--rightsize`: Filter analysis to display only right-sizing opportunities.
- `--orphaned`: Filter analysis to display only orphaned resources (unattached EBS volumes, unassociated Elastic IPs).
- `-d`, `--days <int>`: Telemetry observation window in days (default: `7`).
- `-a`, `--all-regions`: Scan and analyze costs across all enabled AWS regions.
- `--refresh-pricing`: Bypass local SQLite cache and fetch fresh on-demand rates from the AWS Pricing API.

**Examples:**
```bash
# Full cost analysis for active region
ec2kit cost

# Cost analysis across all enabled regions
ec2kit cost --all-regions

# Show only idle instances over a 14-day observation window
ec2kit cost --idle --days 14

# Show only over-provisioned right-sizing candidates
ec2kit cost --rightsize

# Show orphaned unattached EBS volumes and unassociated Elastic IPs
ec2kit cost --orphaned

# Machine-readable JSON output for automated FinOps pipelines
ec2kit --json cost
```

### `ec2kit scan`
Discovers VPC network topology and generates clean Mermaid architecture diagrams.

**Options:**
- `--vpc <id>`: Target a single VPC by ID (e.g. `vpc-0123456789abcdef0`).
- `--all-vpcs`: Scan and map all VPCs in the target region.
- `-o`, `--output <path>`: Export Mermaid architecture diagram to file (`.mmd`).

**Examples:**
```bash
# Scan and preview architecture diagram in terminal
ec2kit scan

# Target a specific VPC and export diagram to a file
ec2kit scan --vpc vpc-0123456789abcdef0 --output architecture.mmd

# Machine-readable JSON topology inventory
ec2kit --json scan
```


---

### `ec2kit security`

Audit EC2, Security Group, EBS, and IMDS configurations against CIS AWS benchmarks and AWS security best practices.

```bash
# Audit security posture in the active or configured region
ec2kit security

# Audit across all enabled AWS regions
ec2kit security --all-regions

# Filter findings by minimum severity threshold (CRITICAL, HIGH, MEDIUM, LOW, INFO)
ec2kit security --severity HIGH

# Output machine-readable JSON security inventory for CI/CD pipelines
ec2kit --json security > security-findings.json
```

#### Supported Security Rules
- **SG-UNRESTRICTED-ALL**: Ingress rule with protocol `-1` open to `0.0.0.0/0` or `::/0` (CRITICAL).
- **SG-RDP-EXPOSED**: Windows RDP port 3389 exposed to `0.0.0.0/0` (CRITICAL).
- **SG-SSH-EXPOSED**: SSH port 22 exposed to `0.0.0.0/0` or `::/0` (HIGH).
- **SG-DB-EXPOSED**: Database ports (MySQL 3306, Postgres 5432, MSSQL 1433, Mongo 27017, Redis 6379) exposed to `0.0.0.0/0` (HIGH).
- **SEC-EBS-UNENCRYPTED**: EBS volume not encrypted at rest (HIGH).
- **SEC-EC2-IMDSV1**: Instance Metadata Service v1 enabled (`HttpTokens != 'required'`), vulnerable to SSRF credential exfiltration (HIGH).
- **SEC-EC2-MISSING-TAGS**: Missing recommended operational governance tags (`Environment`, `Owner`, `Project`) (LOW).


---

### `ec2kit export terraform`

Export discovered AWS infrastructure to reviewable, syntactically valid Terraform 1.5+ HCL configuration files.

> [!IMPORTANT]
> `ec2kit` is strictly read-only and **never** manages Terraform state or executes `terraform apply`. The generated configuration files are intended for code reviews, migrations, and clean infrastructure-as-code onboarding.

```bash
# Export infrastructure in active region to ./terraform directory
ec2kit export terraform --output-dir ./terraform

# Target a specific VPC
ec2kit export terraform --vpc vpc-0123456789abcdef0 --output-dir ./my-vpc-tf

# Print rendered main.tf directly to stdout (useful for piping)
ec2kit export terraform --stdout

# Output machine-readable JSON structure containing all rendered files and import commands
ec2kit --json export terraform
```

#### Generated Files
- `main.tf`: Provider setup and resource blocks (`aws_vpc`, `aws_subnet`, `aws_internet_gateway`, `aws_security_group`, `aws_instance`) annotated with exact `terraform import` commands.
- `variables.tf`: Configurable input parameters (`aws_region`, `environment`).
- `outputs.tf`: Exported identifiers (VPC IDs, instance IDs, private IPs).


---

### `ec2kit drift`

Detect configuration drift between your declared Terraform state and live AWS cloud infrastructure.

```bash
# Compare live AWS instances with local terraform.tfstate
ec2kit drift --state terraform.tfstate

# Support for `terraform show -json` output files
ec2kit drift --state tf_state.json

# Machine-readable drift report for CI/CD audit pipelines
ec2kit --json drift --state terraform.tfstate > drift-report.json

# Minimal output for automated scripts
ec2kit --quiet drift --state terraform.tfstate
```

#### Detected Drift Categories
- **`MISSING_IN_AWS`**: Resource exists in Terraform state file but is missing or terminated in AWS.
- **`UNMANAGED_IN_TF`**: Running instance exists in AWS but is not tracked in Terraform state.
- **`MODIFIED`**: Resource exists in both, but key attributes (e.g. `instance_type`, `tags.Name`) have drifted out of sync.

---

### `ec2kit start / stop / reboot / terminate`

Safe, blast-radius-aware EC2 instance lifecycle operations.

> [!CAUTION]
> Lifecycle operations modify cloud resources. `ec2kit` provides strict safety guardrails:
> 1. Displays complete impact analysis and blast radius before taking any action.
> 2. Supports AWS native `--dry-run` to validate IAM permissions and parameters.
> 3. Requires explicit confirmation prompt or `--yes` (`-y`) flag in automated environments.

```bash
# Dry-run validation (probes IAM permissions without altering state)
ec2kit stop i-0123456789abcdef0 --dry-run

# Start a stopped instance (interactive prompt asks for confirmation)
ec2kit start i-0123456789abcdef0

# Stop a running instance with explicit bypass for CI/CD
ec2kit stop i-0123456789abcdef0 --yes

# Force-stop an unresponsive instance
ec2kit stop i-0123456789abcdef0 --force --yes

# Reboot an instance
ec2kit reboot i-0123456789abcdef0 --yes

# Terminate an instance (displays red alert and blast-radius warning)
ec2kit terminate i-0123456789abcdef0 --yes
```

---

### `ec2kit policy check`

Evaluate AWS infrastructure against organizational governance policies defined in declarative YAML. Exits with code `0` if 100% compliant, or code `1` if violations exist (ideal for GitHub Actions and deployment gates).

```bash
# Validate live cloud against default policy.yaml
ec2kit policy check

# Validate against custom policy file
ec2kit policy check --policy ./compliance/production-policy.yaml

# Machine-readable JSON output for automated policy reporting
ec2kit --json policy check --policy policy.yaml
```

#### Example `policy.yaml`:
```yaml
version: "1.0"
rules:
  - name: required-tags
    description: Instances must include governance tags
    required_tags:
      - Environment
      - Owner
      - Project

  - name: allowed-types
    description: Only cost-effective instance families are allowed
    allowed_types:
      - "t3.*"
      - "t4g.*"
      - "m5.*"

  - name: max-running-instances
    description: Quota limit on running instances
    max_count: 25

  - name: require-ebs-encryption
    description: All attached and unattached volumes must be encrypted
    require_encryption: true
```
