# Architecture Decisions — MusicStream ETL Pipeline

This document records every binding architectural decision, the alternatives that were rejected, and what was learned. Decisions are numbered to match the `docs/decision.md` record.

---

## D-02-R: Single Glue Python Shell Job for All Three DynamoDB Tables

**Problem:** Three DynamoDB tables need to be populated from three Parquet datasets after every pipeline run. Should each table get its own Glue job, or should one job handle all three?

**Options Considered:**
1. Three separate Glue Python Shell jobs — one per table
2. One job that loads all three tables sequentially
3. Parallel Lambda writes (no Glue)

**Decision:** One Glue Python Shell job loads all three tables.

**Rationale:** The three tables are always populated together from the same pipeline run. Splitting into three jobs would triple the job startup cost (~30s per Glue Python Shell cold start), require Step Functions to fan out and join three parallel branches, and add three points of partial-failure with complex compensating logic. All three datasets are small (single-day KPIs, hundreds of rows); sequential writes complete in well under the 15-minute Glue timeout.

**Trade-offs:**
- All-or-nothing writes per run (if the job fails mid-way, some tables may be partially updated) — mitigated by Step Functions retry and idempotent `overwrite_by_pkeys` in batch_write
- Cannot independently retry a single table — acceptable for this volume

---

## D-03-R: DynamoDB Key Design

**Problem:** The downstream Streamlit UI needs three access patterns: (1) trend for one genre over a date range, (2) top 3 songs for a genre on a specific date, (3) top 5 genres on a specific date. DynamoDB requires the key design to match the access pattern.

**Options Considered:**
1. Single table with GSI overloading (all three query types in one table)
2. Three separate tables, each designed for its primary access pattern
3. RDS/Aurora for flexible querying

**Decision:** Three DynamoDB tables with keys designed for the primary access pattern of each.

| Table | PK | SK | Primary Query |
|-------|----|----|---------------|
| `dev_genre_daily_kpi` | `genre` (S) | `date` (S) | Genre trend over date range — `KeyConditionExpression: genre = :g AND date BETWEEN :start AND :end` |
| `dev_top_songs_daily` | `genre` (S) | `date_rank` (S) e.g. `2024-06-25#01` | Top 3 songs for a genre on a date — `KeyConditionExpression: genre = :g AND begins_with(date_rank, :date)` |
| `dev_top_genres_daily` | `date` (S) | `rank` (N) | Top 5 genres on a date — `KeyConditionExpression: date = :d` + `ScanIndexForward: false, Limit: 5` |

A GSI `date_genre_index` on `genre_daily_kpi` (PK=`date`, SK=`genre`) covers the secondary "all genres for a date" pattern without a full table scan.

**Rationale:** DynamoDB performs best when the key design matches the access pattern exactly. Forcing three patterns into one table with GSI overloading adds query complexity and wastes RCUs on projection.

**Trade-offs:**
- Three tables to manage vs one — acceptable since Terraform manages them all
- RDS would allow ad-hoc SQL but adds VPC complexity, connection management, and ~10× cost at this scale

---

## D-10: No Glue Job Bookmarks

**Problem:** Glue job bookmarks track which files have been processed to prevent reprocessing. Should bookmarks be enabled on the PySpark transform job?

**Options Considered:**
1. Enable Glue job bookmarks
2. Rely on archive directory layout for idempotency (processed files are moved to `archive/`, not present in `raw/`)

**Decision:** Bookmarks disabled. Idempotency is enforced by the archive step.

**Rationale:** The Step Functions state machine's final step copies each valid key to `s3://archive/` and deletes it from `s3://raw/`. The PySpark job only receives keys that were passed through by the Lambda validator in the current batch — it never scans the raw bucket itself. Bookmarks would add state (stored in S3) that could desync if a partial failure left files in raw but the bookmark recorded them as processed.

**Trade-offs:**
- If the archive step fails after transform but before delete, the next pipeline run will reprocess the same file — mitigated by DynamoDB `overwrite_by_pkeys` making DynamoDB writes idempotent
- Bookmarks would be required if the job scanned raw/ directly, but it doesn't — keys are injected by Step Functions

---

## D-17: Lambda T1 Schema Gate

**Problem:** The Glue PySpark job takes 60–90s to spin up workers. Should schema validation happen in Lambda before starting Glue, or should Glue handle all validation?

**Options Considered:**
1. Lambda validates schema before Glue starts
2. Glue job validates schema as part of the transform (fail fast inside Glue)
3. No schema validation — trust all files

**Decision:** Lambda performs T1 schema gate. Files with invalid headers or missing required columns are quarantined before Glue starts.

**Rationale:** If schema validation is done inside Glue, an invalid file still burns 60–90s of G.1X worker time and incurs Glue DPU costs (~$0.44/DPU-hour × 2 workers). With a Lambda gate, an invalid file is quarantined in <1s for ~$0.0000002. At high file volumes, this is a significant cost saving.

**Trade-offs:**
- Lambda can only read the first 4 KB of the file (D-23 range read) — it validates headers but not every row
- Row-level validation (referential integrity, business rules) still happens in Glue (T2, T3)

---

## D-18: Reference Data Stored as Parquet

**Problem:** Songs and users reference data needs to be broadcast-joined against the raw streams data in PySpark. What format should reference data be stored in?

**Options Considered:**
1. CSV files in S3
2. Parquet files in S3
3. DynamoDB lookup tables
4. Hardcoded Python dictionaries

**Decision:** Parquet in S3 (`s3://reference/songs/`, `s3://reference/users/`).

**Rationale:** PySpark reads Parquet natively with columnar pushdown. A broadcast join of a small Parquet file is fast and zero-cost. CSV would require Spark to infer schema on every read and is slower for large reference datasets. DynamoDB lookups from Spark would require a custom connector and per-row API calls.

**Trade-offs:**
- Reference data must be pre-converted from CSV to Parquet before first deployment (a manual step that caused one of the smoke-test bugs — see bug #4 below)
- Updates to reference data require re-uploading Parquet; there is no streaming update path

**Smoke-test bug #4:** During the first sandbox deploy, songs and users were uploaded as CSV. The PySpark job failed with "not a Parquet file" because Glue reads the entire S3 prefix and expects Parquet. Fix: convert locally with pandas/pyarrow, delete CSVs, upload only Parquet.

---

## D-19: Left-Join for T2 Referential Integrity

**Problem:** Some stream records may reference a `track_id` or `user_id` not present in the reference tables (songs, users). Should these records be dropped silently, fail the job, or be quarantined?

**Options Considered:**
1. Inner join — drops unmatched rows silently
2. Left join — keeps unmatched rows, routes to quarantine
3. Fail the job on any unmatched row

**Decision:** Left join. Rows with `null` on the join side (no match in reference) are written to the quarantine bucket instead of being silently dropped.

**Rationale:** Silently dropping rows would make data quality problems invisible — KPI numbers would be wrong with no signal. Failing the entire job on one bad row is too aggressive for a streaming workload where occasional data quality issues are expected. Left-join + quarantine gives visibility without blocking valid rows.

**Trade-offs:**
- Quarantine bucket requires a monitoring process to review and replay rows after reference data is updated
- Slightly more complex PySpark logic than an inner join

---

## D-22: EventBridge Pipe (SQS → Step Functions)

**Problem:** SQS receives batches of S3 event notifications. Something must consume the SQS messages and trigger a Step Functions execution with the batch as input. What should play this role?

**Options Considered:**
1. EventBridge Pipe (native SQS→Step Functions connector)
2. Lambda consumer that reads SQS and calls `StartExecution`
3. Direct EventBridge rule → Step Functions (no SQS buffer)

**Decision:** EventBridge Pipe with `BatchSize=50`, `MaximumBatchingWindowInSeconds=120`.

**Rationale:** EventBridge Pipe natively supports SQS as a source and Step Functions as a target, with built-in batching. It removes the need for a Lambda function that exists only to forward messages, reducing cost and operational surface area.

**Trade-offs:**
- Known gap: the Pipe delivers raw SQS message records (an array with `messageId`, `body`, etc.) to Step Functions, but the ASL `ParseInput` state expects `$.detail.bucket.name` from a parsed EventBridge event. This works when the SM is invoked directly (smoke test method), but fails via the full Pipe→SM path (smoke-test bug #5). **Fix required before production:** add a Pipe input transformer or Lambda enrichment that extracts bucket/keys from the SQS body before passing to the SM.

---

## D-23: 4 KB Range Read in Lambda T1

**Problem:** The Lambda validator needs to read enough of each uploaded CSV to validate the header row. Should it download the entire file or just the header?

**Options Considered:**
1. Download the full file — guarantees the header is present, allows row-count validation
2. HTTP Range request for the first 4 KB — cheap, covers any realistic header row
3. Use S3 Select to query just the header

**Decision:** `GetObject` with `Range: bytes=0-4095` (4 KB range read).

**Rationale:** CSV headers fit in well under 1 KB. A 4 KB range read costs the same Lambda invocation fee but transfers ~1000× less data than downloading a typical 10 MB stream file. S3 Select would require the file to be valid CSV first (catch-22 for validation).

**Trade-offs:**
- Cannot validate row count or row-level types — that is T2/T3's job in Glue
- Extremely long column names could theoretically overflow 4 KB — not a realistic concern for this schema

---

## D-24: Worker Type G.1X (G.025X Fallback)

**Problem:** The Glue PySpark job needs to be sized for cost efficiency. G.025X is the smallest Glue worker type and cheapest. Is it available?

**Options Considered:**
1. G.025X × 2 (minimum) — cheapest, ~$0.11/DPU-hour
2. G.1X × 2 — standard, ~$0.44/DPU-hour
3. G.2X × 2 — large, ~$0.88/DPU-hour

**Decision:** G.1X × 2. G.025X is not available for batch Glue jobs in eu-west-1.

**Rationale:** G.025X is only available for Glue Streaming jobs in some regions. The dev plan specified G.025X (D-24) but it failed at apply time. G.1X is the smallest available for batch. For backfill runs, the job autoscales up to G.1X × 8.

**Trade-offs:**
- G.1X costs ~4× more per run than G.025X would — for daily micro-batches on a dev account this is negligible, but matters at production scale
- Regional availability should be verified before deploying to a new region

---

## D-25: KMS Root-Principal Delegation Only

**Problem:** KMS key policies must grant access to AWS services (Lambda, Glue, S3) and IAM roles. How should the key policy be structured?

**Options Considered:**
1. Grant each IAM role ARN explicitly in the key policy
2. Root-principal delegation: key policy grants `arn:aws:iam::ACCOUNT_ID:root`, then IAM policies control access

**Decision:** Root-principal delegation only. Key policy grants the account root; IAM policies on roles grant `kms:Decrypt`, `kms:GenerateDataKey` etc.

**Rationale:** Granting IAM role ARNs directly in the key policy creates a Terraform circular dependency: the key needs the role ARN, the role needs the key ARN, neither can be created first. Root delegation breaks the cycle.

**Trade-offs:**
- Slightly less fine-grained than per-role key policies — mitigated by IAM policy conditions
- **Smoke-test bug #1:** EventBridge service principal (`events.amazonaws.com`) cannot use a CMK via root delegation because it is not an IAM principal — it is an AWS service. The SQS queues were CMK-encrypted; EventBridge could not deliver messages. Fix: switch both SQS queues to `sqs_managed_sse_enabled = true` (AWS-managed SSE), which EventBridge can use without a key policy grant.

---

## D-26: Adaptive boto3 Retry in DynamoDB Writes

**Problem:** DynamoDB `BatchWriteItem` can return `UnprocessedItems` when throughput is exceeded. How should the DynamoDB loader handle this?

**Options Considered:**
1. Ignore unprocessed items — data loss
2. Raise an exception on any unprocessed items — job fails unnecessarily
3. Adaptive retry: loop on unprocessed items with exponential backoff

**Decision:** Adaptive retry via `dynamo_utils.batch_write()`. The function loops on `UnprocessedItems` with jittered exponential backoff until all items are written or the retry budget is exhausted.

**Rationale:** DynamoDB on-demand mode can still throttle during burst writes from a cold start. Adaptive retry is the AWS-recommended pattern and handles this transparently without over-provisioning throughput.

**Trade-offs:**
- Longer write time under heavy throttling — acceptable for micro-batch (not latency-sensitive)
- All Glue and UI code must use `dynamo_utils.get_ddb_table()` — never instantiate `boto3.resource("dynamodb")` directly

---

## D-28-R: No API Gateway Between Streamlit and DynamoDB

**Problem:** The Streamlit dashboard needs to query DynamoDB. Should there be an API Gateway + Lambda layer between the UI and DynamoDB?

**Options Considered:**
1. Streamlit → API Gateway → Lambda → DynamoDB
2. Streamlit → boto3 → DynamoDB directly

**Decision:** Direct boto3 call. No API Gateway.

**Rationale:** The Streamlit app runs locally on the operator's machine. It already has AWS credentials (same profile used for Terraform). Adding API Gateway would add latency, cost, and a deployment artifact that adds no value — the UI is not publicly exposed. API Gateway makes sense when the consumer is an external client that cannot hold AWS credentials.

**Trade-offs:**
- The dashboard cannot be deployed as a public web app without adding an auth/API layer — acceptable for an internal ops tool

---

## Smoke-Test Bug Summary

Five bugs were found and fixed during the first end-to-end sandbox smoke test. All fixes are committed in PR #2 (`fix/smoke-test-bugs`).

| # | Bug | Root Cause | Fix |
|---|-----|-----------|-----|
| 1 | EventBridge couldn't deliver to SQS | SQS queues were CMK-encrypted; `events.amazonaws.com` service principal not in key policy (root delegation only per D-25) | Switch SQS queues to `sqs_managed_sse_enabled = true` |
| 2 | Glue PySpark job read wrong reference bucket | ASL template had `"${raw_bucket}"` instead of `"${reference_bucket}"` for `--reference_bucket` argument | Fix ASL template; add `reference_bucket_name` variable to SM module |
| 3 | DynamoDB load failed with KeyError: 'date' | PySpark `partitionBy("listen_date")` removes `listen_date` from Parquet file bytes; Python Shell read raw bytes without partition context | Add `_partition_values_from_key()` to parse `key=value` from S3 path; inject into each row |
| 4 | Glue PySpark AnalysisException: not a Parquet file | Reference data uploaded as CSV; Glue reads entire prefix and expects Parquet (D-18) | Convert CSV → Parquet locally with pandas/pyarrow; delete CSV; upload Parquet only |
| 5 | SM failed at ParseInput via Pipe | EventBridge Pipe delivers raw SQS record array; ASL expects `$.detail.bucket.name` | Workaround: invoke SM directly for smoke test. **Known gap** — needs Pipe input transformer for production |
