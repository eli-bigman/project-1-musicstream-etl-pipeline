# human.md — Operator Setup Guide

> Everything a human needs to go from a fresh AWS account to a running pipeline.
> Read `docs/master_plan.md` first for context. This file is the *how*; that file is the *why*.

---

## 1. Prerequisites

Install these before anything else.

| Tool | Minimum version | Install |
|------|----------------|---------|
| AWS CLI | v2.15+ | https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html |
| Terraform | 1.6+ | https://developer.hashicorp.com/terraform/install |
| Python | 3.11+ | https://www.python.org/downloads/ |
| Streamlit | 1.35+ | `pip install streamlit` (or via `ui/requirements.txt`) |
| Git | any | https://git-scm.com/ |
| `pip` / `venv` | bundled with Python | — |

Verify:
```bash
aws --version
terraform --version
python --version
streamlit --version
```

---

## 2. AWS Identity Setup — Who Runs Terraform?

> **You only need ONE human identity.** All service roles (Glue, Lambda, Step Functions, etc.) are created *by* Terraform — never create them by hand.

### Option A — IAM Identity Center (SSO) ← Recommended for any real work

1. In the AWS Console → **IAM Identity Center** → enable it.
2. Create a **permission set** named `ETLDeveloper` with the `AdministratorAccess` managed policy.
3. Assign it to your user and your dev account.
4. Run:
   ```bash
   aws configure sso
   # Follow prompts; set profile name to "musicstream-dev"
   aws sso login --profile musicstream-dev
   export AWS_PROFILE=musicstream-dev
   ```
5. Terraform picks up the SSO session automatically.

### Option B — IAM User with Programmatic Keys ← Quick start for solo dev

1. AWS Console → **IAM** → Users → Create user.
2. Name: `musicstream-dev-deployer`.
3. Attach policy: `AdministratorAccess` (scoped to dev account only).
4. Create **access key** → download CSV → keep it safe.
5. Copy `.env.example` → `.env` and fill in `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`.
6. Source it before any AWS/Terraform commands:
   ```bash
   source .env          # Linux/macOS
   # or on Windows:
   set /p < .env        # cmd (crude) — better to use direnv or dotenv
   ```

> **Never commit `.env` to git.** It is already in `.gitignore`.

### Which to choose?

| Situation | Choice |
|-----------|--------|
| Solo dev, learning project, just getting it running | Option B — faster |
| Will eventually add a second developer or CI/CD | Option A — SSO scales; keys don't |
| GitHub Actions CI/CD | Option A with an OIDC role (no long-lived keys ever) |

---

## 3. One-Time Bootstrap (first run on a fresh account)

This creates the S3 bucket and DynamoDB table that store Terraform state. Run once per account.

```bash
# 1. Clone the repo (if you haven't already)
git clone <repo-url>
cd "Project 1 -- ETL with s3, dynamo and glue"

# 2. Copy and fill in environment variables
cp .env.example .env
# Edit .env — see Section 4

# 3. Source your credentials
source .env   # or export AWS_PROFILE=musicstream-dev

# 4. Apply the bootstrap stack (uses local state, safe to run)
terraform -chdir=infra/bootstrap init
terraform -chdir=infra/bootstrap apply
# → creates: musicstream-tfstate S3 bucket + musicstream-tfstate-lock DynamoDB table
```

---

## 4. Environment Variables (`.env`)

Copy `.env.example` to `.env` and fill every value. See `.env.example` for descriptions.

The minimum required values are:

| Variable | Where used |
|----------|-----------|
| `AWS_REGION` | All AWS CLI + Terraform calls |
| `AWS_PROFILE` or (`AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`) | Authentication |
| `TF_VAR_env` | Selects dev vs prod in Terraform |
| `TF_VAR_project` | Resource naming prefix |

---

## 5. Deploy Infrastructure

```bash
# 1. Initialise Terraform for dev
terraform -chdir=infra/envs/dev init

# 2. Review what will be created (read the plan carefully)
terraform -chdir=infra/envs/dev plan -out plan.bin

# 3. Apply
terraform -chdir=infra/envs/dev apply plan.bin
```

Terraform creates (in dependency order):
1. KMS CMK
2. S3 buckets (raw, archive, quarantine, scripts, reference)
3. DynamoDB tables (genre_daily_kpi, top_songs_daily, top_genres_daily)
4. IAM roles
5. SQS buffer queue + DLQ
6. Glue jobs
7. Lambda functions (validate_schema)
8. Step Functions state machine
9. EventBridge rule + Pipe

Typical first-apply time: **5–8 minutes**.

---

## 6. Upload Glue Scripts and Reference Data

After `terraform apply`, upload the application code and reference datasets.

```bash
# Set your bucket names (match your TF_VAR_env and TF_VAR_project)
SCRIPTS_BUCKET="musicstream-${TF_VAR_env}-scripts"
REFERENCE_BUCKET="musicstream-${TF_VAR_env}-reference"

# Build and upload the shared wheel
cd glue/
pip install build
python -m build --wheel
aws s3 cp dist/shared-*.whl "s3://${SCRIPTS_BUCKET}/glue/shared/"
cd ..

# Upload Glue job scripts
aws s3 sync glue/pyspark/ "s3://${SCRIPTS_BUCKET}/glue/pyspark/"
aws s3 sync glue/python_shell/ "s3://${SCRIPTS_BUCKET}/glue/python_shell/"

# Upload Lambda zip (validate_schema)
cd lambda/validate_schema/
pip install -r requirements.txt -t package/
cd package && zip -r ../function.zip . && cd ..
zip function.zip handler.py
aws lambda update-function-code \
  --function-name "${TF_VAR_env}-validate-schema" \
  --zip-file fileb://function.zip
cd ../..

# Convert reference CSVs to Parquet and upload (uses the helper script)
python scripts/upload_reference.py \
  --bucket "${REFERENCE_BUCKET}" \
  --users  data/users/users.csv \
  --songs  data/songs/songs.csv
```

---

## 7. Seed Sample Stream Data (Backfill)

Upload the three sample stream files to trigger the pipeline end-to-end:

```bash
RAW_BUCKET="musicstream-${TF_VAR_env}-raw"

python scripts/seed_sample_streams.py \
  --src   data/streams/ \
  --bucket "${RAW_BUCKET}" \
  --prefix streams/
```

This partitions each file by `listen_time` date and puts it under
`streams/yyyy=YYYY/mm=MM/dd=DD/<filename>.csv`. EventBridge picks up
each PUT, the SQS buffer collects them, and the EventBridge Pipe
dispatches them to Step Functions as a batch within ~2 minutes.

To trigger immediately (skip the 2-minute buffer), send a message to SQS manually:
```bash
SQS_URL=$(aws cloudformation describe-stacks ... # or grab from Terraform output)
aws sqs send-message \
  --queue-url "${SQS_URL}" \
  --message-body '{"bucket":"'${RAW_BUCKET}'","keys":["streams/yyyy=2024/mm=06/dd=25/streams1.csv"]}'
```

---

## 8. Monitor a Pipeline Run

### Step Functions console
AWS Console → Step Functions → State machines → `dev-streaming-etl-sm`
→ click the most recent execution to see the visual flow.

### CloudWatch dashboard
AWS Console → CloudWatch → Dashboards → `dev-etl-overview`

### CLI — tail execution status
```bash
SM_ARN=$(terraform -chdir=infra/envs/dev output -raw state_machine_arn)
aws stepfunctions list-executions --state-machine-arn "${SM_ARN}" \
  --status-filter RUNNING --query "executions[0].executionArn" --output text \
  | xargs aws stepfunctions describe-execution --execution-arn
```

### CLI — check archive (success)
```bash
aws s3 ls "s3://musicstream-${TF_VAR_env}-archive/streams/" --recursive
```

### CLI — check quarantine (failure)
```bash
aws s3 ls "s3://musicstream-${TF_VAR_env}-quarantine/streams/" --recursive
```

---

## 9. Verify DynamoDB KPIs

```bash
# Top 5 genres on 2024-06-25
aws dynamodb query \
  --table-name "dev_top_genres_daily" \
  --key-condition-expression "#d = :d" \
  --expression-attribute-names '{"#d":"date"}' \
  --expression-attribute-values '{":d":{"S":"2024-06-25"}}' \
  --query "Items[*].{rank:rank.N,genre:genre.S,plays:listen_count.N}" \
  --output table

# Genre KPIs for rock
aws dynamodb query \
  --table-name "dev_genre_daily_kpi" \
  --key-condition-expression "genre = :g" \
  --expression-attribute-values '{":g":{"S":"rock"}}' \
  --output table
```

Or open the UI (Section 11) for a point-and-click interface.

---

## 10. Run Tests

```bash
# Install dev dependencies
pip install -e "glue/[dev]"

# Unit + integration tests
pytest tests/unit tests/integration -q

# Terraform lint
terraform -chdir=infra/envs/dev validate
tflint --recursive
checkov -d infra/ --quiet

# SAST (Python)
semgrep --config p/python glue/ lambda/ --quiet
```

All four must be green before opening a PR.

---

## 11. Launch the UI Dashboard

The `ui/` directory is a **Streamlit** Python dashboard. It calls `boto3` directly against your DynamoDB tables — no API Gateway or separate backend needed.

### Install UI dependencies
```bash
pip install -r ui/requirements.txt
# or: pip install streamlit boto3 pandas plotly python-dotenv
```

### Local (most common)
```bash
# Ensure AWS credentials are active (SSO or .env sourced)
streamlit run ui/app.py
# Opens automatically at http://localhost:8501
```

The app reads `AWS_PROFILE` (or `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`) and `TF_VAR_env` from your environment. Set `MOCK_MODE=true` in `.env` to run fully offline with fixture data.

### Mock mode (no AWS needed)
```bash
MOCK_MODE=true streamlit run ui/app.py
```
A banner in the UI shows when mock mode is active.

### Deploy to Streamlit Community Cloud (optional, free)
1. Push the repo to GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io) → New app → point at `ui/app.py`.
3. Add AWS credentials as **secrets** in the app settings (never in the repo).

See `docs/ui.md` for the full page spec, layout wireframes, and deployment options.

---

## 12. Tear Down (dev only)

```bash
# Empty the buckets first (Terraform refuses to destroy non-empty S3 buckets)
for bucket in raw archive quarantine scripts reference; do
  aws s3 rm "s3://musicstream-${TF_VAR_env}-${bucket}/" --recursive
done

terraform -chdir=infra/envs/dev destroy
```

> Never run `destroy` on prod.

---

## 13. Common Problems & Fixes

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `terraform init` fails with "bucket not found" | Bootstrap not applied | Run Section 3 first |
| EventBridge Pipe not firing | S3 event notifications not enabled on bucket | Check `aws s3api get-bucket-notification-configuration` |
| Glue job fails with `G.025X not available` | Region doesn't support that worker type | Set `worker_type = "G.1X"` in `infra/envs/dev/terraform.tfvars` |
| Lambda timeout on large CSV | File > 64 KB before first newline | The Lambda falls back to 64 KB range read automatically; if still failing, check the `wide_header` CloudWatch log |
| DynamoDB write throttled | On-demand scaling lag on first run | Adaptive retry (D-26) handles this; wait ~30 s and the execution retries |
| `checkov` failing on KMS | Key policy using root ARN | This is intentional (D-25) — add a `checkov:skip` annotation in the Terraform resource |
| Step Functions execution stuck in `ValidateSchema` | Lambda not deployed / wrong ARN | Re-run the Lambda deploy step in Section 6 |

---

## 14. Useful Terraform Outputs

After `apply`, retrieve key ARNs and names:
```bash
terraform -chdir=infra/envs/dev output
# Outputs: state_machine_arn, raw_bucket_name, genre_daily_table_name, ...
```

---

## 15. Next Steps After First Successful Run

1. Open `docs/sprint_planning.md` — check the exit gate for Sprint 6 (orchestration). Tick it off.
2. Add a real stream file of your own to `data/streams/` and re-run the seed script.
3. Open the KPI Dashboard in the UI and confirm your data appears.
4. Run the failure drills from `docs/error_handling.md` §7.
5. When all 10 sprint exit gates pass, follow `docs/production_deployment.md` to promote to prod.
