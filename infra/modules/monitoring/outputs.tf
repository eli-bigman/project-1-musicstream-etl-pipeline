output "alarm_topic_arn" {
  value       = aws_sns_topic.pipeline_alarms.arn
  description = "ARN of the SNS topic that receives all pipeline alarm notifications"
}
