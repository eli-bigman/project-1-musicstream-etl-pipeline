terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.50" }
  }
}

# EventBridge Pipe: SQS buffer → Step Functions SM (D-22)
# BatchSize=50, MaximumBatchingWindowInSeconds=120
resource "aws_pipes_pipe" "sqs_to_sfn" {
  name     = "${var.env}-sqs-to-sfn-pipe"
  role_arn = var.pipe_role_arn
  source   = var.sqs_queue_arn
  target   = var.state_machine_arn

  source_parameters {
    sqs_queue_parameters {
      batch_size                         = 50
      maximum_batching_window_in_seconds = 120
    }
  }

  target_parameters {
    step_function_state_machine_parameters {
      invocation_type = "FIRE_AND_FORGET"
    }
  }

  tags = var.common_tags
}
