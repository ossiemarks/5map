variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "eu-west-2"
}

variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
  default     = "fivemap"
}

variable "domain_name" {
  description = "Base domain for all endpoints"
  type        = string
  default     = "voicechatbox.com"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "prod"
}

variable "sagemaker_instance_type" {
  description = "SageMaker endpoint instance type"
  type        = string
  default     = "ml.t2.medium"
}

variable "kinesis_shard_count" {
  description = "Number of Kinesis shards"
  type        = number
  default     = 1
}

variable "billing_alarm_threshold" {
  description = "Monthly cost alarm threshold in USD"
  type        = number
  default     = 50
}
