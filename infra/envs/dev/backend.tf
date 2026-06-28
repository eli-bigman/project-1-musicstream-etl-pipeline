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
  region  = var.region
  profile = "sandbox-musicstream-dev"
  # Uses sandbox_user IAM user on account 970547336735
  default_tags {
    tags = {
      Project   = var.project
      Env       = var.env
      ManagedBy = "terraform"
    }
  }
}
