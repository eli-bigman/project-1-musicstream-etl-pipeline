"""Glue Python Shell job: convert users.csv and songs.csv to Parquet (D-18).

Run manually or on a low-cadence schedule when reference data is refreshed.
"""

import sys
from awsglue.utils import getResolvedOptions
from shared.logging_utils import get_logger

import boto3
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import tempfile
import os

REQUIRED_ARGS = ["JOB_NAME", "run_id", "reference_bucket", "env"]
REF_FILES = ["users", "songs"]


def convert_csv_to_parquet(bucket: str, name: str, logger) -> None:
    s3 = boto3.client("s3")
    csv_key = f"{name}/{name}.csv"
    parquet_key = f"{name}/{name}.parquet"

    with tempfile.TemporaryDirectory() as tmp:
        local_csv = os.path.join(tmp, f"{name}.csv")
        local_parquet = os.path.join(tmp, f"{name}.parquet")
        logger.info("downloading", source_key=csv_key)
        s3.download_file(bucket, csv_key, local_csv)

        df = pd.read_csv(local_csv)
        table = pa.Table.from_pandas(df)
        pq.write_table(table, local_parquet, compression="snappy")

        logger.info("uploading", dest_key=parquet_key, rows=len(df))
        s3.upload_file(local_parquet, bucket, parquet_key)


def main():
    args = getResolvedOptions(sys.argv, REQUIRED_ARGS)
    run_id = args["run_id"]
    logger = get_logger(run_id, "refresh_reference")
    logger.info("job_start", run_id=run_id)

    bucket = args["reference_bucket"]
    for name in REF_FILES:
        convert_csv_to_parquet(bucket, name, logger)

    logger.info("job_end", run_id=run_id)


if __name__ == "__main__":
    main()
