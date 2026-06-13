# PR dev→main + Sprint 7/9 Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Commit all current working-tree changes into logical incremental commits on a `dev` branch, add missing Sprint 7 (CloudWatch alarms) and Sprint 9 (prod CD + e2e stub) deliverables, push, and open a PR from `dev` to `main` that passes CI.

**Architecture:** All changes are already written and tested locally; work is grouping them into semantic commits. New work is: a `monitoring` Terraform module (Sprint 7), a `cd-prod.yml` workflow (Sprint 9), an `tests/e2e/` smoke stub, and `.ai/status.md`.

**Tech Stack:** Terraform 1.6, Python 3.12, GitHub Actions, AWS CloudWatch, Step Functions, Lambda, Glue, SQS.

---

## File Map

| File | Action | Commit# |
|------|--------|---------|
| `infra/modules/kms/main.tf` | modify — 14→7 day deletion window | 1 |
| `infra/modules/s3-data-lake/main.tf` + `variables.tf` | modify — `force_destroy` var | 1 |
| `infra/modules/dynamodb-kpi-tables/main.tf` + `variables.tf` | modify — `deletion_protection` var | 1 |
| `infra/modules/glue-jobs/main.tf` | modify — remove KMS from CW Logs (circular dep) | 1 |
| `infra/modules/lambda-validator/main.tf` | modify — remove KMS from CW Logs | 1 |
| `infra/modules/iam-roles/main.tf` | modify — add `kpi_$folder$` + `tmp/*` S3 paths | 1 |
| `infra/bootstrap/main.tf` | modify — comment + fmt | 2 |
| `infra/envs/dev/main.tf` | modify — pass force_destroy, deletion_protection, kms_key_arn, wildcard ARNs | 2 |
| `infra/envs/dev/backend.tf` | modify — minor | 2 |
| `infra/envs/dev/variables.tf` | modify — G.025X→G.1X default | 2 |
| `infra/envs/dev/terraform.tfvars` | modify — G.1X | 2 |
| `step_functions/pipeline.asl.json` | modify — hardcode kpi_parquet_root, remove broken ResultSelector | 3 |
| `glue/pyproject.toml` | modify — setuptools fix, remove runtime deps | 4 |
| `.gitignore` | modify — cleanup | 4 |
| `.ai/architecture_diagram.drawio` | modify — updated diagram | 5 |
| `infra/modules/monitoring/main.tf` | create — CloudWatch alarms module | 6 |
| `infra/modules/monitoring/variables.tf` | create | 6 |
| `infra/modules/monitoring/outputs.tf` | create | 6 |
| `infra/envs/dev/main.tf` | modify — wire monitoring module | 6 |
| `tests/e2e/__init__.py` | create — smoke test stub | 7 |
| `tests/e2e/test_smoke.py` | create — placeholder smoke test | 7 |
| `.github/workflows/cd-prod.yml` | create — prod CD with manual approval | 8 |
| `.ai/status.md` | create — full project status | 9 |

---

## Task 1: Create dev branch and format Terraform

**Files:** none (git + CLI)

- [ ] **Step 1: Create dev branch**
```bash
git checkout -b dev
```
Expected: `Switched to a new branch 'dev'`

- [ ] **Step 2: Run terraform fmt**
```bash
terraform fmt -recursive infra/
```
Expected: lists any reformatted files or no output if already clean.

---

## Task 2: Commit infra module fixes

**Files:** `infra/modules/kms/main.tf`, `infra/modules/s3-data-lake/`, `infra/modules/dynamodb-kpi-tables/`, `infra/modules/glue-jobs/main.tf`, `infra/modules/lambda-validator/main.tf`, `infra/modules/iam-roles/main.tf`

- [ ] **Step 1: Stage and commit**
```bash
git add infra/modules/kms/main.tf \
        infra/modules/s3-data-lake/main.tf \
        infra/modules/s3-data-lake/variables.tf \
        infra/modules/dynamodb-kpi-tables/main.tf \
        infra/modules/dynamodb-kpi-tables/variables.tf \
        infra/modules/glue-jobs/main.tf \
        infra/modules/lambda-validator/main.tf \
        infra/modules/iam-roles/main.tf

git commit -m "fix(infra/modules): dev-apply hardening — force_destroy, deletion_protection vars, remove CW Logs KMS (circular dep), add kpi tmp/* IAM paths, 7-day KMS window"
```

---

## Task 3: Commit dev env config

**Files:** `infra/bootstrap/main.tf`, `infra/envs/dev/`

- [ ] **Step 1: Stage and commit**
```bash
git add infra/bootstrap/main.tf \
        infra/envs/dev/backend.tf \
        infra/envs/dev/main.tf \
        infra/envs/dev/variables.tf \
        infra/envs/dev/terraform.tfvars

git commit -m "fix(infra/dev): pass force_destroy + deletion_protection to modules; G.1X fallback (G.025X unsupported for batch jobs in eu-west-1); wildcard ARNs break iam↔lambda↔iam circular dep"
```

---

## Task 4: Commit ASL fix

**Files:** `step_functions/pipeline.asl.json`

- [ ] **Step 1: Stage and commit**
```bash
git add step_functions/pipeline.asl.json

git commit -m "fix(orchestration): hardcode kpi_parquet_root in LoadDynamoDB args; remove broken ResultSelector that assumed Glue output shape"
```

---

## Task 5: Commit build tooling

**Files:** `glue/pyproject.toml`, `.gitignore`

- [ ] **Step 1: Stage and commit**
```bash
git add glue/pyproject.toml .gitignore

git commit -m "fix(build): use setuptools.build_meta; strip boto3+pyarrow from wheel deps (already in Glue runtime); gitignore cleanup"
```

---

## Task 6: Commit architecture diagram

**Files:** `.ai/architecture_diagram.drawio`

- [ ] **Step 1: Stage and commit**
```bash
git add .ai/architecture_diagram.drawio

git commit -m "docs(arch): update architecture diagram to reflect D-22 EventBridge Pipe flow"
```

---

## Task 7: Sprint 7 — CloudWatch alarms module

**Files:**
- Create: `infra/modules/monitoring/main.tf`
- Create: `infra/modules/monitoring/variables.tf`
- Create: `infra/modules/monitoring/outputs.tf`
- Modify: `infra/envs/dev/main.tf`

- [ ] **Step 1: Create `infra/modules/monitoring/variables.tf`**

```hcl
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.50" }
  }
}

variable "env"         { type = string }
variable "common_tags" { type = map(string) }

variable "sqs_dlq_url"  { type = string }
variable "sqs_dlq_name" { type = string }

variable "state_machine_arn"  { type = string }
variable "state_machine_name" { type = string }

variable "lambda_function_name" { type = string }

variable "glue_transform_job_name" { type = string }
variable "glue_load_job_name"      { type = string }

variable "alarm_email" {
  type        = string
  description = "Email address to receive alarm notifications"
}

variable "log_retention_days" {
  type    = number
  default = 30
}
```

- [ ] **Step 2: Create `infra/modules/monitoring/main.tf`**

```hcl
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.50" }
  }
}

# ── SNS topic for all pipeline alarms ─────────────────────────────────────────

resource "aws_sns_topic" "pipeline_alarms" {
  name = "${var.env}-pipeline-alarms"
  tags = var.common_tags
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.pipeline_alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# ── SQS DLQ depth alarm ───────────────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "dlq_depth" {
  alarm_name          = "${var.env}-sqs-dlq-not-empty"
  alarm_description   = "Messages landed in the SQS DLQ — a batch failed to dispatch to Step Functions after 3 attempts."
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  evaluation_periods  = 1
  period              = 60
  statistic           = "Sum"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions = {
    QueueName = var.sqs_dlq_name
  }
  alarm_actions = [aws_sns_topic.pipeline_alarms.arn]
  ok_actions    = [aws_sns_topic.pipeline_alarms.arn]
  treat_missing_data = "notBreaching"
  tags = var.common_tags
}

# ── Step Functions execution failure alarm ────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "sf_executions_failed" {
  alarm_name          = "${var.env}-sf-executions-failed"
  alarm_description   = "One or more Step Functions pipeline executions failed."
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  evaluation_periods  = 1
  period              = 300
  statistic           = "Sum"
  namespace           = "AWS/States"
  metric_name         = "ExecutionsFailed"
  dimensions = {
    StateMachineArn = var.state_machine_arn
  }
  alarm_actions = [aws_sns_topic.pipeline_alarms.arn]
  treat_missing_data = "notBreaching"
  tags = var.common_tags
}

# ── Lambda validator error alarm ──────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${var.env}-lambda-validator-errors"
  alarm_description   = "Lambda validate_schema function returned errors."
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  evaluation_periods  = 1
  period              = 300
  statistic           = "Sum"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions = {
    FunctionName = var.lambda_function_name
  }
  alarm_actions = [aws_sns_topic.pipeline_alarms.arn]
  treat_missing_data = "notBreaching"
  tags = var.common_tags
}

# ── Glue job failure alarms (via EventBridge rule → SNS) ─────────────────────
# Glue does not publish a "failures" CloudWatch metric natively;
# we route glueJobRunStatusChange FAILED events to SNS.

resource "aws_cloudwatch_event_rule" "glue_job_failed" {
  name        = "${var.env}-glue-job-failed"
  description = "Fires when any watched Glue job run reaches FAILED state."

  event_pattern = jsonencode({
    source      = ["aws.glue"]
    detail-type = ["Glue Job State Change"]
    detail = {
      jobName = [var.glue_transform_job_name, var.glue_load_job_name]
      state   = ["FAILED", "ERROR", "TIMEOUT"]
    }
  })

  tags = var.common_tags
}

resource "aws_cloudwatch_event_target" "glue_failed_sns" {
  rule      = aws_cloudwatch_event_rule.glue_job_failed.name
  target_id = "glue-failed-sns"
  arn       = aws_sns_topic.pipeline_alarms.arn
}

resource "aws_sns_topic_policy" "allow_eventbridge" {
  arn = aws_sns_topic.pipeline_alarms.arn
  policy = data.aws_iam_policy_document.sns_topic_policy.json
}

data "aws_iam_policy_document" "sns_topic_policy" {
  statement {
    sid     = "AllowEventBridgePublish"
    effect  = "Allow"
    actions = ["sns:Publish"]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
    resources = [aws_sns_topic.pipeline_alarms.arn]
  }

  statement {
    sid     = "AllowCloudWatchPublish"
    effect  = "Allow"
    actions = ["sns:Publish"]
    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }
    resources = [aws_sns_topic.pipeline_alarms.arn]
  }
}

# ── CloudWatch dashboard ──────────────────────────────────────────────────────

resource "aws_cloudwatch_dashboard" "etl_overview" {
  dashboard_name = "${var.env}-etl-overview"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          title  = "Step Functions — Executions"
          region = "eu-west-1"
          metrics = [
            ["AWS/States", "ExecutionsStarted",   "StateMachineArn", var.state_machine_arn],
            ["AWS/States", "ExecutionsSucceeded", "StateMachineArn", var.state_machine_arn],
            ["AWS/States", "ExecutionsFailed",    "StateMachineArn", var.state_machine_arn],
          ]
          period = 300
          stat   = "Sum"
        }
      },
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          title  = "Lambda — Invocations & Errors"
          region = "eu-west-1"
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", var.lambda_function_name],
            ["AWS/Lambda", "Errors",      "FunctionName", var.lambda_function_name],
            ["AWS/Lambda", "Duration",    "FunctionName", var.lambda_function_name],
          ]
          period = 300
          stat   = "Sum"
        }
      },
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          title  = "SQS — Buffer & DLQ"
          region = "eu-west-1"
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", var.sqs_dlq_name],
          ]
          period = 60
          stat   = "Average"
        }
      }
    ]
  })
}
```

- [ ] **Step 3: Create `infra/modules/monitoring/outputs.tf`**

```hcl
output "alarm_topic_arn" {
  value = aws_sns_topic.pipeline_alarms.arn
}
```

- [ ] **Step 4: Wire monitoring module into `infra/envs/dev/main.tf`** — add at end of file (before closing):

```hcl
# ── Monitoring (Sprint 7) ─────────────────────────────────────────────────────

module "monitoring" {
  source = "../../modules/monitoring"

  env         = local.env
  common_tags = local.common_tags

  sqs_dlq_url  = module.sqs.dlq_url
  sqs_dlq_name = module.sqs.dlq_name

  state_machine_arn  = module.sm.state_machine_arn
  state_machine_name = "${local.env}-streaming-etl-sm"

  lambda_function_name = module.lambda_validator.function_name

  glue_transform_job_name = module.glue_jobs.transform_kpis_job_name
  glue_load_job_name      = module.glue_jobs.load_dynamodb_job_name

  alarm_email = var.alarm_email
}
```

- [ ] **Step 5: Add `alarm_email` variable to `infra/envs/dev/variables.tf`**

```hcl
variable "alarm_email" {
  type        = string
  description = "Email that receives CloudWatch alarm notifications"
  default     = "richard.nutsugah@amalitechtraining.org"
}
```

- [ ] **Step 6: Add missing outputs to modules** — check `module.sqs` outputs for `dlq_url`, `dlq_name`; `module.lambda_validator` for `function_name`; `module.glue_jobs` for job names. Add any missing.

- [ ] **Step 7: Commit**
```bash
git add infra/modules/monitoring/ infra/envs/dev/main.tf infra/envs/dev/variables.tf \
        infra/modules/sqs-buffer/outputs.tf infra/modules/lambda-validator/outputs.tf \
        infra/modules/glue-jobs/outputs.tf

git commit -m "feat(infra): Sprint 7 — monitoring module (CloudWatch alarms: SQS DLQ, SF failures, Lambda errors, Glue failures via EventBridge; etl-overview dashboard)"
```

---

## Task 8: Sprint 9 — e2e smoke test stub

**Files:**
- Create: `tests/e2e/__init__.py`
- Create: `tests/e2e/test_smoke.py`

- [ ] **Step 1: Create `tests/e2e/__init__.py`** (empty)

- [ ] **Step 2: Create `tests/e2e/test_smoke.py`**

```python
"""
End-to-end smoke tests. Run against a live dev environment.

Requires env vars:
  ENV               = dev
  AWS_REGION        = eu-west-1
  RAW_BUCKET        = musicstream-dev-raw
  STATE_MACHINE_ARN = arn:aws:states:eu-west-1:...:stateMachine:dev-streaming-etl-sm

Run: pytest tests/e2e -q -m smoke --aws-profile musicstream-dev
"""

import os
import time
import uuid

import boto3
import pytest


@pytest.fixture(scope="module")
def aws_clients():
    region = os.environ.get("AWS_REGION", "eu-west-1")
    profile = os.environ.get("AWS_PROFILE", "musicstream-dev")
    session = boto3.Session(region_name=region, profile_name=profile)
    return {
        "s3": session.client("s3"),
        "sfn": session.client("stepfunctions"),
        "ddb": session.resource("dynamodb"),
    }


@pytest.mark.smoke
def test_environment_variables_present():
    """All required env vars are set before running live smoke tests."""
    required = ["ENV", "AWS_REGION", "RAW_BUCKET", "STATE_MACHINE_ARN"]
    missing = [v for v in required if not os.environ.get(v)]
    assert not missing, f"Missing env vars: {missing}"


@pytest.mark.smoke
@pytest.mark.skipif(
    not os.environ.get("RAW_BUCKET"),
    reason="RAW_BUCKET env var not set — skipping live AWS test",
)
def test_s3_raw_bucket_accessible(aws_clients):
    """Can list the raw S3 bucket (connectivity + permissions check)."""
    bucket = os.environ["RAW_BUCKET"]
    resp = aws_clients["s3"].list_objects_v2(Bucket=bucket, MaxKeys=1)
    assert resp["ResponseMetadata"]["HTTPStatusCode"] == 200


@pytest.mark.smoke
@pytest.mark.skipif(
    not os.environ.get("STATE_MACHINE_ARN"),
    reason="STATE_MACHINE_ARN not set — skipping live SF test",
)
def test_state_machine_exists(aws_clients):
    """State machine ARN resolves to a real STANDARD type machine."""
    arn = os.environ["STATE_MACHINE_ARN"]
    resp = aws_clients["sfn"].describe_state_machine(stateMachineArn=arn)
    assert resp["type"] == "STANDARD"
    assert resp["status"] == "ACTIVE"
```

- [ ] **Step 3: Commit**
```bash
git add tests/e2e/

git commit -m "test(e2e): Sprint 9 — smoke test stub for post-deploy verification (env check, S3 + SF connectivity)"
```

---

## Task 9: Sprint 9 — cd-prod.yml

**Files:** Create `.github/workflows/cd-prod.yml`

- [ ] **Step 1: Create `.github/workflows/cd-prod.yml`**

```yaml
name: CD — Prod Deploy

on:
  push:
    tags:
      - 'v[0-9]+.[0-9]+.[0-9]+'

jobs:
  plan-prod:
    runs-on: ubuntu-latest
    environment: prod-plan
    permissions:
      id-token: write
      contents: read
    outputs:
      plan_exitcode: ${{ steps.plan.outputs.exitcode }}
    steps:
      - uses: actions/checkout@v4

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_PROD_DEPLOY_ROLE_ARN }}
          aws-region: eu-west-1

      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: "1.6.6"

      - name: Terraform plan prod
        id: plan
        run: |
          terraform -chdir=infra/envs/prod init
          terraform -chdir=infra/envs/prod plan -detailed-exitcode -out=prod.plan
        continue-on-error: true

      - name: Upload plan artifact
        uses: actions/upload-artifact@v4
        with:
          name: prod-plan
          path: infra/envs/prod/prod.plan
          retention-days: 1

  apply-prod:
    needs: plan-prod
    runs-on: ubuntu-latest
    environment: prod          # requires manual approval in GitHub environment settings
    if: needs.plan-prod.outputs.plan_exitcode == '2'   # 2 = changes present
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: actions/checkout@v4

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_PROD_DEPLOY_ROLE_ARN }}
          aws-region: eu-west-1

      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: "1.6.6"

      - name: Download plan artifact
        uses: actions/download-artifact@v4
        with:
          name: prod-plan
          path: infra/envs/prod/

      - name: Terraform apply prod
        run: |
          terraform -chdir=infra/envs/prod init
          terraform -chdir=infra/envs/prod apply prod.plan

      - name: Build and upload Glue wheel
        run: |
          cd glue
          pip install build
          python -m build --wheel
          aws s3 cp dist/shared-0.1.0-py3-none-any.whl \
            s3://musicstream-prod-scripts/glue/shared/shared-0.1.0-py3-none-any.whl
          aws s3 sync . s3://musicstream-prod-scripts/glue/ \
            --exclude "*" --include "*.py" --delete
          cd ..

      - name: Post-deploy smoke test
        run: pytest tests/e2e -q -m smoke
        env:
          ENV: prod
          AWS_REGION: eu-west-1
```

- [ ] **Step 2: Commit**
```bash
git add .github/workflows/cd-prod.yml

git commit -m "feat(ci): Sprint 9 — prod CD workflow; plan on tag push, apply behind manual GitHub environment approval"
```

---

## Task 10: Create .ai/status.md

**Files:** Create `.ai/status.md`

- [ ] **Step 1: Create `.ai/status.md`** (full project status — see content in implementation)

- [ ] **Step 2: Commit**
```bash
git add .ai/status.md

git commit -m "docs: add .ai/status.md — pipeline completion audit, sprint status, items needing attention"
```

---

## Task 11: Fix linting and push PR

- [ ] **Step 1: Run ruff + black**
```bash
cd glue && ruff check . && black --check .
cd ../lambda && ruff check . && black --check .
cd ../ui && ruff check . && black --check .
cd ../tests && ruff check . && black --check .
```
Fix any failures before continuing.

- [ ] **Step 2: Run terraform fmt final pass**
```bash
terraform fmt -recursive infra/
git add -u infra/
git diff --cached --name-only
```
If any files were reformatted, amend or add a fixup commit.

- [ ] **Step 3: Run unit + integration tests locally**
```bash
pytest tests/unit tests/integration -q
```
All must pass.

- [ ] **Step 4: Push dev branch**
```bash
git push -u origin dev
```

- [ ] **Step 5: Open PR**
```bash
gh pr create --base main --head dev --title "Sprint 7-9: CloudWatch alarms, prod CD, e2e stub + infra hardening fixes" \
  --body "..."
```

- [ ] **Step 6: Monitor CI — fix any failures**
Watch `gh pr checks <PR#>` until all green.
