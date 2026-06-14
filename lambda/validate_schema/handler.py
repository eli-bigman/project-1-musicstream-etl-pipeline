"""Lambda T1 schema gate (D-17).

Reads only the first 4 KB of each CSV file (D-23) to check:
1. File is accessible.
2. CSV header row is present and parseable.
3. All required columns are present (case-sensitive).
4. No duplicate header names.
5. At least one data row exists.
6. First data row's listen_time parses as a datetime.
7. S3 key partition prefix matches the detected listen_time date.

Valid files are returned in valid_keys[]; invalid files are quarantined
with a _reason.json sidecar and returned in invalid_keys[].
"""

import csv
import io
import json
import os
from datetime import datetime, timezone

import boto3

REQUIRED_COLUMNS = ["user_id", "track_id", "listen_time"]
QUARANTINE_BUCKET = os.environ.get("QUARANTINE_BUCKET", "")

_s3 = boto3.client("s3")


def _get_header_chunk(bucket: str, key: str) -> str:
    """Fetch the first 4 KB of the object; fall back to 64 KB if no newline found."""
    resp = _s3.get_object(Bucket=bucket, Key=key, Range="bytes=0-4095")
    chunk = resp["Body"].read().decode("utf-8", errors="replace")
    if "\n" not in chunk:
        # Wide header — rare but handle gracefully (D-23).
        resp2 = _s3.get_object(Bucket=bucket, Key=key, Range="bytes=0-65535")
        chunk = resp2["Body"].read().decode("utf-8", errors="replace")
        _log_warning("wide_header", key=key)
    return chunk


def _log_warning(event: str, **extra) -> None:
    print(
        json.dumps(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "level": "WARNING",
                "stage": "validate_schema",
                "event": event,
                **extra,
            }
        )
    )


def _log_info(event: str, **extra) -> None:
    print(
        json.dumps(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "level": "INFO",
                "stage": "validate_schema",
                "event": event,
                **extra,
            }
        )
    )


def _quarantine(bucket: str, key: str, run_id: str, reason: str) -> None:
    """Copy file to quarantine bucket and write a _reason.json sidecar."""
    _s3.copy_object(
        CopySource={"Bucket": bucket, "Key": key},
        Bucket=QUARANTINE_BUCKET,
        Key=key,
    )
    sidecar_key = key.rsplit(".", 1)[0] + "_reason.json"
    _s3.put_object(
        Bucket=QUARANTINE_BUCKET,
        Key=sidecar_key,
        Body=json.dumps(
            {
                "run_id": run_id,
                "stage": "validate_schema",
                "reason": reason,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        ).encode(),
        ContentType="application/json",
    )


def _validate_one(bucket: str, key: str, run_id: str) -> tuple[bool, str, str | None]:
    """Validate a single CSV key.

    Returns (is_valid, detected_date_or_empty, error_message_or_None).
    """
    try:
        chunk = _get_header_chunk(bucket, key)
    except Exception as exc:
        return False, "", f"s3_read_error: {exc}"

    lines = chunk.split("\n")
    if not lines or not lines[0].strip():
        return False, "", "empty_or_no_header"

    header = [col.strip() for col in lines[0].strip().split(",")]

    # Check for missing required columns
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        return False, "", f"missing_required_columns: {missing}"

    # Check for duplicate header names
    if len(header) != len(set(header)):
        return False, "", "duplicate_header_names"

    # Check at least one data row
    data_lines = [ln for ln in lines[1:] if ln.strip()]
    if not data_lines:
        return False, "", "zero_data_rows"

    # Parse first data row for listen_time
    reader = csv.DictReader(io.StringIO("\n".join(lines[:2])))
    try:
        first_row = next(reader)
    except Exception as exc:
        return False, "", f"csv_parse_error: {exc}"

    listen_time_raw = first_row.get("listen_time", "").strip()
    try:
        ts = datetime.fromisoformat(listen_time_raw.replace(" ", "T"))
        detected_date = ts.date().isoformat()
    except ValueError:
        return False, "", f"bad_listen_time: {listen_time_raw!r}"

    # Check partition prefix matches detected date (yyyy=YYYY/mm=MM/dd=DD)
    # Key example: streams/yyyy=2024/mm=06/dd=25/file.csv
    if "yyyy=" in key:
        try:
            parts = key.split("/")
            year_part = next(p for p in parts if p.startswith("yyyy="))
            mm_part = next(p for p in parts if p.startswith("mm="))
            dd_part = next(p for p in parts if p.startswith("dd="))
            key_date = f"{year_part[5:]}-{mm_part[3:]}-{dd_part[3:]}"
            if key_date != detected_date:
                return (
                    False,
                    "",
                    f"partition_date_mismatch: key={key_date} data={detected_date}",
                )
        except StopIteration:
            pass  # No partition prefix in key — not an error

    return True, detected_date, None


def lambda_handler(event: dict, context) -> dict:
    """Entry point.

    Input: {"bucket": "...", "keys": ["streams/...", ...], "run_id": "..."}
    Output: {"valid_keys": [...], "invalid_keys": [...], "detected_dates": [...]}
    """
    # EventBridge Pipes sends a list of SQS message bodies.
    # Each message body is the raw S3 EventBridge event JSON.
    bucket = event.get("bucket", "")
    keys = event.get("keys", [])
    run_id = event.get("run_id", "unknown")

    _log_info("start", run_id=run_id, key_count=len(keys), bucket=bucket)

    valid_keys: list[str] = []
    invalid_keys: list[dict] = []
    dates: set[str] = set()

    for key in keys:
        is_valid, detected_date, error = _validate_one(bucket, key, run_id)
        if is_valid:
            valid_keys.append(key)
            if detected_date:
                dates.add(detected_date)
            _log_info("valid", run_id=run_id, key=key, detected_date=detected_date)
        else:
            if QUARANTINE_BUCKET:
                _quarantine(bucket, key, run_id, error)
            invalid_keys.append({"key": key, "reason": error})
            _log_warning("invalid", run_id=run_id, key=key, reason=error)

    result = {
        "valid_keys": valid_keys,
        "invalid_keys": invalid_keys,
        "detected_dates": sorted(dates),
        "bucket": bucket,
    }
    _log_info(
        "done",
        run_id=run_id,
        valid=len(valid_keys),
        invalid=len(invalid_keys),
    )
    return result
