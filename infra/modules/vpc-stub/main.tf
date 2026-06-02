terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.50" }
  }
}

# VPC stub — disabled by default (D-27). Enable only when a service is moved into a VPC.
resource "aws_vpc" "this" {
  count      = var.enabled ? 1 : 0
  cidr_block = "10.0.0.0/24"
  tags       = merge(var.common_tags, { Name = "${var.env}-etl-vpc" })
}

resource "aws_subnet" "private" {
  count             = var.enabled ? 1 : 0
  vpc_id            = aws_vpc.this[0].id
  cidr_block        = "10.0.0.0/25"
  availability_zone = "${var.region}a"
  tags              = merge(var.common_tags, { Name = "${var.env}-private" })
}

resource "aws_route_table" "private" {
  count  = var.enabled ? 1 : 0
  vpc_id = aws_vpc.this[0].id
  tags   = merge(var.common_tags, { Name = "${var.env}-private-rt" })
}

resource "aws_route_table_association" "private" {
  count          = var.enabled ? 1 : 0
  subnet_id      = aws_subnet.private[0].id
  route_table_id = aws_route_table.private[0].id
}

resource "aws_vpc_endpoint" "s3" {
  count           = var.enabled ? 1 : 0
  vpc_id          = aws_vpc.this[0].id
  service_name    = "com.amazonaws.${var.region}.s3"
  route_table_ids = [aws_route_table.private[0].id]
  tags            = merge(var.common_tags, { Name = "${var.env}-s3-endpoint" })
}

resource "aws_vpc_endpoint" "dynamodb" {
  count           = var.enabled ? 1 : 0
  vpc_id          = aws_vpc.this[0].id
  service_name    = "com.amazonaws.${var.region}.dynamodb"
  route_table_ids = [aws_route_table.private[0].id]
  tags            = merge(var.common_tags, { Name = "${var.env}-ddb-endpoint" })
}
