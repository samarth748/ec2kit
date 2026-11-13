# Multi-stage build for minimal, secure runtime image
FROM python:3.12-slim AS builder

WORKDIR /app

RUN pip install --no-cache-dir build

COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/

RUN python -m build --wheel

# Final minimal production image
FROM python:3.12-slim

LABEL org.opencontainers.image.title="ec2kit" \
      org.opencontainers.image.description="Developer-focused CLI for discovering, managing, and auditing AWS EC2 infrastructure" \
      org.opencontainers.image.source="https://github.com/samarth748/ec2kit" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app

COPY --from=builder /app/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -rf /tmp/*.whl

ENTRYPOINT ["ec2kit"]
CMD ["--help"]
