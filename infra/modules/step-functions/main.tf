terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.50" }
  }
}

resource "aws_cloudwatch_log_group" "sm" {
  name              = "/aws/states/${var.env}-streaming-etl-sm"
  retention_in_days = var.log_retention_days
  tags              = var.common_tags
}

resource "aws_sfn_state_machine" "pipeline" {
  name     = "${var.env}-streaming-etl-sm"
  role_arn = var.step_functions_role_arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/../../../step_functions/pipeline.asl.json", {
    validate_schema_function = var.validate_schema_function_arn
    transform_kpis_job       = var.transform_kpis_job_name
    load_dynamodb_job        = var.load_dynamodb_job_name
    archive_bucket           = var.archive_bucket_name
    quarantine_bucket        = var.quarantine_bucket_name
    raw_bucket               = var.raw_bucket_name
    reference_bucket         = var.reference_bucket_name
    genre_daily_table        = var.genre_daily_table
    top_songs_daily_table    = var.top_songs_daily_table
    top_genres_daily_table   = var.top_genres_daily_table
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sm.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  tracing_configuration {
    enabled = true
  }

  tags = var.common_tags
}
