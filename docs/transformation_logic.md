# Transformation Logic — KPI Computation

> Agent: **Transform**.
> Input: `data_validation.md` (clean parquet path + target dates), `dynamodb_schema.md` (target shapes).
> Output: a PySpark job spec deterministic enough that two runs against the same input produce byte-identical KPI parquet outputs.

---

## 1. KPI Catalogue (from the brief)

| # | KPI                              | Grain                | Source columns                                    |
|---|-----------------------------------|----------------------|---------------------------------------------------|
| 1 | Listen Count                      | day × genre          | streams                                           |
| 2 | Unique Listeners                  | day × genre          | streams.user_id                                   |
| 3 | Total Listening Time              | day × genre          | streams × songs.duration_ms                       |
| 4 | Average Listening Time per User   | day × genre          | (Total Listening Time) / (Unique Listeners)       |
| 5 | Top 3 Songs per Genre             | day × genre × rank   | streams × songs                                   |
| 6 | Top 5 Genres                      | day × rank           | streams × songs                                   |

## 2. Pipeline Stages (single PySpark job)

```
read clean parquet ──┐
                     ├── broadcast join with songs (track_id → track_genre, duration_ms) ──┐
                     │                                                                       │
read users (catalog) ┘   (broadcast join with users not strictly needed for KPIs; held back unless region-level KPIs are added in v2)
                                                                                            │
                                                                  ┌─────────────────────────┴─────────────────────────┐
                                                                  ▼                                                   ▼
                                                       genre_day aggregate                                  per-song & per-genre rank stages
                                                                  │                                                   │
                                                                  ▼                                                   ▼
                                                       write Parquet (Snappy)                              write Parquet (Snappy)
                                                       s3://.../kpi/genre_daily/                           s3://.../kpi/top_songs_daily/
                                                                                                          s3://.../kpi/top_genres_daily/
```

The job runs **once per execution** and writes three KPI parquet datasets, then emits a `kpi_targets` list to Step Functions for the loader Map state.

## 3. PySpark Sketch

```python
# glue/pyspark/transform_kpis.py — illustrative excerpt
import sys
from awsglue.utils import getResolvedOptions
from pyspark.sql import SparkSession, functions as F, Window

args = getResolvedOptions(sys.argv, ["clean_path", "target_dates", "run_id",
                                     "reference_bucket", "kpi_output_bucket"])
target_dates = args["target_dates"].split(",")

spark = (SparkSession.builder
         .appName(f"transform_kpis-{args['run_id']}")
         .config("spark.sql.adaptive.enabled", "true")
         .getOrCreate())

streams = spark.read.parquet(args["clean_path"])
songs   = spark.read.option("header", True).csv(f"s3://{args['reference_bucket']}/songs/")

# Derived: listen_date (UTC truncate), join key
streams = (streams
           .withColumn("listen_time", F.to_timestamp("listen_time"))
           .withColumn("listen_date", F.to_date("listen_time"))
           .filter(F.col("listen_date").isin(target_dates)))

songs = (songs
         .select(F.col("track_id"),
                 F.col("track_name"),
                 F.col("track_genre").alias("genre"),
                 F.col("duration_ms").cast("long"))
         .filter(F.col("duration_ms").between(1, 1_800_000))
         .filter(F.col("genre").isNotNull()))

enriched = (streams
            .join(F.broadcast(songs), on="track_id", how="inner"))

# ── KPI 1-4: Genre-day aggregate ───────────────────────────────────────
genre_daily = (enriched
               .groupBy("listen_date", "genre")
               .agg(
                   F.count("*").alias("listen_count"),
                   F.countDistinct("user_id").alias("unique_listeners"),
                   F.sum("duration_ms").alias("total_listening_time_ms"))
               .withColumn(
                   "avg_listening_time_per_user_ms",
                   F.col("total_listening_time_ms") / F.col("unique_listeners")))

# ── KPI 5: Top-3 songs per genre per day ───────────────────────────────
song_counts = (enriched
               .groupBy("listen_date", "genre", "track_id", "track_name")
               .agg(F.count("*").alias("plays")))
w_songs = Window.partitionBy("listen_date", "genre").orderBy(F.desc("plays"), F.asc("track_id"))
top_songs = (song_counts
             .withColumn("rank", F.row_number().over(w_songs))
             .filter(F.col("rank") <= 3))

# ── KPI 6: Top-5 genres per day ───────────────────────────────────────
w_genres = Window.partitionBy("listen_date").orderBy(F.desc("listen_count"), F.asc("genre"))
top_genres = (genre_daily
              .select("listen_date", "genre", "listen_count")
              .withColumn("rank", F.row_number().over(w_genres))
              .filter(F.col("rank") <= 5))

# ── Write Parquet (overwrite the target dates only) ───────────────────
(genre_daily
   .repartition("listen_date")
   .write.mode("overwrite")
   .partitionBy("listen_date")
   .parquet(f"s3://{args['kpi_output_bucket']}/genre_daily/"))

(top_songs
   .repartition("listen_date")
   .write.mode("overwrite")
   .partitionBy("listen_date")
   .parquet(f"s3://{args['kpi_output_bucket']}/top_songs_daily/"))

(top_genres
   .repartition("listen_date")
   .write.mode("overwrite")
   .partitionBy("listen_date")
   .parquet(f"s3://{args['kpi_output_bucket']}/top_genres_daily/"))
```

> `write.mode("overwrite") + partitionBy` with `spark.sql.sources.partitionOverwriteMode = "dynamic"` so only the target dates are overwritten — other days untouched. Setting this property is critical; default is `"static"` (wipes the whole table). Captured in `decision.md` D-05.

## 4. Determinism Guards

- **Tie-breaking** in `Window.orderBy` always includes a stable secondary key (`track_id`, `genre`). Without it, ranks can swap between runs.
- **`countDistinct` vs. `approx_count_distinct`**: use exact `countDistinct` at our volumes; HLL approximations not justified yet.
- **Timestamp parsing**: use `to_timestamp` with explicit format if locale issues arise; sample data uses ISO-like format and parses natively.

## 5. Resource Sizing

- Worker type **G.1X**, 4 workers initially. KPI of 12 k rows per file = trivial; the real bound is the cross-day recompute when a late file lands.
- **Autoscaling enabled** (`--enable-auto-scaling true`).
- Max DPU cap **10** — protects the bill from runaway broadcasts.

## 6. Failure Modes & Mitigations

| Failure                                  | Mitigation                                      |
|------------------------------------------|-------------------------------------------------|
| OOM on broadcast join                    | Songs file is small (~MB) — broadcast is safe; cap at 50 MB and fall back to shuffle if exceeded. |
| Skew (one mega-genre)                    | `spark.sql.adaptive.skewJoin.enabled = true`.   |
| Empty input after T2 drops               | Job exits successfully with `kpi_targets = []`. Loader Map state runs zero iterations. |
| S3 list consistency lag                  | Glue 4.x uses S3A with strong consistency since 2020 — non-issue. |

## 7. Output Contract → Loader

```json
{
  "kpi_targets": [
    {"kind": "genre_daily",      "source_s3": "s3://.../kpi/genre_daily/listen_date=2024-06-25/",      "table": "dev_genre_daily_kpi"},
    {"kind": "top_songs_daily",  "source_s3": "s3://.../kpi/top_songs_daily/listen_date=2024-06-25/",  "table": "dev_top_songs_daily"},
    {"kind": "top_genres_daily", "source_s3": "s3://.../kpi/top_genres_daily/listen_date=2024-06-25/", "table": "dev_top_genres_daily"}
  ]
}
```

## 8. Hand-off

- **Next agent:** Storage / Load agent.
- **They receive:** the three parquet paths above, with deterministic schemas described in `dynamodb_schema.md` §3.
