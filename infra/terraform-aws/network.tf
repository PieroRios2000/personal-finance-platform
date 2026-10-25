# Networking for RDS and the ECS Express Mode service (ADR 0052, amended after App
# Runner turned out to be closed to new AWS accounts -- see the ADR's amendment).
# Unlike GCP's Cloud SQL (one subnet, one managed private-services peering), RDS's own
# subnet-group requirement forces at least two subnets in two different availability
# zones even for a single-AZ instance (database.tf sets multi_az = false) -- confirmed
# against the hashicorp/aws provider docs for aws_db_subnet_group.
#
# Two subnet tiers:
# - Private (no route to the internet): RDS and the SSM VPC endpoints below. The
#   one-time data load (the real-apply stage's equivalent of GCP's `gcloud sql import
#   sql`) reaches RDS through AWS Systems Manager Session Manager port forwarding from
#   a short-lived bastion the owner launches manually into one of these subnets (see
#   README.md) -- never a public IP, never an open inbound port.
# - Public (a route to an Internet Gateway): where the ECS Express Mode service's tasks
#   run, because Express Mode only provisions an internet-facing Application Load
#   Balancer when it is given public subnets (a private-subnet-only Express service
#   gets an *internal* ALB, per AWS's own docs on how Express Mode resolves its network
#   configuration) -- and a public URL is this trial's whole point, same as Cloud Run's
#   `allUsers` invoker grant in infra/terraform/run.tf. RDS itself never moves off the
#   private subnets; the ECS task reaches it over the VPC's own internal routing,
#   gated by the security-group-to-security-group rule below, not by subnet tier.

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

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.demo.id
  cidr_block              = "10.20.1${count.index}.0/24"
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = { Name = "${var.demo_name}-public-${count.index}" }
}

resource "aws_internet_gateway" "demo" {
  vpc_id = aws_vpc.demo.id

  tags = { Name = "${var.demo_name}-igw" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.demo.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.demo.id
  }

  tags = { Name = "${var.demo_name}-public-rt" }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_db_subnet_group" "demo" {
  name       = "${var.demo_name}-db-subnet-group"
  subnet_ids = aws_subnet.private[*].id
}

# RDS: reachable only from the ECS task's security group and the manually-launched
# bastion, never from the open internet -- even though the ECS task itself now sits in
# a public subnet, this rule is what actually gates access, not the subnet tier.
resource "aws_security_group" "rds" {
  name_prefix = "${var.demo_name}-rds-"
  vpc_id      = aws_vpc.demo.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_task.id, aws_security_group.bastion.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Passed explicitly to the ECS Express Mode service's network_configuration
# (run.tf) so this module controls it, rather than falling back to the VPC's own
# default security group (the hashicorp/aws provider's documented default when this
# argument is omitted). Express Mode still creates its own separate load-balancer
# security group on top of this one; this one scopes only the task itself.
resource "aws_security_group" "ecs_task" {
  name_prefix = "${var.demo_name}-ecs-task-"
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
