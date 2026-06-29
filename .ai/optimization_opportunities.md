# Senior Engineer Review & Cloud Optimization Opportunities

This document outlines senior-level optimizations for the MusicStream ETL pipeline to reduce operational costs, improve performance, and transition the current architecture into a production-grade, real-world deployment.

---

## 1. DynamoDB Read Cost Optimization: Application-Level Caching

### **The Problem:**
* The Streamlit dashboard (`ui/app.py`) is designed as an operations tool. Streamlit is a reactive framework; it re-runs the entire script on every user interaction (e.g., clicking a tab, changing a slider, or adjusting a dropdown).
* Under our current setup, each rerun queries or scans the live DynamoDB tables (`dev_genre_daily_kpi`, etc.) using `boto3`. 
* With **PAY_PER_REQUEST (On-Demand)** billing, you are billed per Read Capacity Unit (RCU) request. High dashboard usage or repetitive user interaction will trigger hundreds of redundant database reads, driving up costs unnecessarily and adding database query latency.

### **The Solution:**
* Implement **Streamlit Application-Level Caching** using `@st.cache_data`.
* Since the daily streaming KPIs are only computed when the Glue ETL pipeline completes (typically once a day or on a schedule), the database contents are static between pipeline runs.
* We can cache the DynamoDB query results (e.g. for a TTL of 1 hour or 1 day):
  ```python
  @st.cache_data(ttl=3600)  # Cache query results for 1 hour
  def get_genre_daily_kpi_cached(genre, start_date, end_date):
      return query_genre_daily_kpi(genre, start_date, end_date)
  ```
* **Impact:** 
  * **Cost:** Redundant queries hit memory instead of DynamoDB, reducing dashboard read costs by **99%**.
  * **Latency:** Read latency drops from 100-200ms (database network call) to sub-millisecond (RAM lookup), making the dashboard feel incredibly snappy.

---

## 2. Infrastructure & Compute Cost Optimizations

### **Optimization A: DynamoDB Billing Mode Transition (On-Demand vs. Provisioned)**
* **Current State:** Tables use `PAY_PER_REQUEST`.
* **Recommendation:** For production, transition to **Provisioned Capacity with Auto Scaling**.
* **Rationale:** On-Demand billing is great for developer sandboxes or highly unpredictable, spiky workloads. However, at steady-state production traffic, On-Demand is **7x more expensive** than provisioned capacity. By switching to provisioned capacity and enabling AWS Auto Scaling (e.g., target utilization of 70%), DynamoDB automatically adjusts RCU/WCU limits during batch runs and scales down during idle hours, saving up to **70% of database costs**.

### **Optimization B: Glue Auto Scaling & Dynamic Worker Allocation**
* **Current State:** Glue PySpark job is hardcoded to use 2 `G.1X` workers.
* **Recommendation:** Enable **Glue Auto Scaling** in the job configuration.
* **Rationale:** AWS Glue 3.0+ dynamically scales the cluster size (adding or removing executors) based on the Spark execution plan. 
  * During the initial header load and validation, Glue will run on a single worker.
  * During the heavy shuffle joins and aggregations, Glue will scale out to more workers.
  * This ensures we only pay for the exact DPU-seconds needed, rather than paying for a fixed size cluster that sits idle during parts of the Spark job.

### **Optimization C: S3 Storage Class Lifecycle Policies**
* **Current State:** Raw, quarantine, and archive files are stored in S3 Standard storage indefinitely.
* **Recommendation:** Implement **S3 Lifecycle Rules**:
  * Transition raw CSV files in S3 Archive to **Glacier Instant Retrieval** after 30 days.
  * Permanently delete raw CSVs in Archive after 90 days.
  * Automatically transition historical Parquet KPIs to **S3 Standard-IA (Infrequent Access)** after 90 days.
* **Rationale:** Storage costs accumulate. Moving cold CSV files to Glacier reduces S3 storage costs by **60% to 80%** without losing access to historical data.

### **Optimization D: Step Functions Billing (Standard vs. Express Workflows)**
* **Current State:** Step Functions uses a **Standard Workflow**.
* **Recommendation:** Transition to **Express Workflows** if the execution time is guaranteed to be under 5 minutes.
* **Rationale:** Standard Workflows are billed per state transition ($\$$$0.025 per 1,000 transitions). Express Workflows are billed based on execution duration and memory consumption. For short, high-frequency ETL pipelines, Express Workflows are up to **20x cheaper**.
* *Note:* Standard is currently required because the Glue PySpark job takes ~2 minutes (including cluster start). If we optimize Glue job startup or replace Glue with ECS Fargate tasks, switching to Express would yield massive cost savings.

---

## 3. Performance & Code Optimizations

### **Optimization E: PySpark Partition Pruning**
* **Current State:** PySpark loads the entire songs and users Parquet directories for joining.
* **Recommendation:** Filter reference datasets in Spark *before* the join by passing date ranges or matching criteria (e.g. only loading active users/songs if the reference data is timestamped).
* **Rationale:** Reduces the memory footprint of the Broadcast Join, ensuring we don't hit Out-Of-Memory (OOM) errors on Spark executors as reference datasets grow.

### **Optimization F: SQS Batch Size Tuning**
* **Current State:** SQS window is 120s or 50 records.
* **Recommendation:** Increase SQS batch window to 300s (5 minutes) for low-priority non-realtime runs, or decrease to 30s for high-priority streams.
* **Rationale:** Allows fine-tuning the trade-off between pipeline latency (how fast data gets to DynamoDB) and Glue DPU cost (aggregating more files per run).
