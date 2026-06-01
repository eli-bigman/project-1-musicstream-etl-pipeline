# Decision Log

> Every decision below is recorded from the perspective of a senior data engineer.
> Format: **D-##** · Decision · Context · Options Considered · Choice · Rationale · Trade-offs · Reversibility.

---

## D-01 · Orchestration: Step Functions over MWAA / EventBridge Pipes
- **Context.** Need orchestration over irregular S3 arrivals across 3–5 Glue jobs with branching.
- **Options.** (a) Step Functions Standard, (b) MWAA (Airflow), (c) EventBridge Pipes + targets only, (d) Glue Workflows.
- **Choice.** **Step Functions Standard.**
- **Rationale.** Native integrations to Glue/DynamoDB/S3, per-run visual history, IAM-scoped, pay-per-transition. MWAA is over-built for ≤10 tasks and adds a $\$$$300+/mo floor. Glue Workflows lack the conditional/branching ergonomics. EventBridge Pipes alone can't model multi-step validation→transform→load.
- **Trade-offs.** ASL is verbose; Step Functions has a 25 KB state payload limit — large file lists must be carried by S3 references, not embedded.
- **Reversibility.** High. Swapping to Airflow later is a definition rewrite, not a data migration.

## D-02 · Glue Job Split: PySpark for Aggregation, Python Shell for Validation/Load
- **Context.** Glue offers two job types; both are billable by DPU-hour.
- **Choice.** Validation + DynamoDB load = **Python Shell** (0.0625 / 1 DPU). KPI transformation = **PySpark** (2+ DPU G.1X).
- **Rationale.** Validation is metadata/row-count work — Spark adds startup latency (~1 min) for no benefit. DynamoDB writes are I/O-bound and benefit from `boto3` batch_writer concurrency, not Spark. PySpark only earns its cost during the join + aggregation stage.
- **Trade-offs.** Two runtimes to maintain; shared utility code must live in a packaged wheel that both can import.
- **Reversibility.** High.

## D-03 · DynamoDB Modelling: Single-Table vs. Multi-Table
- **Context.** Three KPI shapes (genre-daily, top-songs-per-genre-per-day, top-genres-per-day) with distinct access patterns but overlapping date filters.
- **Options.** (a) Single-table with item-type discrimination, (b) Three purpose-built tables.
- **Choice.** **Three tables.**
- **Rationale.** Access patterns are disjoint; a business analyst querying "top 5 genres on date X" should not need to know about `SK begins_with` tricks. Capacity sizing per workload is cleaner. Single-table design's gains (one round-trip multi-entity fetches) don't apply here — we never need a genre KPI *and* its top songs in one call.
- **Trade-offs.** More tables to provision and monitor. Mitigated by Terraform module.
- **Reversibility.** Medium — schema change later requires a backfill.

## D-04 · Billing Mode: On-Demand for KPI Tables
- **Context.** Write spikes occur when a Glue load finishes (5–50k items in seconds); read traffic is unknown.
- **Choice.** **PAY_PER_REQUEST** for all three tables initially.
- **Rationale.** No capacity planning at green-field stage. Switch to provisioned + autoscaling after 30 days of CloudWatch data when patterns are known.
- **Trade-offs.** Per-request pricing is ~7× provisioned at steady state. Acceptable while traffic is unknown.

## D-05 · Idempotency Strategy: Deterministic Primary Keys + Conditional Overwrite
- **Context.** Replaying a stream file must not double-count plays.
- **Choice.** KPI primary keys derived from `(date, genre[, track_id])`. PySpark always **overwrites the full day** of aggregates for the dates present in the input batch.
- **Rationale.** Aggregates are deterministic functions of the raw set. Recomputing the whole day from raw is cheaper than reasoning about deltas.
- **Trade-offs.** Requires reading all raw stream files for the affected day(s), not only the new arrival. Mitigated by Hive-style date partitioning on the raw zone.

## D-06 · Reference Data (`users`, `songs`) Strategy
- **Context.** Reference data is small (≤50 MB), low-cadence change, joined to every batch.
- **Choice.** Land reference data in `s3://.../reference/{users,songs}/`, register as Glue Catalog tables, broadcast-join in PySpark.
- **Rationale.** Broadcast join eliminates shuffle. Catalog registration lets Athena query the same files for ad-hoc validation.
- **Trade-offs.** A schema change in reference data requires crawler refresh. Acceptable.

## D-07 · Validation: Fail-Fast, Quarantine, Alarm
- **Context.** Bad files must not poison KPIs; the pipeline must be observable.
- **Choice.** Three validation tiers: (1) schema (columns/types), (2) referential (`user_id`/`track_id` exist), (3) business rule (`listen_time` parsable, not in the future). Failing tier-1 → move to `quarantine/`, raise CloudWatch alarm, Step Function `Fail` state. Tier-2/3 violations: drop offending rows, log counts to metrics, continue.
- **Rationale.** Hard fail for structural problems (signals upstream contract break); soft fail for row-level noise (signals data quality, not pipeline break).
- **Trade-offs.** Threshold for "too much soft-fail" is judgemental — set at 5% of rows for v1, revisit.

## D-08 · IaC: Terraform with Remote State (S3 + DynamoDB Lock)
- **Context.** Single developer, but solution must be reproducible across `dev`/`prod`.
- **Choice.** Terraform ≥ 1.6, remote state in S3 with DynamoDB lock table, per-env workspaces.
- **Rationale.** Industry standard; AWS provider mature for Glue/Step Functions/DynamoDB. CloudFormation discarded due to weaker module ergonomics.
- **Trade-offs.** Bootstrapping the state bucket itself is a one-time manual or `terragrunt` step.

## D-09 · Trigger: EventBridge → Step Functions (not S3 → Lambda fan-out)
- **Context.** Files arrive irregularly; we need event-driven start.
- **Choice.** S3 `Object Created` → EventBridge rule → `StartExecution` on the state machine.
- **Rationale.** EventBridge supports filtering by prefix/suffix without a Lambda hop, supports DLQ for failed invocations, and is the AWS-recommended pattern for 2024+.
- **Trade-offs.** None material.

## D-10 · Bookmarking: Step Functions State, Not Glue Bookmarks
- **Context.** Need to know which files have been processed.
- **Choice.** Maintain processed/failed state via the **archive directory layout** (`raw/` → `archive/{yyyy=}/{mm=}/{dd=}/`). Do **not** rely on Glue job bookmarks.
- **Rationale.** Glue bookmarks are opaque, hard to replay, and surprising under partial-failure. A directory move is debuggable by anyone with S3 console access.
- **Trade-offs.** Slightly more orchestration logic in the state machine.

## D-11 · Concurrency: One File Per Execution, Parallel Executions Allowed
- **Context.** Multiple files may land simultaneously.
- **Choice.** Each S3 PUT starts its own state machine execution. Step Function-level concurrency cap = 10. Within an execution, the Glue job receives a single file path.
- **Rationale.** Simpler reasoning; each execution is atomic. Idempotent overwrite (D-05) handles same-day collisions.
- **Trade-offs.** Wastes Spark startup if many small files land at once. Accepted at v1; "micro-batch coalescer" is a v2 enhancement noted in `production_deployment.md`.

## D-12 · Secrets & Encryption
- **Choice.** SSE-S3 for buckets, KMS-managed CMKs for DynamoDB; no secrets at this stage (no external APIs).
- **Rationale.** Minimal but correct. CMK adds key-rotation auditability vs. AWS-managed key.

## D-13 · Logging: CloudWatch Logs + Structured JSON
- **Choice.** All Glue jobs emit JSON log lines with `run_id`, `file`, `stage`, `count`, `level`. Log retention 30 days dev / 365 prod.
- **Rationale.** Greppable, queryable from Logs Insights, cheap to aggregate.

## D-14 · "Stick-Holding" Agentic Methodology
- **Context.** Solo build, but plan is structured as an agent relay so each phase produces a hand-off artefact (see `agentic_workflow.md`).
- **Rationale.** Prevents context loss across long work sessions; each `.md` doubles as a step in the implementation procedure.
- **Trade-offs.** Up-front documentation cost. Paid back the first time work resumes after a break.

## D-15 · External-Source Lookup Discipline
- **Context.** Agents in the relay must not guess at AWS / Terraform / Spark behaviour.
- **Choice.** A single `references.md` is the canonical reading list. Before guessing, the agent opens it; after reading, the agent cites the URL in the doc being edited.
- **Rationale.** Curated > rediscovered. Concentrates the rot to one file when a link dies. Makes "I read this here" auditable.
- **Trade-offs.** Slight maintenance cost — `references.md` must stay current.
- **Reversibility.** High.

## D-16 · Out-of-Scope (v1)
Explicitly deferred: Kinesis-based true streaming, Lake Formation fine-grained access, multi-region replication, ML-derived KPIs, Iceberg/Hudi adoption. Captured here so they are *deferred*, not *forgotten*.

---

# Revisions from Architectural Review (`.ai/review.md`)

> Per `agentic_workflow.md` §4, prior decisions are not rewritten. They remain above as the historical record. The revisions below supersede them and are the binding choices going forward.

## D-02-R · Glue Job Consolidation
- **Supersedes.** D-02.
- **Choice.** Two Glue jobs only — **one PySpark** (referential + business validation + KPI compute + parquet write) and **one Python Shell** (single loader writing to all three DynamoDB tables). Tier-1 schema validation moves out of Glue entirely (see D-17).
- **Rationale.** Six Glue runs per file was paying for ~5 minutes of cold-start overhead per ~50 KB of payload. Collapsing to two jobs cuts per-file billed-DPU-minutes by roughly 4× and removes the intermediate `clean/` parquet stage. We still satisfy the brief's explicit "PySpark **and** Python Shell jobs" requirement.
- **Trade-offs.** The single PySpark job now does more (ref join + biz rules + 6 KPIs); it must be partitioned cleanly internally to keep the code readable. The combined loader has a wider blast radius if it fails — mitigated by per-table parquet inputs, so a partial failure can be replayed for the affected table only.
- **Pushback on review.** I did **not** adopt the "write directly from PySpark to DynamoDB" recommendation. Reasons: (1) the brief mandates a separate Glue job for DynamoDB ingestion, (2) keeping the loader separate preserves a clean replay boundary — if DDB throttles, the KPI parquet remains the source of truth, (3) the cost of one Python Shell boot (~10 s, 0.0625 DPU-min ≈ $0.0001) is negligible.

## D-03-R · DynamoDB Key Swap
- **Supersedes.** D-03 partition-key choices on `genre_daily_kpi` and `top_songs_daily`.
- **Choice.**
  - `genre_daily_kpi`: **PK = `genre`, SK = `date`**. A **GSI `date_genre_index`** (PK = `date`, SK = `genre`) supports the lower-cadence "all genres for a date" pattern.
  - `top_songs_daily`: **PK = `genre`, SK = `date#rank`** (zero-padded rank — `01`, `02`, `03`).
  - `top_genres_daily`: **unchanged** (PK = `date`, SK = `rank`). Five items per partition, written once per day — no hot-partition concern and no useful inversion.
- **Rationale.** The dominant analytical query is "trend over time for genre X" (US5). With the swapped keys, this is a base-table `Query` instead of a GSI scan — better latency and no doubled storage.
- **Pushback on review.** The reviewer framed the swap as a *hot-partition* mitigation. At our v1 volumes (a few hundred KPI items written per day per genre) DynamoDB On-Demand absorbs this trivially — hot partitions are not the binding constraint. The swap is justified by **GSI elimination on the dominant query**, not by write-throttle risk. Worth recording so future agents do not over-engineer partition keys for non-existent throughput problems.

## D-11-R · Ingestion Concurrency — SQS Micro-Batch Buffering
- **Supersedes.** D-11 ("one file per execution").
- **Choice.** S3 PUT → EventBridge → **SQS** (FIFO not required) → **scheduled trigger Lambda** (every 2 minutes, or earlier if `ApproximateNumberOfMessagesVisible ≥ 20`) → **one Step Functions execution per micro-batch**. The execution receives a list of S3 keys and the PySpark job processes them as a single Spark read.
- **Rationale.** Removes the worst-case "50 files in 5 minutes triggers 50 parallel Spark cold starts" pathology. One Spark cluster amortises across many small files.
- **Trade-offs.** Adds ≤ 2 minutes of buffering latency. The brief calls for "timely" KPIs, not sub-second — 2 minutes is well within the spirit. The trigger Lambda becomes a stateful piece worth testing carefully.

## D-17 · Tier-1 Schema Validation Moves to Lambda
- **Choice.** A small Lambda (Python 3.12, 256 MB, ~5 s timeout) performs header-row + cheap shape checks. Quarantined files never touch Glue.
- **Rationale.** Lambda cold start is ~100 ms; Python Shell is ~10 s plus 1-DPU-min minimum billing. For a check that completes in milliseconds, Lambda is the right tool.
- **Trade-offs.** The Lambda owns IAM access to `raw/`, `quarantine/`, and the SNS alarm topic. Adds one more deployable to test.

## D-18 · Reference Data Stored as Parquet
- **Choice.** `users.csv` / `songs.csv` are converted to Parquet (Snappy) at ingest, registered in the Glue Catalog, and read by PySpark from Parquet — never CSV.
- **Rationale.** Column pruning, native types, faster Spark init.
- **Trade-offs.** The refresh process gains one conversion step; trivial.

## D-19 · Single PySpark Job Owns Ref-Integrity + KPI
- **Choice.** Inside the PySpark job: `streams.join(broadcast(songs), how="left")` → split into matched/unmatched DataFrames → matched feeds KPI aggregation, unmatched is written to `quarantine/ref-fail/` with a count metric. No separate Tier-2 job.
- **Rationale.** One join, one S3 read of `songs`, no temp parquet.
- **Trade-offs.** The PySpark code is denser; mitigated by clear functional decomposition and unit tests per stage.

## D-20 · IAM Wildcard Cleanup
- **Choice.** Replace every `*` action in role policies with explicit action lists. Specifically: `logs:*` → `logs:CreateLogStream`, `logs:PutLogEvents`; `states:*` → `states:StartExecution`, `states:DescribeExecution`, `states:StopExecution` (scoped to one SM ARN).
- **Rationale.** Compliance defaults + smaller blast radius if a role is compromised.

## D-21 · SAST on Python Sources
- **Choice.** Add Snyk Code (or `semgrep` if Snyk licensing is unavailable) as a CI step, gated on PR. Targets: `glue/shared/`, `glue/pyspark/`, `glue/python_shell/`, and any `lambda/` source.
- **Rationale.** Catches PII-in-logs and path-traversal smells before merge.

---

# Revisions from Architectural Review Round 2 (`.ai/review.md` §2)

> These revisions supersede any conflicting guidance in the sections above. Prior text is preserved as the historical record.

## D-22 · Trigger Lambda → EventBridge Pipes (accepted)
- **Supersedes.** D-11-R (which introduced the Trigger Lambda).
- **Context.** D-11-R replaced "one SM execution per file" with SQS buffering + a Trigger Lambda that polled SQS, drained it, and called `StartExecution`. The reviewer identified this as unnecessary custom code.
- **Choice.** Replace the Trigger Lambda entirely with **AWS EventBridge Pipes** (`aws_pipes_pipe`). Pipe source = the SQS buffer queue; target = the Step Functions state machine. Native `BatchSize = 50`, `MaximumBatchingWindowInSeconds = 120`.
- **Rationale.** EventBridge Pipes is the managed primitive designed for exactly this fan-in → target pattern. Zero Python to write, test, or package. Pipe runs are billed only when messages are processed (no empty-poll charges). Configuration lives entirely in Terraform.
- **Trade-offs.** EventBridge Pipes is a slightly newer service (GA Nov 2022); it is well-supported in the AWS provider v5+. One new IAM role (`pipe_role`) with `sqs:ReceiveMessage`/`DeleteMessage` + `states:StartExecution`.
- **Reversibility.** High — swap back by adding the Lambda and removing the Pipe resource.
- **Brief alignment.** Brief requires Step Functions for orchestration; Pipes is just the entry path, not the orchestrator.

## D-23 · Lambda S3 Range Request Tightened to 1 KB (accepted with nuance)
- **Context.** D-17 introduced the Lambda schema validator. Our sketch already used `Range="bytes=0-65535"` (64 KB). The reviewer proposes `bytes=0-1023` (1 KB).
- **Choice.** Use `Range="bytes=0-4095"` (4 KB) as the default — a middle ground. 1 KB is sufficient for ~100-column headers but can be truncated by a single very-long value in row 1. 4 KB covers even pathological headers safely. If the first newline is not found within the range, the Lambda falls back to `bytes=0-65535` and logs a `wide_header` warning.
- **Rationale.** The core principle (O(1) memory, sub-second execution) stands; the exact byte count is a guard against edge cases. Reviewed code snippet adopted verbatim except for the range value.
- **Trade-offs.** Negligible — 4 KB vs 1 KB is immeasurable in Lambda cost terms.

## D-24 · Glue PySpark Worker Type → G.025X (accepted with escalation path)
- **Context.** D-02-R set `G.1X × 4` as the PySpark worker type.
- **Choice.** Default to **`G.025X × 2`** (0.5 DPU total) with autoscaling enabled. Maximum cap raised to `G.1X × 4` for backfill runs identified by a `--run_mode=backfill` job argument.
- **Rationale.** Each `G.025X` worker has 2 vCPUs and 4 GB RAM. Broadcast-joining a ≤50 MB `songs` Parquet against a few-MB stream batch fits comfortably at this tier. For normal micro-batches of up to 50 files × ~500 rows each, 0.5 DPU is sufficient. For the historical backfill (thousands of files), the job argument escalates to `G.1X × 4` automatically.
- **Cost impact.** 87.5% reduction in compute cost per normal run: 0.5 DPU vs 4 DPU at the same rate.
- **Trade-offs.** `G.025X` is not available in all AWS regions. Must be verified before prod deployment. Fallback: `G.1X × 2`.

## D-25 · KMS Key Policy — Root-Principal Delegation (accepted)
- **Context.** Creating CMKs in Terraform while IAM roles reference the encrypted resources and the key policy references those same IAM roles produces a circular dependency.
- **Choice.** KMS key policies grant **`kms:*` to the account root principal only**. Each IAM role then gets `kms:Decrypt` + `kms:GenerateDataKey*` via its own inline or managed policy. No role ARN appears directly in any key policy.
- **Rationale.** Standard AWS IaC pattern. Decouples the KMS module from the IAM module entirely; `terraform apply` order becomes deterministic. Key control stays with the account (root can always revoke).
- **Trade-offs.** Root-principal key access means anyone with admin IAM rights can use the key — acceptable because the account is single-team; not acceptable in a multi-team org where a key-admin role should be used instead. Noted for future.
- **Reversibility.** High.

## D-26 · Boto3 `adaptive` Retry Mode on DynamoDB Writes (accepted)
- **Context.** The Python Shell loader uses `batch_writer` with default boto3 `standard` retry mode (5 attempts, fixed jitter).
- **Choice.** Configure the DynamoDB resource with `Config(retries={"mode": "adaptive", "max_attempts": 10})` in `dynamo_utils.py`.
- **Rationale.** `adaptive` mode implements a client-side token-bucket rate limiter that back-pressures before the server returns `ProvisionedThroughputExceededException`. Prevents cascading retries that worsen the throttle. Directly satisfies the brief's *robust error handling* criterion.
- **Trade-offs.** `adaptive` mode adds slight CPU overhead tracking the token bucket — negligible in a Python Shell job.

## D-28 · Simple UI Dashboard Added (not in original brief)
- **Context.** The brief does not mention a UI, but all five user stories benefit from a point-and-click interface for testing without requiring AWS console access or CLI knowledge.
- **Choice.** Vanilla HTML/CSS/JS single-page app in `ui/index.html`. No framework, no build step. Chart.js via CDN for KPI visualisation. API backed by API Gateway + Lambda in Sprint 6; mock mode for local dev.
- **Rationale.** Lowers the barrier to demonstrating the full pipeline end-to-end (file upload → pipeline status → KPI query). Maps directly to all five user stories. Vanilla HTML keeps the implementation cost low and reviewable without toolchain setup.
- **Trade-offs.** No framework = manual DOM updates. Acceptable at this scale; upgrade to React in v2 if the dashboard grows.
- **Brief alignment.** "Documentation — step-by-step documentation on setting up and running the pipeline" and "Sample queries for retrieving insights from DynamoDB" — the UI is a richer version of both.

## D-27 · VPC + S3/DynamoDB Gateway Endpoints — Stub on Day 1 (partial accept)
- **Context.** D-15 in the original plan and `terraform.md` both deferred VPC endpoints to v2.
- **Reviewer's claim.** Add endpoints on Day 1 to prevent future NAT Gateway charges.
- **Assessment.** Gateway endpoints are free, but they require a VPC and route table entries to exist. At v1, Glue and Lambda run in AWS-managed networks (no customer VPC), so endpoints have zero effect on their traffic today. Adding them requires provisioning a VPC, which is non-trivial infrastructure overhead for a benefit that is currently theoretical.
- **Choice.** Add a **`modules/vpc-stub`** Terraform module that creates a minimal VPC (one AZ, one private subnet, no NAT gateway) with S3 and DynamoDB Gateway Endpoints attached to the route table. The module is `enabled = false` by default in `dev/tfvars`; it can be enabled when any service is moved into the VPC. This way the Terraform pattern exists and is tested, but no resources are billed until needed.
- **Rationale.** The reviewer's point is sound in principle; the partial accept avoids adding live VPC infrastructure for no current benefit while keeping the path paved.
- **Trade-offs.** Slightly more Terraform module surface to maintain. Mitigated by the `enabled` flag keeping it off by default.
- **Reversibility.** High.
