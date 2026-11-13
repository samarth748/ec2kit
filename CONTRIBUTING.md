# Contributing to ec2kit

Thank you for your interest in contributing to `ec2kit`!

## Code Quality Standards

Before submitting changes, ensure all tests and linting pass:

```bash
# Run test suite with coverage
pytest -v --cov=ec2kit

# Run linter
ruff check .

# Check code formatting
ruff format --check .
```

## Engineering Principles

1. **Read-Only by Default**: Ensure all scanning and discovery commands do not modify cloud resources.
2. **Never Expose Secrets**: Never log or print secret credentials, tokens, or private keys.
3. **Stream Separation**: Always send machine-readable data to `stdout` and logs/progress to `stderr`.
4. **Mocked AWS Tests**: Use `moto` for all automated AWS interactions. Never require real AWS credentials in CI.
