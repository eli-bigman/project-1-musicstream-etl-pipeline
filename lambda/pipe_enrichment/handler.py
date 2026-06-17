"""Pipe enrichment Lambda: reshape SQS batch from EventBridge Pipe into SM input (D-22).

EventBridge Pipe delivers a list of SQS records. Each record's body is the
JSON-encoded S3 EventBridge event. This function extracts bucket + key from
every record and returns the single unified structure the ASL ParseInput state
expects: {"detail": {"bucket": {"name": "..."}, "object": {"keys": [...]}}}
"""

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    """Input: list of SQS records (from EventBridge Pipe enrichment call).
    Output: {"detail": {"bucket": {"name": str}, "object": {"keys": [str]}}}
    """
    records = event if isinstance(event, list) else event.get("Records", [event])

    bucket = None
    keys = []

    for record in records:
        body_raw = record.get("body", "")
        try:
            body = json.loads(body_raw) if isinstance(body_raw, str) else body_raw
        except (json.JSONDecodeError, TypeError):
            logger.warning("Skipping record with unparseable body: %r", body_raw)
            continue

        record_bucket = (
            body.get("detail", {}).get("bucket", {}).get("name")
            or body.get("Records", [{}])[0].get("s3", {}).get("bucket", {}).get("name")
        )
        record_key = (
            body.get("detail", {}).get("object", {}).get("key")
            or body.get("Records", [{}])[0].get("s3", {}).get("object", {}).get("key")
        )

        if not record_key:
            logger.warning("No key found in record body")
            continue

        if bucket is None:
            bucket = record_bucket
        keys.append(record_key)

    if not bucket or not keys:
        raise ValueError(f"Could not extract bucket/keys from batch. bucket={bucket!r}, keys={keys!r}")

    logger.info("Enriched batch: bucket=%s keys_count=%d", bucket, len(keys))

    return {
        "detail": {
            "bucket": {"name": bucket},
            "object": {"keys": keys},
        }
    }
