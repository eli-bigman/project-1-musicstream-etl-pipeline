variable "env" { type = string }
variable "region" { type = string }
variable "enabled" { type = bool; default = false }
variable "common_tags" { type = map(string); default = {} }
