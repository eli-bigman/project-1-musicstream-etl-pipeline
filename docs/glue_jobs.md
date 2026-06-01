# Glue Jobs — Inventory & Operations

> Agent: **Glue ops**.
> Summarises *every* Glue job in the pipeline, why it exists, and how it is sized.

---

## 1. Job Inventory

| Job name                 | Type          | DPU / Workers      | Purpose                                                     | Source script                          |
|--------------------------|---------------|--------------------|-------------------------------------------------------------|----------------------------------------|
| `validate_schema`        | Python Shell  | 0.0625 DPU         | Tier-1 schema gate; runs per arrival                        | `glue/python_shell/validate_schema.py` |
| `validate_referential`   | Python Shell  | 1 DPU              | Tier-2 ref-integrity; writes clean parquet                   | `glue/python_shell/validate_referential.py` |
| `transform_kpis`         | PySpark (4.0) | G.1X × 4 (auto)    | Compute the six KPIs into parquet                            | `glue/pyspark/transform_kpis.py`       |
| `load_dynamodb`          | Python Shell  | 1 DPU              | Read KPI parquet, batch-write to DynamoDB                    | `glue/python_shell/load_dynamodb.py`   |
| `refresh_reference`      | Python Shell  | 0.0625 DPU         | (Manual) Refresh users/songs reference + crawl               | `glue/python_shell/refresh_reference.py` |

## 2. Why this mix (Python Shell + PySpark)

The brief explicitly calls for both job types. The choice for each is **driven by the cost/latency profile of the work**, not by ticking a box:

- Python Shell wins anywhere a Pandas-sized payload is enough — schema check, DynamoDB load, manual catalogue refresh.
- PySpark wins where a join or a windowed aggregation across many partitions matters — the transform step.

Captured as `decision.md` D-02.

## 3. Shared Library

`glue/shared/` is packaged as `shared-X.Y.Z-py3-none-any.whl` and passed to every job through `--extra-py-files` (PySpark) and `--additional-python-modules` (Python Shell). It contains:

- `schemas.py` — schema constants.
- `s3_utils.py` — bucket/key helpers, partition path builders.
- `dynamo_utils.py` — `batch_writer` wrapper with retries.
- `logging_utils.py` — JSON log formatter, `bind_run_id()` context.

Versioning is mechanical: bump in `pyproject.toml`, CI builds the wheel, uploads to `s3://.../glue/shared/`, then a Terraform variable bumps the URI consumed by jobs.

## 4. Common Job Arguments

All jobs receive at minimum:

| Argument         | Purpose                            |
|------------------|------------------------------------|
| `--run_id`       | Execution name from Step Functions; goes into every log line. |
| `--env`          | `dev` / `prod`; used for table-name suffixes. |
| `--TempDir`      | `s3://${scripts_bucket}/tmp/`      |

PySpark-only extras: `--enable-metrics`, `--enable-continuous-cloudwatch-log`, `--enable-job-insights`, `--enable-auto-scaling`.

## 5. Concurrency

- `MaxConcurrentRuns = 10` on each job; matches the Step Functions concurrency cap.
- `Glue.ConcurrentRunsExceededException` is retried by the state machine with exponential backoff (`decision.md` D-09, retry table in `step_functions.md`).

## 6. Bookmarking

**Disabled.** Idempotent reprocessing relies on the archive-directory move (D-10). Glue bookmarks add opaque state that bites under partial failure.

## 7. Loader Job Sketch

```python
# glue/python_shell/load_dynamodb.py — illustrative
import sys, json, boto3
import pyarrow.parquet as pq
from urllib.parse import urlparse
from awsglue.utils import getResolvedOptions

args = getResolvedOptions(sys.argv, ["kpi_kind", "source_s3", "table", "run_id"])

ddb = boto3.resource("dynamodb")
table = ddb.Table(args["table"])

# Read all parquet parts under source_s3 (one date partition)
s3 = boto3.client("s3")
parsed = urlparse(args["source_s3"])
keys = [o["Key"] for o in s3.list_objects_v2(Bucket=parsed.netloc, Prefix=parsed.path.lstrip("/")).get("Contents", [])]

def items_iter():
    for k in keys:
        local = f"/tmp/{k.rsplit('/', 1)[-1]}"
        s3.download_file(parsed.netloc, k, local)
        for batch in pq.ParquetFile(local).iter_batches():
            for row in batch.to_pylist():
                yield shape_for_dynamo(args["kpi_kind"], row)

with table.batch_writer(overwrite_by_pkeys=["date", "genre"]) as bw:
    for item in items_iter():
        bw.put_item(Item=item)
```

`shape_for_dynamo` is a small dispatch in `dynamo_utils.py` that converts a row dict to the right primary-key shape per KPI kind (see `dynamodb_schema.md` §3).

## 8. Per-Job DPU Cost Model (back-of-envelope)

| Job                  | Avg duration | Avg cost per run (eu-west-1, 2024 rates) |
|----------------------|--------------|------------------------------------------|
| `validate_schema`    | 20 s         | < $0.001                                 |
| `validate_referential` | 60 s       | ~$0.005                                  |
| `transform_kpis`     | 2 min        | ~$0.06 (4 × G.1X)                        |
| `load_dynamodb` × 3  | 30 s each    | ~$0.005                                  |
| **Per file total**   | ~4 min       | **~$0.07**                               |

At 100 files/day this is roughly $200/month. Volumetric scaling is linear in file count.

## 9. Hand-off

- **Next agent:** Reliability + Observability.
- **What they need:** the job names (for alarms) and the structured log key names (`run_id`, `stage`, `count`, `level`).

---

## 10. Revisions from `.ai/review.md`

### 10.1 Revised job inventory

| Job name                 | Type          | DPU / Workers      | Purpose (revised)                                          |
|--------------------------|---------------|--------------------|------------------------------------------------------------|
| `transform_kpis`         | PySpark 4.0   | G.1X × 4 (auto)    | Reads `keys[]` of raw CSV + reference Parquet; left-joins songs; T2 unmatched rows → `quarantine/ref-fail/`; applies T3 biz rules; computes the 6 KPIs; writes 3 KPI parquet datasets. |
| `load_dynamodb`          | Python Shell  | 1 DPU              | **Single** job. Reads all 3 KPI parquets; writes to all 3 DynamoDB tables via `batch_writer`. |
| `refresh_reference`      | Python Shell  | 0.0625 DPU         | (Manual) Parquet conversion + crawl. Now also performs the CSV→Parquet conversion (D-18). |

Removed: `validate_schema` (moved to Lambda — D-17), `validate_referential` (fused into `transform_kpis` — D-19), the per-table loader Map fan-out (collapsed — D-02-R).

### 10.2 Why this still satisfies the brief

The brief requires *both* PySpark and Python Shell Glue jobs and a separate "Glue job to reshape and insert transformed metrics into DynamoDB tables." The revised inventory keeps:
- A PySpark job (`transform_kpis`).
- A Python Shell job (`load_dynamodb`) that exists *specifically* to ingest into DynamoDB.

### 10.3 Revised cost model

| Job                  | Avg duration | Avg cost per batch run |
|----------------------|--------------|------------------------|
| Lambda `validate_schema` | ~500 ms  | ~$0.000001             |
| `transform_kpis`     | 2 min        | ~$0.06 (4 × G.1X)      |
| `load_dynamodb`      | 30 s         | ~$0.005                |
| **Per batch total**  | ~3 min       | **~$0.07**             |

A batch can now contain up to 50 files (SQS drain limit). With 1,000 files/day arriving in ~30 batches, daily cost is ~$2 — about 35× cheaper than the original "1 SM per file" model under the same load.

### 10.5 Worker type → G.025X (D-24)

Revised job spec for `transform_kpis`:

| Parameter         | Old        | New                                   |
|-------------------|------------|---------------------------------------|
| `worker_type`     | `G.1X`     | `G.025X`                              |
| `number_of_workers` | 4        | 2 (autoscales up to 8 for backfill)   |
| DPU total (normal)| 4.0        | 0.5                                   |
| DPU total (backfill) | —       | up to 8.0 (`--run_mode=backfill`)     |

**G.025X memory.** 4 GB RAM per worker × 2 = 8 GB driver + executor pool. Sufficient for broadcasting a ≤50 MB Parquet songs table and processing micro-batches of a few thousand rows.

**Fallback region check.** `G.025X` is not available in all regions. The Terraform `modules/glue-jobs` module will add a `variable "worker_type"` with default `G.025X` and a note to override to `G.1X` in regions that lack it.

### 10.6 Revised cost model (updated for D-24)

| Job                       | Avg duration | DPU   | Avg cost per normal batch run |
|---------------------------|--------------|-------|-------------------------------|
| Lambda `validate_schema`  | ~500 ms      | —     | ~$0.000001                    |
| `transform_kpis` (G.025X) | 2 min        | 0.5   | ~$0.008                       |
| `load_dynamodb`           | 30 s         | 0.0625| ~$0.001                       |
| **Per batch total**       | ~3 min       |       | **~$0.009**                   |

Down from ~$0.07/batch (D-02-R revision). At 30 batches/day: ~$0.27/day vs. $2.10/day.

### 10.4 Direct-write rationale (pushback)

The reviewer proposed writing DynamoDB items directly from PySpark via `foreachPartition`. We did **not** adopt this — see `decision.md` D-02-R for the rationale (brief compliance + replay separation). The Python Shell loader reads the KPI parquet and replays cheaply on DDB throttling.
