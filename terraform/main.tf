locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.name
  prefix     = "${var.project_name}-${var.environment}"
}

module "iot" {
  source       = "./modules/iot"
  prefix       = local.prefix
  kinesis_arn  = module.kinesis.stream_arn
  kinesis_name = module.kinesis.stream_name
}

module "kinesis" {
  source      = "./modules/kinesis"
  prefix      = local.prefix
  shard_count = var.kinesis_shard_count
}

module "dynamodb" {
  source = "./modules/dynamodb"
  prefix = local.prefix
}

module "lambda" {
  source = "./modules/lambda"
  prefix = local.prefix

  kinesis_stream_arn     = module.kinesis.stream_arn
  s3_data_bucket         = module.lambda.s3_data_bucket_name
  dynamodb_maps_table    = module.dynamodb.maps_table_name
  dynamodb_device_table  = module.dynamodb.device_table_name
  dynamodb_presence_table = module.dynamodb.presence_table_name
  dynamodb_sessions_table = module.dynamodb.sessions_table_name
  dynamodb_connections_table = module.dynamodb.connections_table_name
  websocket_api_endpoint = module.api.websocket_api_endpoint
}

module "api" {
  source = "./modules/api"
  prefix = local.prefix

  api_handler_arn        = module.lambda.api_handler_arn
  api_handler_name       = module.lambda.api_handler_name
  ws_handler_arn         = module.lambda.ws_handler_arn
  ws_handler_name        = module.lambda.ws_handler_name
  authorizer_handler_arn = module.lambda.authorizer_handler_arn
  authorizer_handler_name = module.lambda.authorizer_handler_name
  domain_name            = var.domain_name
}

module "monitoring" {
  source = "./modules/monitoring"
  prefix = local.prefix

  lambda_preprocessor_name = module.lambda.preprocessor_name
  kinesis_stream_name      = module.kinesis.stream_name
  billing_threshold        = var.billing_alarm_threshold
}

output "iot_endpoint" {
  value = module.iot.iot_endpoint
}

output "api_endpoint" {
  value = module.api.api_endpoint
}

output "websocket_endpoint" {
  value = module.api.websocket_endpoint
}

output "iot_cert_arn" {
  value     = module.iot.certificate_arn
  sensitive = true
}
