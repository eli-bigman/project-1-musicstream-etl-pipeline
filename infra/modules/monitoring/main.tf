terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.50" }
  }
}

# ── SNS topic for all pipeline alarms ─────────────────────────────────────────

resource "aws_sns_topic" "pipeline_alarms" {
  name = "${var.env}-pipeline-alarms"
  tags = var.common_tags
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.pipeline_alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

data "aws_iam_policy_document" "sns_topic_policy" {
  statement {
    sid     = "AllowEventBridgePublish"
    effect  = "Allow"
    actions = ["sns:Publish"]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
    resources = [aws_sns_topic.pipeline_alarms.arn]
  }

  statement {
    sid     = "AllowCloudWatchPublish"
    effect  = "Allow"
    actions = ["sns:Publish"]
    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }
    resources = [aws_sns_topic.pipeline_alarms.arn]
  }
}

resource "aws_sns_topic_policy" "allow_publishers" {
  arn    = aws_sns_topic.pipeline_alarms.arn
  policy = data.aws_iam_policy_document.sns_topic_policy.json
}

# ── SQS DLQ depth alarm ───────────────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "dlq_depth" {
  alarm_name          = "${var.env}-sqs-dlq-not-empty"
  alarm_description   = "Messages in SQS DLQ — a batch failed to dispatch to Step Functions after 3 attempts."
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  evaluation_periods  = 1
  period              = 60
  statistic           = "Sum"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions = {
    QueueName = var.sqs_dlq_name
  }
  alarm_actions      = [aws_sns_topic.pipeline_alarms.arn]
  ok_actions         = [aws_sns_topic.pipeline_alarms.arn]
  treat_missing_data = "notBreaching"
  tags               = var.common_tags
}

# ── Step Functions execution failure alarm ────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "sf_executions_failed" {
  alarm_name          = "${var.env}-sf-executions-failed"
  alarm_description   = "One or more Step Functions pipeline executions failed."
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  evaluation_periods  = 1
  period              = 300
  statistic           = "Sum"
  namespace           = "AWS/States"
  metric_name         = "ExecutionsFailed"
  dimensions = {
    StateMachineArn = var.state_machine_arn
  }
  alarm_actions      = [aws_sns_topic.pipeline_alarms.arn]
  treat_missing_data = "notBreaching"
  tags               = var.common_tags
}

# ── Lambda validator error alarm ──────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${var.env}-lambda-validator-errors"
  alarm_description   = "Lambda validate_schema returned errors."
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  evaluation_periods  = 1
  period              = 300
  statistic           = "Sum"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions = {
    FunctionName = var.lambda_function_name
  }
  alarm_actions      = [aws_sns_topic.pipeline_alarms.arn]
  treat_missing_data = "notBreaching"
  tags               = var.common_tags
}

# ── Glue job failure alarms (EventBridge rule → SNS) ─────────────────────────
# Glue does not publish a native "failures" CW metric; we route
# GlueJobStateChange FAILED/ERROR/TIMEOUT events to SNS instead.

resource "aws_cloudwatch_event_rule" "glue_job_failed" {
  name        = "${var.env}-glue-job-failed"
  description = "Fires when a watched Glue job run reaches FAILED/ERROR/TIMEOUT state."

  event_pattern = jsonencode({
    source      = ["aws.glue"]
    detail-type = ["Glue Job State Change"]
    detail = {
      jobName = [var.glue_transform_job_name, var.glue_load_job_name]
      state   = ["FAILED", "ERROR", "TIMEOUT"]
    }
  })

  tags = var.common_tags
}

resource "aws_cloudwatch_event_target" "glue_failed_sns" {
  rule      = aws_cloudwatch_event_rule.glue_job_failed.name
  target_id = "GlueFailedToSNS"
  arn       = aws_sns_topic.pipeline_alarms.arn
}

# ── CloudWatch dashboard ──────────────────────────────────────────────────────

resource "aws_cloudwatch_dashboard" "etl_overview" {
  dashboard_name = "${var.env}-etl-overview"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Step Functions — Executions"
          region = "eu-west-1"
          metrics = [
            ["AWS/States", "ExecutionsStarted", "StateMachineArn", var.state_machine_arn],
            ["AWS/States", "ExecutionsSucceeded", "StateMachineArn", var.state_machine_arn],
            ["AWS/States", "ExecutionsFailed", "StateMachineArn", var.state_machine_arn],
          ]
          period = 300
          stat   = "Sum"
          view   = "timeSeries"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Lambda — Invocations & Errors"
          region = "eu-west-1"
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", var.lambda_function_name],
            ["AWS/Lambda", "Errors", "FunctionName", var.lambda_function_name],
          ]
          period = 300
          stat   = "Sum"
          view   = "timeSeries"
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "SQS — DLQ Depth"
          region = "eu-west-1"
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", var.sqs_dlq_name],
          ]
          period = 60
          stat   = "Maximum"
          view   = "timeSeries"
        }
      }
    ]
  })
}
