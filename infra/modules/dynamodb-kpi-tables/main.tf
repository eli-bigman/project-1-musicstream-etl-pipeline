terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.50" }
  }
}

# genre_daily_kpi — PK=genre, SK=date (D-03-R)
# GSI date_genre_index (PK=date, SK=genre) for the "all genres on a date" query.
resource "aws_dynamodb_table" "genre_daily_kpi" {
  name                        = "${var.env}_genre_daily_kpi"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "genre"
  range_key                   = "date"
  deletion_protection_enabled = var.deletion_protection

  attribute {
    name = "genre"
    type = "S"
  }
  attribute {
    name = "date"
    type = "S"
  }

  global_secondary_index {
    name            = "date_genre_index"
    hash_key        = "date"
    range_key       = "genre"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  tags = var.common_tags
}

# top_songs_daily — PK=genre, SK=date_rank (D-03-R, e.g. "2024-06-25#01")
resource "aws_dynamodb_table" "top_songs_daily" {
  name                        = "${var.env}_top_songs_daily"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "genre"
  range_key                   = "date_rank"
  deletion_protection_enabled = var.deletion_protection

  attribute {
    name = "genre"
    type = "S"
  }
  attribute {
    name = "date_rank"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  tags = var.common_tags
}

# top_genres_daily — PK=date, SK=rank (N) — unchanged per D-03-R
resource "aws_dynamodb_table" "top_genres_daily" {
  name                        = "${var.env}_top_genres_daily"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "date"
  range_key                   = "rank"
  deletion_protection_enabled = var.deletion_protection

  attribute {
    name = "date"
    type = "S"
  }
  attribute {
    name = "rank"
    type = "N"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  tags = var.common_tags
}
