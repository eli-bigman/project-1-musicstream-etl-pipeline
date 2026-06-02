# MusicStream — Streaming Analytics ETL Pipeline

An event-driven, micro-batch ETL pipeline for a music streaming service.

Raw CSV files land in S3 → EventBridge → SQS buffer → EventBridge Pipe → Step Functions → Lambda schema validation → Glue PySpark (ref-integrity + KPI compute) → Glue Python Shell (DynamoDB load) → archive.

Results are stored in three DynamoDB tables queryable by a Streamlit dashboard.

## Quick Start

```powershell
# 1. Authenticate
aws sso login --profile musicstream-dev
$env:AWS_PROFILE="musicstream-dev"

# 2. Bootstrap state backend (once per account)
terraform -chdir=infra/bootstrap init
terraform -chdir=infra/bootstrap apply

# 3. Deploy dev infrastructure
terraform -chdir=infra/envs/dev init
terraform -chdir=infra/envs/dev apply -auto-approve

# 4. Build and upload Glue wheel
cd glue && pip install build && python -m build --wheel
aws s3 cp dist/shared-0.1.0-py3-none-any.whl s3://musicstream-dev-scripts/glue/shared/
aws s3 sync . s3://musicstream-dev-scripts/glue/ --exclude "*" --include "*.py"
cd ..

# 5. Seed reference data and sample streams
bash scripts/upload_reference.sh dev
bash scripts/seed_sample_streams.sh dev

# 6. Run the dashboard
cd ui && streamlit run app.py
```

See `human.md` for the full operator guide and `docs/master_plan.md` for architecture.

## Run Tests

```powershell
pytest tests/unit tests/integration -q
terraform -chdir=infra/envs/dev validate
```

## Mock Mode (no AWS credentials)

```powershell
$env:MOCK_MODE="true"
streamlit run ui/app.py
```
