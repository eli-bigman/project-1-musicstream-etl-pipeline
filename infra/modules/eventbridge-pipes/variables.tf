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

variable "enrichment_lambda_arn" {
  type        = string
  description = "ARN of the Lambda that reshapes the SQS batch into the SM input format."
}

variable "common_tags" {
  type    = map(string)
  default = {}
}
