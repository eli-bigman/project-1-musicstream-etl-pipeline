output "glue_pyspark_role_arn" {
  value = aws_iam_role.glue_pyspark.arn
}
output "glue_python_shell_role_arn" {
  value = aws_iam_role.glue_python_shell.arn
}
output "lambda_validator_role_arn" {
  value = aws_iam_role.lambda_validator.arn
}
output "step_functions_role_arn" {
  value = aws_iam_role.step_functions.arn
}
output "eventbridge_pipe_role_arn" {
  value = aws_iam_role.eventbridge_pipe.arn
}
output "pipe_enrichment_role_arn" {
  value = aws_iam_role.pipe_enrichment.arn
}
