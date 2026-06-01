# UI Dashboard — Plan

> Added per user request. Not in the original brief, but maps directly to all five user stories.
> See `decision.md` D-28 for the decision to add it.

---

## 1. Purpose

A lightweight single-page dashboard that lets both the **data engineer** and the **business analyst** test the pipeline without touching the AWS console or CLI.

| User Story | UI Feature |
|------------|-----------|
| US1: Ingest data via automated pipeline | **Pipeline tab** — drag-and-drop CSV upload to S3 raw bucket |
| US2: Validate incoming datasets | **Pipeline tab** — real-time execution status showing validation stage |
| US3: Transform raw data using Glue | **Pipeline tab** — Step Functions stage tracker |
| US4: Store processed data in DynamoDB | **Pipeline tab** — confirms items written count |
| US5: Query DynamoDB for insights | **KPI Dashboard tab** — date picker, genre filter, charts |

## 2. Architecture

```
Browser
  │
  │ fetch()
  ▼
API Gateway  (HTTP API, IAM auth or API key)
  ├── POST /pipeline/trigger  → Lambda: reads file from browser,
  │                              puts it to S3 raw bucket,
  │                              returns execution ARN
  ├── GET  /pipeline/status/{arn} → Lambda: calls StepFunctions DescribeExecution
  ├── GET  /kpi/genres?date={d}   → Lambda: queries genre_daily_kpi table
  ├── GET  /kpi/top-genres?date={d} → Lambda: queries top_genres_daily table
  └── GET  /kpi/top-songs?date={d}&genre={g} → Lambda: queries top_songs_daily
```

In **mock mode** (no `UI_API_BASE_URL` set), the dashboard uses hardcoded fixture data so the UI can be developed and tested without a deployed backend.

## 3. Technology Choice

**Vanilla HTML + CSS + JavaScript** — no framework, no build step, one file.

- Served locally via `python -m http.server 8080 --directory ui/`.
- In production: static files in S3 + CloudFront (optional, Sprint 9 scope).
- No npm, no webpack, no transpilation — anyone can open it.
- Chart library: **Chart.js** (CDN, no install needed).

## 4. Page Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  🎵 MusicStream ETL Dashboard              [env: dev]  [Settings]│
├──────────────────┬──────────────────────────────────────────────┤
│  Pipeline  │ KPI │                                               │
├────────────┤     │           (active tab content)                │
│            │     │                                               │
└────────────┴─────┴───────────────────────────────────────────────┘
```

### Tab 1: Pipeline

```
┌────────────────────────────────────────────────────┐
│  Drop a CSV file here or click to browse            │
│  [  streams1.csv  ×  ]  [Upload & Trigger]         │
└────────────────────────────────────────────────────┘

Execution: arn:aws:states:...  [Refresh]

Stage tracker:
  ✅ ValidateSchema     — 0.4 s
  ✅ TransformAndCompute — 112 s
  ✅ LoadDynamoDB        — 8 s
  ✅ ArchiveBatch        — 1 s
  ✅ Success

Items written: 42 genre KPIs · 126 top-song records · 5 top-genre records
```

### Tab 2: KPI Dashboard

```
Date: [2024-06-25 ▾]   Genre: [All ▾]   [Query]

┌────────────────────────┐  ┌────────────────────────┐
│  Top 5 Genres          │  │  Listen Count by Genre │
│  1. pop     8,421      │  │  [bar chart]           │
│  2. rock    6,104      │  │                        │
│  3. hip-hop 5,832      │  │                        │
│  4. jazz    4,211      │  │                        │
│  5. r&b     3,901      │  └────────────────────────┘
└────────────────────────┘

┌────────────────────────────────────────────────────┐
│  Genre Detail: rock on 2024-06-25                  │
│  Listen Count: 6,104  │  Unique Listeners: 2,341   │
│  Total Time: 12.4 hrs │  Avg Time/User: 19 min     │
└────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────┐
│  Top 3 Songs: rock on 2024-06-25                   │
│  #1  Bohemian Rhapsody   412 plays                 │
│  #2  Hotel California    389 plays                 │
│  #3  Stairway to Heaven  301 plays                 │
└────────────────────────────────────────────────────┘
```

### Settings panel (slide-in)

| Setting | Description |
|---------|-------------|
| API Base URL | `UI_API_BASE_URL` — blank = mock mode |
| AWS Region | For display only |
| Dev / Prod toggle | Switches table name prefix |
| Mock data on/off | Forces mock mode even with a URL set |

## 5. API Gateway Lambda (brief spec — Sprint 6 scope)

A single `api_handler` Python Lambda handles all routes:

```python
# lambda/api_handler/handler.py — illustrative
ROUTES = {
    ("POST", "/pipeline/trigger"):          trigger_pipeline,
    ("GET",  "/pipeline/status"):           pipeline_status,
    ("GET",  "/kpi/genres"):                get_genre_kpis,
    ("GET",  "/kpi/top-genres"):            get_top_genres,
    ("GET",  "/kpi/top-songs"):             get_top_songs,
}

def lambda_handler(event, ctx):
    method = event["requestContext"]["http"]["method"]
    path   = event["requestContext"]["http"]["path"]
    handler = ROUTES.get((method, path))
    if not handler:
        return {"statusCode": 404, "body": "Not found"}
    return handler(event)
```

Auth: **API key** (simple; upgrade to Cognito in v2 if multi-user).

## 6. Mock Data

When `UI_API_BASE_URL` is empty, `ui/mock.js` supplies:
- Five genre KPI rows for `2024-06-25`.
- Top-5 genres for `2024-06-25`.
- Top-3 songs for `rock` on `2024-06-25`.
- A fake execution trace (stages complete one-by-one with a 1-second interval).

This lets the UI be demoed without any AWS account or deployed pipeline.

## 7. Hand-off

- **Next agent** (implementation): build `ui/index.html` per this spec.
- **What they need**: bucket name (for the upload endpoint), table names, API base URL.
- The actual UI implementation is at `ui/index.html` — see that file for the built version.
