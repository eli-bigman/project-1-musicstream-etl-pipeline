terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.50" }
  }
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.env}-validate-schema"
  retention_in_days = var.log_retention_days
  tags              = var.common_tags
}

resource "aws_lambda_function" "validate_schema" {
  function_name = "${var.env}-validate-schema"
  role          = var.lambda_role_arn
  runtime       = "python3.12"
  handler       = "handler.lambda_handler"
  timeout       = 30
  memory_size   = 256

  s3_bucket = var.scripts_bucket_name
  s3_key    = "lambda/${var.lambda_version}/validate_schema.zip"

  environment {
    variables = {
      ENV               = var.env
      QUARANTINE_BUCKET = var.quarantine_bucket_name
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda]

  tags = var.common_tags
}

# ── Pipe Enrichment Lambda (D-22) ─────────────────────────────────────────────
# Reshapes SQS batch from EventBridge Pipe into {detail:{bucket,object:{keys:[...]}}}
# so the ASL ParseInput state can extract bucket/keys without any changes.

resource "aws_cloudwatch_log_group" "pipe_enrichment" {
  name              = "/aws/lambda/${var.env}-pipe-enrichment"
  retention_in_days = var.log_retention_days
  tags              = var.common_tags
}

resource "aws_lambda_function" "pipe_enrichment" {
  function_name = "${var.env}-pipe-enrichment"
  role          = var.pipe_enrichment_role_arn
  runtime       = "python3.12"
  handler       = "handler.lambda_handler"
  timeout       = 30
  memory_size   = 128

  s3_bucket = var.scripts_bucket_name
  s3_key    = "lambda/${var.lambda_version}/pipe_enrichment.zip"

  depends_on = [aws_cloudwatch_log_group.pipe_enrichment]

  tags = var.common_tags
}
