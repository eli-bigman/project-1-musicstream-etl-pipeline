"""S3 upload and Step Functions polling helpers for the Pipeline page."""

import json
import os
import time

import boto3

from .aws_clients import get_s3_client, get_sfn_client

_RAW_BUCKET = os.environ.get("RAW_BUCKET", "musicstream-dev-raw-970547336735")
_SM_ARN = os.environ.get("STATE_MACHINE_ARN", "")
_SQS_URL = os.environ.get("SQS_BUFFER_QUEUE_URL", "")


def upload_csv_to_s3(file_bytes: bytes, filename: str, date_str: str) -> str:
    """Upload a CSV to the raw bucket under the Hive-style prefix.

    Returns the S3 key.
    """
    year, month, day = date_str.split("-")
    key = f"streams/yyyy={year}/mm={month}/dd={day}/{filename}"
    s3 = get_s3_client()
    s3.put_object(Bucket=_RAW_BUCKET, Key=key, Body=file_bytes)
    return key


def start_execution_via_sqs(bucket: str, key: str) -> str:
    """Send the S3 event to SQS so the EventBridge Pipe picks it up.

    Returns the SQS MessageId.
    """
    sqs = boto3.client("sqs")
    body = json.dumps(
        {
            "detail": {
                "bucket": {"name": bucket},
                "object": {"keys": [key]},
            }
        }
    )
    resp = sqs.send_message(QueueUrl=_SQS_URL, MessageBody=body)
    return resp["MessageId"]


def list_recent_executions(max_results: int = 10) -> list[dict]:
    """Return the N most recent SM executions with their status."""
    if not _SM_ARN:
        return []
    sfn = get_sfn_client()
    resp = sfn.list_executions(stateMachineArn=_SM_ARN, maxResults=max_results)
    return resp.get("executions", [])


def get_execution_history(execution_arn: str) -> list[dict]:
    """Return all events for a specific execution."""
    sfn = get_sfn_client()
    events = []
    kwargs = {"executionArn": execution_arn, "reverseOrder": False}
    while True:
        resp = sfn.get_execution_history(**kwargs)
        events.extend(resp["events"])
        token = resp.get("nextToken")
        if not token:
            break
        kwargs["nextToken"] = token
    return events


def poll_execution(execution_arn: str, timeout_s: int = 300) -> str:
    """Poll until execution completes or timeout. Returns final status."""
    sfn = get_sfn_client()
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = sfn.describe_execution(executionArn=execution_arn)
        status = resp["status"]
        if status not in ("RUNNING",):
            return status
        time.sleep(5)
    return "TIMEOUT"
