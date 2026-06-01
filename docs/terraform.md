# Terraform — Infrastructure as Code

> Agent: **Infra**.
> Input: `master_plan.md`, `directory_structure.md`, `decision.md` D-08.
> Output: a Terraform layout that any agent picking up the stick can `terraform apply` from a clean AWS account and get an identical environment.

The principle here is **stick-holding**: this document is the only thing the next implementer should need to read in order to know *what gets built, in what order, in which module*. The **telephone skill** rule is enforced by making the module inputs and outputs explicit — if it's not on the stick, it doesn't exist.

---

## 1. State & Backend

```hcl
# infra/envs/dev/backend.tf
terraform {
  required_version = ">= 1.6"
  backend "s3" {
    bucket         = "musicstream-tfstate"
    key            = "envs/dev/terraform.tfstate"
    region         = "eu-west-1"
    dynamodb_table = "musicstream-tfstate-lock"
    encrypt        = true
  }
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.50" }
  }
}
```

A one-time **bootstrap** stack (`infra/bootstrap/`) creates the state bucket and lock table. It is documented separately and runs with local state.

## 2. Module Layout & Hand-off Contracts

Each module is a self-contained "stick" the infra agent passes to the next. Every module declares **inputs**, **outputs**, and **named resources** explicitly.

### 2.1 `modules/s3-data-lake`
Creates four buckets: `raw`, `archive`, `quarantine`, `scripts`. (Reference data may sit in a `reference/` prefix of the raw bucket or a fifth bucket — implementer's call; current plan is a fifth bucket for clearer IAM.)

**Inputs**
- `project` (string)
- `env` (string)
- `kms_key_arn` (string, optional — defaults to AWS-managed SSE-S3)

**Outputs**
- `raw_bucket_name`, `raw_bucket_arn`
- `archive_bucket_name`, `archive_bucket_arn`
- `quarantine_bucket_name`, `quarantine_bucket_arn`
- `scripts_bucket_name`, `scripts_bucket_arn`
- `reference_bucket_name`, `reference_bucket_arn`

**Resources**
- `aws_s3_bucket` × 5 with versioning enabled
- `aws_s3_bucket_public_access_block` (block all public) on each
- `aws_s3_bucket_server_side_encryption_configuration` on each
- `aws_s3_bucket_notification` on `raw` → EventBridge enabled
- `aws_s3_bucket_lifecycle_configuration` on `archive` (Glacier after 90 d, expire 730 d)
- `aws_s3_bucket_lifecycle_configuration` on `quarantine` (expire 30 d after manual review)

### 2.2 `modules/iam-roles`
Centralises every role; consuming modules never create roles inline (this avoids permission drift).

**Outputs**
- `glue_pyspark_role_arn` (s3:GetObject on raw/reference/scripts, s3:PutObject on archive; glue:* on own job)
- `glue_python_shell_role_arn` (same plus DynamoDB write on the three KPI tables)
- `step_functions_role_arn` (states:* on its SM, glue:StartJobRun on the four jobs, s3:* on archive/quarantine)
- `eventbridge_role_arn` (states:StartExecution on the SM)

Each role is least-privilege; wildcards forbidden in policy `Resource`.

### 2.3 `modules/dynamodb-kpi-tables`
**Inputs**
- `env`, `kms_key_arn`

**Outputs**
- `genre_daily_table_name` + `_arn`
- `top_songs_daily_table_name` + `_arn`
- `top_genres_daily_table_name` + `_arn`

**Resources** — see `dynamodb_schema.md` for keys.

```hcl
# excerpt — illustrative only
resource "aws_dynamodb_table" "genre_daily" {
  name         = "${var.env}_genre_daily_kpi"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "date"
  range_key    = "genre"

  attribute { name = "date"  type = "S" }
  attribute { name = "genre" type = "S" }

  point_in_time_recovery { enabled = true }
  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }
  deletion_protection_enabled = true
  tags = local.common_tags
}
```

### 2.4 `modules/glue-jobs`
Wraps the four Glue jobs.

**Inputs**
- `scripts_bucket_name`
- `glue_pyspark_role_arn`, `glue_python_shell_role_arn`
- `env`
- `shared_wheel_s3_uri` (where `shared-X.Y.Z-py3-none-any.whl` is uploaded)
- DynamoDB table names (for `--default-arguments`)

**Outputs**
- `validate_schema_job_name`
- `validate_referential_job_name`
- `transform_kpis_job_name`
- `load_dynamodb_job_name`

```hcl
resource "aws_glue_job" "transform_kpis" {
  name              = "${var.env}-transform-kpis"
  role_arn          = var.glue_pyspark_role_arn
  glue_version      = "4.0"
  worker_type       = "G.1X"
  number_of_workers = 4
  timeout           = 30  # minutes

  command {
    name            = "glueetl"
    python_version  = "3"
    script_location = "s3://${var.scripts_bucket_name}/glue/pyspark/transform_kpis.py"
  }

  default_arguments = {
    "--enable-metrics"                   = "true"
    "--enable-continuous-cloudwatch-log" = "true"
    "--enable-job-insights"              = "true"
    "--enable-glue-datacatalog"          = "true"
    "--job-language"                     = "python"
    "--extra-py-files"                   = var.shared_wheel_s3_uri
    "--additional-python-modules"        = "pydantic==2.7.0"
    "--TempDir"                          = "s3://${var.scripts_bucket_name}/tmp/"
  }
}
```

Python Shell jobs use `command.name = "pythonshell"`, `MaxCapacity = 0.0625` (or 1.0 for the loader if write parallelism is needed).

### 2.5 `modules/step-functions`
**Inputs**
- `step_functions_role_arn`
- All four job names
- DynamoDB table names (passed into job parameters)
- Archive + quarantine bucket names

**Resources**
- `aws_sfn_state_machine` reading the ASL from `../step_functions/pipeline.asl.json` via `templatefile()`.
- A CloudWatch log group for execution history with `INCLUDE_EXECUTION_DATA = true`.

### 2.6 `modules/eventbridge-trigger`
**Inputs**
- `raw_bucket_name`, `sm_arn`, `eventbridge_role_arn`

**Resources**
- `aws_cloudwatch_event_rule` filtering `source = ["aws.s3"]`, `detail-type = ["Object Created"]`, with `detail.bucket.name` and `detail.object.key` prefix `streams/`, suffix `.csv`.
- `aws_cloudwatch_event_target` → state machine, input transformer extracting `bucket` + `key`.
- Dead-letter SQS queue for failed invocations.

## 3. Environment Composition

```hcl
# infra/envs/dev/main.tf  (sketch)
locals {
  env     = "dev"
  project = "musicstream"
  common_tags = {
    Project = local.project
    Env     = local.env
    Owner   = "data-eng"
    ManagedBy = "terraform"
  }
}

module "data_lake" {
  source  = "../../modules/s3-data-lake"
  project = local.project
  env     = local.env
}

module "ddb" {
  source = "../../modules/dynamodb-kpi-tables"
  env    = local.env
}

module "iam" {
  source                  = "../../modules/iam-roles"
  env                     = local.env
  raw_bucket_arn          = module.data_lake.raw_bucket_arn
  archive_bucket_arn      = module.data_lake.archive_bucket_arn
  quarantine_bucket_arn   = module.data_lake.quarantine_bucket_arn
  scripts_bucket_arn      = module.data_lake.scripts_bucket_arn
  reference_bucket_arn    = module.data_lake.reference_bucket_arn
  ddb_table_arns          = [module.ddb.genre_daily_arn, module.ddb.top_songs_daily_arn, module.ddb.top_genres_daily_arn]
}

module "jobs" {
  source                       = "../../modules/glue-jobs"
  env                          = local.env
  scripts_bucket_name          = module.data_lake.scripts_bucket_name
  glue_pyspark_role_arn        = module.iam.glue_pyspark_role_arn
  glue_python_shell_role_arn   = module.iam.glue_python_shell_role_arn
  genre_daily_table            = module.ddb.genre_daily_table_name
  top_songs_daily_table        = module.ddb.top_songs_daily_table_name
  top_genres_daily_table       = module.ddb.top_genres_daily_table_name
  shared_wheel_s3_uri          = "s3://${module.data_lake.scripts_bucket_name}/glue/shared/shared-0.1.0-py3-none-any.whl"
}

module "sm" {
  source                  = "../../modules/step-functions"
  env                     = local.env
  step_functions_role_arn = module.iam.step_functions_role_arn
  validate_schema_job     = module.jobs.validate_schema_job_name
  validate_ref_job        = module.jobs.validate_referential_job_name
  transform_job           = module.jobs.transform_kpis_job_name
  load_job                = module.jobs.load_dynamodb_job_name
  archive_bucket          = module.data_lake.archive_bucket_name
  quarantine_bucket       = module.data_lake.quarantine_bucket_name
}

module "trigger" {
  source                = "../../modules/eventbridge-trigger"
  raw_bucket_name       = module.data_lake.raw_bucket_name
  sm_arn                = module.sm.state_machine_arn
  eventbridge_role_arn  = module.iam.eventbridge_role_arn
}
```

## 4. Apply Order (the stick passes through this sequence)

```
terraform -chdir=infra/bootstrap apply       # state bucket + lock table (once per account)
terraform -chdir=infra/envs/dev init
terraform -chdir=infra/envs/dev plan -out plan.bin
terraform -chdir=infra/envs/dev apply plan.bin
# upload glue scripts + wheel
aws s3 sync glue/ s3://musicstream-dev-scripts/glue/ --exclude "*" --include "*.py"
aws s3 cp dist/shared-0.1.0-py3-none-any.whl s3://musicstream-dev-scripts/glue/shared/
# seed reference data
aws s3 cp data/users/users.csv  s3://musicstream-dev-reference/users/
aws s3 cp data/songs/songs.csv  s3://musicstream-dev-reference/songs/
```

## 5. Promotion to `prod`

- `prod` is *not* a fork of `dev` — it is a sibling directory with identical structure and a different `tfvars`. Drift is impossible because `terraform plan` is run on both.
- Promotion = (1) merge to main, (2) CI runs `plan` against prod, (3) human approves, (4) CI runs `apply`.
- The Glue scripts in `prod` come from a tagged release artefact (`v0.3.0/shared-0.3.0-py3-none-any.whl`), not from main.

## 6. What Terraform Does *Not* Manage

| Resource | Why outside Terraform |
|----------|------------------------|
| Glue script content | High change cadence; managed by `aws s3 cp` from CI to keep `plan` clean. |
| Reference data files | Manual / scripted upload; not infra. |
| Step Functions ASL body | Lives in `step_functions/pipeline.asl.json`; Terraform reads via `templatefile()`. |
| One-time state bucket | Bootstrapped manually. |

## 7. Hand-off

- **Next agent:** Validation agent.
- **They need:** Bucket names + IAM role ARN, both of which appear in the `outputs` of this module set.
- **Stick contents passed forward:** `data_validation.md` (will describe what the validate jobs read from S3 and what they emit back to Step Functions).

---

## 8. Revisions from `.ai/review.md`

### 8.1 Module additions

| New module                  | Purpose                                                          |
|-----------------------------|------------------------------------------------------------------|
| `modules/lambda-validator`  | Tier-1 schema gate (D-17). Python 3.12, 256 MB, 30 s timeout.    |
| `modules/sqs-buffer`        | EventBridge → SQS standard queue + redrive DLQ (D-11-R).         |
| `modules/lambda-trigger`    | EventBridge schedule (`rate(2 minutes)`) → drains SQS in batches up to 50 → `StartExecution`. |

### 8.2 Module removals / consolidations

- `modules/glue-jobs` shrinks from four jobs to **two**:
  - `${env}-transform-kpis` — Glue PySpark.
  - `${env}-load-dynamodb` — Glue Python Shell (single, not three).
- The standalone `validate_schema` and `validate_referential` Python Shell jobs are gone (D-02-R, D-19).

### 8.3 IAM tightening (D-20)

In `modules/iam-roles`, every `*` action becomes an explicit list:

```hcl
# Step Functions role — no states:* wildcards
data "aws_iam_policy_document" "sfn_states" {
  statement {
    actions = [
      "states:StartExecution",
      "states:DescribeExecution",
      "states:StopExecution",
    ]
    resources = [aws_sfn_state_machine.this.arn]
  }
}

# Glue role — scoped logs
data "aws_iam_policy_document" "glue_logs" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/glue/jobs/${var.env}-*:*"]
  }
}
```

### 8.4 Reference-data conversion (D-18)

The `scripts/upload_reference.sh` flow gains a Parquet conversion step. The reference S3 layout becomes:

```
musicstream-${env}-reference/
├── users/users.parquet
└── songs/songs.parquet
```

Crawler points at the parquet prefixes; Spark consumes parquet, never CSV.

---

## 9. Revisions from Architectural Review Round 2 (`.ai/review.md` §2)

### 9.1 Replace Trigger Lambda with EventBridge Pipes (D-22)

Remove `modules/lambda-trigger`. Add `modules/eventbridge-pipes`.

```hcl
# modules/eventbridge-pipes/main.tf — illustrative
resource "aws_pipes_pipe" "sqs_to_sfn" {
  name     = "${var.env}-sqs-to-sfn-pipe"
  role_arn = aws_iam_role.pipe_role.arn
  source   = var.sqs_queue_arn
  target   = var.state_machine_arn

  source_parameters {
    sqs_queue_parameters {
      batch_size                         = 50
      maximum_batching_window_in_seconds = 120
    }
  }

  target_parameters {
    step_functions_state_machine_parameters {
      invocation_type = "FIRE_AND_FORGET"
    }
  }
}

resource "aws_iam_role" "pipe_role" {
  name               = "${var.env}-pipe-sqs-to-sfn"
  assume_role_policy = data.aws_iam_policy_document.pipe_assume.json
}

data "aws_iam_policy_document" "pipe_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals { type = "Service"; identifiers = ["pipes.amazonaws.com"] }
  }
}

data "aws_iam_policy_document" "pipe_perms" {
  statement {
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [var.sqs_queue_arn]
  }
  statement {
    actions   = ["states:StartExecution"]
    resources = [var.state_machine_arn]
  }
}
```

**Inputs**: `sqs_queue_arn`, `state_machine_arn`, `env`.
**Outputs**: `pipe_arn`.

The module replaces both `modules/lambda-trigger` (removed) and the cron EventBridge rule that was polling SQS. The SQS module (`modules/sqs-buffer`) stays; only the consumer changes.

### 9.2 Glue PySpark Worker Type → G.025X (D-24)

In `modules/glue-jobs`, the `transform_kpis` job configuration changes:

```hcl
resource "aws_glue_job" "transform_kpis" {
  name              = "${var.env}-transform-kpis"
  role_arn          = var.glue_pyspark_role_arn
  glue_version      = "4.0"
  worker_type       = "G.025X"   # was G.1X
  number_of_workers = 2           # was 4; 0.5 DPU total
  timeout           = 30

  command {
    name            = "glueetl"
    python_version  = "3"
    script_location = "s3://${var.scripts_bucket_name}/glue/pyspark/transform_kpis.py"
  }

  default_arguments = {
    "--enable-metrics"                   = "true"
    "--enable-continuous-cloudwatch-log" = "true"
    "--enable-auto-scaling"              = "true"
    "--auto-scaling-min-workers"         = "2"
    "--auto-scaling-max-workers"         = "8"   # escalates for backfill
    # ...
  }
}
```

Backfill runs set `--run_mode=backfill` in their `StartJobRun` arguments; the job logic reads this and sets a higher partition count. Autoscaling handles DPU provisioning.

### 9.3 KMS Key Policy — Root-Principal Delegation (D-25)

All CMK resources now use this policy shape:

```hcl
# modules/kms/main.tf — illustrative
data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "key_policy" {
  statement {
    sid     = "RootAdministration"
    effect  = "Allow"
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
    actions   = ["kms:*"]
    resources = ["*"]
  }
}

resource "aws_kms_key" "this" {
  description             = "${var.env}-${var.purpose}"
  deletion_window_in_days = 14
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.key_policy.json
}
```

Each consuming IAM role then gets an inline policy:

```hcl
data "aws_iam_policy_document" "glue_kms" {
  statement {
    actions   = ["kms:Decrypt", "kms:GenerateDataKey*"]
    resources = [var.kms_key_arn]
  }
}
```

No role ARN in the key policy → no circular dependency. The `modules/kms` module is now self-contained and can be applied before any IAM module.

### 9.4 VPC Stub Module (D-27, `enabled = false` by default)

A new `modules/vpc-stub` creates a minimal VPC when enabled. Default in `dev/terraform.tfvars`: `vpc_stub_enabled = false`.

```hcl
# modules/vpc-stub/main.tf — illustrative
variable "enabled" { type = bool; default = false }

resource "aws_vpc" "this" {
  count      = var.enabled ? 1 : 0
  cidr_block = "10.0.0.0/24"
  tags       = { Name = "${var.env}-etl-vpc" }
}

resource "aws_subnet" "private" {
  count      = var.enabled ? 1 : 0
  vpc_id     = aws_vpc.this[0].id
  cidr_block = "10.0.0.0/25"
  tags       = { Name = "${var.env}-private" }
}

resource "aws_route_table" "private" {
  count  = var.enabled ? 1 : 0
  vpc_id = aws_vpc.this[0].id
}

resource "aws_vpc_endpoint" "s3" {
  count           = var.enabled ? 1 : 0
  vpc_id          = aws_vpc.this[0].id
  service_name    = "com.amazonaws.${var.region}.s3"
  route_table_ids = [aws_route_table.private[0].id]
}

resource "aws_vpc_endpoint" "dynamodb" {
  count           = var.enabled ? 1 : 0
  vpc_id          = aws_vpc.this[0].id
  service_name    = "com.amazonaws.${var.region}.dynamodb"
  route_table_ids = [aws_route_table.private[0].id]
}
```

**Why deferred by default.** Glue and Lambda at v1 run in AWS-managed networks, so the endpoints have no effect on their traffic today. The module is enabled when any service is placed in a VPC. No resources billed while `enabled = false`.

### 8.5 New top-level `lambda/` source tree

```
lambda/
├── validate_schema/
│   ├── handler.py
│   └── pyproject.toml
└── trigger_pipeline/
    ├── handler.py
    └── pyproject.toml
```

Packaged into zip artefacts by CI, uploaded to `s3://${scripts_bucket}/lambda/${version}/`, referenced by Terraform via `aws_lambda_function.s3_object_*` attributes.

### 8.6 SAST in CI (D-21)

`ci.yml` adds a Snyk Code (or `semgrep --config p/python`) step. Failure blocks merge.

The earlier sections of this document remain the layout reference; consume them with the deltas above applied.
