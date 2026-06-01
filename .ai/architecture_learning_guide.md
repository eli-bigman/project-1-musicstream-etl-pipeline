<!-- ai-ignore -->

# Master Architecture & Learning Guide
### NSS Phase 2 · Project 1 — Streaming Analytics ETL Pipeline

> **For human eyes only.** This file is a learning and interview-prep resource.
> The `<!-- ai-ignore -->` tag at the top prevents coding agents from ingesting it during development.
> Every claim below is verified against the actual source files and data.

---

## 1. The Big Picture — What, Why, and How

### What the system does

A music streaming service records every time a user listens to a track. Those listen events arrive as CSV files dropped into cloud storage at unpredictable times — a burst of files might land at midnight, then nothing for hours.

This pipeline picks up those files automatically, checks them for quality, joins them with reference data about songs and users, computes six business metrics (KPIs), and stores the results in a fast database so a business analyst can query them within minutes.

**The actual data we work with** (confirmed from source files):

| File | Columns | What it is |
|------|---------|------------|
| `streams*.csv` | `user_id`, `track_id`, `listen_time` | One row = one listening event. e.g. user `26213` listened to track `4dBa8T7oDV9WvGr7kVS4Ez` at `2024-06-25 17:43:13` |
| `songs.csv` | `track_id`, `track_name`, `artists`, `duration_ms`, `track_genre`, + 17 audio features | Reference catalogue — tells us each track's genre and length |
| `users.csv` | `user_id`, `user_name`, `user_age`, `user_country`, `created_at` | Reference catalogue — tells us who each user is |

### The six KPIs we compute (directly from the brief)

All six are computed at **day × genre** grain:

1. **Listen Count** — how many times tracks in a genre were played
2. **Unique Listeners** — how many distinct users played a track in that genre
3. **Total Listening Time** — sum of `duration_ms` for all plays
4. **Average Listening Time per User** — total time ÷ unique listeners
5. **Top 3 Songs per Genre** — most-played tracks, ranked 1–3
6. **Top 5 Genres** — most-listened genres across all users, ranked 1–5

### The business use case

A product manager at a streaming company wants to know: *"Which genres are people listening to the most right now, and which specific songs are trending today?"* Without this pipeline, answering that question requires a data analyst to run queries manually. With it, the answer is in DynamoDB and available to any application in under 50 ms.

### The Agentic Approach

"Agentic" means the system reacts to events by itself — no human presses a button. Here is how it works:

1. A producer (could be an app, a script, or another service) drops a CSV file into S3.
2. S3 fires an event: *"a new object was created."*
3. That event cascades automatically through EventBridge → SQS → EventBridge Pipe → Step Functions, which kicks off the entire processing chain without any human involvement.
4. The AI-assisted part of this project is the **agentic planning and documentation methodology** (stick-holding relay described in `docs/agentic_workflow.md`) — each phase of implementation produces a written hand-off artefact so the next development session picks up exactly where the last one left off.

---

## 2. AWS Component Breakdown — The Learning Hub

### S3 (Simple Storage Service)

**Analogy.** S3 is like a giant filing cabinet in the cloud. Each "drawer" is a bucket. Each "folder" is a prefix (S3 doesn't have real folders — it fakes them using `/` in key names). Every file you put in it is stored safely and durably — AWS promises 99.999999999% (11 nines) durability.

**Technical role in this pipeline.** Five buckets serve five distinct purposes:

| Bucket | Purpose |
|--------|---------|
| `musicstream-dev-raw` | Landing zone. Producers drop CSV files here. Path: `streams/yyyy=2024/mm=06/dd=25/file.csv` |
| `musicstream-dev-reference` | Holds `users.parquet` and `songs.parquet` — the lookup tables Spark reads every run |
| `musicstream-dev-scripts` | Stores the Glue Python scripts and the shared wheel file that jobs load at runtime |
| `musicstream-dev-archive` | Processed files are moved here on success — same path as raw, different bucket |
| `musicstream-dev-quarantine` | Failed files land here with a `_reason.json` sidecar explaining why they failed |

**How it communicates securely.** S3 does not call other services. Instead, other services (Glue, Lambda) are granted `s3:GetObject` / `s3:PutObject` permissions via IAM roles. No usernames or passwords — AWS IAM handles all authentication.

---

### EventBridge (Event Bus)

**Analogy.** EventBridge is a smart post office. When something happens in your AWS account (like a file being dropped in S3), EventBridge receives a notification and, based on rules you define, routes that notification to the right destination.

**Technical role.** When a `.csv` file lands in `raw/streams/`, S3 sends an `Object Created` event to EventBridge. A rule filters for that exact pattern (bucket = `musicstream-dev-raw`, key prefix = `streams/`, suffix = `.csv`) and forwards the event to an SQS queue.

**How it communicates securely.** EventBridge uses an IAM role (`eventbridge_role`) that has permission only to put messages on the specific SQS queue. It cannot access any other resource.

---

### SQS (Simple Queue Service)

**Analogy.** SQS is like a waiting room. If many files arrive at once, they all sit in the queue patiently. The next component picks them up in batches at its own pace, preventing an avalanche of simultaneous processing jobs.

**Technical role.** Acts as a buffer between EventBridge (which fires for every single file) and Step Functions (which should process files in efficient batches). Instead of launching a new pipeline execution per file — which would cause 50 concurrent Spark jobs if 50 files arrive in 2 minutes — SQS holds the messages until the EventBridge Pipe drains them as a batch of up to 50.

**How it communicates securely.** The SQS queue has a **Dead Letter Queue (DLQ)** — a second queue that catches messages that failed to be processed more than 5 times. An alarm fires when the DLQ depth > 0. The EventBridge Pipe role has `sqs:ReceiveMessage` + `sqs:DeleteMessage` only on this specific queue.

---

### EventBridge Pipes

**Analogy.** EventBridge Pipes is a direct conveyor belt between two services. It removes the need for a custom Lambda function to poll the queue, batch messages, and call Step Functions. AWS manages the belt; you just configure the speed.

**Technical role.** The Pipe connects the SQS buffer queue (source) directly to the Step Functions state machine (target). It is configured with `BatchSize = 50` and `MaximumBatchingWindowInSeconds = 120` — meaning it waits up to 2 minutes to collect up to 50 messages, then fires one state machine execution with a list of S3 keys as input.

**Why this replaces a Lambda.** A custom "trigger Lambda" would require writing Python code to handle SQS visibility timeouts, batch deletion, and error handling — all of which the Pipe does natively with zero custom code.

---

### AWS Lambda

**Analogy.** Lambda is a vending machine. You put in a request, it runs a specific function, and it shuts down. You only pay for the few milliseconds it runs. There is no server sitting idle waiting for work.

**Technical role.** One Lambda function: `dev-validate-schema`. It receives a list of S3 file keys, downloads only the **first 4 KB** of each file (using an HTTP Range Request), reads the header row, and checks that all required columns (`user_id`, `track_id`, `listen_time`) are present. Invalid files are moved to quarantine immediately — before any expensive Spark job starts.

**Why 4 KB, not the whole file?** The streams files can be large. Downloading the entire file just to check the header wastes memory and time. The header fits in the first few hundred bytes; 4 KB is a safe ceiling even for very wide CSV headers.

---

### AWS Glue

**Analogy.** Glue is a managed data factory. You give it Python or Spark code, tell it how many workers to use, and it runs the code on a cluster it provisions, manages, and shuts down for you. No EC2 instances to set up or patch.

**Technical role — two job types used:**

**Job 1: `transform_kpis` (PySpark, G.025X × 2 workers)**
- Reads the validated raw CSV files from S3.
- Reads `songs.parquet` from the reference bucket (confirmed: `track_id`, `track_name`, `track_genre`, `duration_ms` are the key columns).
- Does a **broadcast join**: the songs table (~few MB) is sent to every worker in full, avoiding a slow shuffle join across the network.
- Applies business rules: drops rows where `duration_ms` is outside 1–1,800,000 ms (30 min cap), drops rows with null genre.
- Rows in the stream that don't match any song in the catalogue are written to `quarantine/ref-fail/` as evidence.
- Computes the six KPIs using PySpark's `groupBy`, `agg`, and windowed `row_number()`.
- Writes three Parquet datasets to S3 (Snappy-compressed), one per KPI family.

**Job 2: `load_dynamodb` (Python Shell, 1 DPU)**
- Reads the three KPI Parquet datasets.
- Writes items to three DynamoDB tables using `batch_writer` (up to 25 items per API call — DynamoDB's maximum).
- Uses boto3 `adaptive` retry mode: if DynamoDB throttles, the client slows itself down before the server errors out.

**How Glue gets its code.** A Python wheel (`shared-X.Y.Z-py3-none-any.whl`) is uploaded to the scripts S3 bucket. Both jobs load it at startup via `--extra-py-files`. This wheel contains shared utilities: `logging_utils`, `s3_utils`, `dynamo_utils`, `schemas`.

---

### AWS Step Functions

**Analogy.** Step Functions is a conductor in an orchestra. It doesn't play any instruments itself — it coordinates which instruments play when, handles mistakes (a violin goes out of tune → retry it), and knows when the piece is finished.

**Technical role.** The state machine defines the exact sequence and branching logic:

```
ParseInput
    → ValidateSchema (Lambda)
         ├── invalid keys → quarantine files → SNS alarm → Fail
         └── valid keys →
              TransformAndCompute (Glue PySpark)
                   → LoadDynamoDB (Glue Python Shell)
                        → ArchiveBatch (S3 CopyObject + DeleteObject per key)
                             → Success
```

Every Glue task uses `.sync` integration — Step Functions waits for the Glue job to finish before moving to the next step. If a step fails, `Catch` blocks route to `HandleFailure` → SNS alarm → quarantine → `Fail` state.

**Retry logic (actual values from the docs):**
- Concurrent runs exceeded on Glue: retry 5 times, starting at 60 seconds, doubling each time.
- General task failures: retry 1–3 times at 30 seconds.
- Schema-invalid files: no retry — immediately quarantine.

---

### Amazon DynamoDB

**Analogy.** DynamoDB is like a super-fast index card system. Each card (item) is identified by a unique combination of a Partition Key and Sort Key. When you ask for card `rock / 2024-06-25`, you get it in microseconds — DynamoDB doesn't scan every card, it goes straight to the right shelf.

**Technical role — three tables (verified against `dynamodb_schema.md`):**

**Table 1: `dev_genre_daily_kpi`**
| Key | Value | Example |
|-----|-------|---------|
| PK: `genre` (String) | e.g. `"rock"` | The genre |
| SK: `date` (String) | e.g. `"2024-06-25"` | The day |
| Attributes | `listen_count`, `unique_listeners`, `total_listening_time_ms`, `avg_listening_time_per_user_ms`, `updated_at` | The four genre-level KPIs |

> **Why PK=genre, not PK=date?** The dominant analyst query is: *"How did rock perform over the last 30 days?"* With PK=genre, this is a single `Query` call. With PK=date, it would require 30 separate `GetItem` calls or an expensive GSI. This key choice was explicitly revised in `decision.md` D-03-R after architectural review.

**Table 2: `dev_top_songs_daily`**
| Key | Value | Example |
|-----|-------|---------|
| PK: `genre` (String) | e.g. `"pop"` | |
| SK: `date_rank` (String) | e.g. `"2024-06-25#01"` | Zero-padded so sort is lexicographically correct |
| Attributes | `track_id`, `track_name`, `plays` | |

**Table 3: `dev_top_genres_daily`**
| Key | Value | Example |
|-----|-------|---------|
| PK: `date` (String) | e.g. `"2024-06-25"` | |
| SK: `rank` (Number) | `1` through `5` | |
| Attributes | `genre`, `listen_count` | |

**Billing mode: PAY_PER_REQUEST.** No capacity planning needed. DynamoDB scales automatically and you pay per read/write operation — ideal when traffic is unpredictable.

---

### AWS KMS (Key Management Service)

**Analogy.** KMS is a locksmith that creates and manages master keys. Whenever S3 stores a file or DynamoDB stores an item, it asks KMS to encrypt the data using a key that KMS controls. You never see the actual encryption key — only KMS does.

**Technical role.** Customer-managed CMKs (keys you own, not AWS-owned) encrypt: all five S3 buckets, all three DynamoDB tables, CloudWatch Logs, SNS topic, and SQS queues.

**Key policy pattern (D-25).** The key policy grants `kms:*` to the AWS account root only. Each service role then has `kms:Decrypt` + `kms:GenerateDataKey*` in its IAM policy. This avoids a circular dependency in Terraform where the key policy would need to reference IAM roles that haven't been created yet.

---

### Amazon CloudWatch

**Analogy.** CloudWatch is the health monitor of your system — like a hospital's vital-signs display. It collects logs, tracks metrics, and sets off alarms when something goes wrong.

**Technical role.** Three layers:

1. **Logs** — Every Glue job emits JSON log lines with `ts`, `level`, `run_id`, `stage`, `event`, `count`. Stored in `/aws/glue/jobs/${job-name}`. Retention: 14 days (dev), 90 days (prod).
2. **Metrics** — Custom metrics via Embedded Metric Format: `RowsDropped`, `DropRate`, `LateArrival`, `KpiItemsWritten`, `KpiLoadLatencyMs`.
3. **Alarms** — Five alarms trigger SNS notifications: pipeline execution failed, file landed in quarantine, drop rate > 5%, DynamoDB write throttled, Glue job timed out.

---

### Amazon SNS (Simple Notification Service)

**Analogy.** SNS is a megaphone. When an alarm fires, it shouts the alert to everyone subscribed — an email address, a Slack webhook via Chatbot, or another Lambda function.

**Technical role.** One topic (`etl-ops`). Step Functions' `HandleFailure` state publishes to this topic when a pipeline execution fails. CloudWatch alarms also publish here. Subscribers (email, Slack) are configured in Terraform.

---

### Streamlit (UI)

**Analogy.** Streamlit is like a Python script that draws a web page. You write Python, and it automatically renders sliders, charts, tables, and buttons in a browser.

**Technical role.** A multi-page dashboard in `ui/`:
- **Pipeline page** — upload a CSV, watch the stage tracker (Lambda → PySpark → Python Shell → Archive), see items written to DynamoDB.
- **KPI Dashboard page** — pick a date and genre, see bar charts of listen counts, top-5 genres table, top-3 songs table, genre detail metrics.

**Key architectural choice.** Streamlit calls `boto3` directly against DynamoDB using the same AWS credentials as Terraform — no API Gateway, no Lambda in between. This removes an entire service layer from the architecture.

---

## 3. Data Flow & Lifecycle

Walk through the journey of a single row: `user_id=26213, track_id=4dBa8T7oDV9WvGr7kVS4Ez, listen_time=2024-06-25 17:43:13`.

```
STEP 1 — Landing
Producer drops streams1.csv into:
s3://musicstream-dev-raw/streams/yyyy=2024/mm=06/dd=25/streams1.csv

STEP 2 — Event routing (milliseconds)
S3 → EventBridge (Object Created event)
EventBridge rule matches: bucket=raw, prefix=streams/, suffix=.csv
Message goes to SQS buffer queue

STEP 3 — Batching (up to 2 minutes)
SQS collects up to 50 messages
EventBridge Pipe drains the queue → fires one Step Functions execution
Input: { "bucket": "musicstream-dev-raw", "keys": ["streams/yyyy=2024/.../streams1.csv"] }

STEP 4 — Schema Validation (Lambda, ~500ms)
Lambda downloads first 4 KB of streams1.csv
Confirms header = ["user_id", "track_id", "listen_time"] ✓
Checks partition prefix matches first-row date ✓
Returns: { "valid_keys": ["streams/.../streams1.csv"], "invalid_keys": [], "detected_dates": ["2024-06-25"] }

STEP 5 — Transform & Enrich (Glue PySpark, ~2 min)
Reads streams1.csv: 11,346 rows (confirmed from file)
Reads songs.parquet from reference bucket
Broadcast join: match track_id=4dBa8T7oDV9WvGr7kVS4Ez → genre="acoustic", duration_ms=230666
Rows with no song match → written to quarantine/ref-fail/
Filter: duration_ms must be between 1 and 1,800,000 ms ✓ (230,666 ms = 3.8 min, valid)
Computes aggregates:
  - genre_daily: { genre="acoustic", date="2024-06-25", listen_count=N, unique_listeners=M, ... }
  - top_songs: { genre="acoustic", date_rank="2024-06-25#01", track_name="Comedy", plays=412, ... }
  - top_genres: { date="2024-06-25", rank=1, genre="pop", listen_count=8421 }
Writes three Parquet files to s3://musicstream-dev-raw/kpi/...

STEP 6 — DynamoDB Load (Glue Python Shell, ~30s)
Reads KPI Parquets
Batches up to 25 items per API call (DynamoDB maximum)
PutItem with overwrite: same key = update, not duplicate
Our row's contribution is now visible as part of the acoustic genre KPI

STEP 7 — Archival (Step Functions native, ~1s)
CopyObject: streams1.csv → s3://musicstream-dev-archive/streams/yyyy=.../streams1.csv
DeleteObject: removes from raw bucket
Raw bucket is now empty for this file ✓

STEP 8 — Consumption
Business analyst opens Streamlit UI
Selects date=2024-06-25, genre=acoustic
Streamlit calls: dynamodb.Table("dev_genre_daily_kpi").query(PK="acoustic", SK="2024-06-25")
Result returned in <50ms
```

**Where data is secured at each stage:**
- In transit: TLS (all AWS service calls use HTTPS by default)
- At rest in S3: SSE-KMS (KMS CMK)
- At rest in DynamoDB: KMS CMK
- PII exposure: `user_name` and `user_country` from `users.csv` are **never written to DynamoDB or logs** — only the aggregate counts are stored

---

## 4. Architectural Decisions & "Why This, Not That"

### Decision 1: Serverless vs. Provisioned (Servers)

**What serverless means.** A provisioned server (like an EC2 instance) runs 24/7 and you pay for it whether it does work or not. A serverless service (Lambda, Glue, DynamoDB On-Demand, Step Functions) only exists — and only charges you — when it is actively doing work.

**Why we chose serverless.** Files arrive at *unpredictable intervals*. If we used a provisioned server, it would sit idle most of the time, wasting money. With serverless, the cost scales to exactly the workload:

| Workload | Serverless cost | Provisioned server cost |
|----------|----------------|------------------------|
| 0 files today | ~$0 | ~$50/day (EC2 + RDS) |
| 1,000 files today | ~$9 (at ~$0.009/batch) | ~$50/day |

**The trade-off.** Serverless services have **cold start latency** — Glue PySpark takes ~30–60 seconds to provision a cluster before processing starts. A provisioned cluster starts instantly. For this use case (business metrics updated within 10 minutes), the cold start is acceptable.

---

### Decision 2: G.025X Workers vs. G.1X Workers (Cost vs. Capacity)

**What a DPU is.** A Data Processing Unit (DPU) is Glue's billing unit. One DPU = 4 vCPUs + 16 GB RAM. AWS bills per DPU-hour.

**The original design** used `G.1X × 4` workers = 4 DPUs. The architectural review identified this as over-provisioned for our data size (a few MB per batch).

**The revised design** uses `G.025X × 2` = 0.5 DPU total. Each `G.025X` worker has 2 vCPUs + 4 GB RAM. Our broadcast join (songs file ~5 MB) and KPI aggregations fit comfortably.

**Cost impact:** 4 DPU → 0.5 DPU = **87.5% cost reduction** on every normal batch run. Autoscaling escalates to `G.1X × 8` automatically for backfill runs with thousands of files.

**The trade-off.** If someone uploads a very large backfill file, `G.025X` might OOM (run out of memory). Mitigated by the `--run_mode=backfill` argument that bumps the worker tier automatically.

---

### Decision 3: EventBridge Pipes vs. Custom Trigger Lambda (Simplicity vs. Control)

**The problem.** SQS doesn't natively start Step Functions — you need something to drain the queue and call `StartExecution`.

**Option A: Custom Lambda.** Write Python code to poll SQS, handle visibility timeouts, delete messages after processing, batch them, and call Step Functions. That's ~100 lines of infrastructure glue code to test, deploy, and maintain.

**Option B: EventBridge Pipes.** A managed AWS feature — 12 lines of Terraform configures a Pipe from SQS to Step Functions with native batching. Zero custom code.

**Why we chose Pipes.** Zero maintenance surface. The code that doesn't exist can't have bugs.

**The trade-off.** Less flexibility — if we needed complex logic (e.g. filter messages by content before dispatching), a Lambda would be necessary. For our use case (all CSV files in the queue go to the same state machine), Pipes is sufficient.

---

### Decision 4: DynamoDB Key Design (Access Speed vs. Flexibility)

**The original design** had `genre_daily_kpi` with PK=`date`, SK=`genre`. Querying "how did rock perform over 30 days?" required a GSI — a secondary index that duplicates data and costs extra storage + write capacity.

**The revised design** swaps the keys: PK=`genre`, SK=`date`. Now the trend query is a native base-table `Query` with `SK BETWEEN "2024-05-26" AND "2024-06-25"`. The GSI is used only for the "all genres on a date" pattern (lower cadence).

**The lesson.** In DynamoDB, the key design is the most important architectural decision. Unlike relational databases (SQL), you can't add indexes freely — every GSI costs extra storage and write capacity. Design your keys around your most frequent, most latency-sensitive query.

---

## 5. Terraform 101 — Infrastructure as Code

### What Terraform does

**Analogy.** Terraform is like a building blueprint combined with a construction crew. You write a description of what AWS resources you want (the blueprint), and Terraform figures out how to build them in the right order, detects what already exists, and only changes what needs changing.

Without Terraform: you click through the AWS Console, and there is no record of what you clicked. Two developers can end up with different environments. You can't reproduce it.

With Terraform: the entire AWS environment is described in text files. Anyone with the files and the right AWS credentials can build an identical environment with one command.

### The State File — Why It Matters

**Analogy.** The state file (`terraform.tfstate`) is Terraform's memory. When Terraform creates an S3 bucket named `musicstream-dev-raw`, it writes "I created a bucket with ARN `arn:aws:s3:::musicstream-dev-raw`" into the state file. Next time you run `terraform plan`, it compares your code against the state file to know what changed.

**Why it's critical.** Without the state file, Terraform doesn't know what already exists. It would try to create everything again — and fail, because you can't create a bucket that already exists.

**How we protect it.** The state file is stored in an S3 bucket (`musicstream-tfstate`) with:
- Versioning enabled (recover from accidental overwrites)
- A DynamoDB lock table (`musicstream-tfstate-lock`) that prevents two people from running `terraform apply` simultaneously
- KMS encryption at rest

This bootstrap stack is created once manually before any other Terraform runs.

### Module Structure

**Analogy.** A Terraform module is like a prefabricated room. Instead of specifying every brick and wire, you say "I want a kitchen module" and pass in the dimensions. The module handles the details.

**Our eight modules and what each builds:**

```
infra/modules/
├── s3-data-lake/          → Creates all 5 S3 buckets with encryption + lifecycle rules
├── iam-roles/             → Creates all 5 IAM roles with least-privilege policies
├── dynamodb-kpi-tables/   → Creates 3 DynamoDB tables with correct key schemes
├── glue-jobs/             → Creates 2 Glue jobs (PySpark + Python Shell) with correct DPU sizing
├── step-functions/        → Creates the state machine, reads ASL from a template file
├── eventbridge-pipes/     → Creates the SQS→StepFunctions Pipe with batch config
├── sqs-buffer/            → Creates the buffer queue + DLQ
└── vpc-stub/              → Creates a minimal VPC + Gateway Endpoints (disabled by default)
```

**Variables and Outputs.** Each module declares `variable` blocks (inputs) and `output` blocks (what it exposes to the outside). For example, `s3-data-lake` outputs `raw_bucket_arn`, which `iam-roles` uses to build a least-privilege policy that only allows access to that specific bucket — not all buckets.

**Environment promotion.** `infra/envs/dev/` and `infra/envs/prod/` are identical in structure but have different `terraform.tfvars` files. The same module code builds both environments. This means a bug fixed in `dev` is guaranteed to also be fixed in `prod` — there is no separate "prod codebase" that can drift.

---

## 6. Interview & Review Prep — Q&A

---

### Q1: "Why did you use Step Functions for orchestration instead of just having Lambda call Glue directly?"

**Answer:**

"Great question. Lambda calling Glue directly would work for simple pipelines, but it creates problems at scale. First, if we need conditional logic — like branching to a quarantine path when validation fails — that logic would have to live in Lambda code, making it harder to visualise and debug. Second, Glue PySpark jobs can take 2–3 minutes. Lambda has a 15-minute maximum, so we'd need careful timeout management.

Step Functions gives us a visual representation of every execution — I can open the console and see exactly which stage failed and why. It handles retries with configurable backoff, it has native `.sync` integration with Glue that waits for job completion, and every execution is recorded in history. It's the right tool for multi-step, conditional workflows with human-readable state."

---

### Q2: "The brief says 'real-time pipeline' but you described it as micro-batch. Is that a problem?"

**Answer:**

"The brief uses 'real-time' to mean *timely* — KPIs available within minutes of data arrival, not hours. It doesn't mean true streaming at the event level.

The data itself arrives as batch CSV files, not as individual events. True streaming with Kinesis would require the producers to send individual events, which the brief doesn't specify. The SQS buffering + EventBridge Pipes architecture I've designed processes a new batch within 2 minutes of arrival — that satisfies the 'unpredictable intervals' and 'timely computation' requirements from the brief without the operational complexity of a streaming platform.

If the business requirement shifted to sub-second KPIs, I'd add Kinesis Data Streams as the ingestion layer — I've explicitly noted that as a deferred v2 decision in `decision.md` D-15."

---

### Q3: "How do you ensure that re-processing the same file doesn't double-count plays?"

**Answer:**

"This is the idempotency question. We handle it at two levels.

First, the PySpark job uses `spark.sql.sources.partitionOverwriteMode = dynamic` when writing Parquet. This means it only overwrites the date partitions present in the current input batch — other dates are untouched. Running the same file twice produces the same Parquet output, not doubled data.

Second, the DynamoDB loader uses `batch_writer` with `overwrite_by_pkeys` set to the primary key columns. DynamoDB `PutItem` is a full overwrite — putting the same item twice results in one item, not two.

The practical recovery procedure is: if something went wrong, copy the original CSV back to the raw bucket and let the pipeline run again. The result will be identical to the first successful run."

---

### Q4: "Why is the DynamoDB Partition Key for `genre_daily_kpi` set to `genre` and not `date`?"

**Answer:**

"DynamoDB's key design should match the most frequent, most latency-sensitive access pattern. I identified two access patterns:

1. *Trend query*: 'How did rock perform over the last 30 days?' — this is run regularly by analysts and needs to be fast.
2. *Daily snapshot*: 'What were all genres on 2024-06-25?' — this is a dashboard refresh, lower cadence.

With PK=genre and SK=date, the trend query is a single base-table `Query` call using `SK BETWEEN :start AND :end` — one API call, fast. With PK=date, this same query would require a Global Secondary Index, which doubles storage costs and adds write capacity overhead.

For the daily snapshot pattern, I added a GSI (`date_genre_index`) with PK=date. Since it's lower cadence, routing it through a GSI is a reasonable trade-off to avoid paying for GSI storage on the primary access pattern."

---

### Q5: "What would happen if someone uploaded a malformed CSV — say, with a missing `track_id` column?"

**Answer:**

"The validation Lambda catches it immediately in Tier 1 — the header check. It reads the first 4 KB of the file, splits the header row on commas, and checks that `user_id`, `track_id`, and `listen_time` are all present. If `track_id` is missing, the Lambda returns it in `invalid_keys`.

The Step Functions state machine then runs a Map state that copies those invalid files to the quarantine bucket with a sidecar file called `_reason.json`. That JSON contains the run ID, the specific validation check that failed, and a timestamp.

No Glue job ever runs for that file — we save the DPU costs of a Spark cluster startup for a file that was never worth processing. An SNS alarm fires, so the ops team gets an email within seconds. The recovery procedure is in `human.md`: fix the upstream producer, correct the file, copy it back to the raw bucket, and the pipeline re-runs it automatically."

---

*End of document.*
