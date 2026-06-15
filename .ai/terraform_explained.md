# Terraform Fundamentals — Using the MusicStream ETL Pipeline as a Teaching Example

Target audience: someone who has seen Terraform before but has not worked on a real multi-module AWS project. Every concept below is grounded in the actual code in this repository.

---

## 1. Why Terraform?

When you build cloud infrastructure you have four broad options:

| Approach | How it works | Main weakness |
|----------|--------------|---------------|
| AWS Console (manual) | Click through the UI | Nothing is repeatable. Next week you cannot remember what you clicked. |
| AWS CloudFormation | YAML/JSON templates, AWS-specific | Verbose syntax; limited reuse; AWS-only |
| AWS CDK | Write CloudFormation in Python/TypeScript | Still compiles to CloudFormation; full runtime language brings its own complexity |
| Terraform | Declarative HCL; provider-agnostic | Requires learning a new DSL and the state model |

Terraform wins for infrastructure that spans multiple services and needs to be promoted across environments (dev → prod). You write what the end state should look like; Terraform figures out the sequence of API calls to get there.

In this project, a single `terraform apply` in `infra/envs/dev/` provisions 30+ AWS resources — KMS keys, five S3 buckets, three DynamoDB tables, four IAM roles, two Glue jobs, an SQS queue with DLQ, an EventBridge Pipe, a Step Functions state machine, CloudWatch alarms, and an SNS topic — in the right order, without you specifying that order.

---

## 2. State Management — the S3 Backend with DynamoDB Locking

Terraform tracks everything it has created in a **state file** (`terraform.tfstate`). Without state, Terraform cannot know that a bucket it created last week already exists — it would try to create it again and fail.

### The bootstrap problem

The very first thing this project does is create the S3 bucket that will hold state. That step has to happen outside normal Terraform flow because you cannot store state in a bucket that Terraform has not created yet. That is why `infra/bootstrap/` exists — it runs once, locally, with local state.

```hcl
# infra/bootstrap/main.tf

resource "aws_s3_bucket" "tfstate" {
  bucket = "musicstream-tfstate"

  lifecycle {
    prevent_destroy = true   # this bucket must never be deleted by accident
  }
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_dynamodb_table" "tfstate_lock" {
  name         = "musicstream-tfstate-lock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }
}
```

### Why versioning?

S3 versioning on the state bucket means every `terraform apply` leaves the previous state version intact. If a bad apply corrupts the state, you can roll back to the previous version in the S3 console. Without versioning, a corrupted state file is unrecoverable.

### Why DynamoDB locking?

If two engineers run `terraform apply` at the same moment against the same state file, they would both read the same current state, compute conflicting diffs, and race to write back — corrupting state. DynamoDB provides a lightweight lock: Terraform writes a record to the lock table at the start of every apply and deletes it on completion. The second engineer's apply fails immediately with a "state is locked" message rather than proceeding and corrupting things.

### The actual backend config used by the dev environment

```hcl
# infra/envs/dev/backend.tf

terraform {
  backend "s3" {
    bucket         = "musicstream-tfstate"
    key            = "envs/dev/terraform.tfstate"
    region         = "eu-west-1"
    dynamodb_table = "musicstream-tfstate-lock"
    encrypt        = true
  }
}
```

The `key` is the path inside the bucket. `infra/envs/prod/` uses a different key (`envs/prod/terraform.tfstate`), so dev and prod state are completely separate files. Corrupting dev state never touches prod state.

---

## 3. The Module Pattern — Encapsulation and Reuse

A Terraform module is just a directory of `.tf` files. When one configuration calls another directory with `source = "..."`, it is instantiating that module — passing inputs in, getting outputs back.

### Why use modules?

Without modules, all 30+ resources would live in one flat file. That file would be thousands of lines long, hard to read, and impossible to reuse across environments. Modules give you the same benefits as functions in a programming language: you define the logic once, parameterise it, and call it from multiple places.

### The KMS module is the simplest example

The module lives in `infra/modules/kms/`. It has three files: `main.tf`, `variables.tf`, and `outputs.tf`.

**Input variables** declare what the caller must provide:

```hcl
# infra/modules/kms/variables.tf

variable "env" {
  type = string
}

variable "purpose" {
  type        = string
  description = "Short label appended to alias, e.g. 'data' or 'ddb'"
}

variable "common_tags" {
  type    = map(string)
  default = {}
}
```

**The resource** uses those inputs:

```hcl
# infra/modules/kms/main.tf

resource "aws_kms_key" "this" {
  description             = "${var.env}-${var.purpose}"
  deletion_window_in_days = 7
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.key_policy.json

  tags = var.common_tags
}

resource "aws_kms_alias" "this" {
  name          = "alias/${var.env}-${var.purpose}"
  target_key_id = aws_kms_key.this.key_id
}
```

**Outputs** expose values the caller can use:

```hcl
# infra/modules/kms/outputs.tf

output "key_arn" {
  value = aws_kms_key.this.arn
}

output "key_id" {
  value = aws_kms_key.this.key_id
}
```

**The caller** instantiates the module twice — once for data encryption, once for DynamoDB encryption — by changing only the `purpose` argument:

```hcl
# infra/envs/dev/main.tf

module "kms_data" {
  source      = "../../modules/kms"
  env         = local.env
  purpose     = "data"
  common_tags = local.common_tags
}

module "kms_ddb" {
  source      = "../../modules/kms"
  env         = local.env
  purpose     = "ddb"
  common_tags = local.common_tags
}
```

This produces two completely independent KMS keys — `alias/dev-data` and `alias/dev-ddb` — from one module definition. The `source` path `../../modules/kms` is a relative path from `infra/envs/dev/` up two levels to `infra/`, then down into `modules/kms/`.

---

## 4. The Variable → tfvars → Module Chain

Trace how `pyspark_worker_type` travels from a static file all the way to the AWS API call.

**Step 1 — `terraform.tfvars` provides the concrete value:**

```hcl
# infra/envs/dev/terraform.tfvars

pyspark_worker_type = "G.1X"
```

Terraform automatically loads this file when you run any command inside `infra/envs/dev/`. It is the mechanism for environment-specific values without hard-coding them in logic files.

**Step 2 — `variables.tf` declares the variable so Terraform knows it exists:**

```hcl
# infra/envs/dev/variables.tf

variable "pyspark_worker_type" {
  type    = string
  default = "G.1X"
  # G.025X is only supported for gluestreaming job type in eu-west-1 (D-24 fallback)
}
```

The `default` here is a safety net — if someone runs `apply` without a `tfvars` file, Terraform still has a value to use.

**Step 3 — `main.tf` passes it into the module:**

```hcl
# infra/envs/dev/main.tf

module "glue_jobs" {
  source              = "../../modules/glue-jobs"
  pyspark_worker_type = var.pyspark_worker_type
  # ... other inputs ...
}
```

**Step 4 — the module's `variables.tf` receives it:**

```hcl
# infra/modules/glue-jobs/variables.tf

variable "pyspark_worker_type" {
  type    = string
  default = "G.025X"
}
```

**Step 5 — the resource uses it:**

```hcl
# infra/modules/glue-jobs/main.tf

resource "aws_glue_job" "transform_kpis" {
  name        = "${var.env}-transform-kpis"
  worker_type = var.pyspark_worker_type
  # ...
}
```

The AWS API call that creates the Glue job will include `WorkerType: "G.1X"` — the value that started life in a plain text file. To change the worker type in prod, you only touch `infra/envs/prod/terraform.tfvars`. The module itself never changes.

---

## 5. `templatefile()` for the Step Functions ASL

The Step Functions state machine is defined in Amazon States Language (ASL), which is a JSON document. That document needs to reference real AWS resource ARNs — for example, the Lambda function ARN and the Glue job names. Those ARNs do not exist until after Terraform creates those resources, so they cannot be hard-coded.

The solution is `templatefile()`. Terraform reads the JSON file as a template, substitutes placeholders, and passes the resulting string to the state machine resource.

**The template** (note `${}` syntax — not JSON, but Terraform's template syntax inside a `.json` file):

```json
// step_functions/pipeline.asl.json (excerpt)

"ValidateSchema": {
  "Type": "Task",
  "Resource": "arn:aws:states:::lambda:invoke",
  "Parameters": {
    "FunctionName": "${validate_schema_function}",
    ...
  }
}
```

**The `templatefile()` call** in the step-functions module:

```hcl
# infra/modules/step-functions/main.tf

resource "aws_sfn_state_machine" "pipeline" {
  name     = "${var.env}-streaming-etl-sm"
  role_arn = var.step_functions_role_arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/../../../step_functions/pipeline.asl.json", {
    validate_schema_function = var.validate_schema_function_arn
    transform_kpis_job       = var.transform_kpis_job_name
    load_dynamodb_job        = var.load_dynamodb_job_name
    archive_bucket           = var.archive_bucket_name
    quarantine_bucket        = var.quarantine_bucket_name
    raw_bucket               = var.raw_bucket_name
    reference_bucket         = var.reference_bucket_name
  })
}
```

`path.module` is a Terraform built-in that always refers to the directory of the current module — so `${path.module}/../../../step_functions/` resolves to the repo root `step_functions/` directory regardless of where Terraform is invoked from. The second argument to `templatefile()` is a map: keys match the `${placeholder}` names in the template, values are the real ARNs that Terraform just created.

The result: the state machine definition contains real Lambda ARNs and Glue job names without ever needing to hard-code them or run a separate script.

---

## 6. `for_each` on S3 Buckets — One Resource Block, Five Buckets

Writing five separate `aws_s3_bucket` resources would mean repeating the same encryption, versioning, and public-access-block configuration five times. A bug fix would need to be applied five times. `for_each` solves this.

**Define the set of buckets as a local map:**

```hcl
# infra/modules/s3-data-lake/main.tf

locals {
  suffix = var.bucket_suffix != "" ? "-${var.bucket_suffix}" : ""
  buckets = {
    raw        = "${var.project}-${var.env}-raw${local.suffix}"
    archive    = "${var.project}-${var.env}-archive${local.suffix}"
    quarantine = "${var.project}-${var.env}-quarantine${local.suffix}"
    scripts    = "${var.project}-${var.env}-scripts${local.suffix}"
    reference  = "${var.project}-${var.env}-reference${local.suffix}"
  }
}
```

**One resource block creates all five:**

```hcl
resource "aws_s3_bucket" "buckets" {
  for_each      = local.buckets
  bucket        = each.value    # e.g. "musicstream-dev-raw"
  force_destroy = var.force_destroy
  tags          = merge(var.common_tags, { Purpose = each.key })
}
```

Terraform expands this into five resources internally, each identified as `aws_s3_bucket.buckets["raw"]`, `aws_s3_bucket.buckets["archive"]`, and so on. The same pattern is then applied to versioning and encryption:

```hcl
resource "aws_s3_bucket_server_side_encryption_configuration" "buckets" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.buckets[each.key].id   # reference the right bucket by key
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.kms_key_arn != null ? "aws:kms" : "AES256"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = true
  }
}
```

`each.key` is `"raw"`, `"archive"`, etc. `each.value` is the full bucket name. Because `for_each` uses a map with stable string keys, Terraform can add or remove individual buckets without destroying and recreating the others — it knows which physical resource corresponds to which map key.

---

## 7. Data Sources — Querying AWS Instead of Hard-Coding Values

A `data` block reads existing information from AWS at plan time. It does not create anything; it fetches. The KMS module uses this to get the AWS account ID without hard-coding it:

```hcl
# infra/modules/kms/main.tf

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "key_policy" {
  statement {
    sid    = "RootAdministration"
    effect = "Allow"
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
    actions   = ["kms:*"]
    resources = ["*"]
  }
}
```

`data.aws_caller_identity.current.account_id` resolves to `647594457599` at plan time by calling the AWS STS `GetCallerIdentity` API. This means the KMS key policy is correct in any account — useful when promoting to prod without changing code.

The IAM module uses a second data source for the same reason:

```hcl
# infra/modules/iam-roles/main.tf

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# Used in a CloudWatch Logs resource ARN:
"arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/glue/jobs/${var.env}-*:*"
```

The `aws_iam_policy_document` data source (used extensively in the IAM module) is a different kind of data source: it does not query AWS at all. Instead it is a Terraform-side helper that generates valid IAM policy JSON from HCL syntax, so you get type checking and proper escaping without writing raw JSON strings.

---

## 8. `depends_on` vs Implicit Dependencies

Terraform builds a dependency graph automatically by tracking references. When module A reads an output from module B, Terraform knows B must be applied first — no explicit instruction needed.

**Implicit dependency example:**

```hcl
# infra/envs/dev/main.tf

module "data_lake" {
  source      = "../../modules/s3-data-lake"
  kms_key_arn = module.kms_data.key_arn   # reference to kms_data output
  ...
}
```

Because `module.data_lake` reads `module.kms_data.key_arn`, Terraform automatically applies `kms_data` first. You do not write `depends_on = [module.kms_data]`. The reference *is* the dependency declaration.

The same pattern repeats throughout `main.tf`:

```hcl
module "sqs" {
  kms_key_id      = module.kms_data.key_id
  raw_bucket_name = module.data_lake.raw_bucket_name
  ...
}
```

`module.sqs` implicitly depends on both `kms_data` and `data_lake`.

**When `depends_on` is necessary:**

`depends_on` is for situations where a dependency exists but is not expressed through a direct reference — for example, a resource that reads from an S3 bucket that another resource populates with data (an S3 sync script). In this project, the Glue job reads scripts from the scripts bucket, but that relationship is not captured in Terraform references. The `aws s3 sync` command that uploads the scripts runs outside Terraform entirely, so it is documented as a manual step in the apply order rather than via `depends_on`.

---

## 9. The Circular Dependency Problem — IAM and Lambda

The `iam-roles` module needs to know the Lambda function ARN so it can grant Step Functions the `lambda:InvokeFunction` permission on exactly that function. But the `lambda-validator` module needs the IAM role ARN first so it can assume the role. Each needs the other to exist first — a true circular dependency.

Here is where it appears in the IAM module:

```hcl
# infra/modules/iam-roles/main.tf

data "aws_iam_policy_document" "sfn_policy" {
  statement {
    sid       = "InvokeLambda"
    actions   = ["lambda:InvokeFunction"]
    resources = [var.lambda_validator_arn]   # needs the Lambda ARN
  }
  ...
}
```

And here is the break in `infra/envs/dev/main.tf`:

```hcl
module "iam" {
  source               = "../../modules/iam-roles"
  # Use wildcard to break the circular dependency: iam↔lambda_validator↔iam and iam↔sm↔iam.
  # The IAM defaults ("*") are still scoped to the correct actions; resource-level tightening
  # can be applied post-deploy if this were a long-lived environment.
  lambda_validator_arn = "*"
  state_machine_arn    = "*"
  ...
}
```

The IAM role is created first with `"*"` as the resource. Then the Lambda is created using the role. In a long-lived production environment you would use a two-pass apply: first apply with `"*"`, then replace `"*"` with the real ARN and apply again. For an ephemeral dev environment, `"*"` is an accepted trade-off documented in the decision log as D-25's companion constraint.

This is a real limitation of infrastructure-as-code when two resources are mutually dependent. There is no clean solution; the `"*"` placeholder is the pragmatic one.

---

## 10. `force_destroy` and `deletion_protection` — Dev vs Prod

Two settings exist specifically to control how easy it is to accidentally delete data.

**`force_destroy` on S3 buckets:**

By default, Terraform cannot delete a non-empty S3 bucket. `force_destroy = true` tells Terraform to empty the bucket first, then delete it. In dev this is useful — you want `terraform destroy` to clean everything up without errors. In prod, you absolutely do not want Terraform to be able to silently empty a bucket full of production data.

```hcl
# infra/envs/dev/main.tf

module "data_lake" {
  source        = "../../modules/s3-data-lake"
  force_destroy = true   # ephemeral dev — allow non-empty bucket destroy
  ...
}
```

The default in the module itself is `false`:

```hcl
# infra/modules/s3-data-lake/variables.tf

variable "force_destroy" {
  type    = bool
  default = false
}
```

So prod gets the safe default by not passing `force_destroy` at all.

**`deletion_protection` on DynamoDB tables:**

DynamoDB has a native deletion protection flag. When enabled, no API call (including Terraform) can delete the table.

```hcl
# infra/envs/dev/main.tf

module "ddb" {
  source              = "../../modules/dynamodb-kpi-tables"
  deletion_protection = false   # ephemeral dev — allow terraform destroy
  ...
}
```

The module default is `true`:

```hcl
# infra/modules/dynamodb-kpi-tables/variables.tf

variable "deletion_protection" {
  type    = bool
  default = true
}
```

Again, prod gets the safe behavior without needing to pass the argument explicitly. This is the correct default pattern: make the dangerous option opt-in, not opt-out.

---

## 11. Common Commands — With Real Examples From This Project

### `terraform init`

Downloads the AWS provider plugin and configures the backend. Run this once when you first check out the repo, and again any time you change the backend config or add a module.

```bash
terraform -chdir=infra/envs/dev init
```

`-chdir=` changes the working directory before running — equivalent to `cd infra/envs/dev && terraform init`.

### `terraform plan`

Computes what changes would be made without applying them. Always read this before applying.

```bash
terraform -chdir=infra/envs/dev plan -out=dev.plan
```

Saving the plan to a file with `-out=dev.plan` means `apply` will execute exactly that plan — no surprises from state changing between plan and apply.

### `terraform apply`

Applies the previously computed plan. The human approval gate in CI runs `apply` with the saved plan file, not a fresh plan.

```bash
terraform -chdir=infra/envs/dev apply dev.plan
```

### `terraform output`

Prints the values of all outputs defined in `infra/envs/dev/outputs.tf`. Useful for scripting.

```bash
terraform -chdir=infra/envs/dev output scripts_bucket_name
# → musicstream-dev-scripts
```

After reading the bucket name, you can run the Glue script sync:

```bash
aws s3 sync glue/ s3://$(terraform -chdir=infra/envs/dev output -raw scripts_bucket_name)/glue/
```

### `terraform state list`

Lists every resource Terraform is tracking in state. Useful for diagnosing what exists.

```bash
terraform -chdir=infra/envs/dev state list
# module.data_lake.aws_s3_bucket.buckets["raw"]
# module.data_lake.aws_s3_bucket.buckets["archive"]
# module.kms_data.aws_kms_key.this
# ...
```

### `terraform import`

Brings an existing AWS resource under Terraform management without recreating it. Useful if someone created a resource manually and you now want Terraform to own it.

```bash
terraform -chdir=infra/envs/dev import \
  module.data_lake.aws_s3_bucket.buckets[\"raw\"] \
  musicstream-dev-raw
```

### `terraform destroy`

Destroys all resources in the state. In dev this is how you tear down and rebuild from scratch. Never run this in prod.

```bash
terraform -chdir=infra/envs/dev destroy
```

---

## 12. Apply Order — Why Bootstrap Runs First and Scripts Come After

### The two-stage apply sequence

```
Stage 1: infra/bootstrap/
  → Creates: musicstream-tfstate (S3) and musicstream-tfstate-lock (DynamoDB)
  → Run once, locally, with local state

Stage 2: infra/envs/dev/
  → Creates: all 30+ pipeline resources
  → State is stored in the Stage 1 S3 bucket
```

Stage 1 must complete before Stage 2 because the `backend "s3"` block in `infra/envs/dev/backend.tf` references the state bucket by name. If that bucket does not exist, `terraform init` in Stage 2 fails with a bucket-not-found error.

### Why Glue scripts must be synced before the first pipeline run

Terraform provisions the Glue job resources — it tells AWS that a Glue job named `dev-transform-kpis` exists and its script lives at `s3://musicstream-dev-scripts/glue/pyspark/transform_kpis.py`. But Terraform does not upload the script itself. The `aws_glue_job` resource only stores the S3 URI as metadata.

If you trigger a Step Functions execution before running:

```bash
aws s3 sync glue/ s3://musicstream-dev-scripts/glue/
```

the Glue job will fail immediately with a "script not found" error when it tries to read the S3 path.

The correct post-apply sequence is therefore:

```bash
# 1. Apply infrastructure
terraform -chdir=infra/envs/dev apply dev.plan

# 2. Upload Glue scripts and shared wheel
aws s3 sync glue/ s3://$(terraform -chdir=infra/envs/dev output -raw scripts_bucket_name)/glue/

# 3. Now the pipeline is ready to process files
```

This split — Terraform owns resource configuration, a shell command owns file content — is a deliberate design boundary. Terraform is not a file sync tool; trying to use it as one (via `aws_s3_object` resources for each script file) would cause Terraform to redeploy jobs on every code change even when no infrastructure changed.

---

## Summary: How the Pieces Fit Together

```
terraform.tfvars         ← concrete values per environment
    │
    ▼
variables.tf             ← type declarations, defaults
    │
    ▼
main.tf                  ← module instantiations, wiring outputs to inputs
    │
    ├── module "kms_data"    source = ../../modules/kms
    ├── module "data_lake"   source = ../../modules/s3-data-lake
    │     kms_key_arn = module.kms_data.key_arn   ← implicit depends_on
    ├── module "ddb"
    ├── module "sqs"
    ├── module "iam"         lambda_validator_arn = "*"  ← circular dep break
    ├── module "lambda_validator"
    ├── module "glue_jobs"   pyspark_worker_type = var.pyspark_worker_type
    ├── module "sm"          definition = templatefile(...)
    ├── module "pipe"
    └── module "monitoring"
          │
          ▼
     Each module: variables.tf + main.tf + outputs.tf
     Outputs bubble back up and become inputs to sibling modules
```

State file in S3 (`envs/dev/terraform.tfstate`) is the single source of truth for what exists. The DynamoDB lock table ensures only one person can modify it at a time. The bootstrap step creates both before anything else can run.
