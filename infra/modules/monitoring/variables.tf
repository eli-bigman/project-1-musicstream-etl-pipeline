terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.50" }
  }
}

variable "env" { type = string }
variable "common_tags" { type = map(string) }

variable "sqs_dlq_url" {
  type        = string
  description = "URL of the SQS dead-letter queue"
}

variable "sqs_dlq_name" {
  type        = string
  description = "Name of the SQS dead-letter queue (used as CloudWatch dimension)"
}

variable "state_machine_arn" {
  type        = string
  description = "ARN of the Step Functions state machine"
}

variable "lambda_function_name" {
  type        = string
  description = "Name of the Lambda validate_schema function"
}

variable "glue_transform_job_name" {
  type        = string
  description = "Name of the Glue PySpark transform_kpis job"
}

variable "glue_load_job_name" {
  type        = string
  description = "Name of the Glue Python Shell load_dynamodb job"
}

variable "alarm_email" {
  type        = string
  description = "Email address to receive alarm notifications"
}

variable "kms_key_arn" {
  type        = string
  description = "KMS key ARN used to encrypt the SNS topic at rest"
}

variable "log_retention_days" {
  type    = number
  default = 30
}
