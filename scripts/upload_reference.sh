#!/usr/bin/env bash
# Upload reference data CSVs to S3 and convert to Parquet.
# Usage: bash scripts/upload_reference.sh [env]
set -euo pipefail

ENV=${1:-dev}
REFERENCE_BUCKET="musicstream-${ENV}-reference"
SCRIPTS_BUCKET="musicstream-${ENV}-scripts"

echo "==> Uploading CSVs to s3://${REFERENCE_BUCKET}/"
aws s3 cp data/users/users.csv "s3://${REFERENCE_BUCKET}/users/users.csv"
aws s3 cp data/songs/songs.csv "s3://${REFERENCE_BUCKET}/songs/songs.csv"

echo "==> Converting to Parquet via refresh_reference Glue job"
aws glue start-job-run \
  --job-name "${ENV}-refresh-reference" \
  --arguments \
    "--run_id=manual-$(date +%s)" \
    "--reference_bucket=${REFERENCE_BUCKET}" \
    "--env=${ENV}" \
  --query 'JobRunId' --output text

echo "==> Done. Parquet files will appear at:"
echo "    s3://${REFERENCE_BUCKET}/users/users.parquet"
echo "    s3://${REFERENCE_BUCKET}/songs/songs.parquet"
