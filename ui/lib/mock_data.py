"""Fixture data for MOCK_MODE=true — no AWS credentials required.

Data mirrors the shape returned by the real DynamoDB queries so UI code
can be tested without a live AWS account.
"""

from datetime import date, timedelta

_TODAY = date(2024, 6, 25)
_GENRES = ["pop", "rock", "hip-hop", "jazz", "classical", "electronic", "r&b", "country", "metal", "acoustic"]


def mock_top_genres(query_date: str) -> list[dict]:
    return [
        {"date": query_date, "rank": 1, "genre": "pop",        "listen_count": 8421, "updated_at": "2024-06-25T18:34:00Z"},
        {"date": query_date, "rank": 2, "genre": "rock",       "listen_count": 6213, "updated_at": "2024-06-25T18:34:00Z"},
        {"date": query_date, "rank": 3, "genre": "hip-hop",    "listen_count": 5870, "updated_at": "2024-06-25T18:34:00Z"},
        {"date": query_date, "rank": 4, "genre": "jazz",       "listen_count": 4502, "updated_at": "2024-06-25T18:34:00Z"},
        {"date": query_date, "rank": 5, "genre": "electronic", "listen_count": 3987, "updated_at": "2024-06-25T18:34:00Z"},
    ]


def mock_all_genres_for_date(query_date: str) -> list[dict]:
    return [
        {
            "genre": g,
            "date": query_date,
            "listen_count": 8421 - i * 400,
            "unique_listeners": 3200 - i * 150,
            "total_listening_time_ms": 100_000_000 - i * 5_000_000,
            "avg_listening_time_per_user_ms": 31250 - i * 200,
            "updated_at": "2024-06-25T18:34:00Z",
        }
        for i, g in enumerate(_GENRES)
    ]


def mock_genre_kpi(genre: str, query_date: str) -> dict:
    idx = _GENRES.index(genre) if genre in _GENRES else 0
    return {
        "genre": genre,
        "date": query_date,
        "listen_count": 8421 - idx * 400,
        "unique_listeners": 3200 - idx * 150,
        "total_listening_time_ms": 100_000_000 - idx * 5_000_000,
        "avg_listening_time_per_user_ms": 31250 - idx * 200,
        "updated_at": "2024-06-25T18:34:00Z",
    }


def mock_top_songs(genre: str, query_date: str) -> list[dict]:
    return [
        {"genre": genre, "date_rank": f"{query_date}#01", "track_id": "TRACK_A1", "track_name": "Thunder Road", "plays": 412, "updated_at": "2024-06-25T18:34:00Z"},
        {"genre": genre, "date_rank": f"{query_date}#02", "track_id": "TRACK_A2", "track_name": "Dancing Queen", "plays": 387, "updated_at": "2024-06-25T18:34:00Z"},
        {"genre": genre, "date_rank": f"{query_date}#03", "track_id": "TRACK_A3", "track_name": "Billie Jean",   "plays": 354, "updated_at": "2024-06-25T18:34:00Z"},
    ]


def mock_genre_trend(genre: str, start_date: str, end_date: str) -> list[dict]:
    from datetime import datetime
    start = datetime.fromisoformat(start_date).date()
    end = datetime.fromisoformat(end_date).date()
    rows = []
    d = start
    while d <= end:
        rows.append({
            "genre": genre,
            "date": d.isoformat(),
            "listen_count": 6000 + (hash(d.isoformat()) % 2000),
            "unique_listeners": 2500 + (hash(d.isoformat() + "u") % 800),
            "total_listening_time_ms": 80_000_000,
            "avg_listening_time_per_user_ms": 32000,
            "updated_at": "2024-06-25T18:34:00Z",
        })
        d += timedelta(days=1)
    return rows


def mock_recent_executions() -> list[dict]:
    return [
        {"name": "exec-2024-06-25-001", "status": "SUCCEEDED", "startDate": "2024-06-25T18:30:00Z", "stopDate": "2024-06-25T18:32:05Z"},
        {"name": "exec-2024-06-25-002", "status": "RUNNING",   "startDate": "2024-06-25T18:35:00Z", "stopDate": None},
        {"name": "exec-2024-06-24-003", "status": "FAILED",    "startDate": "2024-06-24T09:12:00Z", "stopDate": "2024-06-24T09:12:45Z"},
    ]


GENRES = _GENRES
