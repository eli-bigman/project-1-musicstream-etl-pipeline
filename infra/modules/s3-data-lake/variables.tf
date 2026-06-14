variable "project" {
  type = string
}

variable "env" {
  type = string
}

variable "kms_key_arn" {
  type    = string
  default = null
}

variable "common_tags" {
  type    = map(string)
  default = {}
}

variable "force_destroy" {
  type    = bool
  default = false
}

variable "bucket_suffix" {
  type        = string
  default     = ""
  description = "Optional suffix appended to every bucket name (e.g. account ID) to guarantee global uniqueness in sandbox accounts."
}
