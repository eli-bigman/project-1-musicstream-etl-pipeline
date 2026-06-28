# human.md — Operator Setup Guide

> Read `docs/master_plan.md` first for context. This file is the *how*; that file is the *why*.

---

## 1. Prerequisites

Install the following tools on your local system before proceeding:

| Tool | Minimum Version | Install / Setup Link |
|------|-----------------|----------------------|
| **AWS CLI** | v2.15+ | [AWS CLI Installation](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) |
| **Terraform** | 1.6+ | [Terraform Installation](https://developer.hashicorp.com/terraform/install) |
| **Python** | 3.11+ | [Python Downloads](https://www.python.org/downloads/) |
| **Streamlit** | 1.35+ | `pip install streamlit` (also in `ui/requirements.txt`) |
| **Git** | Any | [Git Installation](https://git-scm.com/) |

Verify your installations by running:
```powershell
aws --version
terraform --version
python --version
streamlit --version
```

---

## 2. AWS Authentication (SSO)

We use **IAM Identity Center (SSO)** for development access. This project is configured to use the profile name `musicstream-dev`.

### Initial Setup (One-time)
If you haven't configured the profile yet, run:
```powershell
aws configure sso
# Follow the prompts and set the profile name to: musicstream-dev
```

### Authenticating (Required before every session)
AWS SSO credentials expire periodically. To log in and activate your session, run:
```powershell
aws sso login --profile musicstream-dev
$env:AWS_PROFILE="musicstream-dev"
```

---

## 3. Spinning Up the System

Follow these steps in order to deploy the infrastructure, upload code assets, and ingest sample data.

### Step 3.1: One-Time State Bootstrap
Create the S3 bucket and DynamoDB table that hold the Terraform remote state:
```powershell
terraform -chdir=infra/bootstrap init
terraform -chdir=infra/bootstrap apply
```
*Creates:* S3 bucket `musicstream-tfstate` and DynamoDB table `musicstream-tfstate-lock`.

### Step 3.2: Deploy Environment Infrastructure
Deploy the core pipeline resources (dev environment):
```powershell
terraform -chdir=infra/envs/dev init
terraform -chdir=infra/envs/dev plan -out plan.bin
terraform -chdir=infra/envs/dev apply plan.bin
```
*Deploys:* KMS Keys, S3 buckets (raw, archive, quarantine, scripts, reference), SQS Buffer Queue, Glue Jobs, Lambda (validate_schema), Step Functions, and DynamoDB tables.
*(Approx. 5–8 minutes)*

### Step 3.3: Build & Upload Application Assets
With infrastructure in place, build and upload the Glue code, Lambda functions, and reference data.

1. **Build and Upload Shared Glue Library (Wheel):**
   ```powershell
   cd glue
   pip install build
   python -m build --wheel
   aws s3 cp dist/shared-0.1.0-py3-none-any.whl "s3://musicstream-dev-scripts/glue/shared/"
   cd ..
   ```

2. **Sync Glue Scripts:**
   ```powershell
   aws s3 sync glue/pyspark/ "s3://musicstream-dev-scripts/glue/pyspark/"
   aws s3 sync glue/python_shell/ "s3://musicstream-dev-scripts/glue/python_shell/"
   ```

3. **Package and Deploy Lambda (validate_schema):**
   ```powershell
   cd lambda/validate_schema
   pip install -r requirements.txt -t package/
   cd package
   Compress-Archive -Path * -DestinationPath ../function.zip -Force
   cd ..
   Compress-Archive -Path handler.py -Update -DestinationPath function.zip
   aws lambda update-function-code --function-name dev-validate-schema --zip-file fileb://function.zip
   cd ../..
   ```

4. **Upload Reference Data (Users and Songs):**
   ```powershell
   python scripts/upload_reference.py --bucket "musicstream-dev-reference" --users data/users/users.csv --songs data/songs/songs.csv
   ```

### Step 3.4: Ingest Sample Stream Data (Trigger Pipeline)
Upload sample CSV data to trigger the event-driven ETL flow:
```powershell
python scripts/seed_sample_streams.py --src data/streams/ --bucket "musicstream-dev-raw" --prefix streams/
```
The file lands in S3, triggers the EventBridge Pipe, lands in the SQS buffer, and gets dispatched to Step Functions within ~2 minutes.

---

## 4. Running the Streamlit UI Dashboard

The UI dashboard allows you to view computed streaming analytics KPIs. It connects directly to DynamoDB tables using local AWS credentials.

### Install Dependencies
```powershell
pip install -r ui/requirements.txt
```

### Run Locally (Online Mode)
Ensure you are logged into SSO (`aws sso login`), then start the dashboard:
```powershell
$env:AWS_PROFILE="musicstream-dev"
streamlit run ui/app.py
# Automatically opens at http://localhost:8501
```

### Run Offline (Mock Mode)
To run the UI without calling AWS services, run:
```powershell
$env:MOCK_MODE="true"
streamlit run ui/app.py
```

---

## 5. Tearing Down the System

Follow these steps to safely destroy the dev environment and avoid incurring AWS costs.

### Step 5.1: Empty All Application S3 Buckets
Terraform will refuse to delete S3 buckets that contain files. You must empty them first:
```powershell
for ($bucket in @("raw", "archive", "quarantine", "scripts", "reference")) {
  aws s3 rm "s3://musicstream-dev-$bucket/" --recursive
}
```

### Step 5.2: Destroy Dev Infrastructure
```powershell
terraform -chdir=infra/envs/dev destroy
```

### Step 5.3: Destroy Bootstrap Backend (Optional)
Only run this if you want to delete the remote Terraform state store itself:
```powershell
terraform -chdir=infra/bootstrap destroy
```

---

## 6. Critical Blockers & Operator Attention Points

Be aware of the following potential blockers while running the system:

1. **SSO Session Expiration (Active Blocker):**
   AWS SSO logins expire periodically (typically every 8–12 hours). If you receive `ExpiredToken` or credentials-related errors in Terraform/AWS CLI, re-authenticate immediately:
   `aws sso login --profile musicstream-dev`

2. **Bucket Naming Sync in `.env`:**
   Your S3 bucket names in `.env` (like `RAW_BUCKET`, `SCRIPTS_BUCKET`, etc.) must exactly match the outputs generated after running `terraform apply`. Always check that the environment variables in `.env` are aligned with the actual resources.

3. **Regional Glue Worker Availability (`G.025X`):**
   The small worker type `G.025X` is cost-efficient but not supported in all AWS regions. If Terraform apply fails during Glue job creation, set the variable `worker_type = "G.1X"` in your dev environment Terraform variables.

4. **Lambda Deployment Requirements:**
   If the Step Functions execution gets stuck or fails at the `ValidateSchema` stage, it is likely that the Lambda function wasn't properly packaged and deployed. Make sure to run the deployment commands in Section 3.3.

5. **DynamoDB Write Throttling:**
   If the pipeline runs with a large backfill batch, writes to DynamoDB tables may be throttled. The python shell loader employs adaptive retries, but if it fails repeatedly, check the table write capacity settings in Terraform.

---

## 7. Monitoring & Verification Commands

### Step Functions Status
To check if the state machine is running:
```powershell
aws stepfunctions list-executions --state-machine-arn (terraform -chdir=infra/envs/dev output -raw state_machine_arn) --status-filter RUNNING
```

### Verify S3 Archive vs Quarantine
*   **Success Archive:** `aws s3 ls s3://musicstream-dev-archive/streams/ --recursive`
*   **Failed Quarantine:** `aws s3 ls s3://musicstream-dev-quarantine/streams/ --recursive`

### Query DynamoDB KPIs
Query the top genres for a specific date:
```powershell
aws dynamodb query `
  --table-name "dev_top_genres_daily" `
  --key-condition-expression "#d = :d" `
  --expression-attribute-names '{"#d":"date"}' `
  --expression-attribute-values '{":d":{"S":"2024-06-25"}}' `
  --output table
```
