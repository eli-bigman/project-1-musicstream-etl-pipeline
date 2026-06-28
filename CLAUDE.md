# CLAUDE.md — NSS Phase 2 Project 1: Streaming Analytics ETL Pipeline

This file is read by Claude Code at the start of every session. It is the authoritative fast-start context for this project. Keep it accurate and concise.

---

## Project Overview

An **event-driven, micro-batch ETL pipeline** for a music streaming service.

- Raw CSV files arrive in S3 at irregular intervals.
- An EventBridge Pipe batches them into Step Functions executions.
- A Lambda validates schema; a Glue PySpark job validates referential integrity, applies business rules, and computes six daily genre-level KPIs; a Glue Python Shell job writes KPIs to DynamoDB.
- Results are queryable by downstream applications from three DynamoDB tables.

**Brief:** `Intructions.txt` at repo root — read this before any implementation work.

---

## Key Documentation

All planning lives in `docs/`. The relay order is:

| Document | Purpose |
|----------|---------|
| `docs/master_plan.md` | Strategy, objectives, architecture diagram — **start here** |
| `docs/decision.md` | Every binding decision + revision history — **check before touching any component** |
| `docs/references.md` | Curated external links — **open before guessing at AWS/Terraform/Spark behaviour** |
| `docs/directory_structure.md` | Repo layout and naming conventions |
| `docs/agentic_workflow.md` | Stick-holding & telephone-skill relay conventions |
| `docs/terraform.md` | IaC modules, apply order, env promotion |
| `docs/step_functions.md` | State machine flow, ASL structure, retry policy |
| `docs/data_handling.md` | S3 arrival semantics, backfill, SQS buffering |
| `docs/data_validation.md` | T1 (Lambda), T2 (PySpark left-join), T3 (biz rules) |
| `docs/transformation_logic.md` | PySpark KPI computation — all six KPIs |
| `docs/glue_jobs.md` | Job inventory, worker sizing (G.1X in eu-west-1), cost model |
| `docs/dynamodb_schema.md` | Table designs, PK/SK, GSIs, sample queries |
| `docs/error_handling.md` | Retry matrix, quarantine flow, adaptive retry |
| `docs/logging_monitoring.md` | CloudWatch logs/metrics/alarms, EMF |
| `docs/file_archival.md` | Archive vs quarantine, lifecycle policy |
| `docs/security.md` | IAM (no wildcards), KMS root-principal delegation, PII |
| `docs/testing_strategy.md` | Unit / integration / e2e test pyramid |
| `docs/sprint_planning.md` | 10 solo sprints, goal per sprint |
| `docs/production_deployment.md` | Promotion, rollback, day-2 ops |

**Review history:** `.ai/review.md` — two rounds of senior review; disposition of every suggestion is recorded there.

---

## Current Architecture (binding — as of latest revision)

```
S3 PUT (raw/streams/) → EventBridge → SQS buffer
                                          │ BatchSize=50 / Window=120s
                                          ▼
                                   EventBridge Pipe  (D-22)
                                          │
                                          ▼
                                   Step Functions SM
                                          │
                              ┌───────────┴───────────┐
                              ▼                       ▼ (invalid)
                     Lambda: ValidateSchema      Quarantine + Alarm
                     (4 KB range request, D-23)
                              │ valid_keys[]
                              ▼
                     Glue PySpark: TransformAndCompute  (G.1X×2, D-24 fallback)
                     • T2 left-join ref validation
                     • T3 business rules
                     • 6 KPI aggregations → 3 parquet datasets
                              │
                              ▼
                     Glue Python Shell: LoadDynamoDB  (adaptive retry, D-26)
                     • writes to all 3 DDB tables in one job
                              │
                              ▼
                     ArchiveBatch (S3 CopyObject + DeleteObject)
                              │
                              ▼
                           Success
```

---

## Component Inventory

| Component | Type | Key decision |
|-----------|------|-------------|
| `lambda/validate_schema/` | Lambda Python 3.12 | T1 schema gate; 4 KB range read (D-17, D-23) |
| `glue/pyspark/transform_kpis.py` | Glue PySpark 4.0 | G.1X×2 in eu-west-1 (D-24 fallback) |
| `glue/python_shell/load_dynamodb.py` | Glue Python Shell | Single job; adaptive boto3 retry (D-26) |
| `glue/shared/` | Python wheel | Shared across all jobs; contains `dynamo_utils`, `logging_utils`, `s3_utils`, `schemas` |
| `step_functions/pipeline.asl.json` | ASL | Read by Terraform `templatefile()` |
| `infra/modules/` | Terraform | 8 modules — see `docs/terraform.md` |
| `ui/app.py` + `ui/pages/` | Streamlit | KPI dashboard; calls boto3 directly — no API Gateway (D-28-R) |
| `ui/lib/` | Python | `dynamo_queries`, `pipeline_ops`, `mock_data`, `aws_clients` |

---

## DynamoDB Tables (binding key scheme — D-03-R)

| Table | PK | SK | Primary access pattern |
|-------|----|----|----------------------|
| `${env}_genre_daily_kpi` | `genre` (S) | `date` (S) | Trend for one genre over date range |
| `${env}_top_songs_daily` | `genre` (S) | `date_rank` (S) e.g. `2024-06-25#01` | Top 3 songs for a genre on a date |
| `${env}_top_genres_daily` | `date` (S) | `rank` (N) | Top 5 genres on a date |

GSI `date_genre_index` on `genre_daily_kpi` (PK=`date`, SK=`genre`) covers the secondary "all genres for a date" pattern.

---

## Coding Standards

- **Python style:** `ruff` + `black` enforced via pre-commit. Run `pre-commit run --all-files` before committing.
- **Logging:** All log lines are JSON via `shared.logging_utils`. Mandatory keys: `ts`, `level`, `run_id`, `stage`, `event`. **Never log `user_name` or `user_country` — they are PII.**
- **No IAM wildcards:** Every `Action` in every policy is an explicit list. `checkov` blocks wildcards in CI.
- **KMS policy pattern:** Root-principal delegation only; no role ARNs in key policies (D-25, avoids Terraform circular dependencies). Because EventBridge is a service principal, the SQS buffer uses SQS-managed SSE instead of the project CMK.
- **Boto3 DynamoDB:** Always use `dynamo_utils.get_ddb_table()` — never instantiate `boto3.resource("dynamodb")` directly. This ensures adaptive retry is applied everywhere (D-26). The same rule applies in `ui/lib/dynamo_queries.py`.
- **Streamlit UI:** Run locally with `streamlit run ui/app.py`. The app reads AWS credentials from the environment — same profile used for Terraform. Use `MOCK_MODE=true` to run without credentials. **Do not add API Gateway** between the UI and DynamoDB — the direct `boto3` call is intentional (D-28-R).
- **Spark writes:** Always set `spark.conf.set("spark.sql.sources.partitionOverwriteMode", "dynamic")` before writing partitioned Parquet. Static overwrite will wipe the whole table.
- **Comments:** Write a comment only when the *why* is non-obvious. No docstrings that describe what the code already says.

---

## Terraform Rules

- Never use `terraform apply` directly in `prod` — CI with human approval gate only.
- Bootstrap state bucket first: `terraform -chdir=infra/bootstrap apply`.
- After applying, upload scripts: `aws s3 sync glue/ s3://musicstream-${env}-scripts/glue/`.
- Worker type `G.025X` is not valid for this batch Glue job in eu-west-1; dev uses `G.1X`.
- `modules/vpc-stub` is `enabled = false` by default. Enable only when moving a service into a VPC.

---

## Testing Before Submitting Work

```bash
# Unit + integration tests (includes ui/lib/ tests)
pytest tests/unit tests/integration -q

# Terraform lint
terraform -chdir=infra/envs/dev validate
tflint --recursive
checkov -d infra/

# SAST (covers glue, lambda, and ui)
semgrep --config p/python glue/ lambda/ ui/
```

All four must be clean before a PR is opened.

---

## Where to Look When Stuck

1. `docs/references.md` — curated links for every AWS service, Terraform resource, Spark API, and Python library in this project.
2. `docs/decision.md` — if a past decision covers your question, it is binding. If not, record your new decision there before implementing.
3. `Intructions.txt` — the original brief. If a design choice conflicts with the brief, the brief wins.

---

## Sprint Context

Ten sprints are planned in `docs/sprint_planning.md`. No calendar — each sprint is complete when its exit gate passes, not when time runs out.

Current sprint exit gates are defined per-sprint in that doc. Check it before starting a sprint to know what "done" looks like.

---

## Do Not

- Implement anything not covered by a doc in `docs/` without first updating `docs/decision.md`.
- Use `terraform apply --auto-approve` on `prod`.
- Commit secrets, `.env` files, or files containing `user_name`/`user_country` values.
- Modify a prior section of `docs/decision.md` — append a revision block instead (telephone-skill rule from `docs/agentic_workflow.md`).
- Enable Glue job bookmarks — idempotency relies on archive directory layout, not bookmarks (D-10).
- Add API Gateway between the Streamlit UI and DynamoDB — `boto3` calls DynamoDB directly; API Gateway adds complexity for no benefit here (D-28-R).
- Use `st.write(user_name)` or any Streamlit call that renders PII fields — the UI must display aggregates only.
