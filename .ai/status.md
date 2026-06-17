# Project Status — MusicStream ETL Pipeline

**Last updated:** 2026-06-17
**Branch:** `dev`
**AWS profile:** `sandbox-musicstream-dev` (eu-west-1, account `970547336735`)

---

## Sprint Completion

| Sprint | Goal | Status | Notes |
|--------|------|--------|-------|
| 0 — Bootstrap | Repo + Terraform + CI skeleton | ✅ Done | Bootstrap state bucket: `musicstream-tfstate-970547336735` |
| 1 — Storage Plane | S3, DynamoDB, IAM skeleton | ✅ Done | All 5 S3 buckets suffixed with account ID, 3 DDB tables |
| 2 — Shared Library | `glue/shared/` wheel + scripts | ✅ Done | schemas, logging_utils, s3_utils, dynamo_utils |
| 3 — Validation | Lambda T1 + SQS buffer + EventBridge Pipe | ✅ Done | 4 KB range read; Pipe enrichment Lambda wired |
| 4 — Transform | PySpark KPI job (T2+T3+6 KPIs) | ✅ Done | G.1X workers (G.025X unsupported in eu-west-1) |
| 5 — Loader | Python Shell DynamoDB loader | ✅ Done | Single job, all 3 tables, partition path injection, adaptive retry |
| 6 — Orchestration + UI | ASL, Step Functions, Streamlit | ✅ Done | Full auto-trigger path working via Pipe enrichment Lambda |
| 7 — Reliability & Observability | CloudWatch alarms + dashboard | ✅ Done | `infra/modules/monitoring/` |
| 8 — Hardening | IAM tighten, checkov, semgrep | ⚠️ Partial | CI has checkov + semgrep; wildcard ARNs remain (see below) |
| 9 — CI/CD & Promotion | Full CD pipeline | ✅ Done | `cd-dev.yml` ✅ `cd-prod.yml` ✅ |

---

## End-to-End Status — CONFIRMED WORKING (2026-06-17)

Deployed to sandbox account `970547336735` (eu-west-1). Full pipeline **SUCCEEDED** — execution `8216300c-217e-4653-bd0a-ac615859d5a7`.

| Stage | Result | Timing | Notes |
|-------|--------|--------|-------|
| Terraform apply (65 resources) | ✅ PASS | — | Includes pipe-enrichment Lambda + KMS fixes |
| Lambda T1 ValidateSchema | ✅ PASS | ~1s | Header validation, 4 KB range read |
| Glue PySpark TransformAndCompute | ✅ PASS | 96s | T2 ref-integrity + T3 biz rules + 6 KPIs → 3 Parquet datasets |
| Glue Python Shell LoadDynamoDB | ✅ PASS | 28s | 113 genre_daily + 5 top_genres + 339 top_songs, dates correct |
| ArchiveBatch (Map state) | ✅ PASS | ~1s | streams1.csv moved to archive bucket |
| Auto-trigger path (S3 → SQS → Pipe → SM) | ✅ PASS | — | Pipe enrichment Lambda reshapes SQS batch |
| Total wall-clock (excluding Glue cold start) | ✅ | ~170s | Full execution start-to-finish: ~3 min |

### Bugs Fixed Since First Smoke Test (2026-06-14 → 2026-06-17)

| # | Bug | Root Cause | Fix |
|---|-----|-----------|-----|
| 1 | SQS CMK encryption blocked EventBridge delivery | `events.amazonaws.com` not in key policy (root delegation only per D-25) | Switched SQS to `sqs_managed_sse_enabled = true` |
| 2 | ASL used `${raw_bucket}` for `--reference_bucket` arg | Wrong template variable | Fixed ASL; added `reference_bucket_name` var through SM module |
| 3 | `date: "None"` written to DynamoDB | PySpark `partitionBy("listen_date")` strips column from row bytes | Added `_partition_values_from_key()` — parses `key=value` from S3 path and injects into row |
| 4 | Glue PySpark AnalysisException: not a Parquet file | Reference data was CSV; Glue expects Parquet (D-18) | Converted to Parquet with pandas/pyarrow; upload only `.parquet` |
| 5 | Auto-trigger path (Pipe → SM) failed at ParseInput | Pipe delivers raw SQS record array; ASL expects `$.detail.bucket.name` | Added `dev-pipe-enrichment` Lambda as Pipe enrichment; reshapes batch → SM input format |
| 6 | `load_dynamodb` exit code 2 | `JOB_NAME` required by `getResolvedOptions` but not passed via SFN ASL | Added `"--JOB_NAME": "${load_dynamodb_job}"` to ASL LoadDynamoDB Arguments |
| 7 | `load_dynamodb` KMS AccessDeniedException on DynamoDB | `dev-glue-python-shell-role` only had S3 KMS key, not DDB KMS key | Added `KmsDecryptDdb` statement with `kms_ddb` key ARN to Glue Python Shell IAM policy |
| 8 | ArchiveBatch CopyToArchive: `$.Execution.Input.ctx.bucket` not found | `$$.Execution.Input` is the original SM input (no `ctx`); inside Map iterator `$` is the item string | Changed Map to use `ItemSelector` to pass `{key, bucket}` per item from `$.ctx.bucket` |
| 9 | Step Functions CopyToArchive: KMS AccessDeniedException on S3 | `dev-step-functions-role` lacked `kms:GenerateDataKey` for the S3 data key | Added `KmsForS3Archive` statement to SF role IAM policy |
| 10 | S3 bucket name collisions (409 BucketAlreadyExists) | Bucket names from prior DCE account already owned globally | Added `bucket_suffix = account_id` to all bucket names |

---

## AWS Resources (dev — LIVE)

| Resource | Name |
|----------|------|
| S3 raw | `musicstream-dev-raw-970547336735` |
| S3 archive | `musicstream-dev-archive-970547336735` |
| S3 quarantine | `musicstream-dev-quarantine-970547336735` |
| S3 scripts | `musicstream-dev-scripts-970547336735` |
| S3 reference | `musicstream-dev-reference-970547336735` |
| DynamoDB | `dev_genre_daily_kpi`, `dev_top_songs_daily`, `dev_top_genres_daily` |
| Lambda validator | `dev-validate-schema` |
| Lambda enrichment | `dev-pipe-enrichment` |
| Glue PySpark | `dev-transform-kpis` (G.1X × 2) |
| Glue Python Shell | `dev-load-dynamodb` (0.0625 DPU) |
| Step Functions | `dev-streaming-etl-sm` |
| EventBridge Pipe | `dev-sqs-to-sfn-pipe` (enrichment: `dev-pipe-enrichment`) |
| SQS / DLQ | `dev-etl-buffer`, `dev-etl-buffer-dlq` |
| KMS keys (×2) | `dev-data` (S3), `dev-ddb` (DynamoDB) |
| Terraform state | `musicstream-tfstate-970547336735` |

---

## Pipeline Efficiency (from successful run logs)

| Stage | Execution time | Worker / capacity | Assessment |
|-------|---------------|-------------------|------------|
| Lambda ValidateSchema | ~1s | 256 MB | ✅ Optimal (4 KB range read) |
| Glue PySpark TransformAndCompute | 96–110s | G.1X × 2 | ⚠️ Cold start dominates; actual compute ~20s; acceptable for micro-batch |
| Glue Python Shell LoadDynamoDB | 28–53s | 0.0625 DPU | ✅ Optimal for data volume |
| ArchiveBatch (Map, S3 native SDK) | ~1s | — | ✅ Optimal |
| Total wall-clock | ~3 min | — | ✅ Acceptable for micro-batch SLA |

**Note on G.1X workers:** G.025X is unavailable in eu-west-1. G.1X × 2 is the minimum billing unit. Cold-start overhead (~60–80s) dominates over actual compute for small files. For large backfills, the autoscale-to-G.1X×8 path via `--run_mode=backfill` is available.

---

## Items Needing Attention

### 1. Wildcard ARNs in IAM (Sprint 8 deferred)
`infra/envs/dev/main.tf` passes `lambda_validator_arn = "*"` and `state_machine_arn = "*"` to break a Terraform circular dependency. Acceptable in dev; tighten before prod using a two-phase apply.

### 2. PySpark job has no unit tests (Sprint 4 gap)
`glue/pyspark/transform_kpis.py` — the most complex file — has zero unit tests.
**Fix:** Add `tests/unit/test_transform_kpis.py` using `pyspark` in local mode.

### 3. `infra/envs/prod/` does not exist
`cd-prod.yml` references `infra/envs/prod/`. Create before any prod deploy with `deletion_protection = true`, `force_destroy = false`, and a prod state bucket.

### 4. GitHub environment `prod` not configured
Required for the manual approval gate in `cd-prod.yml`. Create at: repo Settings → Environments → New environment → `prod` → add required reviewer.

### 5. SNS alarm email subscription
After `terraform apply`, AWS sends a confirmation email. The link must be clicked before alarms deliver notifications.

---

## How to Upload stream2.csv

1. Upload `streams2.csv` to `s3://musicstream-dev-raw-970547336735/streams/yyyy=YYYY/mm=MM/dd=DD/streams2.csv`
   - Replace `YYYY/MM/DD` with the date from `streams2.csv`'s first `listen_time` row.
2. EventBridge fires → SQS receives the event → Pipe batches it → `dev-pipe-enrichment` Lambda reshapes → Step Functions SM starts automatically.
3. Monitor at: `aws stepfunctions list-executions --state-machine-arn arn:aws:states:eu-west-1:970547336735:stateMachine:dev-streaming-etl-sm --profile sandbox-musicstream-dev --region eu-west-1`
4. After ~3 min, KPIs appear in the Streamlit dashboard at `http://localhost:8501`.
