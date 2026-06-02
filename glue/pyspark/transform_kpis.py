"""Glue PySpark 4.0 job: T2 ref-integrity + T3 business rules + 6 KPI aggregations.

Decisions:
  D-02-R  Single PySpark job owns ref-integrity and KPI compute.
  D-18    Reference data is Parquet (not CSV).
  D-19    Left-join T2 — unmatched rows → quarantine/ref-fail/; no separate job.
  D-24    G.025X × 2 workers (autoscales for backfill via --run_mode=backfill).
  D-29    songs Parquet has no duplicate track_ids — no dedup needed.

Writes three partitioned Parquet datasets:
  s3://<raw_bucket>/kpi/genre_daily/
  s3://<raw_bucket>/kpi/top_songs_daily/
  s3://<raw_bucket>/kpi/top_genres_daily/

Returns to Step Functions:
  {"kpi_parquet_root": "s3://.../kpi/", "target_dates": ["2024-06-25", ...]}
"""

import json
import sys

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql import Window
from pyspark.sql import functions as F

# shared wheel provides get_logger (--extra-py-files)
try:
    from shared.logging_utils import get_logger
except ImportError:
    # Fallback when running unit tests outside Glue
    import logging

    class _FallbackLogger:
        def info(self, msg, **kw): logging.info(msg + " " + str(kw))
        def warning(self, msg, **kw): logging.warning(msg + " " + str(kw))
        def error(self, msg, **kw): logging.error(msg + " " + str(kw))

    def get_logger(run_id, stage):  # noqa: F811
        return _FallbackLogger()


REQUIRED_ARGS = [
    "JOB_NAME",
    "valid_keys",       # JSON array of s3 keys (raw CSV)
    "bucket",           # raw S3 bucket
    "reference_bucket", # Parquet reference bucket
    "kpi_output_bucket",# bucket where KPI parquets are written
    "run_id",
    "env",
]

OPTIONAL_DEFAULTS = {
    "run_mode": "normal",     # "backfill" scales workers
    "quarantine_bucket": "",
}

# T3 business rule thresholds
MAX_DURATION_MS = 1_800_000  # 30 minutes
BOT_PLAY_THRESHOLD = 1000    # same track × user per day → likely bot


def _parse_args():
    args = getResolvedOptions(sys.argv, REQUIRED_ARGS)
    for key, default in OPTIONAL_DEFAULTS.items():
        if key not in args:
            args[key] = default
    return args


def run(spark, args, logger):
    sc = spark.sparkContext
    run_id = args["run_id"]
    raw_bucket = args["bucket"]
    kpi_bucket = args["kpi_output_bucket"]
    quarantine_bucket = args.get("quarantine_bucket", "")

    # ── Set partition overwrite mode to DYNAMIC so only target dates are touched.
    # Without this, static mode wipes the whole table on each write (D-05).
    spark.conf.set("spark.sql.sources.partitionOverwriteMode", "dynamic")
    spark.conf.set("spark.sql.adaptive.enabled", "true")
    spark.conf.set("spark.sql.adaptive.skewJoin.enabled", "true")

    # ── Read valid stream CSV keys ────────────────────────────────────────────
    keys_json = args["valid_keys"]
    raw_keys = json.loads(keys_json) if isinstance(keys_json, str) else keys_json
    if not raw_keys:
        logger.warning("no_valid_keys", run_id=run_id)
        return {"kpi_parquet_root": f"s3://{kpi_bucket}/kpi/", "target_dates": []}

    raw_paths = [f"s3://{raw_bucket}/{k}" for k in raw_keys]
    logger.info("reading_streams", run_id=run_id, file_count=len(raw_paths))

    streams = (
        spark.read.option("header", True)
        .option("inferSchema", False)
        .csv(raw_paths)
    )

    # Parse and extract listen_date
    streams = (
        streams.withColumn("listen_time", F.to_timestamp("listen_time"))
        .withColumn("listen_date", F.to_date("listen_time"))
        .withColumn("user_id", F.col("user_id").cast("long"))
    )

    target_dates = [
        row["listen_date"].isoformat()
        for row in streams.select("listen_date").distinct().collect()
        if row["listen_date"] is not None
    ]
    logger.info("target_dates", run_id=run_id, dates=target_dates)

    # ── Read reference Parquet (D-18) ─────────────────────────────────────────
    ref_bucket = args["reference_bucket"]
    songs = (
        spark.read.parquet(f"s3://{ref_bucket}/songs/")
        .select(
            F.col("track_id"),
            F.col("track_name"),
            F.col("track_genre").alias("genre"),
            F.col("duration_ms").cast("long"),
        )
        .filter(F.col("duration_ms").between(1, MAX_DURATION_MS))
        .filter(F.col("genre").isNotNull())
    )
    # D-29: songs has no duplicate track_ids — broadcast join is safe.
    songs_broadcast = F.broadcast(songs)

    # ── T2: Left-join ref-integrity (D-19) ────────────────────────────────────
    enriched = streams.join(songs_broadcast, on="track_id", how="left")
    matched = enriched.filter(F.col("genre").isNotNull())
    unmatched = enriched.filter(F.col("genre").isNull())

    unmatched_count = unmatched.count()
    if unmatched_count > 0:
        logger.warning(
            "ref_fail_rows",
            run_id=run_id,
            unmatched_count=unmatched_count,
        )
        if quarantine_bucket:
            (
                unmatched.write.mode("append")
                .parquet(f"s3://{quarantine_bucket}/ref-fail/run_id={run_id}/")
            )

    # ── T3: Business rules ────────────────────────────────────────────────────
    # duration_ms is already filtered in songs; filter bot plays here.
    bot_filter = (
        matched.groupBy("listen_date", "user_id", "track_id")
        .agg(F.count("*").alias("_daily_plays"))
        .filter(F.col("_daily_plays") <= BOT_PLAY_THRESHOLD)
        .drop("_daily_plays")
    )
    clean = matched.join(
        F.broadcast(bot_filter), on=["listen_date", "user_id", "track_id"], how="inner"
    )
    clean_count = clean.count()
    logger.info("clean_row_count", run_id=run_id, clean_rows=clean_count)

    if clean_count == 0:
        logger.warning("empty_clean_dataset", run_id=run_id)
        return {"kpi_parquet_root": f"s3://{kpi_bucket}/kpi/", "target_dates": []}

    # ── KPI 1-4: Genre-day aggregate ─────────────────────────────────────────
    genre_daily = (
        clean.groupBy("listen_date", "genre")
        .agg(
            F.count("*").alias("listen_count"),
            F.countDistinct("user_id").alias("unique_listeners"),
            F.sum("duration_ms").alias("total_listening_time_ms"),
        )
        .withColumn(
            "avg_listening_time_per_user_ms",
            F.col("total_listening_time_ms") / F.col("unique_listeners"),
        )
    )

    # ── KPI 5: Top-3 songs per genre per day ─────────────────────────────────
    song_counts = (
        clean.groupBy("listen_date", "genre", "track_id", "track_name")
        .agg(F.count("*").alias("plays"))
    )
    # Tie-break by track_id for determinism (D-transformation_logic.md §4)
    w_songs = Window.partitionBy("listen_date", "genre").orderBy(
        F.desc("plays"), F.asc("track_id")
    )
    top_songs = (
        song_counts.withColumn("rank", F.row_number().over(w_songs))
        .filter(F.col("rank") <= 3)
    )

    # ── KPI 6: Top-5 genres per day ──────────────────────────────────────────
    w_genres = Window.partitionBy("listen_date").orderBy(
        F.desc("listen_count"), F.asc("genre")
    )
    top_genres = (
        genre_daily.select("listen_date", "genre", "listen_count")
        .withColumn("rank", F.row_number().over(w_genres))
        .filter(F.col("rank") <= 5)
    )

    kpi_root = f"s3://{kpi_bucket}/kpi"

    # ── Write KPI parquets (dynamic partition overwrite) ─────────────────────
    (
        genre_daily.repartition("listen_date")
        .write.mode("overwrite")
        .partitionBy("listen_date")
        .parquet(f"{kpi_root}/genre_daily/")
    )
    logger.info("wrote_genre_daily", run_id=run_id)

    (
        top_songs.repartition("listen_date")
        .write.mode("overwrite")
        .partitionBy("listen_date")
        .parquet(f"{kpi_root}/top_songs_daily/")
    )
    logger.info("wrote_top_songs", run_id=run_id)

    (
        top_genres.repartition("listen_date")
        .write.mode("overwrite")
        .partitionBy("listen_date")
        .parquet(f"{kpi_root}/top_genres_daily/")
    )
    logger.info("wrote_top_genres", run_id=run_id)

    return {
        "kpi_parquet_root": f"{kpi_root}/",
        "target_dates": sorted(target_dates),
    }


if __name__ == "__main__":
    args = _parse_args()
    sc = SparkContext()
    glue_ctx = GlueContext(sc)
    spark = glue_ctx.spark_session
    job = Job(glue_ctx)
    job.init(args["JOB_NAME"], args)

    run_id = args["run_id"]
    logger = get_logger(run_id, "transform_kpis")
    logger.info("job_start", run_id=run_id, env=args["env"])

    result = run(spark, args, logger)

    # Emit result as a Glue job output parameter read by Step Functions.
    print(json.dumps(result))
    logger.info("job_end", run_id=run_id, result=result)
    job.commit()
