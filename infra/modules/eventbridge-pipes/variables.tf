variable "env" {
  type = string
}

variable "sqs_queue_arn" {
  type = string
}

variable "state_machine_arn" {
  type = string
}

variable "pipe_role_arn" {
  type = string
}

variable "common_tags" {
  type    = map(string)
  default = {}
}
