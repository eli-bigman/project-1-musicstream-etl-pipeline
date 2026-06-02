"""Integration tests for the Lambda schema validation using moto S3."""

import io
import json
import os
import sys
from unittest.mock import patch, MagicMock

os.environ.setdefault("AWS_DEFAULT_REGION", "eu-west-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ["QUARANTINE_BUCKET"] = "test-quarantine"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambda", "validate_schema"))

import handler

VALID_CSV = b"user_id,track_id,listen_time\n26213,4dBa8T7oDV9WvGr7kVS4Ez,2024-06-25 17:43:13\n"
MISSING_TRACK_ID = b"user_id,listen_time\n26213,2024-06-25 17:43:13\n"
BAD_LISTEN_TIME = b"user_id,track_id,listen_time\n26213,ABC,not-a-date\n"
FUTURE_TIME = b"user_id,track_id,listen_time\n26213,ABC,2099-01-01 00:00:00\n"
WRONG_PARTITION = b"user_id,track_id,listen_time\n26213,ABC,2024-06-24 00:00:00\n"


def _patched_s3(csv_body: bytes):
    m = MagicMock()
    m.get_object.return_value = {"Body": io.BytesIO(csv_body)}
    m.copy_object.return_value = {}
    m.put_object.return_value = {}
    return m


def _run(csv_body, key="streams/yyyy=2024/mm=06/dd=25/file.csv"):
    with patch.object(handler, "_s3", _patched_s3(csv_body)):
        return handler.lambda_handler(
            {"bucket": "test-raw", "keys": [key], "run_id": "integ-001"},
            None,
        )


def test_valid_passes():
    result = _run(VALID_CSV)
    assert result["valid_keys"] == ["streams/yyyy=2024/mm=06/dd=25/file.csv"]
    assert result["invalid_keys"] == []
    assert result["detected_dates"] == ["2024-06-25"]


def test_missing_required_column_fails():
    result = _run(MISSING_TRACK_ID)
    assert result["valid_keys"] == []
    assert len(result["invalid_keys"]) == 1
    assert "track_id" in result["invalid_keys"][0]["reason"]


def test_bad_listen_time_fails():
    result = _run(BAD_LISTEN_TIME)
    assert len(result["invalid_keys"]) == 1
    assert "bad_listen_time" in result["invalid_keys"][0]["reason"]


def test_future_listen_time_passes_t1():
    """Future listen_time is a parseable date — T1 passes. T2 drops in PySpark."""
    result = _run(FUTURE_TIME)
    assert len(result["valid_keys"]) == 1


def test_wrong_partition_date_fails():
    """File in dd=25 path but data date is 2024-06-24 — partition mismatch."""
    result = _run(WRONG_PARTITION, key="streams/yyyy=2024/mm=06/dd=25/file.csv")
    assert len(result["invalid_keys"]) == 1
    assert "partition_date_mismatch" in result["invalid_keys"][0]["reason"]
