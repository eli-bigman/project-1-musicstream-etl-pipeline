variable "env" {
  type = string
}

variable "scripts_bucket_name" {
  type = string
}

variable "glue_pyspark_role_arn" {
  type = string
}

variable "glue_python_shell_role_arn" {
  type = string
}

variable "shared_wheel_s3_uri" {
  type = string
}

variable "genre_daily_table" {
  type = string
}

variable "top_songs_daily_table" {
  type = string
}

variable "top_genres_daily_table" {
  type = string
}

variable "kms_key_arn" {
  type    = string
  default = null
}

variable "log_retention_days" {
  type    = number
  default = 30
}

# G.025X is not available in all regions; override to G.1X if needed (D-24).
variable "pyspark_worker_type" {
  type    = string
  default = "G.025X"
}

variable "common_tags" {
  type    = map(string)
  default = {}
}
