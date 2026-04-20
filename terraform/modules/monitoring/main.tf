variable "prefix" { type = string }
variable "lambda_preprocessor_name" { type = string }
variable "kinesis_stream_name" { type = string }
variable "billing_threshold" {
  type    = number
  default = 50
}

# SNS topic for alarms
resource "aws_sns_topic" "alarms" {
  name = "${var.prefix}-alarms"
}

# Lambda error rate alarm
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${var.prefix}-lambda-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  alarm_description   = "Lambda preprocessor error rate exceeds threshold"
  alarm_actions       = [aws_sns_topic.alarms.arn]

  dimensions = {
    FunctionName = var.lambda_preprocessor_name
  }
}

# Kinesis iterator age alarm (processing falling behind)
resource "aws_cloudwatch_metric_alarm" "kinesis_age" {
  alarm_name          = "${var.prefix}-kinesis-iterator-age"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "GetRecords.IteratorAgeMilliseconds"
  namespace           = "AWS/Kinesis"
  period              = 300
  statistic           = "Maximum"
  threshold           = 60000 # 1 minute behind
  alarm_description   = "Kinesis processing falling behind"
  alarm_actions       = [aws_sns_topic.alarms.arn]

  dimensions = {
    StreamName = var.kinesis_stream_name
  }
}

# Monthly billing alarm
resource "aws_cloudwatch_metric_alarm" "billing" {
  alarm_name          = "${var.prefix}-billing-alarm"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "EstimatedCharges"
  namespace           = "AWS/Billing"
  period              = 21600 # 6 hours
  statistic           = "Maximum"
  threshold           = var.billing_threshold
  alarm_description   = "Monthly estimated charges exceed ${var.billing_threshold} USD"
  alarm_actions       = [aws_sns_topic.alarms.arn]

  dimensions = {
    Currency = "USD"
  }
}

output "alarms_topic_arn" {
  value = aws_sns_topic.alarms.arn
}
