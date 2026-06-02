#!/usr/bin/env bash
# Manually trigger the ETL pipeline for a file already in S3.
# Usage: bash scripts/trigger_pipeline.sh [key] [env]
set -euo pipefail

KEY=${1:-"streams/yyyy=2024/mm=06/dd=25/streams1.csv"}
ENV=${2:-dev}
RAW_BUCKET="musicstream-${ENV}-raw"
SQS_URL=$(aws ssm get-parameter --name "/${ENV}/sqs/buffer-queue-url" --query "Parameter.Value" --output text 2>/dev/null || echo "")

if [ -z "${SQS_URL}" ]; then
  SQS_URL=$(terraform -chdir=infra/envs/${ENV} output -raw sqs_buffer_queue_url 2>/dev/null || echo "")
fi

if [ -z "${SQS_URL}" ]; then
  echo "ERROR: Could not determine SQS queue URL. Set SQS_BUFFER_QUEUE_URL in .env or run terraform output."
  exit 1
fi

PAYLOAD=$(cat <<EOF
{
  "detail": {
    "bucket": {"name": "${RAW_BUCKET}"},
    "object": {"keys": ["${KEY}"]}
  }
}
EOF
)

echo "==> Sending message to SQS: ${SQS_URL}"
MSG_ID=$(aws sqs send-message \
  --queue-url "${SQS_URL}" \
  --message-body "${PAYLOAD}" \
  --query 'MessageId' --output text)

echo "==> Queued. MessageId: ${MSG_ID}"
echo "    EventBridge Pipe will start the Step Functions execution within 2 minutes."
