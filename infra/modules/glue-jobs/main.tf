terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.50" }
  }
}

resource "aws_cloudwatch_log_group" "transform_kpis" {
  name              = "/aws/glue/jobs/${var.env}-transform-kpis"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
  tags              = var.common_tags
}

resource "aws_cloudwatch_log_group" "load_dynamodb" {
  name              = "/aws/glue/jobs/${var.env}-load-dynamodb"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
  tags              = var.common_tags
}

# PySpark job: T2 ref-integrity + T3 biz rules + 6 KPIs (D-02-R, D-24)
resource "aws_glue_job" "transform_kpis" {
  name              = "${var.env}-transform-kpis"
  role_arn          = var.glue_pyspark_role_arn
  glue_version      = "4.0"
  worker_type       = var.pyspark_worker_type
  number_of_workers = 2
  timeout           = 30
  max_retries       = 0 # retries handled by Step Functions

  command {
    name            = "glueetl"
    python_version  = "3"
    script_location = "s3://${var.scripts_bucket_name}/glue/pyspark/transform_kpis.py"
  }

  default_arguments = {
    "--enable-metrics"                   = "true"
    "--enable-continuous-cloudwatch-log" = "true"
    "--enable-job-insights"              = "true"
    "--enable-auto-scaling"              = "true"
    "--auto-scaling-min-workers"         = "2"
    "--auto-scaling-max-workers"         = "8"
    "--job-language"                     = "python"
    "--extra-py-files"                   = var.shared_wheel_s3_uri
    "--TempDir"                          = "s3://${var.scripts_bucket_name}/tmp/"
    "--continuous-log-logGroup"          = aws_cloudwatch_log_group.transform_kpis.name
    "--continuous-log-logStreamPrefix"   = "transform"
    "--env"                              = var.env
    "--run_mode"                         = "normal"
  }

  tags = var.common_tags
}

# Python Shell loader: single job, all 3 DDB tables (D-02-R)
resource "aws_glue_job" "load_dynamodb" {
  name         = "${var.env}-load-dynamodb"
  role_arn     = var.glue_python_shell_role_arn
  glue_version = "3.0"
  max_capacity = 0.0625
  timeout      = 30
  max_retries  = 0

  command {
    name            = "pythonshell"
    python_version  = "3.9"
    script_location = "s3://${var.scripts_bucket_name}/glue/python_shell/load_dynamodb.py"
  }

  default_arguments = {
    "--enable-metrics"                   = "true"
    "--enable-continuous-cloudwatch-log" = "true"
    "--extra-py-files"                   = var.shared_wheel_s3_uri
    "--additional-python-modules"        = "pyarrow==14.0.2,boto3>=1.34"
    "--TempDir"                          = "s3://${var.scripts_bucket_name}/tmp/"
    "--continuous-log-logGroup"          = aws_cloudwatch_log_group.load_dynamodb.name
    "--env"                              = var.env
    "--genre_daily_table"                = var.genre_daily_table
    "--top_songs_daily_table"            = var.top_songs_daily_table
    "--top_genres_daily_table"           = var.top_genres_daily_table
  }

  tags = var.common_tags
}
