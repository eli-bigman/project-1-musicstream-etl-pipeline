output "transform_kpis_job_name" {
  value = aws_glue_job.transform_kpis.name
}

output "load_dynamodb_job_name" {
  value = aws_glue_job.load_dynamodb.name
}

output "refresh_reference_job_name" {
  value = aws_glue_job.refresh_reference.name
}
