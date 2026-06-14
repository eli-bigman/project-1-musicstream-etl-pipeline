"""Unit tests for shared/dynamo_utils.py — shape_for_dynamo and key correctness."""

import sys
import os
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "glue"))

from shared.dynamo_utils import shape_for_dynamo

# ── genre_daily (D-03-R: PK=genre, SK=date) ──────────────────────────────────


def test_shape_genre_daily_keys():
    row = {
        "genre": "rock",
        "listen_date": "2024-06-25",
        "listen_count": 1234,
        "unique_listeners": 456,
        "total_listening_time_ms": 31415926,
        "avg_listening_time_per_user_ms": 68893.7,
    }
    item = shape_for_dynamo("genre_daily", row)
    assert item["genre"] == "rock"
    assert item["date"] == "2024-06-25"
    assert item["listen_count"] == 1234
    assert item["unique_listeners"] == 456
    assert isinstance(item["avg_listening_time_per_user_ms"], Decimal)
    assert "updated_at" in item


def test_shape_genre_daily_accepts_date_key():
    """If row uses 'date' instead of 'listen_date', it should still work."""
    row = {
        "genre": "pop",
        "date": "2024-06-25",
        "listen_count": 100,
        "unique_listeners": 50,
        "total_listening_time_ms": 5_000_000,
        "avg_listening_time_per_user_ms": 100_000.0,
    }
    item = shape_for_dynamo("genre_daily", row)
    assert item["date"] == "2024-06-25"


# ── top_songs_daily (D-03-R: PK=genre, SK=date_rank zero-padded) ─────────────


def test_shape_top_songs_sk_format():
    row = {
        "genre": "rock",
        "listen_date": "2024-06-25",
        "rank": 1,
        "track_id": "5SuOikwiRyPMVoIQDJUgSV",
        "track_name": "Comedy",
        "plays": 412,
    }
    item = shape_for_dynamo("top_songs_daily", row)
    assert item["genre"] == "rock"
    assert item["date_rank"] == "2024-06-25#01", "rank must be zero-padded to 2 digits"
    assert item["track_id"] == "5SuOikwiRyPMVoIQDJUgSV"
    assert item["plays"] == 412


def test_shape_top_songs_rank_03_padding():
    row = {
        "genre": "pop",
        "listen_date": "2024-06-25",
        "rank": 3,
        "track_id": "X",
        "track_name": "Y",
        "plays": 100,
    }
    item = shape_for_dynamo("top_songs_daily", row)
    assert item["date_rank"].endswith("#03")


def test_shape_top_songs_rank_2digit_if_needed():
    row = {
        "genre": "pop",
        "listen_date": "2024-06-25",
        "rank": 10,
        "track_id": "X",
        "track_name": "Y",
        "plays": 100,
    }
    item = shape_for_dynamo("top_songs_daily", row)
    assert item["date_rank"].endswith("#10")


# ── top_genres_daily (unchanged: PK=date, SK=rank (int)) ─────────────────────


def test_shape_top_genres_keys():
    row = {"listen_date": "2024-06-25", "rank": 1, "genre": "pop", "listen_count": 8421}
    item = shape_for_dynamo("top_genres_daily", row)
    assert item["date"] == "2024-06-25"
    assert item["rank"] == 1
    assert item["genre"] == "pop"
    assert item["listen_count"] == 8421


def test_shape_unknown_kind_raises():
    import pytest

    with pytest.raises(ValueError, match="Unknown kpi_kind"):
        shape_for_dynamo("bad_kind", {})


# ── PII guard — user_name and user_country must never appear in shaped items ──


def test_no_pii_in_shaped_items():
    row = {
        "genre": "pop",
        "listen_date": "2024-06-25",
        "listen_count": 100,
        "unique_listeners": 50,
        "total_listening_time_ms": 1_000_000,
        "avg_listening_time_per_user_ms": 20000.0,
        "user_name": "Alice",  # PII — must be excluded
        "user_country": "US",  # PII — must be excluded
    }
    item = shape_for_dynamo("genre_daily", row)
    assert "user_name" not in item
    assert "user_country" not in item
