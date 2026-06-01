# Directory Structure

The repo separates **infrastructure**, **application code**, **tests**, and **documentation** so that changing one does not force-rebuild the others.

```
.
├── README.md
├── docs/                       ← all planning + ops documentation (this folder)
│   ├── master_plan.md
│   ├── decision.md
│   ├── directory_structure.md
│   ├── agentic_workflow.md
│   ├── terraform.md
│   ├── step_functions.md
│   ├── data_handling.md
│   ├── data_validation.md
│   ├── transformation_logic.md
│   ├── glue_jobs.md
│   ├── dynamodb_schema.md
│   ├── error_handling.md
│   ├── logging_monitoring.md
│   ├── file_archival.md
│   ├── security.md
│   ├── testing_strategy.md
│   ├── sprint_planning.md
│   └── production_deployment.md
│
├── infra/                      ← Terraform IaC
│   ├── envs/
│   │   ├── dev/
│   │   │   ├── main.tf
│   │   │   ├── backend.tf
│   │   │   ├── variables.tf
│   │   │   └── terraform.tfvars
│   │   └── prod/
│   │       └── ... (mirror of dev)
│   ├── modules/
│   │   ├── s3-data-lake/
│   │   ├── glue-jobs/
│   │   ├── step-functions/
│   │   ├── dynamodb-kpi-tables/
│   │   ├── iam-roles/
│   │   └── eventbridge-trigger/
│   └── bootstrap/              ← one-time state bucket + lock table
│
├── glue/                       ← Glue job source — what gets uploaded to S3 scripts/
│   ├── pyspark/
│   │   └── transform_kpis.py
│   ├── python_shell/
│   │   ├── validate_schema.py
│   │   ├── validate_referential.py
│   │   └── load_dynamodb.py
│   ├── shared/                 ← packaged as a wheel & passed via --extra-py-files
│   │   ├── __init__.py
│   │   ├── schemas.py          ← pydantic / dataclass schema definitions
│   │   ├── logging_utils.py
│   │   ├── s3_utils.py
│   │   └── dynamo_utils.py
│   └── pyproject.toml
│
├── step_functions/             ← ASL definitions (kept out of Terraform for diffability)
│   └── pipeline.asl.json
│
├── tests/
│   ├── unit/
│   │   ├── test_schemas.py
│   │   ├── test_transform_kpis.py    ← uses pyspark local
│   │   └── test_dynamo_utils.py
│   ├── integration/
│   │   ├── test_validation_job.py    ← moto-mocked S3
│   │   └── test_load_job.py          ← moto-mocked DynamoDB
│   ├── e2e/
│   │   └── test_pipeline_smoke.py    ← runs against dev env, drops fixture file
│   └── fixtures/
│       ├── valid_streams.csv
│       ├── missing_column.csv
│       ├── bad_listen_time.csv
│       └── unknown_user_id.csv
│
├── ui/                         ← Streamlit KPI dashboard (D-28-R)
│   ├── app.py                  ← home page + quick stats
│   ├── pages/
│   │   ├── 1_Pipeline.py       ← upload, trigger, stage tracker (US1–US4)
│   │   └── 2_KPI_Dashboard.py  ← date/genre filters, charts, tables (US5)
│   ├── lib/
│   │   ├── aws_clients.py      ← boto3 client factory
│   │   ├── dynamo_queries.py   ← KPI table query helpers
│   │   ├── pipeline_ops.py     ← S3 upload + Step Functions start/poll
│   │   └── mock_data.py        ← fixture data for offline demo
│   ├── requirements.txt        ← streamlit, boto3, pandas, plotly, python-dotenv
│   └── .streamlit/
│       └── config.toml         ← dark theme matching project palette
│
├── data/                       ← provided sample data (read-only)
│   ├── streams/
│   ├── songs/
│   └── users/
│
├── scripts/                    ← local dev helpers (sync to S3, trigger SM, etc.)
│   ├── upload_reference.sh
│   ├── seed_sample_streams.sh
│   └── trigger_pipeline.sh
│
├── .github/
│   └── workflows/
│       ├── ci.yml              ← lint, unit, terraform validate
│       └── cd-dev.yml          ← on merge to main → apply dev
│
├── .gitignore
├── .pre-commit-config.yaml
└── Intructions.txt             ← original brief
```

## Naming Conventions

- **Buckets.** `${project}-${env}-${purpose}` → e.g. `musicstream-dev-raw`, `musicstream-dev-archive`, `musicstream-dev-quarantine`, `musicstream-dev-scripts`.
- **DynamoDB tables.** `${env}_genre_daily_kpi`, `${env}_top_songs_daily`, `${env}_top_genres_daily`.
- **Glue jobs.** `${env}-validate-schema`, `${env}-validate-referential`, `${env}-transform-kpis`, `${env}-load-dynamodb`.
- **Step Functions state machine.** `${env}-streaming-etl-sm`.
- **CloudWatch log groups.** `/aws/glue/jobs/${job-name}`.

## S3 Bucket Layout (data lake)

```
musicstream-${env}-raw/
└── streams/
    ├── yyyy=2024/mm=06/dd=25/file_1234.csv        ← landing zone
    └── ...

musicstream-${env}-reference/
├── users/users.csv
└── songs/songs.csv

musicstream-${env}-archive/
└── streams/yyyy=…/mm=…/dd=…/file_1234.csv          ← post-success

musicstream-${env}-quarantine/
└── streams/yyyy=…/mm=…/dd=…/file_1234.csv          ← post-failure
    └── _reason.json                                ← why it failed

musicstream-${env}-scripts/
├── glue/pyspark/transform_kpis.py
├── glue/python_shell/*.py
└── glue/shared/shared-0.1.0-py3-none-any.whl
```

## Why this layout

- **`infra/` ↔ `glue/` separation** lets you change a job's Python without `terraform plan` ever needing to think about it (jobs reference scripts by S3 URI, not embedded source).
- **`envs/dev` and `envs/prod` are sibling, not branches**, so prod is reviewable in the same PR — no surprise drift.
- **`step_functions/pipeline.asl.json`** lives outside Terraform as a file Terraform reads via `file()`. Diffs are readable.
- **`shared/` as a wheel** is the standard way to share code between PySpark and Python Shell jobs without copy-paste.
