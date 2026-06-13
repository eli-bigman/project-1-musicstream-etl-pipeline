# Project Status — MusicStream ETL Pipeline

**Last updated:** 2026-06-13  
**Branch:** `dev` → PR open against `main`  
**AWS profile:** `musicstream-dev` (eu-west-1, account 647594457599)

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
| 7 — Reliability & Observability | CloudWatch alarms + dashboard | ✅ Done | `infra/modules/monitoring/` — see below |
| 8 — Hardening | IAM tighten, checkov, semgrep | ⚠️ Partial | CI has checkov + semgrep; wildcard ARNs remain (see below) |
| 9 — CI/CD & Promotion | Full CD pipeline | ✅ Done | `cd-dev.yml` ✅ `cd-prod.yml` ✅ |

---

## What Was Done in This PR (dev → main)

### Infra fixes from dev apply testing
- `infra/modules/kms/main.tf` — deletion window 14→7 days (faster teardown in dev)
- `infra/modules/s3-data-lake/` — `force_destroy` variable added; dev passes `true`
- `infra/modules/dynamodb-kpi-tables/` — `deletion_protection` variable; dev passes `false`
- `infra/modules/glue-jobs/main.tf` — removed `kms_key_id` from CW Log Groups (requires separate key policy grant for `logs.amazonaws.com`; skipped for dev)
- `infra/modules/lambda-validator/main.tf` — same CW Logs KMS removal
- `infra/modules/iam-roles/main.tf` — added `kpi_$folder$` and `tmp/*` S3 paths to Glue PySpark role
- `infra/envs/dev/` — `force_destroy=true`, `deletion_protection=false`, G.1X, wildcard ARNs for circular dep, `kms_key_arn` wired to glue + sm modules

### ASL fix
- `step_functions/pipeline.asl.json` — removed `ResultSelector` block that assumed Glue sync response shape (Glue `StartJobRun` is async; no `Output` key exists). Hardcoded `kpi_parquet_root` in LoadDynamoDB args.

### Build tooling
- `glue/pyproject.toml` — `setuptools.build_meta` backend; stripped `boto3`/`pyarrow` from wheel deps (present in Glue runtime; re-downloading causes pip compile failure)

### Sprint 7 — Monitoring (`infra/modules/monitoring/`)
- SNS topic `{env}-pipeline-alarms` + email subscription
- CloudWatch alarm: SQS DLQ depth > 0 (1 min period)
- CloudWatch alarm: Step Functions `ExecutionsFailed` > 0 (5 min period)
- CloudWatch alarm: Lambda `Errors` > 0 (5 min period)
- EventBridge rule → SNS for Glue job FAILED/ERROR/TIMEOUT state changes
- CloudWatch dashboard `{env}-etl-overview` (SF executions, Lambda invocations, DLQ depth)
- Wired into `infra/envs/dev/main.tf`

### Sprint 9 — CI/CD
- `tests/e2e/test_smoke.py` — smoke test stub used by CD workflows; skips gracefully when env vars absent
- `.github/workflows/cd-prod.yml` — triggers on semver tag push; plans prod, blocks apply behind GitHub environment manual approval gate

---

## Items Needing Your Attention

### 1. Confirm alarm email subscription (ACTION REQUIRED after `terraform apply`)
After the monitoring module is applied, AWS will send a confirmation email to `richard.nutsugah@amalitechtraining.org`. You **must click the confirmation link** before any alarms can deliver notifications to that email.

### 2. Wildcard ARNs in IAM (Sprint 8 — deferred)
`infra/envs/dev/main.tf` passes `lambda_validator_arn = "*"` and `state_machine_arn = "*"` to the IAM module to break a Terraform circular dependency:
```
iam_role → lambda_function → iam_role  (lambda needs role; role needs lambda ARN for scoped policy)
```
**Impact:** The IAM policy allows Step Functions to invoke *any* Lambda and *any* state machine in the account, rather than just the pipeline resources. Acceptable for a dev-only account but must be tightened before production.  
**Fix path:** Use a two-phase apply (apply IAM with wildcards first, then tighten), or use `aws_iam_policy` as a separate resource with `depends_on`.

### 3. PySpark job has no automated tests (Sprint 4 — gap)
`glue/pyspark/transform_kpis.py` — the most complex file in the project — has zero unit tests. KPI correctness (top-3 tie-breaking, bot-play filter, left-join ref validation) is entirely untested.  
**Risk:** A regression in KPI logic produces wrong numbers in DynamoDB with no automated signal.  
**Fix:** Add `tests/unit/test_transform_kpis.py` using `pyspark` in local mode (`SparkSession.builder.master("local[1]")`); no Glue context needed for pure transform logic.

### 4. Future-date rows pass silently through the pipeline
`transform_kpis.py` has no explicit filter for `listen_time_date > current_date`. A malformed stream with a future date (e.g. `2099-01-01`) creates KPI rows that pollute DynamoDB tables.  
**Fix (one line in PySpark):**
```python
.filter(F.col("listen_time_date") <= F.current_date())
```
Add after the existing T3 bot-play filter.

### 5. `load_dynamodb.py` temp file cleanup is fragile
`_iter_parquet_rows` calls `os.remove(local)` inside the generator, but if `batch_write` raises mid-iteration the temp file is never cleaned up. On Glue container warm-starts this accumulates stale `.parquet` files.  
**Fix:**
```python
try:
    for batch in pf.iter_batches():
        yield from batch.to_pylist()
finally:
    os.remove(local)
```

### 6. `infra/envs/prod/` does not exist yet
`cd-prod.yml` references `infra/envs/prod/` for Terraform. This directory needs to be created before a prod deploy is attempted. It should mirror `infra/envs/dev/` with:
- `backend.tf` pointing at the prod state bucket (create with a second bootstrap apply)
- `terraform.tfvars` with `env = "prod"`, `force_destroy = false`, `deletion_protection = true`
- No `alarm_email` override (will use variable default or a prod ops address)

### 7. GitHub environments need to be configured
For `cd-prod.yml` to enforce the manual approval gate, you must create a GitHub environment named **`prod`** in the repo settings with:
- At least one required reviewer (yourself)
- Optional: deployment branch rule limited to `main`

Also create **`prod-plan`** environment (no reviewers needed — this just runs the plan).

---

## Next Steps (Recommended Order)

1. **Merge this PR** — all CI gates should pass
2. **Apply Terraform on dev** — `terraform -chdir=infra/envs/dev apply` with `musicstream-dev` profile
3. **Confirm SNS email subscription** — check inbox after apply
4. **Upload Glue scripts** — `aws s3 sync glue/ s3://musicstream-dev-scripts/glue/ --profile musicstream-dev`
5. **Run end-to-end test** — drop a CSV into `s3://musicstream-dev-raw/streams/` and watch the Step Functions console
6. **Fix PySpark tests** (item 3 above) — highest code quality risk
7. **Fix temp file cleanup** (item 5 above) — low effort, eliminates a real operational bug
8. **Create `infra/envs/prod/`** (item 6) — prerequisite for any prod deploy
9. **Configure GitHub environments** (item 7) — prerequisite for prod CD gate

---

## AWS Resources (dev)

| Resource | Name/ARN pattern |
|----------|-----------------|
| S3 raw | `musicstream-dev-raw` |
| S3 archive | `musicstream-dev-archive` |
| S3 quarantine | `musicstream-dev-quarantine` |
| S3 scripts | `musicstream-dev-scripts` |
| S3 reference | `musicstream-dev-reference` |
| DynamoDB | `dev_genre_daily_kpi`, `dev_top_songs_daily`, `dev_top_genres_daily` |
| Lambda | `dev-validate-schema` |
| Glue PySpark | `dev-transform-kpis` |
| Glue Python Shell | `dev-load-dynamodb` |
| Step Functions | `dev-streaming-etl-sm` |
| SQS buffer | `dev-etl-buffer` |
| SQS DLQ | `dev-etl-buffer-dlq` |
| SNS alarms | `dev-pipeline-alarms` |
| CW dashboard | `dev-etl-overview` |

**Terraform state:** `s3://musicstream-dev-tfstate` (DynamoDB lock: `musicstream-dev-tfstate-lock`)
