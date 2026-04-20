variable "prefix" { type = string }
variable "api_handler_arn" { type = string }
variable "api_handler_name" { type = string }
variable "ws_handler_arn" { type = string }
variable "ws_handler_name" { type = string }
variable "authorizer_handler_arn" { type = string }
variable "authorizer_handler_name" { type = string }
variable "domain_name" { type = string }

# REST API
resource "aws_apigatewayv2_api" "rest" {
  name          = "${var.prefix}-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["Authorization", "Content-Type"]
    max_age       = 3600
  }
}

resource "aws_apigatewayv2_integration" "rest" {
  api_id                 = aws_apigatewayv2_api.rest.id
  integration_type       = "AWS_PROXY"
  integration_uri        = var.api_handler_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "get_map" {
  api_id    = aws_apigatewayv2_api.rest.id
  route_key = "GET /api/map/{session_id}"
  target    = "integrations/${aws_apigatewayv2_integration.rest.id}"
}

resource "aws_apigatewayv2_route" "get_devices" {
  api_id    = aws_apigatewayv2_api.rest.id
  route_key = "GET /api/devices/{session_id}"
  target    = "integrations/${aws_apigatewayv2_integration.rest.id}"
}

resource "aws_apigatewayv2_route" "get_presence" {
  api_id    = aws_apigatewayv2_api.rest.id
  route_key = "GET /api/presence/{session_id}"
  target    = "integrations/${aws_apigatewayv2_integration.rest.id}"
}

resource "aws_apigatewayv2_route" "post_sessions" {
  api_id    = aws_apigatewayv2_api.rest.id
  route_key = "POST /api/sessions"
  target    = "integrations/${aws_apigatewayv2_integration.rest.id}"
}

resource "aws_apigatewayv2_route" "post_positions" {
  api_id    = aws_apigatewayv2_api.rest.id
  route_key = "POST /api/positions"
  target    = "integrations/${aws_apigatewayv2_integration.rest.id}"
}

resource "aws_apigatewayv2_stage" "rest" {
  api_id      = aws_apigatewayv2_api.rest.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "rest_api" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = var.api_handler_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.rest.execution_arn}/*/*"
}

# WebSocket API
resource "aws_apigatewayv2_api" "ws" {
  name                       = "${var.prefix}-ws"
  protocol_type              = "WEBSOCKET"
  route_selection_expression = "$request.body.action"
}

resource "aws_apigatewayv2_authorizer" "ws" {
  api_id           = aws_apigatewayv2_api.ws.id
  authorizer_type  = "REQUEST"
  authorizer_uri   = "arn:aws:apigateway:${data.aws_region.current.name}:lambda:path/2015-03-31/functions/${var.authorizer_handler_arn}/invocations"
  name             = "${var.prefix}-ws-authorizer"
  identity_sources = ["route.request.querystring.token"]
}

data "aws_region" "current" {}

resource "aws_apigatewayv2_integration" "ws" {
  api_id             = aws_apigatewayv2_api.ws.id
  integration_type   = "AWS_PROXY"
  integration_uri    = "arn:aws:apigateway:${data.aws_region.current.name}:lambda:path/2015-03-31/functions/${var.ws_handler_arn}/invocations"
  integration_method = "POST"
}

resource "aws_apigatewayv2_route" "ws_connect" {
  api_id             = aws_apigatewayv2_api.ws.id
  route_key          = "$connect"
  target             = "integrations/${aws_apigatewayv2_integration.ws.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.ws.id
}

resource "aws_apigatewayv2_route" "ws_disconnect" {
  api_id    = aws_apigatewayv2_api.ws.id
  route_key = "$disconnect"
  target    = "integrations/${aws_apigatewayv2_integration.ws.id}"
}

resource "aws_apigatewayv2_route" "ws_default" {
  api_id    = aws_apigatewayv2_api.ws.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.ws.id}"
}

resource "aws_apigatewayv2_stage" "ws" {
  api_id      = aws_apigatewayv2_api.ws.id
  name        = "prod"
  auto_deploy = true
}

resource "aws_lambda_permission" "ws_handler" {
  statement_id  = "AllowWSAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = var.ws_handler_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.ws.execution_arn}/*/*"
}

resource "aws_lambda_permission" "ws_authorizer" {
  statement_id  = "AllowWSAuthorizerInvoke"
  action        = "lambda:InvokeFunction"
  function_name = var.authorizer_handler_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.ws.execution_arn}/authorizers/${aws_apigatewayv2_authorizer.ws.id}"
}

output "api_endpoint" {
  value = aws_apigatewayv2_api.rest.api_endpoint
}

output "websocket_endpoint" {
  value = "${aws_apigatewayv2_api.ws.api_endpoint}/prod"
}

output "websocket_api_endpoint" {
  value = "https://${aws_apigatewayv2_api.ws.id}.execute-api.${data.aws_region.current.name}.amazonaws.com/prod"
}

output "rest_api_id" {
  value = aws_apigatewayv2_api.rest.id
}

output "ws_api_id" {
  value = aws_apigatewayv2_api.ws.id
}
