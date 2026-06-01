# UI Dashboard — Plan

> Added per user request. Not in the original brief, but maps directly to all five user stories.
> See `decision.md` D-28 (revised to D-28-R) for the technology decision.
> **Status: planned — not yet implemented.**

---

## 1. Purpose

A lightweight dashboard that lets both the **data engineer** and the **business analyst** interact with the pipeline and query results without touching the AWS console or CLI.

| User Story | UI Feature |
|------------|-----------|
| US1: Ingest data via automated pipeline | **Pipeline** page — upload CSV to S3 raw bucket, trigger execution |
| US2: Validate incoming datasets | **Pipeline** page — execution stage tracker showing validation result |
| US3: Transform raw data using Glue | **Pipeline** page — live Step Functions stage progress |
| US4: Store processed data in DynamoDB | **Pipeline** page — items-written confirmation after load stage |
| US5: Query DynamoDB for insights | **KPI Dashboard** page — date picker, genre filter, charts, top-N tables |

---

## 2. Technology: Streamlit

**Framework:** [Streamlit](https://streamlit.io/) — Python-native, no frontend build tooling, runs anywhere Python runs.

### Why Streamlit

| Criterion | Streamlit | Vanilla HTML/JS (prior choice) |
|-----------|-----------|-------------------------------|
| Build tooling | None — `streamlit run app.py` | None |
| Language | Python — same as the rest of the project | JavaScript — separate skill set |
| AWS SDK | Native `boto3` — queries DynamoDB directly | Needs API Gateway intermediary |
| Charts | `st.bar_chart`, `st.plotly_chart` (Altair/Plotly/Matplotlib) | Chart.js via CDN |
| Auth | Streamlit Community Cloud auth or `streamlit-authenticator` | Manual |
| State management | `st.session_state` | Manual JS |
| Deployment | `streamlit run` locally; Streamlit Community Cloud or ECS for hosted | S3 + CloudFront |
| Effort to build | Low — Python data engineers can maintain it | Requires JS knowledge |

The key advantage: the dashboard calls `boto3` directly to query DynamoDB — **no API Gateway Lambda needed**. This removes a full service layer from Sprint 6 scope.

### Trade-offs

- Streamlit is not a production-grade web framework — not suitable for public-facing apps or high-concurrency use. Acceptable here: this is a data engineering ops/BI tool, not a customer product.
- Streamlit's layout flexibility is more limited than a full frontend framework. Acceptable for a KPI dashboard.
- The app must run somewhere with AWS credentials. For local use this is trivial; for hosted deployment a task role or SSO session is needed.

---

## 3. Stack

```
ui/
├── app.py                  ← main Streamlit entry point
├── pages/
│   ├── 1_Pipeline.py       ← US1–US4: upload, trigger, stage tracker
│   └── 2_KPI_Dashboard.py  ← US5: date/genre filters, charts, tables
├── lib/
│   ├── aws_clients.py      ← boto3 client factory (reads from .env / AWS_PROFILE)
│   ├── dynamo_queries.py   ← query helpers for the three KPI tables
│   ├── pipeline_ops.py     ← S3 upload, Step Functions start/poll
│   └── mock_data.py        ← fixture data for local demo without AWS
├── requirements.txt        ← streamlit, boto3, pandas, plotly, python-dotenv
└── .streamlit/
    └── config.toml         ← theme, server settings
```

---

## 4. Page Specifications

### 4.1 `app.py` — Home / Navigation

```
┌──────────────────────────────────────────┐
│  🎵 MusicStream ETL Dashboard    [env: dev] │
│  ──────────────────────────────────────── │
│  ← Pipeline    ← KPI Dashboard           │
│                                           │
│  Quick stats (today):                     │
│  • Executions: 12  ✅ 11  ❌ 1            │
│  • Items in DynamoDB: 3,420               │
│  • Last run: 4 min ago                    │
└──────────────────────────────────────────┘
```

### 4.2 `pages/1_Pipeline.py` — Pipeline Trigger & Status

**Section 1 — Upload**
```
st.file_uploader("Upload stream CSV", type=["csv"], accept_multiple_files=True)
[Upload & Trigger Pipeline]  ← calls S3 put_object then SQS send_message
```

**Section 2 — Execution Status**
```
Execution ARN: arn:aws:states:…
Status: ● RUNNING

Stage             Status    Duration
ValidateSchema    ✅ Done    0.4 s
TransformAndComp  ⏳ Running  —
LoadDynamoDB      ⬜ Pending  —
ArchiveBatch      ⬜ Pending  —

[Auto-refresh every 5s]
```

**Section 3 — Result**
```
✅ Succeeded in 122 s
Items written:
  genre_daily_kpi   →  42 records
  top_songs_daily   →  126 records
  top_genres_daily  →  5 records
```

### 4.3 `pages/2_KPI_Dashboard.py` — KPI Query Interface

**Filters**
```python
date  = st.date_input("Date", value=date(2024, 6, 25))
genre = st.selectbox("Genre", ["All"] + GENRES)
st.button("Query")
```

**Summary metrics row**
```
st.metric("Total Plays",         "28,349")
st.metric("Unique Listeners",    "10,776")
st.metric("Total Listening Hrs", "1,683")
st.metric("Active Genres",       "10")
```

**Charts (side-by-side columns)**
```python
col1, col2 = st.columns(2)
with col1:
    st.bar_chart(listen_count_df)      # listen count by genre
with col2:
    st.bar_chart(unique_listeners_df)  # unique listeners by genre
```

**Top 5 Genres table**
```python
st.dataframe(top_genres_df, use_container_width=True)
```

**Top 3 Songs (shown when a specific genre is selected)**
```python
if genre != "All":
    st.subheader(f"Top 3 Songs — {genre}")
    st.dataframe(top_songs_df)
    st.subheader(f"Genre Detail — {genre}")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Listen Count",       ...)
    col2.metric("Unique Listeners",   ...)
    col3.metric("Total Time",         ...)
    col4.metric("Avg Time / User",    ...)
```

---

## 5. AWS Access Pattern (no API Gateway needed)

The Streamlit app runs with the operator's AWS credentials (same profile used for Terraform). It calls `boto3` directly:

```python
# lib/dynamo_queries.py — illustrative
import boto3, os
from botocore.config import Config

_CFG = Config(retries={"mode": "adaptive", "max_attempts": 5})

def _table(name: str):
    return boto3.resource("dynamodb", config=_CFG).Table(name)

def get_top_genres(date: str, env: str = "dev"):
    return _table(f"{env}_top_genres_daily").query(
        KeyConditionExpression="#d = :d",
        ExpressionAttributeNames={"#d": "date"},
        ExpressionAttributeValues={":d": date},
    )["Items"]

def get_genre_kpis(genre: str, start: str, end: str, env: str = "dev"):
    return _table(f"{env}_genre_daily_kpi").query(
        KeyConditionExpression="genre = :g AND #d BETWEEN :s AND :e",
        ExpressionAttributeNames={"#d": "date"},
        ExpressionAttributeValues={":g": genre, ":s": start, ":e": end},
    )["Items"]
```

This matches the adaptive-retry pattern from `dynamo_utils.py` (D-26) already planned for the Glue jobs.

---

## 6. Mock Mode

When `AWS_PROFILE` / credentials are not set (or when `MOCK_MODE=true` in `.env`), `lib/mock_data.py` returns the same fixture data used in `tests/fixtures/`. The Streamlit app shows a banner: `⚡ Mock mode — no AWS credentials detected`.

---

## 7. Deployment Options

| Option | How | When |
|--------|-----|------|
| **Local** | `streamlit run ui/app.py` | Development, demos |
| **Streamlit Community Cloud** | Connect GitHub repo, set AWS secrets in app settings | Free hosted, shareable URL |
| **AWS ECS Fargate** | Docker container, task role with DynamoDB read | Production if needed in v2 |

For Sprint 6, **local** is the target. Community Cloud or ECS deferred to v2.

---

## 8. Dependencies

```
# ui/requirements.txt
streamlit>=1.35.0
boto3>=1.34.0
pandas>=2.2.0
plotly>=5.22.0
python-dotenv>=1.0.0
```

---

## 9. Theme

```toml
# ui/.streamlit/config.toml
[theme]
base            = "dark"
primaryColor    = "#6c63ff"
backgroundColor = "#0f1117"
secondaryBackgroundColor = "#1a1d27"
textColor       = "#e8eaf0"
font            = "sans serif"
```

---

## 10. Sprint Placement

The Streamlit UI is built in **Sprint 6** (orchestration sprint) alongside the Step Functions end-to-end wiring. The pipeline must be running before the UI's live mode is testable; mock mode is available immediately for UI layout work.

Exit gate: the Pipeline page triggers a real run and the KPI Dashboard shows the resulting items from DynamoDB.

---

## 11. Hand-off

- **Next agent (implementation):** build `ui/app.py` + `pages/` + `lib/` per this spec.
- **What they need:** DynamoDB table names (from `dynamodb_schema.md`), adaptive retry pattern (from `error_handling.md`), AWS credential setup (from `human.md` §2).
- **References:** [Streamlit docs](https://docs.streamlit.io), [st.plotly_chart](https://docs.streamlit.io/library/api-reference/charts/st.plotly_chart), [Streamlit multipage](https://docs.streamlit.io/library/get-started/multipage-apps).
