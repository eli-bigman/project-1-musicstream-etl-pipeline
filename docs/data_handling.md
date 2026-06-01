# Data Handling — Historical Backfill + Ongoing Arrivals

> Agent: **Ingestion**.
> Input: provided sample dataset (`data/`), `data_validation.md`.
> Output: a strategy that lets the pipeline absorb the historical `data/streams/*.csv` files seamlessly *alongside* arrivals that show up at unpredictable times.

---

## 1. Sources of Data

| Source                   | Cadence                    | Shape                                                 | Volume (today) |
|--------------------------|----------------------------|-------------------------------------------------------|----------------|
| `streams/streams*.csv`   | irregular, event-triggered | `user_id, track_id, listen_time`                      | 3 files × ~MBs |
| `users/users.csv`        | rare (manual refresh)      | `user_id, user_name, user_age, user_country, created_at` | <1 MB     |
| `songs/songs.csv`        | rare (manual refresh)      | `id, track_id, artists, album_name, ..., track_genre` | a few MB       |

The brief calls this "streaming data", but at the storage layer it is **micro-batch CSV in S3** — every file is a discrete event.

## 2. Two Ingestion Modes

### Mode A — *Historical backfill* (one-time)

Used to seed the system with `streams1.csv`, `streams2.csv`, `streams3.csv` and the reference files.

```bash
# reference data — land first, before anything else
aws s3 cp data/users/users.csv s3://musicstream-dev-reference/users/users.csv
aws s3 cp data/songs/songs.csv s3://musicstream-dev-reference/songs/songs.csv

# historical stream files — partition by listen_date as we land them
# (a Python Shell helper job reads the first row to find the date and writes
#  the file under the correct prefix, simulating the production arrival path)
python scripts/seed_sample_streams.py \
  --src data/streams/ \
  --bucket musicstream-dev-raw \
  --prefix streams/
```

A backfill **looks identical to a normal arrival** to the rest of the pipeline. The seed script:
1. Reads each CSV header to confirm shape (a local mirror of schema validation).
2. Computes the partition date from the first row's `listen_time` (or splits the file if it straddles dates — see §4).
3. Writes to `s3://musicstream-dev-raw/streams/yyyy=<>/mm=<>/dd=<>/<original_name>.csv`.
4. EventBridge fires; the state machine runs; the file ends up in `archive/`.

There is **no special "backfill mode" Glue job**. Reuse the live path. That is the seamless integration.

### Mode B — *Live arrivals* (ongoing)

Producers `PUT` files into `raw/streams/`. The partition prefix is the producer's responsibility *or* an upstream Lambda's; if a producer uploads to `raw/streams/incoming/file.csv` (no partition), a small fan-out Lambda relocates it under the partition prefix derived from its header row. This Lambda is the only stateful piece of the ingestion edge and lives in the same Terraform module as the trigger.

The data validation gate later rechecks that the partition prefix matches the data inside, so producer mistakes are caught — not paved over.

## 3. Partitioning Scheme

```
streams/yyyy=2024/mm=06/dd=25/<file>.csv
```

Why:
- Aligns with the daily KPI cadence — the PySpark transform scans only the partition(s) it needs.
- Compatible with Glue Catalog + Athena for ad-hoc inspection.
- Predictable archive path (the same prefix is mirrored into `archive/`).

If a file contains rows from multiple dates (rare, but possible during a clock-skew or producer-buffer flush), the validation job **splits** it into per-date sub-files in a `clean/` staging prefix and passes the *list* of clean sub-files forward; the transform job then knows which dates to recompute.

## 4. Late-Arriving Data

> "Late" = a file arrives whose `listen_time` is older than the most-recently-processed partition.

Treatment:

| Lateness            | Behaviour                                                                                                              |
|---------------------|-----------------------------------------------------------------------------------------------------------------------|
| < 7 days late       | Recompute that date's KPIs in full (overwrite DynamoDB items for that date). See `decision.md` D-05.                  |
| 7–30 days late      | Same, but emit a CloudWatch metric `LateArrival` for visibility.                                                       |
| > 30 days late      | Validation tier-3 rule rejects → quarantine. Suggests upstream is broken; needs human triage before reprocessing.      |

## 5. Reference Data Refresh

A separate, manually-invoked Glue Python Shell job (`refresh_reference`):
1. Diffs the new `users.csv` / `songs.csv` against the catalog table.
2. Snapshots the previous version to `reference/_snapshots/yyyy-mm-ddTHH:MM:SS/`.
3. Replaces the live file.
4. Runs the Glue crawler to update the catalog.

The transform job reads reference data fresh at the start of every run — no caching layer needed at v1 volumes.

## 6. Idempotency of Backfill

Replaying a file is safe:
- Schema + ref validation runs again (cheap).
- Transform recomputes the day's KPIs (overwrites in DynamoDB).
- Archive copy is a `CopyObject` to the same archive key — idempotent.
- Source `DeleteObject` is idempotent.

This means the safe recovery procedure for *anything* that went wrong is: copy the file back into `raw/streams/<partition>/` and let the pipeline run.

## 7. What's Out of Scope

- Compaction of many small files into Parquet — deferred to v2 once volume warrants it.
- Streaming via Kinesis Firehose — captured in `decision.md` D-15.
- Compressed CSV / gzip handling — supported in PySpark trivially, but explicit testing deferred.

## 8. Hand-off

- **Next agent:** Orchestration agent — already has the input contract (`bucket`, `key`) and the partition convention.
- **What they need from this doc:** the partition prefix shape, the meaning of "split on multi-date files", and the late-arrival policy.

---

## 9. Revisions from `.ai/review.md`

### 9.1 Arrival path now buffers through SQS (D-11-R)

```
PUT raw/streams/yyyy=…/mm=…/dd=…/file.csv
        ▼
EventBridge rule (prefix=streams/, suffix=.csv)
        ▼
SQS standard queue  ← buffers up to 14 days; DLQ after 5 failed receives
        ▼
Trigger Lambda (cron rate(2 minutes) OR depth ≥ 20)
        ▼
StartExecution(input = { bucket, keys: [k1, k2, …] })
```

The state machine input contract changes from `{bucket, key}` to `{bucket, keys[]}`. Everything downstream consumes the list. The partitioning scheme (§3) is unchanged — only the *triggering* changes.

### 9.2 Reference data is Parquet now (D-18)

The conversion happens inside the `refresh_reference` Python Shell job (see `glue_jobs.md` §10.1). PySpark reads `s3://…/reference/users/users.parquet` and `…/songs/songs.parquet`.

### 9.3 Backfill workflow unchanged in spirit, with one twist

`scripts/seed_sample_streams.py` still writes CSVs to `raw/streams/yyyy=…/`. The new behaviour is that EventBridge now routes those PUTs into SQS, where they buffer for up to 2 minutes before triggering the state machine. The seed script can pass `--immediate` to invoke the trigger Lambda directly (bypassing the wait) when you want a sub-minute feedback loop during development.

### 9.3 Trigger Lambda removed — replaced by EventBridge Pipes (D-22)

The trigger path from `data_handling.md` §9.1 simplifies further:

```
PUT raw/streams/…/file.csv
       ▼
EventBridge rule (object-created, prefix=streams/)
       ▼
SQS standard queue  ← still present (D-11-R)
       ▼
EventBridge Pipe  ← replaces Trigger Lambda
  source: sqs_queue_arn
  BatchSize=50, MaxBatchingWindow=120s
       ▼
states:StartExecution → SM input = { bucket, keys: [...] }
```

The `--immediate` dev shortcut previously documented (bypass the wait by invoking the trigger Lambda) is now replaced by **manually publishing a JSON message to SQS** with the desired key list, which the Pipe then routes to the SM instantly.

### 9.4 Late-arrival policy unchanged

The < 7 d / 7–30 d / > 30 d treatment in §4 holds — the buffering layer does not alter how late files are processed once the SM picks them up.
