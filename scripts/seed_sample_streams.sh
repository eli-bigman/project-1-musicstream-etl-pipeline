#!/usr/bin/env bash
# Seed the three sample stream CSV files into S3 raw bucket.
# Usage: bash scripts/seed_sample_streams.sh [env]
set -euo pipefail

ENV=${1:-dev}
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
RAW_BUCKET="musicstream-${ENV}-raw-${ACCOUNT_ID}"

declare -A FILE_DATES=(
  ["data/streams/streams6.csv"]="2024-06-25"
)

for FILE in "${!FILE_DATES[@]}"; do
  DATE="${FILE_DATES[$FILE]}"
  YEAR=$(echo $DATE | cut -d- -f1)
  MONTH=$(echo $DATE | cut -d- -f2)
  DAY=$(echo $DATE | cut -d- -f3)
  BASENAME=$(basename $FILE)
  KEY="streams/yyyy=${YEAR}/mm=${MONTH}/dd=${DAY}/${BASENAME}"
  echo "==> Uploading ${FILE} → s3://${RAW_BUCKET}/${KEY}"
  aws s3 cp "${FILE}" "s3://${RAW_BUCKET}/${KEY}"
done

echo "==> All sample stream files seeded."
