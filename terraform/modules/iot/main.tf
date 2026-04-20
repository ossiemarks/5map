variable "prefix" { type = string }
variable "kinesis_arn" { type = string }
variable "kinesis_name" { type = string }

data "aws_iot_endpoint" "current" {
  endpoint_type = "iot:Data-ATS"
}

resource "aws_iot_thing" "pineapple" {
  name = "${var.prefix}-pineapple"
}

resource "aws_iot_certificate" "pineapple" {
  active = true
}

resource "aws_iot_thing_principal_attachment" "pineapple" {
  principal = aws_iot_certificate.pineapple.arn
  thing     = aws_iot_thing.pineapple.name
}

resource "aws_iot_policy" "pineapple" {
  name = "${var.prefix}-pineapple-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["iot:Connect"]
        Resource = ["arn:aws:iot:*:*:client/${var.prefix}-*"]
      },
      {
        Effect   = "Allow"
        Action   = ["iot:Publish"]
        Resource = ["arn:aws:iot:*:*:topic/5map/*"]
      }
    ]
  })
}

resource "aws_iot_policy_attachment" "pineapple" {
  policy = aws_iot_policy.pineapple.name
  target = aws_iot_certificate.pineapple.arn
}

resource "aws_iam_role" "iot_kinesis" {
  name = "${var.prefix}-iot-kinesis-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "iot.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "iot_kinesis" {
  name = "${var.prefix}-iot-kinesis-policy"
  role = aws_iam_role.iot_kinesis.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["kinesis:PutRecord", "kinesis:PutRecords"]
      Resource = [var.kinesis_arn]
    }]
  })
}

resource "aws_iot_topic_rule" "rssi_to_kinesis" {
  name        = "${replace(var.prefix, "-", "_")}_rssi_to_kinesis"
  enabled     = true
  sql         = "SELECT * FROM '5map/rssi/+'"
  sql_version = "2016-03-23"

  kinesis {
    stream_name = var.kinesis_name
    role_arn    = aws_iam_role.iot_kinesis.arn
    partition_key = "$${topic(3)}"
  }
}

output "iot_endpoint" {
  value = data.aws_iot_endpoint.current.endpoint_address
}

output "certificate_arn" {
  value = aws_iot_certificate.pineapple.arn
}

output "certificate_pem" {
  value     = aws_iot_certificate.pineapple.certificate_pem
  sensitive = true
}

output "private_key" {
  value     = aws_iot_certificate.pineapple.private_key
  sensitive = true
}
