terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.50" }
  }
}

data "aws_caller_identity" "current" {}

# Root-principal delegation only — no role ARNs in key policy (D-25).
data "aws_iam_policy_document" "key_policy" {
  statement {
    sid    = "RootAdministration"
    effect = "Allow"
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
    actions   = ["kms:*"]
    resources = ["*"]
  }
}

resource "aws_kms_key" "this" {
  description             = "${var.env}-${var.purpose}"
  deletion_window_in_days = 14
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.key_policy.json

  tags = var.common_tags
}

resource "aws_kms_alias" "this" {
  name          = "alias/${var.env}-${var.purpose}"
  target_key_id = aws_kms_key.this.key_id
}
