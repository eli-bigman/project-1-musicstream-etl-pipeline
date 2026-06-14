"""Glue Python Shell job: read three KPI parquet datasets and write to DynamoDB.

Single job, all three tables (D-02-R). Adaptive boto3 retry (D-26).
DynamoDB key shapes follow D-03-R schema.
"""

import json
import sys
from urllib.parse import urlparse

import boto3
import pyarrow.parquet as pq
from awsglue.utils import getResolvedOptions

from shared.dynamo_utils import batch_write, shape_for_dynamo
from shared.logging_utils import get_logger
from shared.s3_utils import list_s3_keys

REQUIRED_ARGS = [
    "JOB_NAME",
    "run_id",
    "env",
    "kpi_parquet_root",  # e.g. s3://musicstream-dev-raw/kpi/
    "genre_daily_table",
    "top_songs_daily_table",
    "top_genres_daily_table",
]


def _iter_parquet_rows(bucket: str, prefix: str):
    """Yield raw row dicts from all Parquet files under prefix."""
    keys = list_s3_keys(bucket, prefix)
    s3 = boto3.client("s3")
    for key in keys:
        if not (key.endswith(".parquet") or "part-" in key.split("/")[-1]):
            continue
        import os
        import tempfile

        local = os.path.join(tempfile.gettempdir(), key.split("/")[-1])
        s3.download_file(bucket, key, local)
        pf = pq.ParquetFile(local)
        for batch in pf.iter_batches():
            yield from batch.to_pylist()
        os.remove(local)


def load_one_kind(kpi_root: str, kpi_kind: str, table_name: str, logger) -> int:
    """Load all partitions of a single KPI kind into DynamoDB."""
    parsed = urlparse(kpi_root)
    bucket = parsed.netloc
    prefix = parsed.path.lstrip("/") + f"{kpi_kind}/"

    def items():
        for row in _iter_parquet_rows(bucket, prefix):
            yield shape_for_dynamo(kpi_kind, row)

    count = batch_write(table_name, kpi_kind, items())
    logger.info("loaded", kpi_kind=kpi_kind, table=table_name, item_count=count)
    return count


def main():
    args = getResolvedOptions(sys.argv, REQUIRED_ARGS)
    run_id = args["run_id"]
    logger = get_logger(run_id, "load_dynamodb")
    logger.info("job_start", run_id=run_id, env=args["env"])

    kpi_root = args["kpi_parquet_root"]

    totals = {}
    for kind, table_key in [
        ("genre_daily", "genre_daily_table"),
        ("top_songs_daily", "top_songs_daily_table"),
        ("top_genres_daily", "top_genres_daily_table"),
    ]:
        table_name = args[table_key]
        count = load_one_kind(kpi_root, kind, table_name, logger)
        totals[kind] = count

    logger.info("job_end", run_id=run_id, totals=totals)
    print(json.dumps({"status": "success", "items_written": totals}))


if __name__ == "__main__":
    main()
