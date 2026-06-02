"""DynamoDB helpers with adaptive retry (D-26).

Every component must use get_ddb_table() — never instantiate
boto3.resource("dynamodb") directly. This ensures adaptive retry is applied
everywhere and the pattern is consistent across Glue jobs and the Streamlit UI.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterator

import boto3
from botocore.config import Config

# Adaptive mode implements a client-side token bucket that back-pressures before
# the server returns ProvisionedThroughputExceededException (D-26).
_ADAPTIVE_CFG = Config(retries={"mode": "adaptive", "max_attempts": 10})


def get_ddb_table(table_name: str):
    """Return a DynamoDB Table resource with adaptive retry configured."""
    return boto3.resource("dynamodb", config=_ADAPTIVE_CFG).Table(table_name)


def _to_decimal(value: Any) -> Any:
    """Convert floats to Decimal for DynamoDB compatibility."""
    if isinstance(value, float):
        return Decimal(str(value))
    return value


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shape_for_dynamo(kpi_kind: str, row: dict) -> dict:
    """Convert a parquet row dict to the correct DynamoDB item shape (D-03-R)."""
    updated_at = _now_iso()

    if kpi_kind == "genre_daily":
        return {
            "genre": row["genre"],
            "date": str(row.get("listen_date") or row.get("date")),
            "listen_count": int(row["listen_count"]),
            "unique_listeners": int(row["unique_listeners"]),
            "total_listening_time_ms": int(row["total_listening_time_ms"]),
            "avg_listening_time_per_user_ms": _to_decimal(
                row["avg_listening_time_per_user_ms"]
            ),
            "updated_at": updated_at,
        }

    if kpi_kind == "top_songs_daily":
        # SK is zero-padded date#rank, e.g. "2024-06-25#01"
        rank = int(row["rank"])
        date_str = str(row.get("listen_date") or row.get("date"))
        return {
            "genre": row["genre"],
            "date_rank": f"{date_str}#{rank:02d}",
            "track_id": row["track_id"],
            "track_name": row["track_name"],
            "plays": int(row["plays"]),
            "updated_at": updated_at,
        }

    if kpi_kind == "top_genres_daily":
        return {
            "date": str(row.get("listen_date") or row.get("date")),
            "rank": int(row["rank"]),
            "genre": row["genre"],
            "listen_count": int(row["listen_count"]),
            "updated_at": updated_at,
        }

    raise ValueError(f"Unknown kpi_kind: {kpi_kind!r}")


def batch_write(table_name: str, kpi_kind: str, items_iter: Iterator[dict]) -> int:
    """Write all items to the table using batch_writer with idempotent overwrite.

    Returns the total number of items written.
    """
    pkeys_by_kind = {
        "genre_daily": ["genre", "date"],
        "top_songs_daily": ["genre", "date_rank"],
        "top_genres_daily": ["date", "rank"],
    }
    pkeys = pkeys_by_kind[kpi_kind]
    table = get_ddb_table(table_name)
    count = 0
    with table.batch_writer(overwrite_by_pkeys=pkeys) as bw:
        for item in items_iter:
            bw.put_item(Item=item)
            count += 1
    return count
