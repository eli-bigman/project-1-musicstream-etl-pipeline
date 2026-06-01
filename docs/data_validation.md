# Data Validation

> Agent: **Validation**.
> Input: sample CSV headers, user-story US2 ("validate required columns").
> Output: a tiered validation contract that the Step Functions schema-gate and ref-gate jobs implement.

---

## 1. Validation Tiers

| Tier | Name                  | Failure action                                    | Where it runs                  |
|------|------------------------|---------------------------------------------------|--------------------------------|
| T1   | Schema validation      | Hard fail → quarantine, alarm                     | `validate_schema` (Python Shell) |
| T2   | Referential integrity  | Soft fail → drop bad rows, emit metric            | `validate_referential` (Python Shell) |
| T3   | Business rules         | Soft fail → drop bad rows, emit metric            | Inside `transform_kpis` (PySpark) before aggregation |

The split between T2 and T3 keeps the heavy join cheap (T2 emits a clean S3 path; T3 enforces only what needs the joined view).

## 2. Expected Schemas (the contract)

```python
# glue/shared/schemas.py — illustrative
from dataclasses import dataclass

STREAMS_SCHEMA = {
    "columns": ["user_id", "track_id", "listen_time"],
    "types":   {"user_id": "int", "track_id": "str", "listen_time": "timestamp"},
    "required": ["user_id", "track_id", "listen_time"],
}

USERS_SCHEMA = {
    "columns": ["user_id", "user_name", "user_age", "user_country", "created_at"],
    "types":   {"user_id": "int", "user_name": "str", "user_age": "int",
                "user_country": "str", "created_at": "date"},
    "required": ["user_id"],
}

SONGS_SCHEMA = {
    # 'id' is the row index; 'track_id' is the natural key
    "columns": ["id", "track_id", "artists", "album_name", "track_name",
                "popularity", "duration_ms", "explicit", "danceability",
                "energy", "key", "loudness", "mode", "speechiness",
                "acousticness", "instrumentalness", "liveness", "valence",
                "tempo", "time_signature", "track_genre"],
    "required_for_kpi": ["track_id", "duration_ms", "track_genre", "track_name"],
}
```

The full column list is the *expected* schema. The `required` (or `required_for_kpi`) list is the *minimum* set that must be present and non-null for the KPI computation to be valid.

## 3. Tier-1: Schema Validation Job

`glue/python_shell/validate_schema.py` — runs in <30 s on files up to 100 MB.

Checks performed:

1. **File accessible** in S3 (raises if 404).
2. **CSV parseable** (UTF-8, single header row, `,` separator).
3. **Header row contains all required columns** (case-sensitive match).
4. **No duplicated header names.**
5. **Row count > 0.**
6. **First-row sample parses** to expected types (cheap shallow type check; full type check happens in the PySpark stage).
7. **Partition prefix matches first-row `listen_time` date** (catches misfiled uploads).

Outputs to Step Functions:

```json
{
  "schema_valid": true,
  "row_count": 12345,
  "detected_date": "2024-06-25",
  "warnings": [],
  "errors": []
}
```

If any check fails, the job raises a typed exception with `error_code = "SchemaInvalid"`, which the state machine catches and routes to `QuarantineFile`. A `_reason.json` sidecar is written next to the quarantined file:

```json
{
  "run_id": "exec-2024-06-25-abc",
  "stage": "validate_schema",
  "errors": [
    {"check": "missing_required_column", "column": "track_id"}
  ],
  "ts": "2024-06-25T18:23:00Z"
}
```

## 4. Tier-2: Referential Integrity Job

`glue/python_shell/validate_referential.py` — reads the validated CSV, the catalog tables for `users` and `songs`, and emits a `clean/` version.

Checks:

1. **`user_id` exists in `users` table** — drop rows that don't.
2. **`track_id` exists in `songs` table** — drop rows that don't.
3. **`listen_time` not in the future** — drop.
4. Records per-rule drop counts to CloudWatch metrics.

If the drop rate exceeds **5%** of input rows, the job still completes but emits a CloudWatch alarm metric `HighDropRate` (default threshold configurable per env). The pipeline does **not** fail — bad data is upstream's problem, not the ETL's, but the alarm gives ops visibility.

Outputs to Step Functions:

```json
{
  "clean_path": "s3://musicstream-dev-raw/streams/clean/yyyy=2024/mm=06/dd=25/file_1234.parquet",
  "input_rows": 12345,
  "kept_rows": 12300,
  "dropped": {
    "unknown_user_id": 30,
    "unknown_track_id": 10,
    "future_listen_time": 5
  },
  "dates": ["2024-06-25"]
}
```

> Note: the clean file is rewritten as **Snappy-compressed Parquet** to speed up the next stage. CSV remains as the source of truth in `raw/`.

## 5. Tier-3: Business Rules (inside PySpark transform)

Run on the joined DataFrame:

- `duration_ms` from `songs` must be > 0 and < 30 minutes (`1_800_000` ms). Outliers dropped.
- `track_genre` non-null.
- A user playing the *same track* more than 1000 times in one day is filtered (likely bot).

These rules require the joined view and are cheaper to express in Spark than in the Python Shell stage.

## 6. Sample Fixtures

In `tests/fixtures/`:

| File                       | Defect                          | Expected outcome              |
|----------------------------|----------------------------------|-------------------------------|
| `valid_streams.csv`        | none                             | passes all tiers              |
| `missing_column.csv`       | no `track_id` column             | T1 quarantine                 |
| `bad_listen_time.csv`      | `listen_time` is `"nope"`        | T1 type check failure         |
| `unknown_user_id.csv`      | 50% of rows have `user_id=99999` | T2 drops 50%, alarm fires     |
| `future_listen_time.csv`   | timestamps 2099                  | T2 drops all, pipeline succeeds with zero KPIs (interesting edge to verify) |
| `wrong_partition.csv`      | file in `2024/06/24/` but dates are `2024/06/25` | T1 partition mismatch         |

## 7. Why Python Shell (not Lambda, not PySpark)

- **Lambda**: 15-min limit and the deployment-package ergonomics for `pandas`/`pyarrow` are painful. Avoidable here.
- **PySpark**: 60 s+ cold start and 1–2 DPU minimum — pure overhead for a header-row check.
- **Python Shell**: 0.0625 DPU floor, boots in ~10 s, has `pandas`/`pyarrow` baked in. The right tool.

## 8. Hand-off

- **Next agent:** Transform agent.
- **What they receive on the stick:** `clean_path` (parquet), `dates` (list of date strings), `dropped` counts (passed through for observability), `run_id`.

---

## 9. Revisions from `.ai/review.md`

The tier structure stands (T1 / T2 / T3) but the *runtimes* change:

| Tier | Original runtime          | Revised runtime                                  |
|------|---------------------------|--------------------------------------------------|
| T1   | Glue Python Shell         | **AWS Lambda** (D-17). ~100 ms cold start; no DPU floor. |
| T2   | Glue Python Shell + Pandas join → temp parquet | **Fused into PySpark transform** (D-19). Left-join with `broadcast(songs)`; unmatched rows are written to `quarantine/ref-fail/` and counted as a metric. |
| T3   | Inside PySpark (unchanged) | Unchanged.                                       |

Why this matters for the validation contract:

- **No intermediate `clean/` parquet.** The transform job consumes raw CSV directly (validated by Lambda) plus the reference Parquet (D-18). T2 violations are emitted as a side-output, not as a precondition on the next job.
- **`validate_schema` no longer outputs `clean_path` or `dates`.** It outputs `{valid_keys: [...], invalid_keys: [...], detected_dates: [...]}`. The state machine fans `invalid_keys` to quarantine and passes `valid_keys` + `detected_dates` to the transform job.
- **Fixtures (§6 above) keep their names** but the *expected stage that catches them* shifts: `missing_column.csv` → caught by Lambda (T1); `unknown_user_id.csv` → caught inside the PySpark left-join (T2). Test assertions update accordingly.
- **Performance.** The previous T1+T2 pair burned ~80 s of Python Shell time per file. Revised: Lambda T1 in ~500 ms, T2 absorbed into the Spark job with no extra read pass.

### 9.1 Lambda schema-gate sketch

```python
# lambda/validate_schema.py — illustrative
import boto3, csv, io, json, os, urllib.parse
from datetime import datetime, timezone

REQUIRED = ["user_id", "track_id", "listen_time"]
s3 = boto3.client("s3")

def lambda_handler(event, ctx):
    valid, invalid, dates = [], [], set()
    for key in event["keys"]:
        bucket = event["bucket"]
        try:
            head = s3.get_object(Bucket=bucket, Key=key, Range="bytes=0-65535")
            reader = csv.reader(io.TextIOWrapper(head["Body"], encoding="utf-8"))
            header = next(reader)
            if any(c not in header for c in REQUIRED):
                raise ValueError(f"missing columns: {set(REQUIRED) - set(header)}")
            first = next(reader, None)
            if not first:
                raise ValueError("zero data rows")
            ts = datetime.fromisoformat(first[header.index("listen_time")])
            dates.add(ts.date().isoformat())
            valid.append(key)
        except Exception as e:
            _quarantine(bucket, key, str(e))
            invalid.append({"key": key, "reason": str(e)})
    return {"valid_keys": valid, "invalid_keys": invalid, "detected_dates": sorted(dates)}
```

### 10. Lambda Range-Request Tightening (D-23)

The Lambda validator reads only the first **4 KB** of each file (not 64 KB as in the original sketch). This keeps Lambda memory O(1) regardless of CSV size.

```python
# lambda/validate_schema/handler.py — updated excerpt
def get_header(bucket: str, key: str) -> list[str]:
    resp = s3.get_object(Bucket=bucket, Key=key, Range="bytes=0-4095")
    chunk = resp["Body"].read().decode("utf-8", errors="replace")
    if "\n" not in chunk:
        # Header line longer than 4 KB — rare but handle gracefully
        resp2 = s3.get_object(Bucket=bucket, Key=key, Range="bytes=0-65535")
        chunk = resp2["Body"].read().decode("utf-8", errors="replace")
        logger.warning(event="wide_header", key=key)
    return chunk.split("\n")[0].strip().split(",")
```

**Guard.** If the file has no newline within 65 KB (i.e. the entire file is one huge row with no header), the job raises `SchemaInvalid` and quarantines — the file is structurally broken regardless.

### 9.2 PySpark side-output for T2 (illustrative)

```python
enriched = streams.join(F.broadcast(songs), on="track_id", how="left")
matched   = enriched.filter(F.col("genre").isNotNull())
unmatched = enriched.filter(F.col("genre").isNull())

(unmatched
   .write.mode("append")
   .parquet(f"s3://{quarantine_bucket}/ref-fail/run_id={run_id}/"))

unmatched_count = unmatched.count()  # emit as CloudWatch metric
```
