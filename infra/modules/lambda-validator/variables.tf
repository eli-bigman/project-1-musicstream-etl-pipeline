variable "env" { type = string }
variable "lambda_role_arn" { type = string }
variable "scripts_bucket_name" { type = string }
variable "quarantine_bucket_name" { type = string }
variable "kms_key_arn" { type = string; default = null }
variable "log_retention_days" { type = number; default = 30 }
variable "lambda_version" { type = string; default = "0.1.0" }
variable "common_tags" { type = map(string); default = {} }
