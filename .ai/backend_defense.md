# Project Defense: Data Engineering & Backend Architecture

This guide prepares you to defend the data engineering decisions, code design, and data processing logic of the MusicStream ETL pipeline during your technical review or interview.

---

## 1. Core Architecture Overview
The backend is an **event-driven, micro-batch ETL pipeline** designed to process user streaming behavior data arriving at unpredictable intervals.

### The Flow:
1. **Raw CSV Ingestion:** Streams CSV files land in S3 raw bucket.
2. **SQS Buffering:** Buffered via SQS queue over a 120-second window to prevent Glue DPU spin-up thrashing.
3. **EventBridge Pipe:** Batches the SQS messages, runs a Lambda enrichment step (`dev-pipe-enrichment`) to extract metadata, and triggers Step Functions.
4. **T1 Schema Gate (Lambda):** Validates basic structural schema using an S3 Range Request (reading only the first 4 KB of headers).
5. **T2 & T3 Validation + Aggregation (Glue PySpark):** Checks referential integrity against reference datasets (songs, users) and filters out bot traffic/malformed durations. Computes 6 daily genre-level KPIs and outputs them as partitioned Parquet.
6. **Loader (Glue Python Shell):** Reads the output Parquet files and loads them into three distinct DynamoDB KPI tables using boto3 batch-write with adaptive retry.
7. **Archival (Step Functions native):** Copies raw files to S3 archive and deletes them from raw to enforce idempotency.

---

## 2. Key Data Engineering Decisions & Defenses

### Q1: Why use AWS Glue PySpark and Glue Python Shell separately? Why not just one PySpark job?
* **Defense:** **Cost optimization and compute-matching.** 
  * PySpark is designed for heavy distributed join and aggregation workloads across multi-node clusters. Running a Glue PySpark job costs a minimum of 2 DPUs (~$0.44/hour per DPU, billed in seconds, with a 1-minute minimum).
  * Instantiating a Spark session just to check if a CSV header is correct (Validation) or to perform sequential `boto3` DynamoDB API writes (Loading) is extremely wasteful. Spark startup takes ~60–90 seconds of dead-time billing.
  * By splitting them, we use a lightweight **Lambda** for T1 validation (takes ~1 second, costing fractions of a cent), **PySpark** *only* for the CPU/Memory intensive joins and aggregations, and a cheap **Glue Python Shell** (0.0625 DPU) for loading to DynamoDB. This reduces our total AWS run cost by over 60%.

### Q2: Explain your 3-Tier Data Validation Strategy (T1, T2, T3)
We designed a progressive validation model to catch errors as early as possible before wasting budget on downstream compute:
1. **Tier 1 (Schema Gate - Lambda):** Checks if the file is accessible, headers are valid and not duplicated, data rows exist, and the key partition date matches the record timestamps. If a file fails here, it is quarantined immediately. We never spin up a Glue cluster for a garbage file.
2. **Tier 2 (Referential Integrity - PySpark Left-Join):** We broadcast-join the streams against the reference datasets (`songs` and `users`). Instead of doing an `inner join` (which silently drops bad records), we do a `left join` and filter rows where the reference key is `null`. These are sent to S3 quarantine (`ref-fail/`), and the clean rows proceed. This keeps data quality issues fully visible.
3. **Tier 3 (Domain Business Rules - PySpark):** Filters out anomalies: track durations exceeding 30 minutes, or bot streaming activity (defined as a user streaming the same track > 1,000 times in a single day).

### Q3: How did you implement the 4 KB range request in Lambda, and why?
* **Defense:** S3 objects can be large (10MB+). Downloading the entire file into a Lambda container just to check the first line (headers) wastes network bandwidth and memory, causing higher Lambda execution times and costs. By passing `Range="bytes=0-4095"` to the SDK `get_object` call, we fetch only the first 4 KB. This always contains the CSV header and first data row. If a header is abnormally wide, we handle it gracefully with a fallback range request, but 99% of the time, the 4 KB read completes in under 100ms.

### Q4: Why did you model DynamoDB with three separate tables instead of a Single-Table Design?
* **Defense:** **Disjoint access patterns and analytical querying ergonomics.**
  * In classic OLTP apps, Single-Table Design is preferred to fetch related entities in a single round-trip query. However, our downstream consumers (BI tools, Streamlit dashboards) query these KPIs independently (e.g. "Get Trend of Pop genre", "Get Top 3 songs of Rock", "Get Top 5 genres today").
  * Putting them in one table would require complex Index Overloading (GSI partition/sort keys) and require downstream analysts to write obscure query filters.
  * Three tables allow us to size and scale read/write capacity individually. For example, `top_genres_daily` only holds 5 items per day and needs negligible capacity, whereas `top_songs_daily` holds 339 items per day and needs higher write capacity.

### Q5: How do you handle idempotency and prevent duplicate records in DynamoDB?
* **Defense:**
  * **Deterministic Primary Keys:** We enforce that table keys are derived directly from the business identifiers:
    * `genre_daily_kpi`: Partition Key = `genre`, Sort Key = `date`
    * `top_songs_daily`: Partition Key = `genre`, Sort Key = `date_rank` (e.g. `2024-06-25#01`)
    * `top_genres_daily`: Partition Key = `date`, Sort Key = `rank`
  * **Dynamic Partition Overwrite:** The PySpark job runs in `dynamic` partition overwrite mode. It overwrites only the S3 Parquet partitions for dates present in the current input batch.
  * **Upsert Writes:** When loading to DynamoDB, the Python Shell job uses `PutItem` (via boto3 `batch_writer`). If the pipeline re-runs a batch for `2024-06-25`, the loader simply overwrites the exact records for that date. No duplicate records or double-counting can occur.
  * **Post-Execution Archival:** Once the Step Functions run succeeds, the S3 raw files are moved to the S3 archive bucket and deleted from raw. This ensures they are never re-processed on subsequent SQS batch arrivals.

### Q6: How does the PySpark job handle large reference datasets like `songs` safely?
* **Defense:** We use a **Broadcast Join** (`F.broadcast(songs)`). The songs dataset is relatively small (tens of thousands of rows, under 10MB in Parquet). By broadcasting the reference dataframe, Spark replicates it to the memory of all executor nodes. This converts a costly distributed shuffle join into a highly efficient local map-side join, drastically speeding up execution.

---

## 3. Key Backend Code Artifacts to Highlight
* **`glue/shared/schemas.py`:** Authoritative schemas for streams, songs, and users, ensuring Python Shell, Lambda, and PySpark use the exact same validation criteria.
* **`glue/shared/dynamo_utils.py`:** Implements `batch_write` with customized chunking (25 items max per DynamoDB batch write limit) and utilizes the `boto3` client with adaptive retries to handle capacity throttling.
* **`glue/shared/logging_utils.py`:** Structurizes JSON logging across all jobs. Ensures that PII fields like `user_name` or `user_country` are stripped out before printing logs to comply with GDPR/CCPA regulations.
