"""S3 utility helpers for Glue jobs."""

import os
import tempfile
from typing import Iterator
from urllib.parse import urlparse

import boto3


def _s3_client():
    return boto3.client("s3")


def list_s3_keys(bucket: str, prefix: str) -> list[str]:
    """Return all object keys under prefix (handles pagination)."""
    s3 = _s3_client()
    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


def parse_s3_uri(uri: str) -> tuple[str, str]:
    """Return (bucket, key_prefix) from an s3:// URI."""
    parsed = urlparse(uri)
    return parsed.netloc, parsed.path.lstrip("/")


def download_parquet_files(s3_uri: str) -> Iterator[str]:
    """Download all Parquet parts under s3_uri to /tmp and yield local paths."""
    bucket, prefix = parse_s3_uri(s3_uri)
    s3 = _s3_client()
    keys = list_s3_keys(bucket, prefix)
    for key in keys:
        if not key.endswith(".parquet") and "part-" not in key:
            continue
        local = os.path.join(tempfile.gettempdir(), key.rsplit("/", 1)[-1])
        s3.download_file(bucket, key, local)
        yield local


def put_json_sidecar(bucket: str, key: str, payload: dict) -> None:
    """Write a small JSON sidecar next to a quarantined file."""
    import json

    s3 = _s3_client()
    sidecar_key = key.rsplit(".", 1)[0] + "_reason.json"
    s3.put_object(
        Bucket=bucket,
        Key=sidecar_key,
        Body=json.dumps(payload, indent=2).encode(),
        ContentType="application/json",
    )


def quarantine_file(
    src_bucket: str,
    src_key: str,
    quarantine_bucket: str,
    run_id: str,
    reason: str,
) -> None:
    """Copy a file to quarantine and write a _reason.json sidecar."""
    import json

    s3 = _s3_client()
    dest_key = src_key
    s3.copy_object(
        CopySource={"Bucket": src_bucket, "Key": src_key},
        Bucket=quarantine_bucket,
        Key=dest_key,
    )
    put_json_sidecar(
        quarantine_bucket,
        dest_key,
        {"run_id": run_id, "stage": "validate_schema", "reason": reason},
    )
