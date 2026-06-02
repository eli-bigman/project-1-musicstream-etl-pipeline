variable "env" {
  type = string
}

variable "raw_bucket_arn" {
  type = string
}

variable "archive_bucket_arn" {
  type = string
}

variable "quarantine_bucket_arn" {
  type = string
}

variable "scripts_bucket_arn" {
  type = string
}

variable "reference_bucket_arn" {
  type = string
}

variable "ddb_table_arns" {
  type = list(string)
}

variable "kms_key_arn" {
  type    = string
  default = "*"
}

variable "lambda_validator_arn" {
  type    = string
  default = "*"
}

variable "sqs_queue_arn" {
  type    = string
  default = "*"
}

variable "state_machine_arn" {
  type    = string
  default = "*"
}

variable "common_tags" {
  type    = map(string)
  default = {}
}
