"""
End-to-end smoke tests. Run against a live dev/prod environment after deploy.

Required env vars:
  ENV               — dev | prod
  AWS_REGION        — eu-west-1
  RAW_BUCKET        — musicstream-{env}-raw
  STATE_MACHINE_ARN — arn:aws:states:...:stateMachine:{env}-streaming-etl-sm

Run:
  pytest tests/e2e -q -m smoke

AWS credentials must be active in the shell (profile or OIDC role from CI).
"""

import os

import boto3
import pytest


@pytest.fixture(scope="module")
def clients():
    region = os.environ.get("AWS_REGION", "eu-west-1")
    session = boto3.Session(region_name=region)
    return {
        "s3": session.client("s3"),
        "sfn": session.client("stepfunctions"),
    }


@pytest.mark.smoke
def test_required_env_vars_present():
    """All required env vars exist before any live AWS calls are made."""
    required = ["ENV", "AWS_REGION", "RAW_BUCKET", "STATE_MACHINE_ARN"]
    missing = [v for v in required if not os.environ.get(v)]
    assert not missing, f"Missing env vars: {missing}"


@pytest.mark.smoke
@pytest.mark.skipif(
    not os.environ.get("RAW_BUCKET"),
    reason="RAW_BUCKET not set — skipping S3 connectivity check",
)
def test_raw_bucket_accessible(clients):
    """Raw S3 bucket exists and credentials have ListBucket permission."""
    bucket = os.environ["RAW_BUCKET"]
    resp = clients["s3"].list_objects_v2(Bucket=bucket, MaxKeys=1)
    assert resp["ResponseMetadata"]["HTTPStatusCode"] == 200


@pytest.mark.smoke
@pytest.mark.skipif(
    not os.environ.get("STATE_MACHINE_ARN"),
    reason="STATE_MACHINE_ARN not set — skipping Step Functions check",
)
def test_state_machine_active(clients):
    """State machine ARN resolves to an ACTIVE STANDARD machine."""
    arn = os.environ["STATE_MACHINE_ARN"]
    resp = clients["sfn"].describe_state_machine(stateMachineArn=arn)
    assert resp["type"] == "STANDARD"
    assert resp["status"] == "ACTIVE"
