# Error Handling

> Agent: **Reliability**.
> Goal: every failure mode has a *named* response — no silent drops, no zombie executions.

---

## 1. Taxonomy of Failures

| Class | Examples | Strategy |
|-------|----------|----------|
| **Structural** | missing column, unparseable CSV, wrong partition prefix | hard fail → quarantine + alarm |
| **Referential** | unknown `user_id`, unknown `track_id`, future timestamp | soft fail → drop rows, emit metric, continue |
| **Transient** | `Glue.ConcurrentRunsExceededException`, S3 throttling, DynamoDB throughput | retry with exponential backoff |
| **Resource** | OOM, job timeout, DPU limit | retry once with larger sizing then fail to ops |
| **Logic bug** | NaN in `avg_listening_time`, negative duration, rank > expected | fail-fast inside the job; never write bad KPIs |
| **External** | upstream IAM permission, AWS service outage | fail; ops triage |

## 2. Retry Matrix (mirrored in `step_functions.md`)

| Stage                | Retry on              | Attempts | Backoff       | Then                          |
|----------------------|-----------------------|----------|---------------|-------------------------------|
| `validate_schema`    | `States.TaskFailed`   | 2        | 30 s × 2.0    | quarantine + alarm            |
| `validate_referential` | `States.TaskFailed` | 2        | 30 s × 2.0    | alarm                         |
| `transform_kpis`     | `ConcurrentRuns…`     | 5        | 60 s × 2.0    | alarm                         |
|                      | `States.TaskFailed`   | 1        | 30 s          | quarantine + alarm            |
| `load_dynamodb`      | `States.TaskFailed`   | 3        | 30 s × 2.0    | partial-load alarm (no quarantine — the parquet KPI is the truth, the load is replayable) |
| `Archive` / `Delete` | `S3.SlowDown`         | 3        | 5 s × 2.0     | alarm                         |

## 3. Quarantine Flow

```
raw/streams/yyyy=2024/mm=06/dd=25/file_1234.csv
        │
        │ failure in T1 or unrecoverable retry exhaustion
        ▼
quarantine/streams/yyyy=2024/mm=06/dd=25/file_1234.csv
quarantine/streams/yyyy=2024/mm=06/dd=25/file_1234.csv._reason.json
```

`_reason.json` carries: run_id, stage, error code, error message, retries attempted, timestamp. It is the *only* artefact ops needs to triage.

Recovery procedure: fix the issue, copy the CSV back to `raw/streams/<partition>/`, EventBridge re-fires automatically.

## 4. Alarms

| Alarm name                         | Source metric                                              | Threshold | Action            |
|------------------------------------|------------------------------------------------------------|-----------|-------------------|
| `pipeline_execution_failed`        | `AWS/States ExecutionsFailed` per state machine            | ≥ 1 / 5 min | SNS → ops email |
| `quarantine_object_landed`         | S3 `PutObject` event on `quarantine/`                       | any       | SNS → ops email |
| `high_drop_rate`                   | custom `DropRate` metric > 5 %                              | sustained | SNS → ops email |
| `dynamo_write_throttled`           | `AWS/DynamoDB WriteThrottleEvents`                          | > 0       | SNS → ops email |
| `late_arrival`                     | custom `LateArrival` metric                                 | > 0       | SNS (info-only) |
| `glue_job_timeout`                 | `AWS/Glue glue.driver.jobMetric.timeout`                    | > 0       | SNS → ops email |

All alarms go to a single `etl-ops` SNS topic; subscribers (email, Slack via Chatbot) configured in Terraform.

## 5. Dead-Letter Queues

- **SQS buffer redrive**: messages that the EventBridge Pipe cannot process after the source queue redrive policy land in `dev-etl-buffer-dlq`. Alarms on `ApproximateNumberOfMessagesVisible > 0`.
- **EventBridge rule target delivery**: failed S3-rule deliveries to the SQS target show up as `AWS/Events FailedInvocations` for `dev-s3-raw-csv-created`. If this rises while SQS `NumberOfMessagesSent` stays at zero, check SQS resource policy and SQS encryption first.
- **SNS → external subscriber**: failed deliveries to `etl-sns-dlq`.
- **DynamoDB writes**: no native DLQ; the loader writes a `failed_items.jsonl` to `quarantine/loader/` if any item fails after retries.

## 6. Idempotency Guarantees (recap)

| Stage           | Idempotent?                                            |
|-----------------|--------------------------------------------------------|
| Validate-schema | Yes — pure read.                                       |
| Validate-ref    | Yes — overwrites `clean/` parquet for the partition.   |
| Transform       | Yes — `dynamic` partition overwrite over target dates. |
| Load            | Yes — `overwrite_by_pkeys`.                            |
| Archive         | Yes — `CopyObject` same key, then `DeleteObject`.      |

Net: replaying any file is safe. This is the recovery primitive.

## 7. Failure Drill (manual checklist before prod cut-over)

1. Drop a CSV with a missing column → expect quarantine + alarm within 60 s.
2. Drop a CSV with 50% unknown users → expect success with `DropRate` metric ≥ 50%, alarm fires.
3. Throttle the DynamoDB table by lowering RCU to 1 → expect loader retries and partial-load alarm.
4. Replay an archived file → expect KPIs unchanged.
5. Disconnect the Glue role's S3 read permission → expect transform `Catch` → `HandleFailure` → alarm.

## 8. Hand-off

- **Next agent:** Observability — to wire the metrics this doc names.

---

## 9. Revisions from `.ai/review.md`

The retry table (§2) is updated to reflect the new stage set:

| Stage                | Retry on                              | Attempts | Backoff       | Then                          |
|----------------------|---------------------------------------|----------|---------------|-------------------------------|
| `ValidateSchema` (Lambda) | `Lambda.ServiceException`, `Lambda.Unknown` | 3 | 5 s × 2.0 | quarantine + alarm           |
| `TransformAndCompute` | `Glue.ConcurrentRunsExceededException` | 5     | 60 s × 2.0    | alarm                         |
|                      | `States.TaskFailed`                   | 1        | 30 s          | quarantine batch + alarm      |
| `LoadDynamoDB` (single) | `States.TaskFailed`                | 3        | 30 s × 2.0    | partial-load alarm (KPI parquet retains truth) |
| `ArchiveBatch`       | `S3.SlowDown`                         | 3        | 5 s × 2.0     | alarm                         |

New failure surfaces introduced by the revised arch:

| Failure                                  | Source                | Mitigation                                            |
|------------------------------------------|-----------------------|-------------------------------------------------------|
| SQS message redrive                       | DLQ depth > 0         | Alarm `sqs_dlq_nonempty`; ops triages bad payloads.   |
| EventBridge Pipe failure (D-22)          | Pipe execution error  | Pipe has a built-in DLQ for failed target invocations; alarms on Pipe error metrics. `trigger_pipeline` Lambda role removed from system. |
| Quarantine fan-out on partially-invalid batch | Lambda T1 partial | Quarantine *only* the invalid keys; the batch continues with the valid subset. |
| EventBridge cannot deliver to SQS        | EventBridge `FailedInvocations`; SQS sent count remains zero | Confirm SQS uses SQS-managed SSE or add explicit CMK key-policy grants for `events.amazonaws.com`. |

---

### Round 2 revisions from `.ai/review.md`

#### Adaptive Retry on DynamoDB (D-26)

`dynamo_utils.py` centralises all DDB access through a single factory that applies adaptive retry:

```python
from botocore.config import Config

_ADAPTIVE_CFG = Config(retries={"mode": "adaptive", "max_attempts": 10})

def get_ddb_table(table_name: str):
    return boto3.resource("dynamodb", config=_ADAPTIVE_CFG).Table(table_name)
```

`adaptive` mode maintains a client-side token bucket. It throttles the caller *before* the server returns `ProvisionedThroughputExceededException`, preventing retry storms that can worsen the spike. Combined with `max_attempts = 10`, the loader survives the On-Demand auto-scale lag (typically <30 s).

#### Pipe-related failure surfaces

The "Trigger Lambda concurrent invocation cap" failure surface from the prior revision is replaced by EventBridge Pipe error handling (see table above). No Lambda polling code to fail.
