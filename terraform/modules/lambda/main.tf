variable "prefix" { type = string }
variable "kinesis_stream_arn" { type = string }
variable "s3_data_bucket" { type = string }
variable "dynamodb_maps_table" { type = string }
variable "dynamodb_device_table" { type = string }
variable "dynamodb_presence_table" { type = string }
variable "dynamodb_sessions_table" { type = string }
variable "dynamodb_connections_table" { type = string }
variable "websocket_api_endpoint" { type = string }

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# S3 bucket for raw data archive
resource "aws_s3_bucket" "data" {
  bucket = "${var.prefix}-data-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  versioning_configuration {
    status = "Enabled"
  }
}

# IAM role for all Lambda functions
resource "aws_iam_role" "lambda" {
  name = "${var.prefix}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "lambda" {
  name = "${var.prefix}-lambda-policy"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = ["arn:aws:logs:*:*:*"]
      },
      {
        Effect = "Allow"
        Action = [
          "kinesis:GetRecords",
          "kinesis:GetShardIterator",
          "kinesis:DescribeStream",
          "kinesis:ListShards",
          "kinesis:ListStreams"
        ]
        Resource = [var.kinesis_stream_arn]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject"]
        Resource = ["${aws_s3_bucket.data.arn}/*"]
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Scan"
        ]
        Resource = [
          "arn:aws:dynamodb:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:table/${var.prefix}-*"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["execute-api:ManageConnections"]
        Resource = ["arn:aws:execute-api:*:*:*/@connections/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["sagemaker:InvokeEndpoint"]
        Resource = ["arn:aws:sagemaker:*:*:endpoint/${var.prefix}-*"]
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = [aws_sqs_queue.dlq.arn]
      }
    ]
  })
}

# DLQ for failed Kinesis processing
resource "aws_sqs_queue" "dlq" {
  name                      = "${var.prefix}-preprocessor-dlq"
  message_retention_seconds = 1209600 # 14 days
}

# Lambda: Preprocessor (Kinesis trigger)
data "archive_file" "preprocessor" {
  type        = "zip"
  source_file = "${path.root}/../backend/handlers/preprocessor.py"
  output_path = "${path.root}/.build/preprocessor.zip"
}

resource "aws_lambda_function" "preprocessor" {
  function_name    = "${var.prefix}-preprocessor"
  filename         = data.archive_file.preprocessor.output_path
  source_code_hash = data.archive_file.preprocessor.output_base64sha256
  handler          = "preprocessor.handler"
  runtime          = "python3.12"
  role             = aws_iam_role.lambda.arn
  timeout          = 60
  memory_size      = 256

  environment {
    variables = {
      S3_BUCKET               = aws_s3_bucket.data.bucket
      DYNAMODB_DEVICE_TABLE   = var.dynamodb_device_table
      DYNAMODB_PRESENCE_TABLE = var.dynamodb_presence_table
      WEBSOCKET_API_ENDPOINT  = var.websocket_api_endpoint
      SAGEMAKER_ENDPOINT      = ""
    }
  }

  dead_letter_config {
    target_arn = aws_sqs_queue.dlq.arn
  }
}

resource "aws_lambda_event_source_mapping" "kinesis" {
  event_source_arn                   = var.kinesis_stream_arn
  function_name                      = aws_lambda_function.preprocessor.arn
  starting_position                  = "LATEST"
  batch_size                         = 100
  maximum_batching_window_in_seconds = 5
  bisect_batch_on_function_error     = true
  maximum_retry_attempts             = 3

  destination_config {
    on_failure {
      destination_arn = aws_sqs_queue.dlq.arn
    }
  }
}

# Lambda: API Handler
data "archive_file" "api_handler" {
  type        = "zip"
  source_file = "${path.root}/../backend/handlers/api_handler.py"
  output_path = "${path.root}/.build/api_handler.zip"
}

resource "aws_lambda_function" "api_handler" {
  function_name    = "${var.prefix}-api-handler"
  filename         = data.archive_file.api_handler.output_path
  source_code_hash = data.archive_file.api_handler.output_base64sha256
  handler          = "api_handler.handler"
  runtime          = "python3.12"
  role             = aws_iam_role.lambda.arn
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      DYNAMODB_MAPS_TABLE    = var.dynamodb_maps_table
      DYNAMODB_DEVICE_TABLE  = var.dynamodb_device_table
      DYNAMODB_PRESENCE_TABLE = var.dynamodb_presence_table
      DYNAMODB_SESSIONS_TABLE = var.dynamodb_sessions_table
    }
  }
}

# Lambda: WebSocket Handler
data "archive_file" "ws_handler" {
  type        = "zip"
  source_file = "${path.root}/../backend/handlers/ws_handler.py"
  output_path = "${path.root}/.build/ws_handler.zip"
}

resource "aws_lambda_function" "ws_handler" {
  function_name    = "${var.prefix}-ws-handler"
  filename         = data.archive_file.ws_handler.output_path
  source_code_hash = data.archive_file.ws_handler.output_base64sha256
  handler          = "ws_handler.handler"
  runtime          = "python3.12"
  role             = aws_iam_role.lambda.arn
  timeout          = 30
  memory_size      = 128

  environment {
    variables = {
      DYNAMODB_CONNECTIONS_TABLE = var.dynamodb_connections_table
    }
  }
}

# Lambda: Authorizer
data "archive_file" "authorizer" {
  type        = "zip"
  source_file = "${path.root}/../backend/handlers/authorizer.py"
  output_path = "${path.root}/.build/authorizer.zip"
}

resource "aws_lambda_function" "authorizer" {
  function_name    = "${var.prefix}-authorizer"
  filename         = data.archive_file.authorizer.output_path
  source_code_hash = data.archive_file.authorizer.output_base64sha256
  handler          = "authorizer.handler"
  runtime          = "python3.12"
  role             = aws_iam_role.lambda.arn
  timeout          = 10
  memory_size      = 128
}

output "preprocessor_name" { value = aws_lambda_function.preprocessor.function_name }
output "preprocessor_arn" { value = aws_lambda_function.preprocessor.arn }
output "api_handler_name" { value = aws_lambda_function.api_handler.function_name }
output "api_handler_arn" { value = aws_lambda_function.api_handler.arn }
output "ws_handler_name" { value = aws_lambda_function.ws_handler.function_name }
output "ws_handler_arn" { value = aws_lambda_function.ws_handler.arn }
output "authorizer_handler_name" { value = aws_lambda_function.authorizer.function_name }
output "authorizer_handler_arn" { value = aws_lambda_function.authorizer.arn }
output "s3_data_bucket_name" { value = aws_s3_bucket.data.bucket }
output "dlq_arn" { value = aws_sqs_queue.dlq.arn }
