# IAM Permissions Guide

`ec2kit` is strictly **read-only by default** and follows the principle of least privilege. It does **not** require `AdministratorAccess`.

## Milestones 1–4 Policy: Discovery, Cost & Architecture Scan

For session identity, instance listing, cost intelligence, and network architecture scan (`ec2kit info`, `ec2kit ls`, `ec2kit cost`, `ec2kit scan`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EC2KitCorePermissions",
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity",
        "ec2:DescribeRegions",
        "ec2:DescribeInstances",
        "ec2:DescribeTags",
        "ec2:DescribeAvailabilityZones",
        "ec2:DescribeVolumes",
        "ec2:DescribeAddresses",
        "ec2:DescribeSnapshots",
        "ec2:DescribeVpcs",
        "ec2:DescribeSubnets",
        "ec2:DescribeRouteTables",
        "ec2:DescribeInternetGateways",
        "ec2:DescribeNatGateways",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeNetworkInterfaces",
        "ec2:DescribeVpcEndpoints",
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:GetMetricData",
        "pricing:GetProducts",
        "pricing:DescribeServices"
      ],
      "Resource": "*"
    }
  ]
}
```

## Upcoming Milestone Permission Sets

### Cost Intelligence (`ec2kit cost`)
- `pricing:GetProducts`
- `pricing:DescribeServices`
- `cloudwatch:GetMetricData`
- `cloudwatch:GetMetricStatistics`
- `ec2:DescribeVolumes`
- `ec2:DescribeSnapshots`
- `ec2:DescribeAddresses`

### Architecture & VPC Scan (`ec2kit scan`)
- `ec2:DescribeVpcs`
- `ec2:DescribeSubnets`
- `ec2:DescribeRouteTables`
- `ec2:DescribeInternetGateways`
- `ec2:DescribeNatGateways`
- `ec2:DescribeSecurityGroups`
- `ec2:DescribeNetworkInterfaces`
- `ec2:DescribeVpcEndpoints`

### Security Checks (`ec2kit security`)
- `ec2:DescribeSecurityGroupRules`
- `ec2:DescribeInstanceAttribute`
- `ec2:DescribeVolumesModifications`


### Terraform Export & Drift Detection (`ec2kit export`, `ec2kit drift`)
- `ec2:DescribeInstances`
- `ec2:DescribeVpcs`
- `ec2:DescribeSubnets`
- `ec2:DescribeSecurityGroups`
- `ec2:DescribeInternetGateways`
*(Read-only. Never requests state management or apply permissions).*

### Lifecycle Operations (`ec2kit start / stop / reboot / terminate`)
Restricted to operational roles performing deliberate changes:
- `ec2:StartInstances`
- `ec2:StopInstances`
- `ec2:RebootInstances`
- `ec2:TerminateInstances`

### Policy Guardrails (`ec2kit policy check`)
- `ec2:DescribeInstances`
- `ec2:DescribeVolumes`
