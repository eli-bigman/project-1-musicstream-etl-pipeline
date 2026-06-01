# Sprint Planning — Agentic Task Breakdown

> No calendar timelines (solo build).
> Each "sprint" is a discrete unit of work whose **deliverable is reviewable in isolation**.
> Each sprint corresponds to one agent on the relay (`agentic_workflow.md`).

---

## Sprint 0 — Bootstrap & Repo Setup
**Agent:** Repo curator.
**Deliverables.**
- Repo scaffolding from `directory_structure.md`.
- `pyproject.toml` (PySpark + Python Shell deps under extras).
- `pre-commit` (ruff, black, terraform fmt, terraform validate).
- `.github/workflows/ci.yml` skeleton (lint + `terraform validate`).
- Bootstrap Terraform stack (`infra/bootstrap/`) applied; state bucket + lock table exist.

**Exit gate:** `terraform -chdir=infra/bootstrap apply` succeeds; CI is green on an empty PR.

---

## Sprint 1 — Storage Plane
**Agent:** Infra + Storage.
**Deliverables.**
- `modules/s3-data-lake` complete; five buckets, encryption, lifecycle.
- `modules/dynamodb-kpi-tables` complete; three tables, PITR, KMS.
- `modules/iam-roles` skeleton with placeholder permissions.

**Exit gate:** `terraform apply` on `dev` stands up storage; `aws s3 ls` and `aws dynamodb describe-table` work.

---

## Sprint 2 — Reference Data & Shared Library
**Agent:** Ingestion.
**Deliverables.**
- `glue/shared/` package: schemas, logging_utils, s3_utils, dynamo_utils.
- `scripts/upload_reference.sh` lands the sample `users.csv` / `songs.csv`.
- `scripts/seed_sample_streams.py` partitions and uploads the three `streams*.csv` files.
- Glue Catalog + crawler (optional v1) over reference data.

**Exit gate:** All sample files are in S3 under correct prefixes; `glue/shared/` wheel builds and uploads.

---

## Sprint 3 — Validation Jobs
**Agent:** Validation.
**Deliverables.**
- `glue/python_shell/validate_schema.py` + tests (`test_schemas.py`).
- `glue/python_shell/validate_referential.py` + tests.
- Terraform `modules/glue-jobs` covering these two jobs.
- All six fixture files committed under `tests/fixtures/`.

**Exit gate:** Unit + integration tests green; manually triggering `validate_schema` on a fixture in S3 succeeds.

---

## Sprint 4 — Transform Job
**Agent:** Transform.
**Deliverables.**
- `glue/pyspark/transform_kpis.py` + unit tests using `pytest-spark`.
- KPI parquet outputs visible in `s3://.../kpi/...` for the sample input.
- DPU sizing committed (G.1X × 4).

**Exit gate:** Running `transform_kpis` manually against the sample dataset yields parquet files matching hand-computed KPIs.

---

## Sprint 5 — Loader & DynamoDB Plane
**Agent:** Storage (cont.).
**Deliverables.**
- `glue/python_shell/load_dynamodb.py` + tests against `moto`.
- Loader writes KPI items to the three tables.
- Sample analyst queries from `dynamodb_schema.md` §6 return expected values.

**Exit gate:** All four canned queries return data; `aws dynamodb scan --table-name ... --select COUNT` matches the parquet row count.

---

## Sprint 6 — Orchestration
**Agent:** Orchestration.
**Deliverables.**
- `step_functions/pipeline.asl.json` complete; templated into Terraform.
- `modules/step-functions` deployed.
- `modules/eventbridge-trigger` deployed; PUT into `raw/` triggers an execution.

**Exit gate:** End-to-end happy path runs from S3 PUT to DynamoDB item, with archive cleanup, on dev.

---

## Sprint 7 — Reliability & Observability
**Agent:** Reliability + Observability.
**Deliverables.**
- All `Catch` branches implemented; quarantine flow verified with the negative fixture.
- CloudWatch dashboard `etl-overview` deployed.
- All alarms from `error_handling.md` §4 firing on simulated failures.
- Logs Insights saved queries deployed.

**Exit gate:** Failure drill (`error_handling.md` §7) passes all five steps.

---

## Sprint 8 — Hardening
**Agent:** Security.
**Deliverables.**
- IAM policies tightened to resource-scoped (no wildcards).
- `checkov` clean.
- KMS CMK encrypted everything; key policies reviewed.
- Fixtures scrubbed of any sample real names → synthetic.

**Exit gate:** `checkov -d infra/` returns 0 high-severity findings.

---

## Sprint 9 — CI/CD & Promotion
**Agent:** Release.
**Deliverables.**
- `cd-dev.yml`: merge-to-main triggers `terraform apply` on dev + post-deploy e2e.
- `cd-prod.yml`: tag triggers prod plan + manual-approval apply.
- Glue wheel + script publish steps automated.
- Rollback procedure documented (`production_deployment.md`).

**Exit gate:** Deploying `dev` is a one-PR operation; `prod` apply requires a human, executes cleanly.

---

## Resource Allocation (solo build)

| Sprint | Estimated effort (relative) | External dependencies |
|--------|-----------------------------|-----------------------|
| 0      | S                           | AWS account, GitHub repo |
| 1      | M                           | none                  |
| 2      | S                           | sample data present   |
| 3      | M                           | Sprint 1 + 2          |
| 4      | L                           | Sprint 3 (clean parquet) |
| 5      | M                           | Sprint 4 (KPI parquet) |
| 6      | L                           | Sprints 3–5           |
| 7      | M                           | Sprint 6              |
| 8      | S                           | All prior             |
| 9      | M                           | All prior             |

S = ½–1 working session, M = 2–3, L = 4+ — relative only; no calendar.

## Goal per Sprint (one sentence each)

| Sprint | Goal |
|--------|------|
| 0 | A repo you can apply Terraform from. |
| 1 | A place to put data and a place to query KPIs. |
| 2 | Sample data lives in the right S3 prefixes; helpers reusable across jobs. |
| 3 | A bad CSV can never poison KPIs. |
| 4 | KPIs are computed correctly from clean parquet. |
| 5 | KPIs are queryable by an analyst in < 50 ms. |
| 6 | A file arriving in S3 ends up as DynamoDB items, automatically. |
| 7 | The pipeline tells you when it's broken before a human notices. |
| 8 | Auditable, least-privilege, encrypted everywhere. |
| 9 | Deploying to prod is boring. |

---

## Revisions from `.ai/review.md`

The sprint sequence holds, but the *contents* of three sprints change.

### Sprint 3 — Validation (revised)
- **Drop** `validate_referential` Python Shell job and its tests.
- **Add** `lambda/validate_schema/` (D-17) and its unit tests.
- **Add** the `modules/sqs-buffer` + `modules/lambda-trigger` Terraform modules and a synthetic integration test that drops a file and confirms it is buffered then dispatched (D-11-R).
- **Exit gate (revised):** A fixture file dropped into `raw/` is captured by EventBridge, buffered in SQS, and triggers one SM execution within 2 minutes.

### Sprint 4 — Transform (revised)
- The PySpark job now also performs T2 referential validation (left-join + side-output) and T3 biz rules (D-19).
- Reference data is read from Parquet (D-18).
- **Exit gate (revised):** Running the PySpark job on a synthetic batch produces (a) three KPI parquet datasets, (b) a `quarantine/ref-fail/` parquet with the expected unmatched rows, (c) hand-computed KPIs match.

### Sprint 5 — Loader (revised)
- A **single** Python Shell job loads all three DynamoDB tables (not three jobs in a Map) — D-02-R.
- DynamoDB tables use the revised key schemes (D-03-R) — base table queries replace the old GSI on `genre_daily_kpi`; a new `date_genre_index` GSI covers the secondary pattern.
- **Exit gate (revised):** All sample analyst queries in `dynamodb_schema.md` §9.5 return expected items.

### Sprint 8 — Hardening (revised)
- Adds the Snyk Code / `semgrep` step (D-21).
- IAM cleanup expands to cover the two new Lambda roles (D-20).
