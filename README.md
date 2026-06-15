# MusicStream — Streaming Analytics ETL Pipeline

An event-driven, micro-batch ETL pipeline that processes music streaming data at scale. Raw CSV files land in S3, trigger an automated pipeline that validates, transforms, and computes six genre-level KPIs, and makes results queryable from a Streamlit dashboard within minutes of arrival — with full infrastructure managed as code on AWS.

---

## Architecture

```
S3 PUT (raw/streams/yyyy=YYYY/mm=MM/dd=DD/)
         │
         ▼
  EventBridge S3 notification
         │
         ▼
  SQS Buffer Queue ◄──────────────── Dead-Letter Queue
  (BatchSize=50, Window=120s)
         │
         ▼
  EventBridge Pipe
         │
         ▼
  ┌─────────────────────────────────────────────────┐
  │          Step Functions State Machine            │
  │                                                  │
  │  ParseInput ──► ValidateSchema (Lambda T1)       │
  │                      │                           │
  │              ┌────────┴────────┐                 │
  │              │ valid           │ invalid          │
  │              ▼                 ▼                  │
  │    TransformAndCompute    Quarantine + Alarm      │
  │    (Glue PySpark)                                 │
  │    • T2 ref-integrity left-join                   │
  │    • T3 business rules                            │
  │    • 6 KPI aggregations                           │
  │    • → 3 Parquet datasets in S3                  │
  │              │                                    │
  │              ▼                                    │
  │    LoadDynamoDB                                   │
  │    (Glue Python Shell)                            │
  │    • genre_daily_kpi                              │
  │    • top_songs_daily                              │
  │    • top_genres_daily                             │
  │              │                                    │
  │              ▼                                    │
  │    ArchiveBatch (S3 copy + delete)                │
  │              │                                    │
  │              ▼                                    │
  │           Success                                 │
  └─────────────────────────────────────────────────┘
         │
         ▼
  Streamlit Dashboard (boto3 → DynamoDB direct)
```

---

## Key Design Decisions

- **EventBridge Pipe with SQS batching** — accumulates up to 50 file notifications over 120 seconds before firing one Step Functions execution, reducing Glue job starts from one-per-file to one-per-batch.

- **Lambda T1 schema gate with 4 KB range read** — validates CSV headers before Glue workers spin up. Invalid files are quarantined in under 1 second instead of burning 60–90 seconds of Glue DPU time.

- **Left-join referential integrity (T2)** — rows with unknown `track_id` or `user_id` are quarantined with full context, not silently dropped. KPI numbers are always accurate; data quality problems are always visible.

- **Parquet reference data with broadcast join** — songs and users reference tables stored as Parquet in S3. PySpark broadcasts them to every worker for zero-shuffle joins against stream data.

- **Hive partition column injection** — PySpark's `partitionBy("listen_date")` removes the column from Parquet file bytes (it lives only in the S3 key path). The Python Shell loader re-injects `listen_date` by parsing `key=value` segments from the S3 object key before writing to DynamoDB.

- **KMS root-principal delegation** — CMK key policies grant only the account root; IAM policies on roles control actual access. This breaks the Terraform circular dependency between KMS keys, IAM roles, and the resources they protect.

- **Direct boto3 to DynamoDB** — the Streamlit dashboard calls DynamoDB directly without an API Gateway layer. The dashboard is an internal ops tool running on the operator's machine, which already holds AWS credentials. API Gateway would add latency and cost for no benefit.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Storage | S3 (raw, reference, archive, quarantine, scripts) |
| Compute | AWS Glue PySpark 4.0 (transform) + Glue Python Shell 3.0 (load) |
| Validation | AWS Lambda Python 3.12 |
| Orchestration | AWS Step Functions (Standard Workflow) |
| Eventing | EventBridge S3 notifications + EventBridge Pipe |
| Buffering | Amazon SQS |
| Database | Amazon DynamoDB (3 tables, on-demand) |
| Encryption | AWS KMS (CMK per data classification layer) |
| IaC | Terraform ≥ 1.6 (11 modules) |
| Monitoring | CloudWatch alarms + dashboard, SNS, EventBridge (Glue state changes) |
| Dashboard | Streamlit + boto3 |
| CI/CD | GitHub Actions (lint → checkov → semgrep → deploy) |
| Code Quality | ruff + black + pre-commit |

---

## DynamoDB Schema

| Table | PK | SK | Access Pattern |
|-------|----|----|----------------|
| `{env}_genre_daily_kpi` | `genre` (S) | `date` (S) | Genre trend over date range |
| `{env}_top_songs_daily` | `genre` (S) | `date_rank` (S) e.g. `2024-06-25#01` | Top 3 songs per genre per day |
| `{env}_top_genres_daily` | `date` (S) | `rank` (N) | Top 5 genres on a date |

GSI `date_genre_index` on `genre_daily_kpi` (PK=`date`, SK=`genre`) supports the "all genres for a date" query.

---

## Quick Start

### Prerequisites

- AWS CLI configured with a profile that has appropriate permissions
- Terraform ≥ 1.6
- Python ≥ 3.11
- `pre-commit` installed (`pip install pre-commit && pre-commit install`)

### 1. Bootstrap the Terraform state backend (once per account)

```powershell
# Create the S3 state bucket and DynamoDB lock table
aws s3api create-bucket `
  --bucket musicstream-tfstate `
  --region eu-west-1 `
  --create-bucket-configuration LocationConstraint=eu-west-1 `
  --profile <your-aws-profile>

aws s3api put-bucket-versioning `
  --bucket musicstream-tfstate `
  --versioning-configuration Status=Enabled `
  --profile <your-aws-profile>

aws dynamodb create-table `
  --table-name musicstream-tfstate-lock `
  --billing-mode PAY_PER_REQUEST `
  --attribute-definitions AttributeName=LockID,AttributeType=S `
  --key-schema AttributeName=LockID,KeyType=HASH `
  --region eu-west-1 `
  --profile <your-aws-profile>
```

> **Sandbox/DCE accounts:** S3 bucket names are globally unique. If `musicstream-tfstate` is taken, append the account ID: `musicstream-tfstate-<account-id>` and update `infra/envs/dev/backend.tf` accordingly. Set `bucket_suffix = "<account-id>"` in `terraform.tfvars` so data lake bucket names are also unique.

### 2. Deploy the dev infrastructure

```powershell
$env:AWS_PROFILE = "<your-aws-profile>"
terraform -chdir=infra/envs/dev init
terraform -chdir=infra/envs/dev apply
```

### 3. Build and upload Glue artifacts

```powershell
# Build the shared Python wheel
cd glue
pip install build
python -m build --wheel --outdir ../dist
cd ..

# Upload Lambda ZIP
Compress-Archive lambda/validate_schema/handler.py dist/validate_schema.zip -Force
aws s3 cp dist/validate_schema.zip `
  s3://musicstream-dev-scripts/lambda/0.1.0/validate_schema.zip `
  --profile <your-aws-profile>

# Upload shared wheel and Glue scripts
aws s3 cp dist/shared-0.1.0-py3-none-any.whl `
  s3://musicstream-dev-scripts/glue/shared/ `
  --profile <your-aws-profile>
aws s3 sync glue/ s3://musicstream-dev-scripts/glue/ --profile <your-aws-profile>
```

### 4. Upload reference data (Parquet format required)

```python
# Convert reference CSVs to Parquet locally before uploading
import pandas as pd
pd.read_csv("data/songs/songs.csv").to_parquet("dist/songs.parquet", index=False)
pd.read_csv("data/users/users.csv").to_parquet("dist/users.parquet", index=False)
```

```powershell
aws s3 cp dist/songs.parquet s3://musicstream-dev-reference/songs/ --profile <your-aws-profile>
aws s3 cp dist/users.parquet s3://musicstream-dev-reference/users/ --profile <your-aws-profile>
```

> Do **not** upload CSV files to the reference bucket — Glue reads the full prefix and will fail if CSVs are present.

### 5. Trigger the pipeline

**Method A — Upload a stream file (automated path via EventBridge Pipe):**
```powershell
aws s3 cp data/streams/streams1.csv `
  s3://musicstream-dev-raw/streams/yyyy=2024/mm=06/dd=25/streams1.csv `
  --profile <your-aws-profile>
# Wait ~2 minutes for the SQS batch window, then check Step Functions console
```

**Method B — Direct invocation (recommended for testing):**
```powershell
aws stepfunctions start-execution `
  --state-machine-arn arn:aws:states:eu-west-1:<account-id>:stateMachine:dev-streaming-etl-sm `
  --name "test-$(Get-Date -Format 'yyyyMMddHHmmss')" `
  --input '{"detail":{"bucket":{"name":"musicstream-dev-raw"},"object":{"keys":["streams/yyyy=2024/mm=06/dd=25/streams1.csv"]}}}' `
  --profile <your-aws-profile>
```

### 6. Verify results

```powershell
# Check DynamoDB item counts
aws dynamodb scan --table-name dev_genre_daily_kpi --select COUNT --profile <your-aws-profile>
aws dynamodb scan --table-name dev_top_songs_daily --select COUNT --profile <your-aws-profile>
aws dynamodb scan --table-name dev_top_genres_daily --select COUNT --profile <your-aws-profile>
```

---

## Run Tests

```powershell
# Unit and integration tests
pytest tests/unit tests/integration -q

# Terraform validation
terraform -chdir=infra/envs/dev validate
tflint --recursive
checkov -d infra/

# SAST
semgrep --config p/python glue/ lambda/ ui/

# Code style
pre-commit run --all-files
```

---

## Streamlit Dashboard

The dashboard queries DynamoDB directly via boto3 — no API layer needed.

```powershell
# With AWS credentials
cd ui
streamlit run app.py

# Without credentials (uses mock data)
$env:MOCK_MODE = "true"
streamlit run app.py
```

The dashboard displays:
- Genre KPI trends over configurable date ranges
- Top 3 songs per genre per day
- Top 5 genres ranked by total plays

---

## Teardown

```powershell
# Destroy all 63 AWS resources
terraform -chdir=infra/envs/dev destroy --profile <your-aws-profile>

# Clean up the state backend (versioned bucket — delete all versions first)
aws s3api list-object-versions --bucket musicstream-tfstate --profile <your-aws-profile> `
  | ... # delete all versions and delete markers
aws s3api delete-bucket --bucket musicstream-tfstate --profile <your-aws-profile>
aws dynamodb delete-table --table-name musicstream-tfstate-lock --profile <your-aws-profile>
```

---

## Repository Structure

```
.
├── docs/                    # Architecture and design documentation
├── infra/
│   ├── bootstrap/           # State bucket + lock table (run once)
│   ├── envs/dev/            # Dev environment root module
│   └── modules/             # 11 reusable Terraform modules
├── glue/
│   ├── pyspark/             # transform_kpis.py — T2+T3+KPI computation
│   ├── python_shell/        # load_dynamodb.py — DynamoDB writes
│   └── shared/              # Shared wheel: logging_utils, dynamo_utils, s3_utils, schemas
├── lambda/
│   └── validate_schema/     # T1 schema gate — 4 KB range read
├── step_functions/
│   └── pipeline.asl.json    # State machine definition (Terraform templatefile)
├── ui/
│   ├── app.py               # Streamlit entry point
│   ├── pages/               # Dashboard pages
│   └── lib/                 # dynamo_queries, mock_data, aws_clients
├── tests/
│   ├── unit/                # Offline tests
│   ├── integration/         # Require deployed AWS resources
│   └── e2e/                 # Smoke test stub
└── .ai/                     # Portfolio docs: architecture decisions, testing guide, interview Q&A
```

---

## CI/CD

- **`ci.yml`** — runs on every push: ruff, black, pytest unit, terraform validate, checkov, semgrep
- **`cd-dev.yml`** — deploys to dev on merge to `main`
- **`cd-prod.yml`** — triggers on semver tag push; plans prod, blocks apply behind GitHub environment manual approval gate
