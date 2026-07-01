terraform {
  required_version = ">= 1.6"
  backend "s3" {
    bucket         = "musicstream-tfstate-970547336735"
    key            = "envs/dev/terraform.tfstate"
    region         = "eu-west-1"
    dynamodb_table = "musicstream-tfstate-lock"
    encrypt        = true
  }
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.50" }
  }
}

provider "aws" {
  region = var.region
  # Credentials come from the default provider chain: AWS_PROFILE env var
  # locally (sandbox_user on account 970547336735), or AWS_ACCESS_KEY_ID /
  # AWS_SECRET_ACCESS_KEY env vars in CI (D-32) — no hardcoded profile so
  # both environments resolve the same provider block.
  default_tags {
    tags = {
      Project   = var.project
      Env       = var.env
      ManagedBy = "terraform"
    }
  }
}
