# Testing Strategy

> Agent: **QA**.
> Goal: high confidence that a green build is deployable, without needing a full AWS environment for the common feedback loop.

---

## 1. Test Pyramid

```
                ▲ slow, scarce, real AWS
                │     ┌──────────────────────────────┐
                │     │  e2e smoke (dev account)     │  ← 1–2
                │     └──────────────────────────────┘
                │
                │     ┌──────────────────────────────┐
                │     │  integration (moto / local)  │  ← 10–20
                │     └──────────────────────────────┘
                │
                │     ┌──────────────────────────────┐
                │     │  unit (pytest)               │  ← 50+
                │     └──────────────────────────────┘
                ▼ fast, plentiful, local
```

## 2. Unit Tests (`tests/unit/`)

- **`test_schemas.py`** — every fixture in `tests/fixtures/` runs through the schema validator; outcome matches the expected verdict (`data_validation.md` §6).
- **`test_transform_kpis.py`** — runs PySpark locally via `pytest-spark` against a tiny inline DataFrame; asserts each of the six KPIs to a hand-computed expected value.
- **`test_dynamo_utils.py`** — `batch_writer` retry behaviour, item-shape conversion per KPI kind.
- **`test_logging_utils.py`** — log lines are valid JSON, contain mandatory keys, redact PII (`user_name`, `user_country`).

```python
# illustrative — tests/unit/test_transform_kpis.py
def test_top_3_songs_per_genre(spark):
    streams = spark.createDataFrame(
        [(1, "tA", "2024-06-25 10:00:00"),
         (2, "tA", "2024-06-25 10:01:00"),
         (1, "tB", "2024-06-25 10:02:00"),
         (3, "tC", "2024-06-25 10:03:00")],
        ["user_id", "track_id", "listen_time"])
    songs = spark.createDataFrame(
        [("tA", "Alpha", "rock", 200000),
         ("tB", "Beta",  "rock", 180000),
         ("tC", "Gamma", "rock", 210000)],
        ["track_id", "track_name", "genre", "duration_ms"])
    out = top_songs(streams, songs, ["2024-06-25"]).collect()
    ranks = {row["track_id"]: row["rank"] for row in out if row["genre"] == "rock"}
    assert ranks == {"tA": 1, "tB": 2, "tC": 3}
```

## 3. Integration Tests (`tests/integration/`)

Use **`moto`** to mock S3 + DynamoDB in-process:

- Drop fixture CSV into mocked S3.
- Invoke `validate_schema.main()` directly with the bucket/key.
- Assert `clean/...` parquet exists with expected row count.
- Repeat for `validate_referential` and `load_dynamodb`.

Step Functions are *not* mocked at this layer — the orchestration is exercised in e2e.

## 4. End-to-End Smoke (`tests/e2e/`)

Runs against the real `dev` environment after `terraform apply`. One test:

1. Uploads `tests/fixtures/valid_streams.csv` to `s3://musicstream-dev-raw/streams/yyyy=2099/mm=01/dd=01/`.
2. Polls Step Functions for the execution started by EventBridge (poll by `name` prefix or by `startedAfter` timestamp).
3. Waits up to 10 minutes for `SUCCEEDED`.
4. Issues `GetItem` against `dev_genre_daily_kpi` and asserts at least one item.
5. Confirms the source file is in `archive/` and gone from `raw/`.

Negative e2e: drop `missing_column.csv`, assert it lands in `quarantine/` with `_reason.json`.

## 5. Terraform Tests

- `terraform validate` on every PR.
- `terraform plan` against `dev` on PR — output posted as PR comment (via tfcomment / Atlantis-style action).
- `tflint` + `checkov` for security smells.

## 6. CI Pipeline

```yaml
# .github/workflows/ci.yml — illustrative
on: [pull_request]
jobs:
  python:
    steps:
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -e glue/[dev]
      - run: pytest tests/unit tests/integration -q

  terraform:
    steps:
      - uses: hashicorp/setup-terraform@v3
      - run: terraform -chdir=infra/envs/dev init -backend=false
      - run: terraform -chdir=infra/envs/dev validate
      - run: tflint --recursive
      - run: checkov -d infra/
```

The e2e job runs **post-deploy** in the `cd-dev.yml` workflow, not on PR.

## 7. Test Data Generation

A small `scripts/gen_synthetic_streams.py` produces fixture CSVs with controlled defects (missing columns, future timestamps, unknown user ids). It is the source of every file under `tests/fixtures/`.

## 8. Coverage Gates

- Unit + integration > 80 % line coverage of `glue/` source.
- No coverage gate on Terraform — `validate` + `plan` is the test.

## 9. Hand-off

- **Next agent:** Release agent — needs to know which gates must be green before promotion to prod.
