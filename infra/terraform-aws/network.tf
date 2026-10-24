# Private networking for RDS and App Runner's VPC connector (ADR 0052). Unlike GCP's
# Cloud SQL (one subnet, one managed private-services peering), RDS's own subnet-group
# requirement forces at least two subnets in two different availability zones even for a
# single-AZ instance (database.tf sets multi_az = false) -- confirmed against the
# hashicorp/aws provider docs for aws_db_subnet_group. No internet gateway and no NAT
# gateway exist in this VPC: RDS is reachable only from App Runner's VPC connector, and
# the one-time data load (the real-apply stage's equivalent of GCP's `gcloud sql import
# sql`) reaches it through AWS Systems Manager Session Manager port forwarding from a
# short-lived bastion the owner launches manually into one of these subnets (see
# README.md) -- never a public IP, never an open inbound port. The three VPC interface
# endpoints below are what let that manually-launched bastion reach the SSM service
# without any NAT/internet path.

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "demo" {
  cidr_block           = "10.20.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${var.demo_name}-vpc" }
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.demo.id
  cidr_block        = "10.20.${count.index}.0/24"
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = { Name = "${var.demo_name}-private-${count.index}" }
}

resource "aws_db_subnet_group" "demo" {
  name       = "${var.demo_name}-db-subnet-group"
  subnet_ids = aws_subnet.private[*].id
}

# RDS: reachable only from the App Runner VPC connector and the manually-launched
# bastion (security groups below), never from the open internet.
resource "aws_security_group" "rds" {
  name_prefix = "${var.demo_name}-rds-"
  vpc_id      = aws_vpc.demo.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.apprunner_connector.id, aws_security_group.bastion.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "apprunner_connector" {
  name_prefix = "${var.demo_name}-apprunner-"
  vpc_id      = aws_vpc.demo.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "bastion" {
  name_prefix = "${var.demo_name}-bastion-"
  vpc_id      = aws_vpc.demo.id
  description = "No inbound rule at all: reached only via SSM Session Manager, never SSH."

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "vpc_endpoints" {
  name_prefix = "${var.demo_name}-endpoints-"
  vpc_id      = aws_vpc.demo.id

  ingress {
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.bastion.id]
  }
}

resource "aws_vpc_endpoint" "ssm" {
  for_each            = toset(["ssm", "ssmmessages", "ec2messages"])
  vpc_id              = aws_vpc.demo.id
  service_name        = "com.amazonaws.${var.aws_region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true
}

resource "aws_apprunner_vpc_connector" "demo" {
  vpc_connector_name = "${var.demo_name}-connector"
  subnets            = aws_subnet.private[*].id
  security_groups    = [aws_security_group.apprunner_connector.id]
}
