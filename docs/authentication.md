# AWS Authentication in ec2kit

`ec2kit` uses standard boto3 credential resolution. It never prompts for secret keys, never stores credentials in configuration or SQLite, and never transmits them externally.

## Supported Credential Providers

`ec2kit` resolves credentials in this exact order:

1. **CLI Flags**: `--profile <name>` and `--region <region>`
2. **Environment Variables**:
   - `AWS_ACCESS_KEY_ID`
   - `AWS_SECRET_ACCESS_KEY`
   - `AWS_SESSION_TOKEN`
   - `AWS_DEFAULT_REGION` / `AWS_REGION`
   - `AWS_PROFILE`
3. **AWS SSO / IAM Identity Center**:
   - Profiles configured via `aws configure sso`
   - Cached SSO tokens in `~/.aws/sso/cache`
4. **AssumeRole Profiles**:
   - Roles configured in `~/.aws/config` with `source_profile` or MFA
5. **Shared AWS Credentials File**:
   - `~/.aws/credentials` and `~/.aws/config`
6. **EC2 Instance Metadata Service (IMDS)** & Container Credentials:
   - IAM roles attached to EC2 instances or ECS/EKS tasks

## Usage Examples

### Using Default Credentials
```bash
ec2kit info
```

### Specifying a Named Profile
```bash
ec2kit --profile development info
```

### Overriding the Target Region
```bash
ec2kit --region ap-south-1 info
```

### AWS SSO Workflow
```bash
# First log in via AWS CLI SSO
aws sso login --profile my-sso-profile

# Then run ec2kit
ec2kit --profile my-sso-profile info
```
