# Step Functions — Orchestration

> Agent: **Orchestration**.
> Input: validation spec (`data_validation.md`), transform spec (`transformation_logic.md`), load spec (`dynamodb_schema.md`), archival spec (`file_archival.md`).
> Output: an ASL definition + retry/error map any operator can reason about from the visual graph alone.

---

## 1. State Machine Type

**Standard** (not Express). Reasons:
- Visual execution history is required for debugging irregular arrivals.
- Each execution lasts seconds to a few minutes — under Standard's 1-year limit.
- Express charges per request *and* per GB-second, which makes long-running Glue waits cost more.

## 2. Visual Flow

```
              ┌───────────────────────┐
              │  ParseInput           │   ← extract bucket, key from EventBridge event
              └───────────┬───────────┘
                          ▼
              ┌───────────────────────┐
              │  ValidateSchema       │   ← Glue Python Shell, sync (.sync)
              └───────────┬───────────┘
                          ▼
                     ┌──┴──┐
                     │     │ on schema_valid == false
                     ▼     ▼
        ┌─────────────────────────────┐
        │  QuarantineFile             │ ──► Fail("SchemaInvalid")
        └─────────────────────────────┘

                  ▼ (valid)
              ┌───────────────────────┐
              │  ValidateReferential  │   ← Glue Python Shell
              └───────────┬───────────┘
                          │ outputs: clean_path, dropped_count
                          ▼
              ┌───────────────────────┐
              │  TransformKPIs        │   ← Glue PySpark (.sync)
              └───────────┬───────────┘
                          ▼
              ┌───────────────────────┐
              │  LoadDynamoDB (Map)   │   ← parallel item writers
              │   • genre_daily       │
              │   • top_songs_daily   │
              │   • top_genres_daily  │
              └───────────┬───────────┘
                          ▼
              ┌───────────────────────┐
              │  ArchiveFile          │   ← Step Functions native S3 CopyObject + DeleteObject
              └───────────┬───────────┘
                          ▼
              ┌───────────────────────┐
              │  Success              │
              └───────────────────────┘
```

A global `Catch` on every Glue task routes to **`HandleFailure`**, which:
1. Moves the source file to `quarantine/` with a `_reason.json` sidecar.
2. Publishes to an SNS topic (ops alarm).
3. Transitions to `Fail` with a typed error code.

## 3. ASL Skeleton

```json
{
  "Comment": "Streaming-ETL pipeline. One execution per arriving file.",
  "StartAt": "ParseInput",
  "States": {
    "ParseInput": {
      "Type": "Pass",
      "Parameters": {
        "bucket.$": "$.detail.bucket.name",
        "key.$": "$.detail.object.key",
        "run_id.$": "$$.Execution.Name"
      },
      "ResultPath": "$.ctx",
      "Next": "ValidateSchema"
    },

    "ValidateSchema": {
      "Type": "Task",
      "Resource": "arn:aws:states:::glue:startJobRun.sync",
      "Parameters": {
        "JobName": "${validate_schema_job}",
        "Arguments": {
          "--bucket.$": "$.ctx.bucket",
          "--key.$": "$.ctx.key",
          "--run_id.$": "$.ctx.run_id"
        }
      },
      "ResultPath": "$.validate_schema",
      "Retry": [{
        "ErrorEquals": ["States.TaskFailed"],
        "IntervalSeconds": 30, "MaxAttempts": 2, "BackoffRate": 2.0
      }],
      "Catch": [{
        "ErrorEquals": ["SchemaInvalid"],
        "ResultPath": "$.error",
        "Next": "QuarantineFile"
      }, {
        "ErrorEquals": ["States.ALL"],
        "ResultPath": "$.error",
        "Next": "HandleFailure"
      }],
      "Next": "ValidateReferential"
    },

    "ValidateReferential": { "...": "..." },

    "TransformKPIs": {
      "Type": "Task",
      "Resource": "arn:aws:states:::glue:startJobRun.sync",
      "Parameters": {
        "JobName": "${transform_kpis_job}",
        "Arguments": {
          "--clean_path.$": "$.validate_ref.clean_path",
          "--target_dates.$": "$.validate_ref.dates",
          "--run_id.$": "$.ctx.run_id"
        }
      },
      "ResultPath": "$.transform",
      "Retry": [{
        "ErrorEquals": ["Glue.ConcurrentRunsExceededException"],
        "IntervalSeconds": 60, "MaxAttempts": 5, "BackoffRate": 2.0
      },{
        "ErrorEquals": ["States.TaskFailed"],
        "IntervalSeconds": 30, "MaxAttempts": 1
      }],
      "Catch": [{ "ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "HandleFailure" }],
      "Next": "LoadDynamoDB"
    },

    "LoadDynamoDB": {
      "Type": "Map",
      "ItemsPath": "$.transform.kpi_targets",
      "MaxConcurrency": 3,
      "Iterator": {
        "StartAt": "LoadOneTable",
        "States": {
          "LoadOneTable": {
            "Type": "Task",
            "Resource": "arn:aws:states:::glue:startJobRun.sync",
            "Parameters": {
              "JobName": "${load_dynamodb_job}",
              "Arguments": {
                "--kpi_kind.$": "$.kind",
                "--source_s3.$": "$.source_s3",
                "--table.$": "$.table"
              }
            },
            "Retry": [{ "ErrorEquals": ["States.TaskFailed"], "MaxAttempts": 3, "IntervalSeconds": 30, "BackoffRate": 2 }],
            "End": true
          }
        }
      },
      "ResultPath": "$.load",
      "Catch": [{ "ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "HandleFailure" }],
      "Next": "ArchiveFile"
    },

    "ArchiveFile": {
      "Type": "Parallel",
      "Branches": [
        {
          "StartAt": "CopyToArchive",
          "States": {
            "CopyToArchive": {
              "Type": "Task",
              "Resource": "arn:aws:states:::aws-sdk:s3:copyObject",
              "Parameters": {
                "Bucket": "${archive_bucket}",
                "CopySource.$": "States.Format('{}/{}', $.ctx.bucket, $.ctx.key)",
                "Key.$": "$.ctx.key"
              },
              "End": true
            }
          }
        }
      ],
      "ResultPath": "$.archive",
      "Next": "DeleteFromRaw"
    },

    "DeleteFromRaw": {
      "Type": "Task",
      "Resource": "arn:aws:states:::aws-sdk:s3:deleteObject",
      "Parameters": { "Bucket.$": "$.ctx.bucket", "Key.$": "$.ctx.key" },
      "End": true
    },

    "QuarantineFile": {
      "Type": "Task",
      "Resource": "arn:aws:states:::aws-sdk:s3:copyObject",
      "Parameters": {
        "Bucket": "${quarantine_bucket}",
        "CopySource.$": "States.Format('{}/{}', $.ctx.bucket, $.ctx.key)",
        "Key.$": "$.ctx.key"
      },
      "Next": "Fail"
    },

    "HandleFailure": {
      "Type": "Task",
      "Resource": "arn:aws:states:::sns:publish",
      "Parameters": {
        "TopicArn": "${alarm_topic_arn}",
        "Subject": "ETL failure",
        "Message.$": "$"
      },
      "Next": "QuarantineFile"
    },

    "Fail": { "Type": "Fail", "Error": "PipelineFailure" }
  }
}
```

The full ASL lives at `step_functions/pipeline.asl.json` and is templated by Terraform via `templatefile()`.

## 4. Retry & Backoff Policy

| Failure source | Retry? | Backoff |
|----------------|--------|---------|
| `Glue.ConcurrentRunsExceededException` | 5× | 60 s × 2.0 |
| Transient `States.TaskFailed` on validation | 2× | 30 s × 2.0 |
| Transient on transform | 1× | 30 s |
| Transient on load | 3× | 30 s × 2.0 |
| `SchemaInvalid` (custom) | 0× | — direct to quarantine |
| `States.Timeout` | 0× | escalate to ops |

## 5. Input Contract

EventBridge delivers:
```json
{
  "detail": {
    "bucket": { "name": "musicstream-dev-raw" },
    "object": { "key": "streams/yyyy=2024/mm=06/dd=25/file_1234.csv" }
  }
}
```

Anything more complex (e.g. multiple files in one S3 `MultipartUploadCompleted`) is out of scope for v1.

## 6. Observability Hooks

- `INCLUDE_EXECUTION_DATA=true` on the log group.
- CloudWatch metrics `ExecutionsFailed`, `ExecutionsTimedOut` → alarm at threshold 1 over 5 min.
- X-Ray tracing enabled (helps when a Glue job's `sync` wait hides the real cause).

## 7. Hand-off

- **Next agent:** Reliability agent.
- **They need:** Knowledge of every `Catch` branch (`HandleFailure`, `QuarantineFile`, `Fail`) → see `error_handling.md`.

---

## 8. Revisions from `.ai/review.md`

The original flow (§§ 2–3 above) collapses per the review. The current binding flow is:

```
EventBridge ──▶ SQS buffer ──▶ Trigger Lambda ──▶ StartExecution(input: keys[])
                                                                  │
                                                                  ▼
                                                    ParseInput (keys[], run_id)
                                                                  │
                                                                  ▼
                                                    ValidateSchema  (Lambda — Task)
                                                       │ valid_keys[]    │ invalid_keys[]
                                                       ▼                 ▼
                                                                       (Map: copy → quarantine + _reason.json)
                                                                       │ continue or terminate
                                                       ▼
                                          TransformAndCompute (Glue PySpark — .sync)
                                          inputs:  valid_keys[], reference_bucket
                                          outputs: kpi_parquet_root, target_dates[]
                                                       │
                                                       ▼
                                          LoadDynamoDB (Glue Python Shell — .sync)
                                          input: kpi_parquet_root  (one job, all 3 tables)
                                                       │
                                                       ▼
                                          ArchiveBatch (Map over valid_keys[])
                                                       │
                                                       ▼
                                                    Success
```

Replaced states:
| Old state              | Replacement                                                    |
|------------------------|----------------------------------------------------------------|
| `ValidateSchema` (Glue)| `ValidateSchema` (Lambda Task — `arn:aws:states:::lambda:invoke`) |
| `ValidateReferential`  | Fused into `TransformAndCompute` PySpark                       |
| `TransformKPIs`        | Renamed `TransformAndCompute`; performs ref join, biz rules, KPI |
| `LoadDynamoDB` Map (×3)| **Single** `LoadDynamoDB` Python Shell task                    |
| Single-file `ArchiveFile` | `ArchiveBatch` Map state                                    |

Input contract change — execution now receives `keys[]` (list of S3 keys), not a single `key`. PySpark reads them with `spark.read.csv(["s3://b/k1", "s3://b/k2", ...])`.

Retry-table updates:
- `ValidateSchema (Lambda)` — `Lambda.ServiceException`, `Lambda.Unknown`: 3× / 5 s × 2.0.
- `LoadDynamoDB` (single task) — `States.TaskFailed`: 3× / 30 s × 2.0 (unchanged).

The full revised ASL skeleton replaces the one in §3; the file at `step_functions/pipeline.asl.json` will reflect this layout when implementation begins.

---

## 9. Revisions from Architectural Review Round 2 (`.ai/review.md` §2)

### Trigger path update (D-22)

The `Trigger Lambda → StartExecution` step is replaced by **EventBridge Pipes**. The SM receives its input directly from the Pipe, which batches SQS messages and calls `StartExecution` natively. The SM itself is unchanged; only the component that calls it changes.

SM input shape is identical to §8:

```json
{ "bucket": "musicstream-dev-raw", "keys": ["streams/…/file1.csv", "streams/…/file2.csv"] }
```

The `ParseInput` `Pass` state extracts `bucket` + `keys[]` + injects `run_id` from `$$.Execution.Name` — no change there.

### ValidateSchema Lambda update (D-23 — range bytes)

The `ValidateSchema` Lambda Task state in §8 is unchanged structurally. The Lambda implementation now fetches `Range="bytes=0-4095"` (4 KB) instead of the prior 64 KB sketch. If the first `\n` is not found in that range, it falls back to `bytes=0-65535` and emits a `wide_header` warning log. Detailed in `data_validation.md` §10.
