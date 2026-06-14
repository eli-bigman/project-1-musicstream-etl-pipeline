variable "region" {
  type    = string
  default = "eu-west-1"
}

variable "project" {
  type    = string
  default = "musicstream"
}

variable "env" {
  type    = string
  default = "dev"
}

variable "vpc_stub_enabled" {
  type    = bool
  default = false
}

variable "pyspark_worker_type" {
  type    = string
  default = "G.1X"
  # G.025X is only supported for gluestreaming job type in eu-west-1 (D-24 fallback)
}

variable "lambda_version" {
  type    = string
  default = "0.1.0"
}

variable "alarm_email" {
  type        = string
  description = "Email that receives CloudWatch alarm notifications"
  default     = "richard.nutsugah@amalitechtraining.org"
}

variable "bucket_suffix" {
  type        = string
  default     = ""
  description = "Suffix appended to S3 bucket names for global uniqueness in sandbox accounts."
}
