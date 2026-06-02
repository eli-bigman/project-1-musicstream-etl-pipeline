output "vpc_id"     { value = var.enabled ? aws_vpc.this[0].id     : null }
output "subnet_id"  { value = var.enabled ? aws_subnet.private[0].id : null }
