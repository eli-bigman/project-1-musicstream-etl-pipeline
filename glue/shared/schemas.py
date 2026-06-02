"""Schema constants for the three CSV sources.

These are the *contract* for what columns must be present.
required_for_kpi is the minimum set that must be non-null for KPI computation.
"""

STREAMS_SCHEMA = {
    "columns": ["user_id", "track_id", "listen_time"],
    "types": {"user_id": "int", "track_id": "str", "listen_time": "timestamp"},
    "required": ["user_id", "track_id", "listen_time"],
}

USERS_SCHEMA = {
    "columns": ["user_id", "user_name", "user_age", "user_country", "created_at"],
    "types": {
        "user_id": "int",
        "user_name": "str",
        "user_age": "int",
        "user_country": "str",
        "created_at": "date",
    },
    # user_name, user_country are PII — never log their values (D-13).
    "required": ["user_id"],
    "pii_columns": ["user_name", "user_country"],
}

SONGS_SCHEMA = {
    "columns": [
        "id", "track_id", "artists", "album_name", "track_name",
        "popularity", "duration_ms", "explicit", "danceability",
        "energy", "key", "loudness", "mode", "speechiness",
        "acousticness", "instrumentalness", "liveness", "valence",
        "tempo", "time_signature", "track_genre",
    ],
    "required_for_kpi": ["track_id", "duration_ms", "track_genre", "track_name"],
}

# Top-N limits
TOP_SONGS_PER_GENRE = 3
TOP_GENRES_PER_DAY = 5
