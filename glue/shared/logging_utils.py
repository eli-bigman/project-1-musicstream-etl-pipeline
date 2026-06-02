"""JSON-structured logger for all Glue jobs and the Lambda validator.

Every log line must contain: ts, level, run_id, stage, event.
PII fields (user_name, user_country) must never appear in log values (D-13).
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


_PII_KEYS = frozenset({"user_name", "user_country"})


def _sanitize(data: dict) -> dict:
    """Remove PII keys from a dict before logging."""
    return {k: v for k, v in data.items() if k not in _PII_KEYS}


class _JsonFormatter(logging.Formatter):
    def __init__(self, run_id: str, stage: str):
        super().__init__()
        self._run_id = run_id
        self._stage = stage

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "run_id": self._run_id,
            "stage": self._stage,
            "event": record.getMessage(),
        }
        if hasattr(record, "extra"):
            payload.update(_sanitize(record.extra))
        return json.dumps(payload)


class StructuredLogger:
    """Thin wrapper that injects run_id and stage into every log call."""

    def __init__(self, name: str, run_id: str, stage: str, level: int = logging.INFO):
        self._logger = logging.getLogger(name)
        self._logger.setLevel(level)
        # Replace any existing handlers so each call to get_logger() gets fresh
        # formatter state — avoids stale run_id/stage from a previous call.
        self._logger.handlers = []
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JsonFormatter(run_id, stage))
        self._logger.addHandler(handler)

    def _log(self, level: int, event: str, **extra: Any) -> None:
        record = self._logger.makeRecord(
            self._logger.name, level, "", 0, event, (), None
        )
        record.extra = _sanitize(extra)  # type: ignore[attr-defined]
        self._logger.handle(record)

    def info(self, event: str, **extra: Any) -> None:
        self._log(logging.INFO, event, **extra)

    def warning(self, event: str, **extra: Any) -> None:
        self._log(logging.WARNING, event, **extra)

    def error(self, event: str, **extra: Any) -> None:
        self._log(logging.ERROR, event, **extra)

    def debug(self, event: str, **extra: Any) -> None:
        self._log(logging.DEBUG, event, **extra)


def get_logger(run_id: str, stage: str) -> StructuredLogger:
    return StructuredLogger(f"musicstream.{stage}", run_id, stage)
