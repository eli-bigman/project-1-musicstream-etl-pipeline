"""Unit tests for shared/schemas.py."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "glue"))

from shared.schemas import (
    STREAMS_SCHEMA,
    SONGS_SCHEMA,
    USERS_SCHEMA,
    TOP_SONGS_PER_GENRE,
    TOP_GENRES_PER_DAY,
)


def test_streams_required_columns_present():
    for col in STREAMS_SCHEMA["required"]:
        assert col in STREAMS_SCHEMA["columns"]


def test_songs_required_for_kpi_present():
    for col in SONGS_SCHEMA["required_for_kpi"]:
        assert col in SONGS_SCHEMA["columns"]


def test_users_pii_not_in_required():
    """PII columns must not be in the required list (they are optional context)."""
    for pii_col in USERS_SCHEMA["pii_columns"]:
        assert pii_col not in USERS_SCHEMA["required"]


def test_top_n_limits():
    assert TOP_SONGS_PER_GENRE == 3
    assert TOP_GENRES_PER_DAY == 5
