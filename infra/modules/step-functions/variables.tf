variable "env" {
  type = string
}

variable "step_functions_role_arn" {
  type = string
}

variable "validate_schema_function_arn" {
  type = string
}

variable "transform_kpis_job_name" {
  type = string
}

variable "load_dynamodb_job_name" {
  type = string
}

variable "archive_bucket_name" {
  type = string
}

variable "quarantine_bucket_name" {
  type = string
}

variable "raw_bucket_name" {
  type = string
}

variable "reference_bucket_name" {
  type = string
}

variable "kms_key_arn" {
  type    = string
  default = null
}

variable "log_retention_days" {
  type    = number
  default = 365
}

variable "common_tags" {
  type    = map(string)
  default = {}
}
