output "function_arn" { value = aws_lambda_function.validate_schema.arn }
output "function_name" { value = aws_lambda_function.validate_schema.function_name }
output "pipe_enrichment_arn" { value = aws_lambda_function.pipe_enrichment.arn }
