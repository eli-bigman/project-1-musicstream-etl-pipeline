variable "env" {
  type = string
}

variable "purpose" {
  type        = string
  description = "Short label appended to alias, e.g. 'data' or 'ddb'"
}

variable "common_tags" {
  type    = map(string)
  default = {}
}
