variable "env" {
  type = string
}

variable "raw_bucket_name" {
  type = string
}

variable "kms_key_id" {
  type    = string
  default = null
}

variable "common_tags" {
  type    = map(string)
  default = {}
}
