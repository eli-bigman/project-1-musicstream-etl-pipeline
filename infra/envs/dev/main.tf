data "aws_caller_identity" "current" {}

locals {
  env          = var.env
  project      = var.project
  account_id   = data.aws_caller_identity.current.account_id
  common_tags = {
    Project   = var.project
    Env       = var.env
    Owner     = "sandbox_user"
    ManagedBy = "terraform"
  }
}

# ── KMS ────────────────────────────────────────────────────────────────────────

module "kms_data" {
  source      = "../../modules/kms"
  env         = local.env
  purpose     = "data"
  common_tags = local.common_tags
}

module "kms_ddb" {
  source      = "../../modules/kms"
  env         = local.env
  purpose     = "ddb"
  common_tags = local.common_tags
}

# ── S3 Data Lake ───────────────────────────────────────────────────────────────

module "data_lake" {
  source        = "../../modules/s3-data-lake"
  project       = local.project
  env           = local.env
  kms_key_arn   = module.kms_data.key_arn
  common_tags   = local.common_tags
  force_destroy = true # ephemeral dev — allow non-empty bucket destroy
  bucket_suffix = local.account_id
}

# ── DynamoDB KPI Tables ────────────────────────────────────────────────────────

module "ddb" {
  source              = "../../modules/dynamodb-kpi-tables"
  env                 = local.env
  kms_key_arn         = module.kms_ddb.key_arn
  common_tags         = local.common_tags
  deletion_protection = false # ephemeral dev — allow terraform destroy
}

# ── SQS Buffer ─────────────────────────────────────────────────────────────────

module "sqs" {
  source          = "../../modules/sqs-buffer"
  env             = local.env
  raw_bucket_name = module.data_lake.raw_bucket_name
  kms_key_id      = module.kms_data.key_id
  common_tags     = local.common_tags
}

# ── IAM Roles (depends on SQS + SM ARNs — use placeholder for pipe role) ──────

module "iam" {
  source                = "../../modules/iam-roles"
  env                   = local.env
  raw_bucket_arn        = module.data_lake.raw_bucket_arn
  archive_bucket_arn    = module.data_lake.archive_bucket_arn
  quarantine_bucket_arn = module.data_lake.quarantine_bucket_arn
  scripts_bucket_arn    = module.data_lake.scripts_bucket_arn
  reference_bucket_arn  = module.data_lake.reference_bucket_arn
  ddb_table_arns = [
    module.ddb.genre_daily_table_arn,
    module.ddb.top_songs_daily_table_arn,
    module.ddb.top_genres_daily_table_arn,
  ]
  kms_key_arn     = module.kms_data.key_arn
  ddb_kms_key_arn = module.kms_ddb.key_arn
  # Use wildcard to break the circular dependency: iam↔lambda_validator↔iam and iam↔sm↔iam.
  # The IAM defaults ("*") are still scoped to the correct actions; resource-level tightening
  # can be applied post-deploy if this were a long-lived environment.
  lambda_validator_arn = "*"
  sqs_queue_arn        = module.sqs.queue_arn
  state_machine_arn    = "*"
  common_tags          = local.common_tags
}

# ── Lambda Validator (D-17) ────────────────────────────────────────────────────

module "lambda_validator" {
  source                   = "../../modules/lambda-validator"
  env                      = local.env
  lambda_role_arn          = module.iam.lambda_validator_role_arn
  pipe_enrichment_role_arn = module.iam.pipe_enrichment_role_arn
  scripts_bucket_name      = module.data_lake.scripts_bucket_name
  quarantine_bucket_name   = module.data_lake.quarantine_bucket_name
  kms_key_arn              = module.kms_data.key_arn
  lambda_version           = var.lambda_version
  common_tags              = local.common_tags
}

# ── Glue Jobs ──────────────────────────────────────────────────────────────────

module "glue_jobs" {
  source                     = "../../modules/glue-jobs"
  env                        = local.env
  scripts_bucket_name        = module.data_lake.scripts_bucket_name
  glue_pyspark_role_arn      = module.iam.glue_pyspark_role_arn
  glue_python_shell_role_arn = module.iam.glue_python_shell_role_arn
  shared_wheel_s3_uri        = "s3://${module.data_lake.scripts_bucket_name}/glue/shared/shared-0.1.0-py3-none-any.whl"
  genre_daily_table          = module.ddb.genre_daily_table_name
  top_songs_daily_table      = module.ddb.top_songs_daily_table_name
  top_genres_daily_table     = module.ddb.top_genres_daily_table_name
  pyspark_worker_type        = var.pyspark_worker_type
  kms_key_arn                = module.kms_data.key_arn
  common_tags                = local.common_tags
}

# ── Step Functions ─────────────────────────────────────────────────────────────

module "sm" {
  source                       = "../../modules/step-functions"
  env                          = local.env
  step_functions_role_arn      = module.iam.step_functions_role_arn
  validate_schema_function_arn = module.lambda_validator.function_arn
  transform_kpis_job_name      = module.glue_jobs.transform_kpis_job_name
  load_dynamodb_job_name       = module.glue_jobs.load_dynamodb_job_name
  archive_bucket_name          = module.data_lake.archive_bucket_name
  quarantine_bucket_name       = module.data_lake.quarantine_bucket_name
  raw_bucket_name              = module.data_lake.raw_bucket_name
  reference_bucket_name        = module.data_lake.reference_bucket_name
  genre_daily_table            = module.ddb.genre_daily_table_name
  top_songs_daily_table        = module.ddb.top_songs_daily_table_name
  top_genres_daily_table       = module.ddb.top_genres_daily_table_name
  kms_key_arn                  = module.kms_data.key_arn
  common_tags                  = local.common_tags
}

# ── EventBridge Pipe (D-22) ────────────────────────────────────────────────────

module "pipe" {
  source                = "../../modules/eventbridge-pipes"
  env                   = local.env
  sqs_queue_arn         = module.sqs.queue_arn
  state_machine_arn     = module.sm.state_machine_arn
  pipe_role_arn         = module.iam.eventbridge_pipe_role_arn
  enrichment_lambda_arn = module.lambda_validator.pipe_enrichment_arn
  common_tags           = local.common_tags
}

# ── VPC Stub (disabled by default, D-27) ──────────────────────────────────────

module "vpc_stub" {
  source      = "../../modules/vpc-stub"
  env         = local.env
  region      = var.region
  enabled     = var.vpc_stub_enabled
  common_tags = local.common_tags
}

# ── Monitoring — CloudWatch alarms + dashboard (Sprint 7) ─────────────────────

module "monitoring" {
  source = "../../modules/monitoring"

  env         = local.env
  common_tags = local.common_tags

  sqs_dlq_url  = module.sqs.dlq_url
  sqs_dlq_name = module.sqs.dlq_name

  state_machine_arn = module.sm.state_machine_arn

  lambda_function_name = module.lambda_validator.function_name

  glue_transform_job_name = module.glue_jobs.transform_kpis_job_name
  glue_load_job_name      = module.glue_jobs.load_dynamodb_job_name

  alarm_email = var.alarm_email
  kms_key_arn = module.kms_data.key_arn
}
