terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.50" }
  }
}

locals {
  suffix = var.bucket_suffix != "" ? "-${var.bucket_suffix}" : ""
  buckets = {
    raw        = "${var.project}-${var.env}-raw${local.suffix}"
    archive    = "${var.project}-${var.env}-archive${local.suffix}"
    quarantine = "${var.project}-${var.env}-quarantine${local.suffix}"
    scripts    = "${var.project}-${var.env}-scripts${local.suffix}"
    reference  = "${var.project}-${var.env}-reference${local.suffix}"
  }
}

resource "aws_s3_bucket" "buckets" {
  for_each      = local.buckets
  bucket        = each.value
  force_destroy = var.force_destroy
  tags          = merge(var.common_tags, { Purpose = each.key })
}

resource "aws_s3_bucket_versioning" "buckets" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.buckets[each.key].id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "buckets" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.buckets[each.key].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.kms_key_arn != null ? "aws:kms" : "AES256"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "buckets" {
  for_each                = local.buckets
  bucket                  = aws_s3_bucket.buckets[each.key].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Enable EventBridge notifications on raw bucket for S3 Object Created events.
resource "aws_s3_bucket_notification" "raw_eventbridge" {
  bucket      = aws_s3_bucket.buckets["raw"].id
  eventbridge = true
}

# Archive: Glacier after 90 days, expire after 730 days.
resource "aws_s3_bucket_lifecycle_configuration" "archive" {
  bucket = aws_s3_bucket.buckets["archive"].id
  rule {
    id     = "archive-transition"
    status = "Enabled"
    filter { prefix = "" }
    transition {
      days          = 90
      storage_class = "GLACIER"
    }
    expiration {
      days = 730
    }
  }
}

# Quarantine: expire after 30 days for manual review.
resource "aws_s3_bucket_lifecycle_configuration" "quarantine" {
  bucket = aws_s3_bucket.buckets["quarantine"].id
  rule {
    id     = "quarantine-expiry"
    status = "Enabled"
    filter { prefix = "" }
    expiration {
      days = 30
    }
  }
}
