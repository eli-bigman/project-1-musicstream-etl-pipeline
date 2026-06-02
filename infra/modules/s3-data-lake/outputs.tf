output "raw_bucket_name" {
  value = aws_s3_bucket.buckets["raw"].id
}
output "raw_bucket_arn" {
  value = aws_s3_bucket.buckets["raw"].arn
}
output "archive_bucket_name" {
  value = aws_s3_bucket.buckets["archive"].id
}
output "archive_bucket_arn" {
  value = aws_s3_bucket.buckets["archive"].arn
}
output "quarantine_bucket_name" {
  value = aws_s3_bucket.buckets["quarantine"].id
}
output "quarantine_bucket_arn" {
  value = aws_s3_bucket.buckets["quarantine"].arn
}
output "scripts_bucket_name" {
  value = aws_s3_bucket.buckets["scripts"].id
}
output "scripts_bucket_arn" {
  value = aws_s3_bucket.buckets["scripts"].arn
}
output "reference_bucket_name" {
  value = aws_s3_bucket.buckets["reference"].id
}
output "reference_bucket_arn" {
  value = aws_s3_bucket.buckets["reference"].arn
}
