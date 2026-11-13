"""Unit tests for AWS Pricing API query parsing."""

import json
from unittest.mock import MagicMock

import boto3

from ec2kit.aws.pricing import query_aws_pricing_api


def test_query_aws_pricing_api_parsing(monkeypatch) -> None:
    """Verify parsing AWS Pricing API GetProducts response."""
    session = boto3.Session(region_name="us-east-1")

    # Mock product payload from AWS Pricing API
    mock_payload = {
        "product": {"attributes": {"instanceType": "t3.micro"}},
        "terms": {
            "OnDemand": {
                "term_key": {
                    "priceDimensions": {
                        "dim_key": {
                            "unit": "Hrs",
                            "pricePerUnit": {"USD": "0.0104000000"},
                        }
                    }
                }
            }
        },
    }

    mock_client = MagicMock()
    mock_client.get_products.return_value = {"PriceList": [json.dumps(mock_payload)]}

    monkeypatch.setattr(session, "client", lambda *_args, **_kwargs: mock_client)

    rate = query_aws_pricing_api(session, "t3.micro", "us-east-1", "linux")
    assert rate == 0.0104


def test_query_aws_pricing_api_unknown_region() -> None:
    """Verify returns None when an unmapped region is queried."""
    session = boto3.Session(region_name="us-east-1")
    assert query_aws_pricing_api(session, "t3.micro", "unmapped-region-1") is None
