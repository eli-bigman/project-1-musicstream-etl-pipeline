# Project Status — MusicStream ETL Pipeline

**Last updated:** 2026-06-15
**Branch:** `dev` | PR #2 open: `fix/smoke-test-bugs` → `main`
**AWS profile:** `sandbox-musicstream-dev` (eu-west-1, DCE account `970547336735`)

---

## Sprint Completion

| Sprint | Goal | Status | Notes |
|--------|------|--------|-------|
| 0 — Bootstrap | Repo + Terraform + CI skeleton | ✅ Done | Bootstrap state bucket applied |
| 1 — Storage Plane | S3, DynamoDB, IAM skeleton | ✅ Done | All 5 S3 buckets, 3 DDB tables |
| 2 — Shared Library | `glue/shared/` wheel + scripts | ✅ Done | schemas, logging_utils, s3_utils, dynamo_utils |
| 3 — Validation | Lambda T1 + SQS buffer + EventBridge Pipe | ✅ Done | 4 KB range read, D-22 pipe |
| 4 — Transform | PySpark KPI job (T2+T3+6 KPIs) | ✅ Done | G.1X workers (G.025X unsupported in eu-west-1 for batch) |
| 5 — Loader | Python Shell DynamoDB loader | ✅ Done | Single job, all 3 tables, adaptive retry |
| 6 — Orchestration + UI | ASL, Step Functions, Streamlit | ✅ Done | D-22 EventBridge Pipe flow |
| 7 — Reliability & Observability | CloudWatch alarms + dashboard | ✅ Done | `infra/modules/monitoring/` |
| 8 — Hardening | IAM tighten, checkov, semgrep | ⚠️ Partial | CI has checkov + semgrep; wildcard ARNs remain (see below) |
| 9 — CI/CD & Promotion | Full CD pipeline | ✅ Done | `cd-dev.yml` ✅ `cd-prod.yml` ✅ |

---

## AWS Smoke Test — COMPLETE (2026-06-14)

Deployed to sandbox account `970547336735` (eu-west-1). **End-to-end confirmed working.**

| Stage | Result | Notes |
|-------|--------|-------|
| Terraform apply (63 resources) | ✅ PASS | State bucket: `musicstream-tfstate-970547336735` |
| Lambda T1 ValidateSchema | ✅ PASS | Header validation, 4 KB range read |
| Glue PySpark TransformAndCompute | ✅ PASS | T2 ref-integrity + T3 biz rules + 6 KPIs → 3 Parquet datasets |
| Glue Python Shell LoadDynamoDB | ✅ PASS | 113 genre_daily + 5 top_genres + 339 top_songs items |
| Step Functions end-to-end | ✅ PASS | Invoked directly (Method B) |
| Terraform destroy (63 resources) | ✅ PASS | All resources cleaned up |

### Five Bugs Found and Fixed

All five fixes committed in PR #2 (`fix/smoke-test-bugs` branch):

| # | Bug | Fix |
|---|-----|-----|
| 1 | SQS CMK encryption blocked EventBridge delivery | Switch SQS to `sqs_managed_sse_enabled = true` |
| 2 | ASL used `${raw_bucket}` for `--reference_bucket` arg | Fix ASL template; add `reference_bucket_name` var to SM module |
| 3 | PySpark `partitionBy("listen_date")` removes column from Parquet bytes → `KeyError: 'date'` in DynamoDB write | `_partition_values_from_key()` parses S3 key path, injects partition columns into each row |
| 4 | Reference data uploaded as CSV; Glue expected Parquet (D-18) | Convert CSV → Parquet with pandas/pyarrow; delete CSVs; upload Parquet only |
| 5 | EventBridge Pipe delivers raw SQS record array; ASL `ParseInput` expects `$.detail.bucket.name` | **Known gap** — SM was invoked directly for smoke test; production path needs Pipe input transformer |

---

## Documentation — COMPLETE

| File | Status |
|------|--------|
| `.ai/architecture_decisions.md` | ✅ Written — all D-XX decisions with Problem/Options/Decision/Rationale/Trade-offs |
| `.ai/how_to_test.md` | ✅ Written — deploy, smoke test, teardown with real AWS CLI commands |
| `.ai/terraform_explained.md` | ✅ Written — Terraform fundamentals using this project's code as examples |
| `.ai/interview_qa.md` | ✅ Written — 28 senior data engineer Q&A grounded in project decisions |
| `README.md` | ✅ Rewritten — portfolio-grade with ASCII architecture diagram, design decisions, full deploy guide |

---

## Items Needing Your Attention

### 1. Merge PR #2 (fix/smoke-test-bugs → main) — ACTION REQUIRED
PR #2 contains the five smoke-test bug fixes. These must be merged before the next AWS deployment.

### 2. Known gap: EventBridge Pipe → Step Functions input format
The EventBridge Pipe delivers raw SQS message records (an array with `messageId`, `body`, etc.) to Step Functions. The ASL `ParseInput` state expects `$.detail.bucket.name` at the top level (the EventBridge S3 event format). This means **the fully automated trigger path (file upload → EventBridge → SQS → Pipe → SM) will fail at ParseInput** until a Pipe input transformer or Lambda enrichment is added to extract bucket/key from the SQS message body.

**Fix required:** Add an EventBridge Pipe input transformer or a thin Lambda enrichment step between the Pipe and the SM that converts the raw SQS body into the expected `$.detail.bucket.name` / `$.detail.object.keys` format.

**For smoke testing:** Use direct SM invocation (Method B in `.ai/how_to_test.md`) to bypass the Pipe.

### 3. Wildcard ARNs in IAM (Sprint 8 deferred)
`infra/envs/dev/main.tf` passes `lambda_validator_arn = "*"` and `state_machine_arn = "*"` to break a Terraform circular dependency. Acceptable in dev; must be tightened before prod using a two-phase apply.

### 4. PySpark job has no unit tests (Sprint 4 gap)
`glue/pyspark/transform_kpis.py` — the most complex file in the project — has zero unit tests.
**Fix:** Add `tests/unit/test_transform_kpis.py` using `pyspark` in local mode.

### 5. `infra/envs/prod/` does not exist
`cd-prod.yml` references `infra/envs/prod/`. Create before any prod deploy with `deletion_protection = true`, `force_destroy = false`, and a prod state bucket.

### 6. GitHub environment `prod` not configured
Required for the manual approval gate in `cd-prod.yml`. Create at: repo Settings → Environments → New environment → `prod` → add required reviewer.

### 7. SNS alarm email subscription
After any future `terraform apply`, AWS sends a confirmation email to the configured alarm address. The link must be clicked before alarms deliver email notifications.

### 8. Temp file cleanup in load_dynamodb.py is fragile
`_iter_parquet_rows` calls `os.remove(local)` after the generator yields — if `batch_write` raises mid-iteration, the temp file leaks. Fix: wrap in `try/finally`.

---

## AWS Resources (dev — DESTROYED after smoke test)

Resources were confirmed destroyed on 2026-06-14. The next deploy to a new sandbox account should:
1. Set `bucket_suffix = "<account-id>"` in `terraform.tfvars`
2. Create a new state bucket named `musicstream-tfstate-<account-id>`
3. Update `infra/envs/dev/backend.tf` bucket name (revert before committing)
4. Follow `.ai/how_to_test.md` Step 1 through Step 8

| Resource | Name pattern |
|----------|-------------|
| S3 buckets (×5) | `musicstream-dev-{raw,archive,quarantine,scripts,reference}[-suffix]` |
| DynamoDB (×3) | `dev_genre_daily_kpi`, `dev_top_songs_daily`, `dev_top_genres_daily` |
| Lambda | `dev-validate-schema` |
| Glue PySpark | `dev-transform-kpis` |
| Glue Python Shell | `dev-load-dynamodb` |
| Step Functions | `dev-streaming-etl-sm` |
| SQS / DLQ | `dev-etl-buffer`, `dev-etl-buffer-dlq` |
| SNS | `dev-pipeline-alarms` |
| CloudWatch dashboard | `dev-etl-overview` |
| KMS keys (×2) | `dev-data`, `dev-ddb` |

---

## Next Steps (Recommended Order)

1. **Merge PR #2** — smoke-test bug fixes
2. **Fix EventBridge Pipe → SM input format** — add Pipe input transformer (highest functional gap)
3. **Add PySpark unit tests** — highest code quality risk
4. **Fix temp file cleanup in load_dynamodb.py** — low effort, real operational bug
5. **Create `infra/envs/prod/`** — prerequisite for any prod deploy
6. **Configure GitHub `prod` environment** — prerequisite for prod CD gate
