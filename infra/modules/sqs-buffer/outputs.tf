output "queue_arn" {
  value = aws_sqs_queue.buffer.arn
}

output "queue_url" {
  value = aws_sqs_queue.buffer.url
}

output "dlq_arn" {
  value = aws_sqs_queue.dlq.arn
}

output "dlq_url" {
  value = aws_sqs_queue.dlq.url
}

output "dlq_name" {
  value = aws_sqs_queue.dlq.name
}
