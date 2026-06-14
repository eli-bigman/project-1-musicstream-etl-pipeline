terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.50" }
  }
}

resource "aws_sqs_queue" "dlq" {
  name                      = "${var.env}-etl-buffer-dlq"
  message_retention_seconds = 1209600 # 14 days
  sqs_managed_sse_enabled   = true    # AWS-managed SSE; EventBridge service principal can't use CMK without explicit key policy grant
  tags                      = var.common_tags
}

resource "aws_sqs_queue" "buffer" {
  name                       = "${var.env}-etl-buffer"
  visibility_timeout_seconds = 300
  message_retention_seconds  = 86400
  sqs_managed_sse_enabled    = true   # AWS-managed SSE; EventBridge service principal can't use CMK without explicit key policy grant

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3
  })

  tags = var.common_tags
}

# Allow S3 EventBridge (via EventBridge rule) to send messages to the queue.
data "aws_iam_policy_document" "sqs_policy" {
  statement {
    sid    = "AllowEventBridge"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.buffer.arn]
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:events:*:*:rule/*"]
    }
  }
}

resource "aws_sqs_queue_policy" "buffer" {
  queue_url = aws_sqs_queue.buffer.id
  policy    = data.aws_iam_policy_document.sqs_policy.json
}

# EventBridge rule: S3 Object Created in raw bucket, streams/ prefix, .csv suffix.
resource "aws_cloudwatch_event_rule" "s3_raw" {
  name        = "${var.env}-s3-raw-csv-created"
  description = "Capture S3 Object Created events from raw bucket for CSV stream files"

  event_pattern = jsonencode({
    source      = ["aws.s3"]
    detail-type = ["Object Created"]
    detail = {
      bucket = { name = [var.raw_bucket_name] }
      object = {
        key = [{ prefix = "streams/" }, { suffix = ".csv" }]
      }
    }
  })

  tags = var.common_tags
}

resource "aws_cloudwatch_event_target" "sqs" {
  rule      = aws_cloudwatch_event_rule.s3_raw.name
  target_id = "SendToSQS"
  arn       = aws_sqs_queue.buffer.arn
}
