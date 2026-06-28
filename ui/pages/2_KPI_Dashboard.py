"""KPI Dashboard — query DynamoDB and visualise genre-level metrics.

No PII is rendered — only aggregated KPI data.
"""

import os
import sys
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

MOCK_MODE = os.environ.get("MOCK_MODE", "false").lower() == "true"

st.set_page_config(
    page_title="KPI Dashboard · MusicStream",
    page_icon="📊",
    layout="wide",
)

st.markdown(
    """
    <style>
    .kpi-number { font-size: 2rem; font-weight: 700; color: #6c63ff; }
    </style>
    """,
    unsafe_allow_html=True,
)

if MOCK_MODE:
    st.warning("⚡ Mock mode — showing fixture data.")

st.title("📊 KPI Dashboard")
st.caption("Daily genre-level streaming metrics from DynamoDB. No PII displayed.")
st.divider()

# ── Date filter + Query button ────────────────────────────────────────────────
col_f1, col_f3 = st.columns([3, 1])
with col_f1:
    query_date = st.date_input("Date", value=date(2024, 6, 25))
with col_f3:
    st.write("")
    st.write("")
    query_btn = st.button("🔍 Query", type="primary")

date_str = query_date.isoformat()

if MOCK_MODE:
    from lib.mock_data import GENRES as _GENRES
else:
    _GENRES = []


# ── Data fetch ────────────────────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def fetch_all_genres(date_str: str) -> list[dict]:
    if MOCK_MODE:
        from lib.mock_data import mock_all_genres_for_date

        return mock_all_genres_for_date(date_str)
    from lib.dynamo_queries import get_all_genres_for_date

    return get_all_genres_for_date(date_str)


@st.cache_data(ttl=60, show_spinner=False)
def fetch_all_genres_list(date_str: str) -> list[str]:
    if MOCK_MODE:
        from lib.mock_data import GENRES as _GENRES

        return _GENRES
    genres = fetch_all_genres(date_str)
    return sorted({row["genre"] for row in genres})


@st.cache_data(ttl=60, show_spinner=False)
def fetch_top_genres(date_str: str) -> list[dict]:
    if MOCK_MODE:
        from lib.mock_data import mock_top_genres

        return mock_top_genres(date_str)
    from lib.dynamo_queries import get_top_genres

    return get_top_genres(date_str)


@st.cache_data(ttl=60, show_spinner=False)
def fetch_genre_kpi(genre: str, date_str: str) -> dict | None:
    if MOCK_MODE:
        from lib.mock_data import mock_genre_kpi

        return mock_genre_kpi(genre, date_str)
    from lib.dynamo_queries import get_genre_kpi

    return get_genre_kpi(genre, date_str)


@st.cache_data(ttl=60, show_spinner=False)
def fetch_top_songs(genre: str, date_str: str) -> list[dict]:
    if MOCK_MODE:
        from lib.mock_data import mock_top_songs

        return mock_top_songs(genre, date_str)
    from lib.dynamo_queries import get_top_songs_for_genre

    return get_top_songs_for_genre(genre, date_str)


@st.cache_data(ttl=60, show_spinner=False)
def fetch_trend(genre: str, date_str: str, days_back: int = 30) -> list[dict]:
    from datetime import datetime

    end = datetime.fromisoformat(date_str)
    start = (end - timedelta(days=days_back)).date().isoformat()
    if MOCK_MODE:
        from lib.mock_data import mock_genre_trend

        return mock_genre_trend(genre, start, date_str)
    from lib.dynamo_queries import get_genre_trend

    return get_genre_trend(genre, start, date_str)


# ── Load data ─────────────────────────────────────────────────────────────────
with st.spinner("Querying DynamoDB…"):
    all_genres_data = fetch_all_genres(date_str)
    top_genres_data = fetch_top_genres(date_str)

all_genres_list = sorted({row["genre"] for row in all_genres_data}) if all_genres_data else []

df_all = pd.DataFrame(all_genres_data) if all_genres_data else pd.DataFrame()
df_top = pd.DataFrame(top_genres_data) if top_genres_data else pd.DataFrame()

# ── Summary metrics ───────────────────────────────────────────────────────────
st.subheader(f"Summary — {date_str}")
if not df_all.empty:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Plays", f"{df_all['listen_count'].sum():,}")
    col2.metric("Unique Listeners", f"{df_all['unique_listeners'].sum():,}")
    total_ms = df_all["total_listening_time_ms"].sum()
    col3.metric("Total Listening Hrs", f"{total_ms / 3_600_000:.0f}")
    col4.metric("Genres Tracked", str(len(df_all)))
else:
    st.info(f"No KPI data found for {date_str}.")

st.divider()

# ── Charts ────────────────────────────────────────────────────────────────────
if not df_all.empty:
    df_sorted = df_all.sort_values("listen_count", ascending=False)

    col_c1, col_c2 = st.columns(2)
    with col_c1:
        st.subheader("Listen Count by Genre")
        fig1 = px.bar(
            df_sorted,
            x="genre",
            y="listen_count",
            color="listen_count",
            color_continuous_scale="Purpor",
            labels={"listen_count": "Plays", "genre": "Genre"},
            template="plotly_dark",
        )
        fig1.update_layout(
            paper_bgcolor="#0f1117",
            plot_bgcolor="#1a1d27",
            showlegend=False,
            coloraxis_showscale=False,
        )
        st.plotly_chart(fig1, use_container_width=True)

    with col_c2:
        st.subheader("Unique Listeners by Genre")
        fig2 = px.bar(
            df_sorted,
            x="genre",
            y="unique_listeners",
            color="unique_listeners",
            color_continuous_scale="Teal",
            labels={"unique_listeners": "Listeners", "genre": "Genre"},
            template="plotly_dark",
        )
        fig2.update_layout(
            paper_bgcolor="#0f1117",
            plot_bgcolor="#1a1d27",
            showlegend=False,
            coloraxis_showscale=False,
        )
        st.plotly_chart(fig2, use_container_width=True)

st.divider()

# ── Top 5 Genres table ────────────────────────────────────────────────────────
st.subheader("🏆 Top 5 Genres")
if not df_top.empty:
    display_cols = ["rank", "genre", "listen_count", "updated_at"]
    cols_present = [c for c in display_cols if c in df_top.columns]
    st.dataframe(
        df_top[cols_present].rename(
            columns={
                "listen_count": "Plays",
                "genre": "Genre",
                "rank": "Rank",
                "updated_at": "Updated",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No top-genres data for this date.")

st.divider()

# ── Genre filter (placed here so users can drill down without scrolling up) ───
st.subheader("🎸 Genre Detail")
genre_options = ["All"] + all_genres_list if all_genres_list else ["All"]
genre_filter = st.selectbox(
    "Filter by genre to see detail, top songs, and 30-day trend",
    genre_options,
    label_visibility="visible",
)

if genre_filter == "All":
    st.caption("Select a genre above to see KPIs, top songs, and 30-day trend for that genre.")
else:
    st.markdown(f"**Showing detail for: {genre_filter}**")
    kpi = fetch_genre_kpi(genre_filter, date_str)
    if kpi:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Listen Count", f"{kpi.get('listen_count', 0):,}")
        c2.metric("Unique Listeners", f"{kpi.get('unique_listeners', 0):,}")
        total_ms = kpi.get("total_listening_time_ms", 0)
        c3.metric("Total Listening Hrs", f"{total_ms / 3_600_000:.1f}")
        avg_ms = kpi.get("avg_listening_time_per_user_ms", 0)
        c4.metric("Avg Time / User (s)", f"{avg_ms / 1000:.1f}")
    else:
        st.info(f"No KPI data for genre '{genre_filter}' on {date_str}.")

    st.subheader(f"🎵 Top 3 Songs — {genre_filter}")
    songs = fetch_top_songs(genre_filter, date_str)
    if songs:
        df_songs = pd.DataFrame(songs)
        show_cols = ["date_rank", "track_name", "plays"]
        st.dataframe(
            df_songs[[c for c in show_cols if c in df_songs.columns]].rename(
                columns={
                    "date_rank": "Date#Rank",
                    "track_name": "Track",
                    "plays": "Plays",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(f"No top songs data for '{genre_filter}' on {date_str}.")

    st.subheader(f"📈 Trend — {genre_filter}")
    trend = fetch_trend(genre_filter, date_str)
    if trend:
        df_trend = pd.DataFrame(trend)
        df_trend["date"] = pd.to_datetime(df_trend["date"])

        x_axis = st.selectbox(
            "X axis for trend",
            ["Date", "Week", "Month"],
            label_visibility="visible",
        )

        if x_axis == "Date":
            df_chart = df_trend.copy()
            x_col = "date"
            x_label = "Date"
        elif x_axis == "Week":
            df_chart = (
                df_trend.groupby(df_trend["date"].dt.to_period("W").apply(lambda p: p.start_time))
                .agg(listen_count=("listen_count", "sum"))
                .reset_index()
            )
            x_col = "date"
            x_label = "Week starting"
        else:
            df_chart = (
                df_trend.groupby(df_trend["date"].dt.to_period("M").astype(str))
                .agg(listen_count=("listen_count", "sum"))
                .reset_index()
            )
            x_col = "date"
            x_label = "Month"

        fig_trend = px.line(
            df_chart,
            x=x_col,
            y="listen_count",
            markers=True,
            labels={"listen_count": "Plays", x_col: x_label},
            title=f"Listen Count — {genre_filter}",
            template="plotly_dark",
        )
        fig_trend.update_layout(
            paper_bgcolor="#0f1117",
            plot_bgcolor="#1a1d27",
            xaxis=dict(showgrid=False),
            yaxis=dict(gridcolor="#2e3250"),
        )
        fig_trend.update_traces(line_color="#6c63ff", marker_color="#a78bfa")
        st.plotly_chart(fig_trend, use_container_width=True)
    else:
        st.info("No trend data available.")
