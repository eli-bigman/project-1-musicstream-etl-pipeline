"""Unit tests for shared/logging_utils.py — PII scrubbing and JSON format."""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "glue"))

from shared.logging_utils import get_logger


def test_log_line_is_valid_json(capsys):
    logger = get_logger("test-run", "test_stage")
    logger.info("hello_world")
    out = capsys.readouterr().out.strip()
    data = json.loads(out)
    assert data["event"] == "hello_world"
    assert data["run_id"] == "test-run"
    assert data["stage"] == "test_stage"
    assert data["level"] == "INFO"
    assert "ts" in data


def test_pii_keys_stripped(capsys):
    logger = get_logger("r", "s")
    logger.info("evt", user_name="Alice", user_country="US", listen_count=42)
    out = capsys.readouterr().out.strip()
    data = json.loads(out)
    assert "user_name" not in data
    assert "user_country" not in data
    assert data["listen_count"] == 42


def test_warning_level(capsys):
    logger = get_logger("r", "s")
    logger.warning("something_fishy")
    out = capsys.readouterr().out.strip()
    data = json.loads(out)
    assert data["level"] == "WARNING"
