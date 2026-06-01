# Master Plan — Streaming Analytics ETL Pipeline

> Owner: Senior Data Engineer (solo build)
> Scope: AWS-native, event-driven ETL over irregular S3 arrivals, orchestrated by Step Functions, transformed by AWS Glue (PySpark + Python Shell), served from DynamoDB.

---

## 1. Problem Restatement

A music streaming service emits user-listen events into S3 as CSV batches at **unpredictable intervals**. We must validate, enrich (join with reference data for users/songs), aggregate to **daily genre-level KPIs**, and land those KPIs in DynamoDB for sub-second downstream lookup. The pipeline must self-heal (validation gates, retries, DLQ), be auditable (logging, archival), and be reproducible (Terraform IaC).

This is **micro-batch**, not true streaming. Files arrive irregularly; each file landing is the trigger. We optimise for *arrival-driven* latency, not for end-to-end real-time semantics.

## 2. North-Star Objectives

| # | Objective                                                                                     | Evaluation Criterion Mapped                       |
|---|------------------------------------------------------------------------------------------------|---------------------------------------------------|
| O1 | Event-driven ingestion: a new file in `s3://.../streams/raw/` triggers the pipeline within seconds. | Proper Step Functions orchestration               |
| O2 | Schema + integrity validation gate before any compute.                                        | Robust validation and error handling              |
| O3 | PySpark KPI computation that scales linearly with stream volume.                              | Efficient Glue usage                              |
| O4 | DynamoDB schema modelled around **known access patterns**, not relational habits.             | DynamoDB optimisation for fast lookups            |
| O5 | All AWS resources defined in Terraform with environments (`dev`, `prod`).                      | Reproducibility / production-readiness            |
| O6 | Idempotent runs — re-processing the same file does not corrupt KPIs.                          | Robustness                                        |
| O7 | Processed files archived; failed files quarantined.                                           | Logging / error handling                          |
| O8 | Documentation a new engineer can onboard from in <1 hour.                                     | Clear, structured documentation                   |

## 3. User Stories → Implementation Anchors

| Story | Anchored In Document |
|-------|---------------------|
| US1: Ingest from S3 via automated pipeline | `step_functions.md`, `terraform.md` |
| US2: Validate required columns before processing | `data_validation.md` |
| US3: Transform raw → KPIs efficiently with Glue | `transformation_logic.md`, `glue_jobs.md` |
| US4: Store KPIs in DynamoDB for fast access | `dynamodb_schema.md` |
| US5: Business analyst queries DynamoDB for insights | `dynamodb_schema.md` (sample queries) |

## 4. High-Level Architecture (Revised per `.ai/review.md`)

```
 Producers ── PUT *.csv ───▶ S3 (raw/streams/) ──▶ EventBridge ──▶ SQS (buffer)
                                                                       │
                                           BatchSize=50 / Window=120s  │
                                                                       ▼
                                                      [EventBridge Pipe] ← replaces Trigger Lambda (D-22)
                                                                       │
                                                                       ▼
                                                          ┌──────────────────┐
                                                          │ Step Functions SM│
                                                          └────────┬─────────┘
                                                                   ▼
                                                     [Lambda: T1 Schema Gate]
                                                       │ valid              │ invalid
                                                       ▼                    ▼
                                            [Glue PySpark]            /quarantine/
                                            ref-integrity (T2)
                                            biz rules (T3)
                                            KPI compute
                                            write 3 KPI parquets
                                                       │
                                                       ▼
                                          [Glue Python Shell — single loader]
                                          reads 3 parquets, writes 3 DDB tables
                                                       │
                                                       ▼
                                                  [Archive]
                                            (S3 CopyObject + DeleteObject)
                                                       │
                                                       ▼
                                          ┌────────────────────────────┐
                                          │           DynamoDB         │
                                          │  genre_daily_kpi           │
                                          │     PK=genre  SK=date      │
                                          │     GSI(date_genre_index)  │
                                          │  top_songs_daily           │
                                          │     PK=genre  SK=date#rank │
                                          │  top_genres_daily          │
                                          │     PK=date   SK=rank      │
                                          └────────────────────────────┘
```

Reference data (`users.csv`, `songs.csv`) is converted at ingest to **Parquet** under `s3://.../reference/{users,songs}/` (D-18), registered in the Glue Data Catalog, and refreshed by a low-cadence Python Shell job.

**Job inventory (revised — see `glue_jobs.md`).** Two Glue jobs per batch run: one PySpark (`G.025X × 2`, D-24), one Python Shell. Tier-1 schema validation runs in Lambda (4 KB range request, D-23). SQS → SM path managed by EventBridge Pipe (D-22). KMS keys use root-principal delegation (D-25). DynamoDB writes use adaptive retry (D-26). VPC stub module exists but is off by default (D-27). See `decision.md` D-02-R through D-27.

## 5. Execution Strategy — The Agentic Relay

This project is built solo, but planned as if a chain of specialised agents picks up the work in sequence. Each agent receives a **stick** (a written hand-off artefact) from the previous one and is responsible for adding to it before passing it on. This is the "stick-holding" model. The "telephone skill" rule says: **whatever the next agent needs must be on the stick, not in your head** — context lost between agents is the dominant failure mode.

| Agent (relay stage) | Stick artefact produced | Hand-off to |
|--------------------|------------------------|-------------|
| Architect           | This `master_plan.md` + `decision.md`         | Infra agent |
| Infra agent         | `terraform.md` + module skeletons             | Validation agent |
| Validation agent    | `data_validation.md` + Python Shell job spec  | Transform agent |
| Transform agent     | `transformation_logic.md` + PySpark job spec  | Load agent |
| Load agent          | `dynamodb_schema.md` + load-job spec          | Orchestration agent |
| Orchestration agent | `step_functions.md` ASL definition            | Ops agent |
| Ops agent           | `logging_monitoring.md`, `error_handling.md`  | Release agent |
| Release agent       | `production_deployment.md`                    | — |

Every sub-plan is the **stick** an agent hands forward.

## 6. Document Index

| Document                          | Purpose                                                                 |
|-----------------------------------|-------------------------------------------------------------------------|
| `master_plan.md`                  | This document — strategy, objectives, index.                            |
| `decision.md`                     | Decision log with rationale and trade-offs.                             |
| `references.md`                   | **Curated external links — open this first when stuck.**                |
| `directory_structure.md`          | Repo layout and rationale.                                              |
| `agentic_workflow.md`             | Stick-holding & telephone-skill conventions.                            |
| `terraform.md`                    | IaC layering, modules, state, environment promotion.                    |
| `step_functions.md`               | State machine, ASL, retries, parallelism.                               |
| `data_handling.md`                | Historical S3 backfill + ongoing arrival semantics.                     |
| `data_validation.md`              | Schema, type, referential, business-rule checks.                        |
| `transformation_logic.md`         | PySpark KPI computation, partitioning, joins.                           |
| `glue_jobs.md`                    | Job inventory: PySpark vs. Python Shell, DPU sizing, bookmarks.         |
| `dynamodb_schema.md`              | Table design, PK/SK, GSIs, access patterns, sample queries.             |
| `error_handling.md`               | Retry strategy, quarantine, DLQ, idempotency.                           |
| `logging_monitoring.md`           | CloudWatch logs, metrics, alarms, dashboards.                           |
| `file_archival.md`                | Archive vs. quarantine flow; lifecycle policy.                          |
| `security.md`                     | IAM, KMS, network, least-privilege.                                     |
| `testing_strategy.md`             | Unit (pytest), integration (LocalStack/Moto), e2e (synthetic file).     |
| `sprint_planning.md`              | Sequenced solo sprints, no timeline, agentic step list.                 |
| `production_deployment.md`        | Promotion, rollback, smoke tests, CI/CD.                                |

## 7. When You Are Stuck

Open `references.md` **before** guessing. It is the single curated reading list for every AWS service, Terraform resource, PySpark API, and Python library this project touches, organised by the question you are likely to be asking. Cite what you read in the doc you edit (filename + section). If the answer is not in any official source linked there, escalate to `decision.md`.

## 8. Review Disposition

`.ai/review.md` triggered the revision tags above. The disposition of each review point is recorded in `decision.md` under "Revisions from Architectural Review" — including the two items where I pushed back (DDB key-swap rationale, retaining a Python Shell loader). Read both before assuming the original sections are current.

## 9. Success Definition

The project is *done* when:

1. A new CSV dropped into `raw/streams/` results in correctly-updated KPIs in DynamoDB within 10 minutes, with no manual action.
2. A malformed CSV is quarantined and an alarm fires — no silent failures.
3. The same file replayed twice yields the same DynamoDB state (idempotency).
4. `terraform apply` from a clean account stands the whole stack up in one command.
5. A sample analyst query (e.g. *"top 5 genres on 2024-06-25"*) returns from DynamoDB in <50 ms.
