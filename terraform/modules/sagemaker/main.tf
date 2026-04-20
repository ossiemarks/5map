variable "prefix" { type = string }
variable "instance_type" {
  type    = string
  default = "ml.t2.medium"
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# S3 bucket for model artifacts
resource "aws_s3_bucket" "models" {
  bucket = "${var.prefix}-models-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_versioning" "models" {
  bucket = aws_s3_bucket.models.id
  versioning_configuration {
    status = "Enabled"
  }
}

# IAM role for SageMaker
resource "aws_iam_role" "sagemaker" {
  name = "${var.prefix}-sagemaker-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "sagemaker.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "sagemaker" {
  role       = aws_iam_role.sagemaker.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
}

resource "aws_iam_role_policy" "sagemaker_s3" {
  name = "${var.prefix}-sagemaker-s3"
  role = aws_iam_role.sagemaker.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:ListBucket"]
      Resource = [
        aws_s3_bucket.models.arn,
        "${aws_s3_bucket.models.arn}/*"
      ]
    }]
  })
}

output "models_bucket" {
  value = aws_s3_bucket.models.bucket
}

output "models_bucket_arn" {
  value = aws_s3_bucket.models.arn
}

output "sagemaker_role_arn" {
  value = aws_iam_role.sagemaker.arn
}
