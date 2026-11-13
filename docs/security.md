# Security Model

Security is a foundational design requirement for `ec2kit`.

## 1. Zero Credential Persistence
- `ec2kit` **never** persists, caches, logs, or exports AWS access keys, secret keys, session tokens, or passwords.
- SQLite caches strictly store non-sensitive metadata (such as public EC2 on-demand pricing lists and resource topologies).

## 2. Read-Only Default Policy
- All discovery, analysis, pricing, and diagramming commands are 100% read-only.
- No command in Milestone 1 through 7 makes mutating AWS API calls.
- Write operations (in Tier 2 safe operations) require explicit confirmation flags (`--yes` / `--apply`) and dry-run previews.

## 3. Safe Logging and Redaction
- Log streams are routed exclusively to `stderr` with sensitive header fields and credentials suppressed.
- Error messages provide actionable remediation hints without printing environment variables containing secrets.

## 4. Machine-Readable Stream Safety
- Standard output (`stdout`) is strictly reserved for user-requested data formats (Rich tables or pure JSON).
- Debugging logs, progress bars, and diagnostics are sent to `stderr`, ensuring scripts parsing `--json` are never broken by unexpected logging.
