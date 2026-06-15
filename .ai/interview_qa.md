# Interview Q&A — MusicStream ETL Pipeline

Senior data engineer interview preparation. Every answer is grounded in this project's specific decisions and code.

---

## Architecture & Design

**Q: Why did you use Step Functions to orchestrate this pipeline instead of a single Lambda or an Airflow DAG?**

**Strong answer:** Step Functions gives me durable, visual state management for free — retries, error branching, and audit history without writing orchestration code. A single Lambda orchestrator would hit the 15-minute timeout for long Glue runs and lose execution state on failure. Airflow would require standing up a managed instance (MWAA costs ~$200/month minimum) for a pipeline that runs infrequently. The Step Functions Express or Standard Workflow model fits exactly: one execution per micro-batch, a clear state graph, and native integration with Lambda and Glue via `.sync` resource types that block until the job completes.

**What they're testing:** Knowledge of AWS orchestration trade-offs; whether you over-engineer or pick the right tool.

---

**Q: Why is there an SQS buffer between EventBridge and Step Functions instead of a direct trigger?**

**Strong answer:** S3 events arrive one file at a time but the Glue job is most cost-efficient when it processes a batch. SQS with a 120-second batching window accumulates up to 50 file notifications before the EventBridge Pipe fires a single Step Functions execution. Without SQS, each file upload would start its own Glue job — 50 files in a minute would spin up 50 G.1X workers. With SQS batching, those 50 files are processed in one Glue run. The SQS queue also acts as a buffer against EventBridge failures and provides the DLQ for files that couldn't be processed.

**What they're testing:** Micro-batch design thinking; cost awareness; SQS batching semantics.

---

**Q: Why is the PySpark transform a separate Glue job from the DynamoDB loader instead of one big script?**

**Strong answer:** PySpark and Python Shell are fundamentally different Glue job types. PySpark runs on a cluster with Spark workers — great for distributed joins on large datasets. Python Shell runs on a single node with standard Python — great for sequential boto3 API calls. Mixing them forces you into the more expensive PySpark environment for what is essentially a for-loop over DynamoDB writes. Separating them also allows independent retries: if DynamoDB write fails due to transient throttling, Step Functions retries only the load job, not the expensive PySpark transform.

**What they're testing:** Understanding of Glue job types; cost/responsibility separation.

---

**Q: How does your pipeline handle duplicate file uploads?**

**Strong answer:** Idempotency is enforced by the archive step, not by job bookmarks (D-10). After a successful pipeline run, the Step Functions state machine copies every valid processed file from `s3://raw/` to `s3://archive/` and then deletes it from raw. If the same file is uploaded again, Lambda validates it and the PySpark job processes it — but DynamoDB writes use `overwrite_by_pkeys=["genre", "date"]` in the batch_writer, so re-computing the same KPIs just overwrites the same items with identical values. No duplicates accumulate. Glue job bookmarks were deliberately disabled because they track state in S3 that can desync from the actual archive state during partial failures.

**What they're testing:** Idempotency reasoning; when bookmarks help vs hurt.

---

**Q: Why is reference data stored as Parquet in S3 instead of a DynamoDB lookup table?**

**Strong answer:** The PySpark job joins streams against reference data using a broadcast join — it reads the full songs and users tables into each worker's memory. Parquet is the native columnar format for Spark with zero schema inference overhead. A DynamoDB lookup from inside a Glue job would require a custom connector or per-row API calls — either extremely slow or operationally complex. The reference tables (songs, users) are small enough (tens of thousands of rows) to broadcast safely, and they change infrequently enough that a manual Parquet re-upload when they change is acceptable.

**What they're testing:** Spark broadcast join knowledge; understanding of when DynamoDB is the wrong tool.

---

**Q: How would you scale this pipeline to 10× the current data volume?**

**Strong answer:** Several levers exist. First, increase the EventBridge Pipe batch window and batch size — the current 50 files/120s would need tuning. Second, the Glue PySpark job autoscales to G.1X × 8 for backfill runs; regular runs can stay at G.1X × 2 unless data volume demands more. Third, the DynamoDB tables are on-demand mode — they scale automatically, though write throttling at burst is handled by the adaptive retry in `dynamo_utils`. Fourth, if file sizes grow significantly, the Lambda 4 KB range read (D-23) remains valid since it only reads headers. The main bottleneck at 10× would likely be the Glue DPU count — I'd profile the PySpark job with a larger sample and right-size from there.

**What they're testing:** Capacity planning; understanding of which components are the bottleneck.

---

## Data Engineering

**Q: Explain T1, T2, and T3 validation. Why is each layer necessary?**

**Strong answer:** T1 (Lambda) validates schema: are the required column headers present? This runs before Glue starts, costing microseconds instead of 90 seconds of Glue spin-up for a structurally invalid file. T2 (PySpark left-join) validates referential integrity: does every `track_id` exist in the songs table and every `user_id` in the users table? Rows that fail join to null on the reference side are quarantined. T3 (PySpark business rules) validates domain logic: is `play_duration_seconds > 0`? Is `listen_time` a parseable timestamp? Is the user not flagged as a bot? Each layer catches different failure modes. Collapsing them would mean Glue always runs for structurally invalid files, or Lambda would need full file access to check referential integrity.

**What they're testing:** Validation layer design thinking; understanding of cost vs thoroughness trade-off.

---

**Q: What does the 4 KB range read in Lambda actually buy you?**

**Strong answer:** It buys a 1000× reduction in Lambda data transfer cost and latency for a common class of failures. A typical stream file is 5–20 MB. The CSV header is at most a few hundred bytes. Downloading the full file to check six column names wastes 99.9% of the transfer. The AWS SDK `GetObject` with `Range: bytes=0-4095` reads only the first 4 KB, which always contains the complete header row of any CSV file in this schema. The cost saving is most significant at high file volumes — 1,000 invalid files per day costs $0.0002 with range reads vs $2.00 with full downloads.

**What they're testing:** Practical cost optimization; S3 Range request knowledge.

---

**Q: Explain the left-join approach for T2 referential integrity. Why not an inner join?**

**Strong answer:** An inner join silently drops rows that don't match — KPI aggregates would be wrong and there'd be no signal that data was lost. A left join keeps all stream rows and produces `null` on the reference columns for any `track_id` or `user_id` not in the reference tables. After the join, I filter rows where the reference key is null into a separate quarantine write — they go to S3 with enough context to diagnose why they failed. The valid rows continue to T3 business rules. This means data quality problems are visible (quarantine bucket fills up, alarm fires) without blocking the valid majority from being processed.

**What they're testing:** Data quality awareness; the difference between silent failure and observable failure.

---

**Q: What is the PySpark partitionBy gotcha you hit during your smoke test, and how did you fix it?**

**Strong answer:** When PySpark writes a DataFrame partitioned by `listen_date` using `df.write.partitionBy("listen_date")`, Spark removes `listen_date` from the Parquet file's column data — the value lives only in the S3 directory path (`listen_date=2024-06-25/part-00000.parquet`). When the Glue Python Shell job reads those Parquet files using PyArrow's `ParquetFile`, it gets raw bytes from the file — there is no Hive metastore to inject the partition column back. So every row's `listen_date` was `None`. The DynamoDB batch writer then tried to write a row with `date=None` as the sort key, and `overwrite_by_pkeys=["genre","date"]` raised `KeyError: 'date'`. The fix was `_partition_values_from_key(key)`: parse `key=value` segments from the S3 object key path and inject them into each row dict before DynamoDB write.

**What they're testing:** Deep understanding of Spark partitioning; ability to debug cross-component issues.

---

**Q: What is a broadcast join and when is it safe to use?**

**Strong answer:** A broadcast join sends a copy of the smaller DataFrame to every Spark executor, avoiding a shuffle of the larger DataFrame. It is safe when the smaller DataFrame fits in each executor's memory — typically under 200 MB with default settings. In this project, the songs and users reference tables are small enough (tens of thousands of rows) to broadcast safely, and D-29 confirmed that songs has no duplicate `track_id` values, so the join won't fan out rows unexpectedly. If reference data grew to millions of rows, I'd switch to a sort-merge join and repartition strategically.

**What they're testing:** Spark optimization knowledge; when broadcast joins cause OOM.

---

**Q: Why do you set `spark.sql.sources.partitionOverwriteMode` to `dynamic`?**

**Strong answer:** Without this setting, writing to a partitioned Parquet table in `overwrite` mode truncates the entire table — every partition, not just the ones in the current write. That would wipe the KPI data for all historical dates every time the job runs. With `dynamic`, Spark only overwrites the specific partitions included in the current DataFrame. This is critical for a pipeline that appends new daily partitions while preserving existing history.

**What they're testing:** Spark write mode awareness; a common production footgun.

---

**Q: How do the 6 KPIs relate to each other computationally?**

**Strong answer:** All six KPIs are derived from the same cleaned DataFrame — the output of T2 + T3 filtering. The computation fans out from one source:
1. `genre_daily_kpi`: group by `(genre, listen_date)` → sum plays, sum duration, count unique users, average completion rate, etc.
2. `top_songs_daily`: group by `(genre, listen_date, track_id)` → rank songs by play count within each (genre, date) window → keep top 3
3. `top_genres_daily`: group by `(listen_date, genre)` → rank genres by total plays per date → keep top 5

The three aggregations share the same source `df` — no re-reading from S3. They write to three separate Parquet paths (`kpi/genre_daily/`, `kpi/top_songs_daily/`, `kpi/top_genres_daily/`) that the Python Shell job then reads.

**What they're testing:** Ability to explain Spark aggregation and window functions; data lineage understanding.

---

## DynamoDB & NoSQL

**Q: Walk me through the DynamoDB table designs and what access patterns they support.**

**Strong answer:** The design follows the single-table principle for each table — keys match the primary query pattern exactly. `genre_daily_kpi` has PK=`genre`, SK=`date`: a range query with `genre = :g AND date BETWEEN :start AND :end` returns the full trend for one genre. A GSI with PK=`date`, SK=`genre` covers the reverse pattern (all genres for a given date). `top_songs_daily` has PK=`genre`, SK=`date_rank` (e.g., `2024-06-25#01`): `begins_with(date_rank, '2024-06-25')` returns all songs for that genre on that date in rank order. `top_genres_daily` has PK=`date`, SK=`rank` (number): `date = :d` with `ScanIndexForward=false, Limit=5` returns the top 5 genres. Every access pattern is a key lookup — no scans.

**What they're testing:** DynamoDB data modeling; single-table design awareness; avoiding scan anti-patterns.

---

**Q: Why is the sort key for `top_songs_daily` the string `"2024-06-25#01"` instead of just rank as a number?**

**Strong answer:** DynamoDB's `begins_with` condition only works on string sort keys. If the SK were `rank` as a number, I'd need to know the exact ranks to query (get rank 1, 2, 3 separately — three API calls). By composing `date#rank` as a string, a single query with `begins_with(date_rank, '2024-06-25')` returns all three songs for that genre on that date in one request, sorted by rank lexicographically (01, 02, 03). Zero-padding the rank ensures lexicographic sort matches numeric sort for ranks 1–99.

**What they're testing:** DynamoDB sort key design patterns; `begins_with` query semantics.

---

**Q: What is adaptive retry and how is it different from simple exponential backoff?**

**Strong answer:** Simple exponential backoff waits a fixed doubling interval between retries regardless of how throttled DynamoDB actually is. Adaptive retry adjusts the retry interval based on the actual `UnprocessedItems` count returned by `BatchWriteItem` — if 20% of items were unprocessed, the next batch is smaller and the wait is proportional to the throttling signal. In `dynamo_utils.batch_write()`, the function loops on `UnprocessedItems` rather than raising an exception, gradually draining the unprocessed set. This is the AWS-recommended pattern for batch writes to on-demand tables during burst periods.

**What they're testing:** DynamoDB throttling handling; knowledge beyond "just add a sleep."

---

**Q: How would you add a new KPI without breaking existing DynamoDB consumers?**

**Strong answer:** DynamoDB items are schema-flexible — I can add a new attribute to existing items without a migration. The process: (1) add the new KPI computation to `transform_kpis.py`, (2) add the new attribute to `shape_for_dynamo()` in `dynamo_utils`, (3) the next pipeline run writes the new attribute alongside existing ones. Existing consumers that don't read the new attribute are unaffected. If the new KPI requires a new table, I'd add it to the `dynamodb-kpi-tables` Terraform module and to the Python Shell job. The only breaking change risk is renaming an existing attribute — which I'd avoid.

**What they're testing:** Schema evolution in NoSQL; understanding of DynamoDB's schemaless model.

---

## Infrastructure & DevOps

**Q: Walk me through what happens when you run `terraform apply` on this project.**

**Strong answer:** Terraform reads the module graph in `infra/envs/dev/main.tf` and builds a dependency DAG. It applies in dependency order: KMS keys first (everything else needs their ARNs), then S3 buckets and DynamoDB tables, then IAM roles (need S3 and DDB ARNs), then Lambda and Glue jobs (need IAM role ARNs and script bucket names), then Step Functions (needs Lambda and Glue job names), then EventBridge Pipe (needs SQS and SM ARNs), then Monitoring (needs everything else). Terraform state is stored in S3 with a DynamoDB lock table to prevent concurrent applies. The output is ~63 resources created. After apply, Glue scripts must be synced to S3 manually because Terraform doesn't manage the script content, only the S3 bucket.

**What they're testing:** Terraform execution model; dependency resolution; state management.

---

**Q: How is the Glue shared library deployed and why is it a Python wheel?**

**Strong answer:** The shared library (`glue/shared/`) contains utilities used by both the PySpark job and the Python Shell job: `dynamo_utils`, `logging_utils`, `s3_utils`, `schemas`. It's packaged as a Python wheel (`python -m build --wheel`) and uploaded to the scripts S3 bucket. Both Glue jobs reference it via `--extra-py-files s3://scripts/glue/shared/shared-0.1.0-py3-none-any.whl`. A wheel is the correct format because Glue can install it on the worker without needing to call pip at runtime — reducing job startup time. `boto3` and `pyarrow` are excluded from the wheel's dependencies because they're already present in the Glue runtime, and re-downloading them at job start causes pip compilation failures.

**What they're testing:** Python packaging knowledge; Glue library deployment patterns.

---

**Q: Why is there no API Gateway between the Streamlit UI and DynamoDB?**

**Strong answer:** The Streamlit dashboard runs on the operator's local machine, which already has AWS credentials configured (the same profile used for Terraform). API Gateway would add latency on every DynamoDB query, cost per million requests, a Lambda behind it, and a deployment artifact to manage — for zero benefit. API Gateway makes sense when the consumer is an external user who cannot hold AWS credentials, or when you need rate limiting, auth, or a stable public endpoint. This is an internal ops tool for a single operator. Direct boto3 is simpler and faster. (D-28-R)

**What they're testing:** Whether you over-engineer; knowing when API Gateway is and isn't warranted.

---

**Q: How would you promote this from dev to prod? What would you change?**

**Strong answer:** I'd create `infra/envs/prod/` mirroring dev with these changes: `force_destroy = false` and `deletion_protection = true` on all tables and buckets; tighten the wildcard IAM ARNs (currently `lambda_validator_arn = "*"` to break circular deps) using a two-phase apply or separate `aws_iam_policy` resources; use a dedicated prod alarm email; set `pyspark_worker_type = "G.1X"` (same as dev since G.025X isn't available). The CD workflow (`.github/workflows/cd-prod.yml`) already gates `terraform apply` behind a GitHub environment manual approval step — I'd configure that environment with a required reviewer. I'd also create the prod state bucket via a second bootstrap apply before the first prod deploy.

**What they're testing:** Environment promotion thinking; security hardening awareness.

---

**Q: What would break if someone accidentally ran `terraform destroy` in prod? How is it prevented?**

**Strong answer:** All 63 resources would be destroyed — S3 buckets (with all data), DynamoDB tables (all KPI history), Lambda, Glue jobs, Step Functions, everything. S3 bucket `force_destroy = false` in prod would protect against accidental bucket deletion when the bucket is non-empty. DynamoDB `deletion_protection = true` would make Terraform fail if it tries to delete a table. These are the two most critical safeguards. Additionally, the CI/CD workflow requires manual approval before `terraform apply` in prod — no `--auto-approve` — and only runs from `main` after a semver tag push, not from arbitrary branches.

**What they're testing:** Production protection mechanisms; understanding of what's actually at risk.

---

## Debugging & Incident Response

**Q: Walk me through a real failure you debugged in this project.**

**Strong answer:** During the smoke test, the DynamoDB load Glue job failed with exit code 2 — "Command failed." I pulled the CloudWatch log group for the Python Shell job. The error was `KeyError: 'date'` inside `batch_write`, which meant `shape_for_dynamo` was returning a row where the `date` key was missing or `None`. I traced it back: the KPI Parquet files were written by PySpark with `partitionBy("listen_date")`, which removes `listen_date` from the file's column data — it's encoded in the S3 key path (`listen_date=2024-06-25/`). The Python Shell was reading raw Parquet bytes via PyArrow, which only sees the file contents, not the path. Every row's `listen_date` was `None`. Fix: parse `key=value` segments from the S3 object key path in `_partition_values_from_key()` and inject them into each row before DynamoDB write.

**What they're testing:** Debugging discipline; cross-component reasoning; ability to read logs.

---

**Q: How would you know the pipeline is failing at 3am without looking at the console?**

**Strong answer:** The monitoring module (Sprint 7) deploys four CloudWatch alarms: (1) SQS DLQ depth > 0, (2) Step Functions `ExecutionsFailed` > 0, (3) Lambda error count > 0, (4) Glue job state FAILED/ERROR/TIMEOUT via EventBridge rule → SNS. All alarms notify the `dev-pipeline-alarms` SNS topic, which sends email to the configured alarm address. The CloudWatch dashboard `dev-etl-overview` shows SF execution counts, Lambda invocations, and DLQ depth in one view. After the monitoring Terraform apply, the SNS email subscription must be manually confirmed — AWS sends a confirmation link. Without that confirmation step, alarms publish to SNS but no email is sent.

**What they're testing:** Operational maturity; monitoring design; knowing the subscription-confirmation gotcha.

---

**Q: A DynamoDB write is failing with `ProvisionedThroughputExceededException`. What do you do?**

**Strong answer:** The tables use on-demand capacity mode, so this exception is transient — DynamoDB is scaling up. First, I'd check the CloudWatch DynamoDB metrics for consumed write capacity and throttled requests to confirm it's a burst issue, not a sustained overload. The adaptive retry in `dynamo_utils.batch_write()` handles transient throttling by looping on `UnprocessedItems` with backoff — it should recover without manual intervention. If the throttling is sustained (table consistently hitting its auto-scaling ceiling), I'd switch from on-demand to provisioned mode with auto-scaling configured for the expected write rate, or reduce the batch write concurrency in the Python Shell job.

**What they're testing:** DynamoDB capacity mode knowledge; reading CloudWatch metrics; not panicking.

---

**Q: Files in the quarantine bucket are piling up. What's your process?**

**Strong answer:** First, I'd query the quarantine bucket structure to understand the failure pattern — files are prefixed by run_id and error type. Then I'd check the corresponding CloudWatch log entries for those run_ids to find the exact validation failure: T1 schema failure (wrong columns), T2 referential integrity (unknown track_id or user_id), or T3 business rule (zero duration, future date, bot flag). If it's T2 failures from unknown track_ids, I'd check whether the reference Parquet in the reference bucket is outdated and re-upload a fresh songs/users Parquet. If it's a systematic T3 issue, I'd review the upstream data producer. For replay, I'd copy the quarantine files back to `raw/` after fixing the root cause — the pipeline is idempotent so re-processing is safe.

**What they're testing:** Operational process for data quality incidents; end-to-end pipeline knowledge.

---

## Security

**Q: Why is there a KMS key per data classification layer?**

**Strong answer:** Separate keys for data-at-rest S3/KMS (`kms_data`) and DynamoDB (`kms_ddb`) allow independent key rotation, different key policies for each service, and audit logs that distinguish between S3 decryption events and DynamoDB decryption events in CloudTrail. If the DynamoDB key is compromised, rotating it doesn't invalidate S3 data and vice versa. In a production setup I'd add a third key for the scripts bucket (immutable artifacts, lower rotation frequency) and potentially a fourth for CloudWatch Logs.

**What they're testing:** KMS key management best practices; separation of concerns.

---

**Q: Explain the least-privilege principle as applied to IAM in this project.**

**Strong answer:** Every IAM role in this project has an explicit `Action` list — no wildcards like `s3:*` or `dynamodb:*`. The Glue PySpark role can read from `raw/`, `reference/`, and write to `kpi/` and `quarantine/` — not to the archive bucket or scripts bucket. The Lambda validator can only read from raw and write to quarantine — not trigger Glue or Step Functions directly. IAM condition keys restrict by resource ARN where possible. The one deliberate exception is the `lambda_validator_arn = "*"` in the Step Functions IAM policy — this breaks a Terraform circular dependency and is documented as a known gap to tighten before production.

**What they're testing:** IAM policy design; understanding of circular dependency trade-offs.

---

**Q: Why is `user_name` never logged, even in debug log lines?**

**Strong answer:** `user_name` is PII — personally identifiable information. Logging it would mean it appears in CloudWatch Logs, which is accessible to anyone with `logs:FilterLogEvents` permission on the log group — potentially a much broader audience than DynamoDB table access. CloudWatch Logs also has a longer default retention than application data, creating a PII data store where none was intended. The project standard (in `docs/security.md` and `CLAUDE.md`) explicitly bans logging `user_name` and `user_country`. All log lines use `user_id` (an opaque hash, not a real name) if user context is needed for debugging.

**What they're testing:** PII/data privacy awareness; GDPR/compliance mindset.
