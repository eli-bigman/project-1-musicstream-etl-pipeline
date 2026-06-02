"""Unit tests for lambda/validate_schema/handler.py."""

import io
import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambda", "validate_schema"))

import handler


VALID_CSV_BYTES = b"user_id,track_id,listen_time\n26213,4dBa8T7oDV9WvGr7kVS4Ez,2024-06-25 17:43:13\n"
MISSING_COL_CSV = b"user_id,listen_time\n26213,2024-06-25 17:43:13\n"
BAD_TIME_CSV    = b"user_id,track_id,listen_time\n26213,ABC,nope\n"
EMPTY_DATA_CSV  = b"user_id,track_id,listen_time\n"


def _make_s3_response(body: bytes) -> dict:
    return {"Body": io.BytesIO(body)}


def _mock_s3(body: bytes):
    mock = MagicMock()
    mock.get_object.return_value = _make_s3_response(body)
    mock.copy_object.return_value = {}
    mock.put_object.return_value = {}
    return mock


@patch.object(handler, "_s3")
def test_valid_file_returns_in_valid_keys(mock_s3):
    mock_s3.get_object.return_value = _make_s3_response(VALID_CSV_BYTES)
    result = handler.lambda_handler(
        {"bucket": "test-bucket", "keys": ["streams/yyyy=2024/mm=06/dd=25/file.csv"], "run_id": "test-run"},
        None,
    )
    assert result["valid_keys"] == ["streams/yyyy=2024/mm=06/dd=25/file.csv"]
    assert result["invalid_keys"] == []
    assert "2024-06-25" in result["detected_dates"]


@patch.object(handler, "_s3")
@patch.object(handler, "QUARANTINE_BUCKET", "test-quarantine")
def test_missing_column_quarantined(mock_s3):
    mock_s3.get_object.return_value = _make_s3_response(MISSING_COL_CSV)
    result = handler.lambda_handler(
        {"bucket": "test-bucket", "keys": ["streams/missing.csv"], "run_id": "r1"},
        None,
    )
    assert result["valid_keys"] == []
    assert len(result["invalid_keys"]) == 1
    assert "track_id" in result["invalid_keys"][0]["reason"]
    mock_s3.copy_object.assert_called_once()


@patch.object(handler, "_s3")
def test_bad_listen_time_quarantined(mock_s3):
    mock_s3.get_object.return_value = _make_s3_response(BAD_TIME_CSV)
    os.environ["QUARANTINE_BUCKET"] = "test-quarantine"
    result = handler.lambda_handler(
        {"bucket": "b", "keys": ["k"], "run_id": "r"},
        None,
    )
    assert len(result["invalid_keys"]) == 1
    assert "bad_listen_time" in result["invalid_keys"][0]["reason"]


@patch.object(handler, "_s3")
def test_empty_data_rows_quarantined(mock_s3):
    mock_s3.get_object.return_value = _make_s3_response(EMPTY_DATA_CSV)
    os.environ["QUARANTINE_BUCKET"] = "test-quarantine"
    result = handler.lambda_handler({"bucket": "b", "keys": ["k"], "run_id": "r"}, None)
    assert len(result["invalid_keys"]) == 1
    assert "zero_data_rows" in result["invalid_keys"][0]["reason"]


@patch.object(handler, "_s3")
def test_mixed_batch(mock_s3):
    """One valid, one invalid in the same batch."""
    def side_effect(Bucket, Key, Range=""):
        if "valid" in Key:
            return _make_s3_response(VALID_CSV_BYTES)
        return _make_s3_response(MISSING_COL_CSV)

    mock_s3.get_object.side_effect = side_effect
    os.environ["QUARANTINE_BUCKET"] = "test-quarantine"
    result = handler.lambda_handler(
        {"bucket": "b", "keys": ["streams/valid.csv", "streams/bad.csv"], "run_id": "r"},
        None,
    )
    assert len(result["valid_keys"]) == 1
    assert len(result["invalid_keys"]) == 1


@patch.object(handler, "_s3")
def test_no_pii_in_logs(mock_s3, capsys):
    """Ensure user_name and user_country are never emitted in any log line."""
    mock_s3.get_object.return_value = _make_s3_response(VALID_CSV_BYTES)
    handler.lambda_handler(
        {"bucket": "b", "keys": ["streams/yyyy=2024/mm=06/dd=25/x.csv"], "run_id": "r"},
        None,
    )
    captured = capsys.readouterr()
    assert "user_name" not in captured.out
    assert "user_country" not in captured.out
