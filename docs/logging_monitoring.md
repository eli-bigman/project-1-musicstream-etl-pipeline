# Logging & Monitoring

> Agent: **Observability**.
> Goal: anyone can answer *"is the pipeline healthy?"* and *"what happened to file X?"* without SSHing anywhere.

---

## 1. Logging Standard

Every log line emitted by every Glue job is **JSON, one object per line**, with at minimum:

```json
{"ts":"2024-06-25T18:34:00.123Z","level":"INFO","run_id":"exec-abc","stage":"validate_schema","file":"streams/yyyy=2024/mm=06/dd=25/file_1234.csv","count":12345,"event":"row_count","msg":"input row count"}
```

Mandatory keys: `ts`, `level`, `run_id`, `stage`, `event`. Optional: `file`, `count`, `error_code`, `latency_ms`.

The helper lives in `glue/shared/logging_utils.py`; jobs `from shared.logging_utils import logger` and call `logger.info(event="row_count", count=n)`.

## 2. Log Groups & Retention

| Group                                                 | Source                  | Retention dev / prod |
|-------------------------------------------------------|-------------------------|----------------------|
| `/aws/glue/jobs/${env}-validate-schema`               | Glue job stdout         | 14 / 90 days         |
| `/aws/glue/jobs/${env}-validate-referential`          | Glue job stdout         | 14 / 90 days         |
| `/aws/glue/jobs/${env}-transform-kpis`                | Glue driver + executors | 14 / 90 days         |
| `/aws/glue/jobs/${env}-load-dynamodb`                 | Glue job stdout         | 14 / 90 days         |
| `/aws/vendedlogs/states/${env}-streaming-etl-sm`      | Step Functions          | 30 / 365 days        |
| `/aws/lambda/${env}-pipe-enrichment`                  | Pipe enrichment Lambda  | 14 / 90 days         |

Set via Terraform `aws_cloudwatch_log_group.retention_in_days`.

## 3. CloudWatch Metrics

### Built-in (free)
- `AWS/States ExecutionsStarted / ExecutionsSucceeded / ExecutionsFailed`
- `AWS/Events Invocations / FailedInvocations` for `dev-s3-raw-csv-created`
- `AWS/SQS NumberOfMessagesSent`, `ApproximateNumberOfMessagesVisible`, `ApproximateNumberOfMessagesNotVisible` for `dev-etl-buffer`
- `AWS/SQS ApproximateNumberOfMessagesVisible` for `dev-etl-buffer-dlq`
- `AWS/Glue glue.driver.aggregate.numCompletedTasks`, `glue.driver.aggregate.elapsedTime`
- `AWS/DynamoDB ConsumedWriteCapacityUnits`, `WriteThrottleEvents`, `SuccessfulRequestLatency`
- `AWS/S3 NumberOfObjects` on `quarantine/`

### Custom (emitted by jobs via `put_metric_data` or EMF)
| Namespace                    | Metric             | Dimensions              | Emitted by         |
|------------------------------|--------------------|-------------------------|--------------------|
| `MusicStream/ETL`            | `RowsKept`         | env, stage              | validate_referential |
| `MusicStream/ETL`            | `RowsDropped`      | env, reason             | validate_referential |
| `MusicStream/ETL`            | `DropRate`         | env                     | validate_referential |
| `MusicStream/ETL`            | `LateArrival`      | env, days_late_bucket   | validate_schema    |
| `MusicStream/ETL`            | `KpiItemsWritten`  | env, kpi_kind           | load_dynamodb      |
| `MusicStream/ETL`            | `KpiLoadLatencyMs` | env, kpi_kind           | load_dynamodb      |

EMF (Embedded Metric Format) preferred — metrics ride on log lines, one less API call.

## 4. Dashboards

Single CloudWatch dashboard `${env}-etl-overview` with five panels:

1. **Throughput** — executions started / succeeded / failed, 1-minute granularity, last 24 h.
2. **Validation health** — `DropRate`, `RowsDropped` by reason, `LateArrival`.
3. **Compute** — Glue elapsed time per job, DPU-hours.
4. **Storage** — DynamoDB consumed write capacity, throttle events, item count.
5. **Quarantine** — count of objects in `quarantine/`, age of oldest.
6. **Trigger health** — EventBridge rule invocations vs failed invocations, SQS buffer depth, SQS DLQ depth.

Dashboard is defined in Terraform.

## 5. Logs Insights Queries (canned)

```
# All errors for a run
fields @timestamp, stage, error_code, msg
| filter run_id = "exec-abc"
| filter level = "ERROR"
| sort @timestamp desc

# Drop-rate by reason for the last 24h
fields @timestamp, event, dropped.unknown_user_id, dropped.unknown_track_id, dropped.future_listen_time
| filter event = "ref_validation_summary"
| stats sum(dropped.unknown_user_id), sum(dropped.unknown_track_id), sum(dropped.future_listen_time) by bin(1h)

# Latency distribution of the transform job
fields @timestamp, latency_ms
| filter stage = "transform_kpis" and event = "job_done"
| stats avg(latency_ms), pct(latency_ms, 95), max(latency_ms) by bin(1h)
```

Saved into the project's Logs Insights "Saved queries" tab via Terraform.

## 6. Tracing

X-Ray enabled on the state machine. Spans:
- ParseInput → ValidateSchema (Glue) → ValidateReferential → TransformKPIs → LoadDynamoDB (Map) → Archive.

X-Ray service map is the fastest way to see *where* time is spent across a run.

## 7. Alarming

See `error_handling.md` §4 for the alarm catalog. This document owns the *metrics*; that document owns *how the alarms react*.

## 8. Audit Trail

CloudTrail at the account level covers IAM/API actions. We do not need a separate audit pipeline at v1.

## 9. Hand-off

- **Next agent:** QA / Testing agent — needs to know what metrics are expected to fire during the failure drills.
