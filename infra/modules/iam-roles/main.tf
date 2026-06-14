terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.50" }
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# ── Glue PySpark Role ──────────────────────────────────────────────────────────

resource "aws_iam_role" "glue_pyspark" {
  name               = "${var.env}-glue-pyspark-role"
  assume_role_policy = data.aws_iam_policy_document.glue_assume.json
  tags               = var.common_tags
}

data "aws_iam_policy_document" "glue_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "glue_pyspark_policy" {
  statement {
    sid     = "ReadRaw"
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      var.raw_bucket_arn,
      "${var.raw_bucket_arn}/*",
      var.reference_bucket_arn,
      "${var.reference_bucket_arn}/*",
      var.scripts_bucket_arn,
      "${var.scripts_bucket_arn}/*",
    ]
  }
  statement {
    sid     = "WriteKpiAndQuarantine"
    actions = ["s3:PutObject", "s3:DeleteObject"]
    resources = [
      "${var.raw_bucket_arn}/kpi/*",
      "${var.raw_bucket_arn}/kpi_$folder$",
      "${var.raw_bucket_arn}/tmp/*",
      "${var.quarantine_bucket_arn}/*",
    ]
  }
  statement {
    sid     = "CloudWatchLogs"
    actions = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [
      "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/glue/jobs/${var.env}-*:*",
    ]
  }
  statement {
    sid = "GlueDataCatalog"
    actions = [
      "glue:GetDatabase", "glue:GetTable", "glue:GetPartition",
      "glue:GetPartitions", "glue:CreateTable", "glue:UpdateTable",
    ]
    resources = ["*"]
  }
  statement {
    sid       = "CloudWatchMetrics"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]
  }
  statement {
    sid       = "KmsDecrypt"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey*", "kms:DescribeKey"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "glue_pyspark" {
  name   = "${var.env}-glue-pyspark-policy"
  role   = aws_iam_role.glue_pyspark.id
  policy = data.aws_iam_policy_document.glue_pyspark_policy.json
}

# ── Glue Python Shell Role ─────────────────────────────────────────────────────

resource "aws_iam_role" "glue_python_shell" {
  name               = "${var.env}-glue-python-shell-role"
  assume_role_policy = data.aws_iam_policy_document.glue_assume.json
  tags               = var.common_tags
}

data "aws_iam_policy_document" "glue_python_shell_policy" {
  statement {
    sid     = "ReadKpiParquet"
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      var.raw_bucket_arn,
      "${var.raw_bucket_arn}/*",
      var.scripts_bucket_arn,
      "${var.scripts_bucket_arn}/*",
    ]
  }
  statement {
    sid = "WriteDynamoDB"
    actions = [
      "dynamodb:BatchWriteItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DescribeTable",
    ]
    resources = var.ddb_table_arns
  }
  statement {
    sid     = "CloudWatchLogs"
    actions = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [
      "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/glue/jobs/${var.env}-*:*",
    ]
  }
  statement {
    sid       = "CloudWatchMetrics"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]
  }
  statement {
    sid       = "KmsDecrypt"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey*", "kms:DescribeKey"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "glue_python_shell" {
  name   = "${var.env}-glue-python-shell-policy"
  role   = aws_iam_role.glue_python_shell.id
  policy = data.aws_iam_policy_document.glue_python_shell_policy.json
}

# ── Lambda Validator Role (D-17) ───────────────────────────────────────────────

resource "aws_iam_role" "lambda_validator" {
  name               = "${var.env}-lambda-validator-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = var.common_tags
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "lambda_validator_policy" {
  statement {
    sid       = "ReadRaw"
    actions   = ["s3:GetObject"]
    resources = ["${var.raw_bucket_arn}/*"]
  }
  statement {
    sid       = "WriteQuarantine"
    actions   = ["s3:PutObject", "s3:CopyObject"]
    resources = ["${var.quarantine_bucket_arn}/*"]
  }
  statement {
    sid       = "DeleteRaw"
    actions   = ["s3:DeleteObject"]
    resources = ["${var.raw_bucket_arn}/*"]
  }
  statement {
    sid     = "CloudWatchLogs"
    actions = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [
      "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.env}-validate-schema:*",
    ]
  }
  statement {
    sid       = "KmsDecrypt"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey*", "kms:DescribeKey"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "lambda_validator" {
  name   = "${var.env}-lambda-validator-policy"
  role   = aws_iam_role.lambda_validator.id
  policy = data.aws_iam_policy_document.lambda_validator_policy.json
}

# ── Step Functions Role ────────────────────────────────────────────────────────

resource "aws_iam_role" "step_functions" {
  name               = "${var.env}-step-functions-role"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
  tags               = var.common_tags
}

data "aws_iam_policy_document" "sfn_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "sfn_policy" {
  statement {
    sid       = "InvokeLambda"
    actions   = ["lambda:InvokeFunction"]
    resources = [var.lambda_validator_arn]
  }
  statement {
    sid       = "StartGlueJobs"
    actions   = ["glue:StartJobRun", "glue:GetJobRun", "glue:GetJobRuns", "glue:BatchStopJobRun"]
    resources = ["*"]
  }
  statement {
    sid     = "S3Archive"
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [
      "${var.raw_bucket_arn}/*",
      "${var.archive_bucket_arn}/*",
      "${var.quarantine_bucket_arn}/*",
    ]
  }
  statement {
    sid = "CloudWatchLogs"
    actions = [
      "logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery",
      "logs:DeleteLogDelivery", "logs:ListLogDeliveries",
      "logs:PutResourcePolicy", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups",
    ]
    resources = ["*"]
  }
  statement {
    sid       = "XRay"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "step_functions" {
  name   = "${var.env}-sfn-policy"
  role   = aws_iam_role.step_functions.id
  policy = data.aws_iam_policy_document.sfn_policy.json
}

# ── EventBridge Pipes Role (D-22) ─────────────────────────────────────────────

resource "aws_iam_role" "eventbridge_pipe" {
  name               = "${var.env}-pipe-role"
  assume_role_policy = data.aws_iam_policy_document.pipe_assume.json
  tags               = var.common_tags
}

data "aws_iam_policy_document" "pipe_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["pipes.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "pipe_policy" {
  statement {
    sid       = "ConsumeSqs"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [var.sqs_queue_arn]
  }
  statement {
    sid       = "StartExecution"
    actions   = ["states:StartExecution"]
    resources = [var.state_machine_arn]
  }
}

resource "aws_iam_role_policy" "eventbridge_pipe" {
  name   = "${var.env}-pipe-policy"
  role   = aws_iam_role.eventbridge_pipe.id
  policy = data.aws_iam_policy_document.pipe_policy.json
}
