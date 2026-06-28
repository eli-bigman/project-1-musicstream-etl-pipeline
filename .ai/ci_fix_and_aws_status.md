# CI/CD Fix & AWS Live Status

**Date:** 2026-06-15

> Update 2026-06-17: the AWS live-status section below was written before the current dev redeploy. MusicStream resources are now live again in account `970547336735`, region `eu-west-1`.

---

## CI/CD — What Was Failing and What Was Fixed

### Failures Diagnosed (from GitHub Actions runs)

| Job | Error | Root Cause |
|-----|-------|-----------|
| `lint-and-test` | `Found 19 errors` — ruff F401/I001/F841 | Old commits before the Sprint 7-9 cleanup; current code already passes |
| `terraform-validate` | `Terraform exited with code 3` | `terraform fmt -check` flagged `infra/modules/sqs-buffer/main.tf` |
| `CD — Dev Deploy` | Failed immediately | No `AWS_DEPLOY_ROLE_ARN` secret configured (environment gate) |

### Root Cause of terraform fmt Failure

`infra/modules/sqs-buffer/main.tf` had a trailing space before an inline comment:

```hcl
# BEFORE (fails fmt)
sqs_managed_sse_enabled    = true   # AWS-managed SSE ...
#                                ^^^^ extra space

# AFTER (passes fmt)
sqs_managed_sse_enabled    = true # AWS-managed SSE ...
```

This came from the `fix/smoke-test-bugs` PR (#2) which switched SQS from CMK to AWS-managed SSE.

### What Was Done to Fix CI

1. Checked out `main` (already the default branch)
2. Cherry-picked the 2 smoke-test bug commits from `fix/smoke-test-bugs`:
   - `5e60413` — three infra deployment fixes (SQS SSE, reference_bucket, bucket_suffix)
   - `3ee2490` — load_dynamodb Hive partition column injection fix
3. Ran `terraform fmt infra/modules/sqs-buffer/main.tf` to fix alignment
4. Committed as `50444e4` — `fix(infra): terraform fmt alignment in sqs-buffer/main.tf`
5. Pushed to `origin/main`

**PR #2 (`fix/smoke-test-bugs`) is now superseded** — all its fixes are on `main`. You can close it manually.

### Remaining CI Gaps (not blocking lint/test)

- `CD — Dev Deploy` will fail until `AWS_DEPLOY_ROLE_ARN` secret is set in the GitHub `dev` environment. This requires an IAM role with a trust policy for `repo:eli-bigman/project-1-musicstream-etl-pipeline:ref:refs/heads/main`.
- Node.js 20 deprecation warnings (actions/checkout@v4, setup-python@v5) — upgrade to v5/v6 before September 2026.

---

## AWS Live Resources (Account 970547336735, eu-west-1)

**Profile used:** `sandbox-musicstream-dev`

### Current MusicStream Status (updated 2026-06-17)

MusicStream dev resources are live:

| Resource | Name |
|----------|------|
| Raw bucket | `musicstream-dev-raw-970547336735` |
| Archive bucket | `musicstream-dev-archive-970547336735` |
| Quarantine bucket | `musicstream-dev-quarantine-970547336735` |
| SQS buffer / DLQ | `dev-etl-buffer`, `dev-etl-buffer-dlq` |
| EventBridge rule | `dev-s3-raw-csv-created` |
| EventBridge Pipe | `dev-sqs-to-sfn-pipe` |
| Step Functions | `dev-streaming-etl-sm` |

The auto-trigger outage was caused by CMK-encrypted SQS queues. EventBridge matched S3 events but failed to deliver them to SQS because `events.amazonaws.com` was not allowed by the project CMK key policy. The queues now use SQS-managed SSE and the EventBridge rule filters keys with `wildcard = "streams/*.csv"`.

`streams2.csv` currently exists in raw at `streams/yyyy=2024/mm=06/dd=26/streams2.csv`; it is not archived or quarantined.

### What IS Live (not your project)

The sandbox account is **shared** — it contains a different project's resources:

| Resource | Name | Notes |
|----------|------|-------|
| Lambda | `ecom-lakehouse-validate-schema-dev` | Python 3.11, different project |
| Glue jobs | `ecom-lakehouse-ingest-dev`, `ecom-lakehouse-optimize-dev` | Not MusicStream |
| Step Functions | `ecom-lakehouse-sm-dev` | Not MusicStream |
| DynamoDB tables | `ecom-lakehouse-tf-locks`, `ecom_lakehouse_ingestion_ledger_dev`, `ecom_lakehouse_watermarks_dev` | Not MusicStream |

### Historical note: MusicStream ETL Resources — NOT Live

All MusicStream dev resources (`musicstream-dev-*` S3 buckets, DynamoDB tables, Lambda, Glue jobs) were **destroyed after the smoke test on 2026-06-14** (`terraform destroy` confirmed 63 resources removed). This is no longer the current state after the 2026-06-17 redeploy.

At the time this historical note was written, `musicstream-dev-raw-970547336735` returned `NoSuchBucket`. It exists again after the 2026-06-17 redeploy.

### To Redeploy MusicStream to This Account

1. Create a new state bucket: `aws s3 mb s3://musicstream-tfstate-970547336735 --region eu-west-1`
2. Update `infra/envs/dev/backend.tf` bucket name to `musicstream-tfstate-970547336735`
3. Set `bucket_suffix = "970547336735"` in `terraform.tfvars`
4. `terraform -chdir=infra/bootstrap apply`
5. `terraform -chdir=infra/envs/dev init && terraform -chdir=infra/envs/dev apply`
6. Follow the full guide in `.ai/how_to_test.md`

> **Note:** The account has an existing `ecom-lakehouse` project — verify there are no IAM permission conflicts before applying.
