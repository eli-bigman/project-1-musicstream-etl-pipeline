output "genre_daily_table_name" {
  value = aws_dynamodb_table.genre_daily_kpi.name
}
output "genre_daily_table_arn" {
  value = aws_dynamodb_table.genre_daily_kpi.arn
}
output "top_songs_daily_table_name" {
  value = aws_dynamodb_table.top_songs_daily.name
}
output "top_songs_daily_table_arn" {
  value = aws_dynamodb_table.top_songs_daily.arn
}
output "top_genres_daily_table_name" {
  value = aws_dynamodb_table.top_genres_daily.name
}
output "top_genres_daily_table_arn" {
  value = aws_dynamodb_table.top_genres_daily.arn
}
