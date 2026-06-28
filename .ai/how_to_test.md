# How to Test — MusicStream ETL Pipeline

This document is the single reference for running every test layer in this project. Open it when you need to validate infrastructure, run unit tests, or execute a full end-to-end smoke test against a live AWS sandbox account.

---

## Environment Reference

| Setting | Value |
|---|---|
| AWS profile | `sandbox-musicstream-dev` |
| Account ID | `970547336735` |
| Region | `eu-west-1` |
| Terraform state bucket | `musicstream-tfstate-970547336735` |
| DynamoDB lock table | `musicstream-tfstate-lock` |
| Raw bucket | `musicstream-dev-raw-970547336735` |
| Reference bucket | `musicstream-dev-reference-970547336735` |
| Scripts bucket | `musicstream-dev-scripts-970547336735` |
| Archive bucket | `musicstream-dev-archive-970547336735` |
| Quarantine bucket | `musicstream-dev-quarantine-970547336735` |
| DynamoDB tables | `dev_genre_daily_kpi`, `dev_top_songs_daily`, `dev_top_genres_daily` |
| Step Functions | `dev-streaming-etl-sm` |
| Lambda validator | `dev-validate-schema` |
| Lambda enrichment | `dev-pipe-enrichment` |
| Glue jobs | `dev-transform-kpis` (G.1X × 2), `dev-load-dynamodb` (0.0625 DPU) |
| SQS encryption | SQS-managed SSE (`sqs_managed_sse_enabled = true`) |

> Replace `<account-id>` in commands below with `970547336735`. Set `bucket_suffix = "970547336735"` in `infra/envs/dev/terraform.tfvars` when deploying to a different account.

---

## Layer 1 — Pre-commit (Ruff + Black)

Run before every commit. This is the fastest gate.

```bash
pre-commit run --all-files
```

If hooks are not installed yet:

```bash
pip install pre-commit
pre-commit install
```

Expected output: all hooks pass with `Passed` or `Skipped`. Any `Failed` line means a formatting or lint violation — `ruff` and `black` will auto-fix most of them on the first run; re-run once to confirm clean.

---

## Layer 2 — Unit Tests

No AWS credentials required. These run fully offline.

```bash
pytest tests/unit -q
```

Coverage includes:
- `lambda/validate_schema/handler.py` — schema gate logic (T1), range-read path, quarantine output shape
- `glue/shared/` utilities — `dynamo_utils`, `logging_utils`, `s3_utils`, `schemas`

To run with coverage report:

```bash
pytest tests/unit -q --cov=lambda --cov=glue/shared --cov-report=term-missing
```

All tests must be green before opening a PR. There should be zero warnings about PII fields (`user_name`, `user_country`) appearing in log output.

---

## Layer 3 — Integration Tests

Require active AWS credentials and deployed infrastructure. Run after `terraform apply` has completed.

```bash
export AWS_PROFILE=sandbox-musicstream-dev
pytest tests/integration -q
```

Or with the profile inline:

```bash
AWS_PROFILE=sandbox-musicstream-dev pytest tests/integration -q
```

Integration tests verify:
- S3 bucket reachability
- Step Functions state machine exists and is in `ACTIVE` state
- DynamoDB tables exist and accept a point-in-time read

If tests skip with a message like `env vars absent`, that is expected when infrastructure is not deployed — the suite is designed to be safe to run anywhere.

---

## Layer 4 — Terraform Linting

Run all three tools in sequence. All must pass before merging IaC changes.

```bash
# 1. Syntax and reference validation
terraform -chdir=infra/envs/dev validate

# 2. Best-practice linting
tflint --recursive

# 3. Security and compliance checks (no IAM wildcards, encryption, etc.)
checkov -d infra/
```

Install dependencies if needed:

```bash
# tflint
# https://github.com/terraform-linters/tflint#installation

# checkov
pip install checkov
```

Checkov will flag any `*` in IAM `Action` lists — this is intentional policy enforcement. Do not suppress these checks; fix the wildcard instead.

---

## Layer 5 — SAST (Semgrep)

Covers `glue/`, `lambda/`, and `ui/` for Python security issues.

```bash
semgrep --config p/python glue/ lambda/ ui/
```

Install if needed:

```bash
pip install semgrep
```

Expected: zero findings at `ERROR` or `WARNING` severity. `INFO`-level notices are acceptable but review them.

---

## Full Smoke Test — End-to-End Against AWS

Work through these steps in order. Each step is a prerequisite for the next.

---

### Step 1 — Bootstrap (first-time only, new sandbox account)

Skip this step if the state bucket and lock table already exist in the account.

```bash
# Create versioned, encrypted state bucket
aws s3api create-bucket \
  --bucket musicstream-tfstate-<account-id> \
  --region eu-west-1 \
  --create-bucket-configuration LocationConstraint=eu-west-1 \
  --profile sandbox-musicstream-dev

aws s3api put-bucket-versioning \
  --bucket musicstream-tfstate-<account-id> \
  --versioning-configuration Status=Enabled \
  --profile sandbox-musicstream-dev

aws s3api put-bucket-encryption \
  --bucket musicstream-tfstate-<account-id> \
  --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' \
  --profile sandbox-musicstream-dev

# Create DynamoDB lock table
aws dynamodb create-table \
  --table-name musicstream-tfstate-lock \
  --billing-mode PAY_PER_REQUEST \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --region eu-west-1 \
  --profile sandbox-musicstream-dev
```

Then update `infra/envs/dev/backend.tf` to reference the new bucket name, and ensure `infra/envs/dev/terraform.tfvars` contains:

```hcl
bucket_suffix = "<account-id>"
```

---

### Step 2 — Terraform Init and Apply

```bash
AWS_PROFILE=sandbox-musicstream-dev \
  terraform -chdir=infra/envs/dev init -reconfigure

AWS_PROFILE=sandbox-musicstream-dev \
  terraform -chdir=infra/envs/dev apply
```

Review the plan output carefully before typing `yes`. Apply time is approximately 5–10 minutes for a fresh deploy.

---

### Step 3 — Build and Upload Artifacts

Run these from the repo root.

**Lambda ZIP (PowerShell):**

```powershell
New-Item -ItemType Directory -Force dist | Out-Null
Compress-Archive -Path lambda/validate_schema/handler.py -DestinationPath dist/validate_schema.zip -Force
aws s3 cp dist/validate_schema.zip `
  s3://musicstream-dev-scripts-<account-id>/lambda/0.1.0/validate_schema.zip `
  --profile sandbox-musicstream-dev
```

**Lambda ZIP (bash):**

```bash
mkdir -p dist
zip dist/validate_schema.zip lambda/validate_schema/handler.py
aws s3 cp dist/validate_schema.zip \
  s3://musicstream-dev-scripts-<account-id>/lambda/0.1.0/validate_schema.zip \
  --profile sandbox-musicstream-dev
```

**Glue shared wheel:**

```bash
pip install build
cd glue && python -m build --wheel --outdir ../dist && cd ..

aws s3 cp dist/shared-0.1.0-py3-none-any.whl \
  s3://musicstream-dev-scripts-<account-id>/glue/shared/ \
  --profile sandbox-musicstream-dev
```

**Glue PySpark and Python Shell scripts:**

```bash
aws s3 sync glue/ \
  s3://musicstream-dev-scripts-<account-id>/glue/ \
  --profile sandbox-musicstream-dev
```

---

### Step 4 — Upload Reference Data (Parquet only)

**Critical:** Reference data must be uploaded as Parquet, not CSV. Glue reads the entire directory prefix; any CSV files present will cause the PySpark job to fail (decision D-18).

Convert locally, then upload:

```bash
python3 -c "
import pandas as pd
df = pd.read_csv('data/songs/songs.csv')
df.to_parquet('dist/songs.parquet', index=False)
"

python3 -c "
import pandas as pd
df = pd.read_csv('data/users/users.csv')
df.to_parquet('dist/users.parquet', index=False)
"

aws s3 cp dist/songs.parquet \
  s3://musicstream-dev-reference-<account-id>/songs/ \
  --profile sandbox-musicstream-dev

aws s3 cp dist/users.parquet \
  s3://musicstream-dev-reference-<account-id>/users/ \
  --profile sandbox-musicstream-dev
```

Verify no CSVs exist in the reference prefixes:

```bash
aws s3 ls s3://musicstream-dev-reference-<account-id>/songs/ --profile sandbox-musicstream-dev
aws s3 ls s3://musicstream-dev-reference-<account-id>/users/ --profile sandbox-musicstream-dev
```

Both listings should show only `.parquet` files.

---

### Step 5 — Trigger the Pipeline

Two methods are available. Both are fully functional. Use Method A to verify the complete auto-trigger path; use Method B for fast ETL iteration without the 120-second Pipe batch window.

**Method A — Upload CSV to raw S3 (full auto-trigger path including Pipe):**

```bash
aws s3 cp data/streams/streams1.csv \
  s3://musicstream-dev-raw-<account-id>/streams/yyyy=2024/mm=06/dd=25/streams1.csv \
  --profile sandbox-musicstream-dev
```

EventBridge detects the S3 PUT event, delivers it to SQS, and the EventBridge Pipe batches messages over a 120-second window. The `dev-pipe-enrichment` Lambda enrichment step reshapes the SQS batch into the `{detail:{bucket:{name},object:{keys:[...]}}}` format the ASL expects. Wait 2–3 minutes before checking for an execution. This path exercises the full S3 → EventBridge → SQS → Pipe → enrichment Lambda → Step Functions flow.

The EventBridge rule only matches raw bucket object-created events whose key matches `streams/*.csv`. This is intentionally implemented with EventBridge `wildcard` matching. Do not replace it with `{prefix = "streams/", suffix = ".csv"}` inside one comparison object; AWS rejects that shape because each comparison object can contain only one operator.

**Method B — Invoke Step Functions directly (recommended for ETL testing):**

```bash
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:eu-west-1:<account-id>:stateMachine:dev-streaming-etl-sm \
  --name "smoke-test-$(date +%s)" \
  --input '{
    "detail": {
      "bucket": { "name": "musicstream-dev-raw-<account-id>" },
      "object": { "keys": ["streams/yyyy=2024/mm=06/dd=25/streams1.csv"] }
    }
  }' \
  --profile sandbox-musicstream-dev
```

Save the `executionArn` from the response — you will need it in Step 6.

**PowerShell equivalent for Method B:**

```powershell
$input = @{
  detail = @{
    bucket = @{ name = "musicstream-dev-raw-<account-id>" }
    object = @{ keys = @("streams/yyyy=2024/mm=06/dd=25/streams1.csv") }
  }
} | ConvertTo-Json -Compress -Depth 5

aws stepfunctions start-execution `
  --state-machine-arn arn:aws:states:eu-west-1:<account-id>:stateMachine:dev-streaming-etl-sm `
  --name "smoke-test-$(Get-Date -UFormat '%s')" `
  --input $input `
  --profile sandbox-musicstream-dev
```

---

### Step 6 — Verify Results

**Check execution status** (replace `<execution-arn>` with the ARN from Step 5):

```bash
aws stepfunctions describe-execution \
  --execution-arn <execution-arn> \
  --query '{status: status, startDate: startDate, stopDate: stopDate}' \
  --profile sandbox-musicstream-dev
```

Expected status: `SUCCEEDED`. Execution typically takes 4–8 minutes (Glue job startup dominates).

If status is `RUNNING`, poll again after a minute. If `FAILED`, see the debugging section below.

**List recent executions:**

```bash
aws stepfunctions list-executions \
  --state-machine-arn arn:aws:states:eu-west-1:<account-id>:stateMachine:dev-streaming-etl-sm \
  --max-results 5 \
  --profile sandbox-musicstream-dev
```

**Verify DynamoDB item counts** (expected for one `streams1.csv`):

```bash
# Expected: ~113 items
aws dynamodb scan \
  --table-name dev_genre_daily_kpi \
  --select COUNT \
  --profile sandbox-musicstream-dev

# Expected: ~339 items
aws dynamodb scan \
  --table-name dev_top_songs_daily \
  --select COUNT \
  --profile sandbox-musicstream-dev

# Expected: ~5 items
aws dynamodb scan \
  --table-name dev_top_genres_daily \
  --select COUNT \
  --profile sandbox-musicstream-dev
```

**Spot-check a DynamoDB item:**

```bash
aws dynamodb get-item \
  --table-name dev_genre_daily_kpi \
  --key '{"genre": {"S": "pop"}, "date": {"S": "2024-06-25"}}' \
  --profile sandbox-musicstream-dev
```

**Verify archive** (file should move from `raw/` to `archive/`):

```bash
aws s3 ls \
  s3://musicstream-dev-archive-<account-id>/streams/yyyy=2024/mm=06/dd=25/ \
  --profile sandbox-musicstream-dev
```

**Verify quarantine is empty** (no unexpected rejects):

```bash
aws s3 ls s3://musicstream-dev-quarantine-<account-id>/ --profile sandbox-musicstream-dev
```

---

### Step 7 — Run the Streamlit UI (Optional)

Verify the dashboard renders against live data:

```bash
export AWS_PROFILE=sandbox-musicstream-dev
streamlit run ui/app.py
```

Open `http://localhost:8501` in a browser. The KPI charts should render data for 2024-06-25. No mock data should be needed after a successful smoke test.

To run without credentials:

```bash
MOCK_MODE=true streamlit run ui/app.py
```

---

### Step 8 — Tear Down

Always destroy the dev environment after testing to avoid ongoing costs.

```bash
AWS_PROFILE=sandbox-musicstream-dev \
  terraform -chdir=infra/envs/dev destroy
```

The state bucket and lock table are not managed by this Terraform workspace (they were created manually in Step 1). Delete them separately:

```bash
# Empty the versioned state bucket first
aws s3api delete-objects \
  --bucket musicstream-tfstate-<account-id> \
  --delete "$(aws s3api list-object-versions \
    --bucket musicstream-tfstate-<account-id> \
    --query '{Objects: Versions[].{Key:Key,VersionId:VersionId}}' \
    --output json \
    --profile sandbox-musicstream-dev)" \
  --profile sandbox-musicstream-dev

aws s3api delete-bucket \
  --bucket musicstream-tfstate-<account-id> \
  --profile sandbox-musicstream-dev

aws dynamodb delete-table \
  --table-name musicstream-tfstate-lock \
  --region eu-west-1 \
  --profile sandbox-musicstream-dev
```

---

## Debugging Failed Executions

**Get execution history with failure events:**

```bash
aws stepfunctions get-execution-history \
  --execution-arn <execution-arn> \
  --query 'events[?type==`ExecutionFailed` || type==`TaskFailed`]' \
  --profile sandbox-musicstream-dev
```

**Check Glue job run logs:**

```bash
# List recent job runs for transform-kpis
aws glue get-job-runs \
  --job-name dev-transform-kpis \
  --max-results 5 \
  --profile sandbox-musicstream-dev

# Get log group for a specific run (replace <job-run-id>)
# Logs appear in /aws-glue/jobs/output and /aws-glue/jobs/error
aws logs tail /aws-glue/jobs/error \
  --log-stream-name-prefix <job-run-id> \
  --profile sandbox-musicstream-dev
```

**Check Lambda logs:**

```bash
aws logs tail /aws/lambda/dev-validate-schema \
  --since 1h \
  --profile sandbox-musicstream-dev
```

---

## Known Issues and Workarounds

All previously known gaps have been resolved. The pipeline is fully operational end-to-end including the automatic trigger path (S3 upload → EventBridge → SQS → Pipe → SM).

### Resolved: EventBridge Pipe input format mismatch (fixed 2026-06-17)

The Pipe now has a `dev-pipe-enrichment` Lambda as its enrichment step. It receives the raw SQS batch, extracts `detail.bucket.name` and `detail.object.key` from each record, and returns the single `{detail:{bucket:{name},object:{keys:[...]}}}` structure the ASL `ParseInput` state expects. No workaround needed.

### Resolved: Glue Python Shell exit code 2 (fixed 2026-06-17)

Three separate causes were fixed:
1. `--JOB_NAME` argument now passed explicitly in the ASL LoadDynamoDB `Arguments` block.
2. `_partition_values_from_key()` added to `load_dynamodb.py` — injects `listen_date` from the S3 key path into each Parquet row (PySpark `partitionBy` removes the column from the file bytes).
3. `dev-glue-python-shell-role` now has `KmsDecryptDdb` permission for the DynamoDB KMS key.

### Resolved: SQS CMK encryption (fixed in smoke test round 1)

Queues use `sqs_managed_sse_enabled = true`. This is required for this architecture because the project KMS policy uses root-principal delegation only. EventBridge is an AWS service principal (`events.amazonaws.com`), not an IAM role in the account, so it could not use the project CMK to encrypt SQS messages. The visible symptom was EventBridge `FailedInvocations` for `dev-s3-raw-csv-created` and zero SQS messages sent.

Validation commands:

```bash
aws sqs get-queue-attributes \
  --queue-url https://sqs.eu-west-1.amazonaws.com/970547336735/dev-etl-buffer \
  --attribute-names SqsManagedSseEnabled KmsMasterKeyId \
  --profile sandbox-musicstream-dev \
  --region eu-west-1

aws cloudwatch get-metric-statistics \
  --namespace AWS/Events \
  --metric-name FailedInvocations \
  --dimensions Name=RuleName,Value=dev-s3-raw-csv-created \
  --start-time <utc-start> \
  --end-time <utc-end> \
  --period 300 \
  --statistics Sum \
  --profile sandbox-musicstream-dev \
  --region eu-west-1
```

### Resolved: ArchiveBatch JsonPath error (fixed 2026-06-17)

`$$.Execution.Input.ctx.bucket` is unavailable inside a Map iterator (the original SM input has no `ctx`). Fixed by adding `ItemSelector` to the Map state, passing `{key, bucket}` from `$.ctx.bucket` of the pre-Map input so the iterator references `$.bucket` and `$.key` directly.

### Resolved: Step Functions KMS AccessDeniedException on S3 copy (fixed 2026-06-17)

`dev-step-functions-role` now has `kms:GenerateDataKey` on the S3 data KMS key for the archive `CopyObject` call.

---

## Quick Reference — All Test Commands

```bash
# Pre-commit
pre-commit run --all-files

# Unit tests
pytest tests/unit -q

# Integration tests (needs deployed infra)
AWS_PROFILE=sandbox-musicstream-dev pytest tests/integration -q

# Terraform lint
terraform -chdir=infra/envs/dev validate
tflint --recursive
checkov -d infra/

# SAST
semgrep --config p/python glue/ lambda/ ui/

# Trigger pipeline (Method B)
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:eu-west-1:<account-id>:stateMachine:dev-streaming-etl-sm \
  --name "smoke-test-$(date +%s)" \
  --input '{"detail":{"bucket":{"name":"musicstream-dev-raw-<account-id>"},"object":{"keys":["streams/yyyy=2024/mm=06/dd=25/streams1.csv"]}}}' \
  --profile sandbox-musicstream-dev

# Verify DynamoDB (all three tables)
for table in dev_genre_daily_kpi dev_top_songs_daily dev_top_genres_daily; do
  echo -n "$table: "
  aws dynamodb scan --table-name $table --select COUNT \
    --query Count --output text --profile sandbox-musicstream-dev
done
```
