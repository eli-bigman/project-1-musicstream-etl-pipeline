"""DynamoDB query helpers for the three KPI tables.

All queries use get_table() from aws_clients — never boto3 directly (D-26).
Queries reflect the D-03-R key schema:
  genre_daily_kpi:  PK=genre, SK=date; GSI date_genre_index (PK=date, SK=genre)
  top_songs_daily:  PK=genre, SK=date_rank (e.g. 2024-06-25#01)
  top_genres_daily: PK=date,  SK=rank (N)
"""

import os
from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Key

from .aws_clients import get_table

_ENV = os.environ.get("ENV", "dev")


def _table_name(suffix: str) -> str:
    return f"{_ENV}_{suffix}"


def _to_python(value: Any) -> Any:
    """Convert Decimal to float/int for display."""
    if isinstance(value, Decimal):
        f = float(value)
        return int(f) if f.is_integer() else round(f, 2)
    return value


def _clean(item: dict) -> dict:
    return {k: _to_python(v) for k, v in item.items()}


def get_top_genres(date: str) -> list[dict]:
    """Top 5 genres for a given date (sorted by rank ascending)."""
    table = get_table(_table_name("top_genres_daily"))
    resp = table.query(
        KeyConditionExpression=Key("date").eq(date),
        ScanIndexForward=True,
    )
    return [_clean(item) for item in resp["Items"]]


def get_genre_kpi(genre: str, date: str) -> dict | None:
    """All KPIs for one genre on one date."""
    table = get_table(_table_name("genre_daily_kpi"))
    resp = table.get_item(Key={"genre": genre, "date": date})
    item = resp.get("Item")
    return _clean(item) if item else None


def get_all_genres_for_date(date: str) -> list[dict]:
    """All genre KPIs for a given date via the GSI date_genre_index."""
    table = get_table(_table_name("genre_daily_kpi"))
    resp = table.query(
        IndexName="date_genre_index",
        KeyConditionExpression=Key("date").eq(date),
    )
    return [_clean(item) for item in resp["Items"]]


def get_genre_trend(genre: str, start_date: str, end_date: str) -> list[dict]:
    """Trend for a genre over a date range (base table query, no GSI)."""
    table = get_table(_table_name("genre_daily_kpi"))
    resp = table.query(
        KeyConditionExpression=Key("genre").eq(genre) & Key("date").between(start_date, end_date),
        ScanIndexForward=True,
    )
    return [_clean(item) for item in resp["Items"]]


def get_top_songs_for_genre(genre: str, date: str) -> list[dict]:
    """Top 3 songs for a genre on a date (SK begins_with date#)."""
    table = get_table(_table_name("top_songs_daily"))
    resp = table.query(
        KeyConditionExpression=Key("genre").eq(genre)
        & Key("date_rank").begins_with(f"{date}#"),
        ScanIndexForward=True,
    )
    return [_clean(item) for item in resp["Items"]]
