"""Boto3 client factory for the Streamlit dashboard.

Uses the same adaptive retry configuration as dynamo_utils (D-26).
Reads credentials from AWS_PROFILE or environment variables.
"""

import os

import boto3
from botocore.config import Config

_ENV = os.environ.get("ENV", "dev")
_REGION = os.environ.get("AWS_REGION", "eu-west-1")
_ADAPTIVE = Config(retries={"mode": "adaptive", "max_attempts": 5})


def get_s3_client():
    return boto3.client("s3", region_name=_REGION)


def get_sfn_client():
    return boto3.client("stepfunctions", region_name=_REGION)


def get_ddb_resource():
    """Return a DynamoDB resource with adaptive retry. Use get_table() for table access."""
    return boto3.resource("dynamodb", region_name=_REGION, config=_ADAPTIVE)


def get_table(table_name: str):
    """Return a DynamoDB Table resource with adaptive retry."""
    return get_ddb_resource().Table(table_name)


def env() -> str:
    return _ENV
