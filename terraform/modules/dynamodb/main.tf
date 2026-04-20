variable "prefix" { type = string }

resource "aws_dynamodb_table" "environment_maps" {
  name         = "${var.prefix}-environment-maps"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_id"
  range_key    = "timestamp"

  attribute {
    name = "session_id"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "S"
  }

  attribute {
    name = "sensor_id"
    type = "S"
  }

  global_secondary_index {
    name            = "sensor-id-index"
    hash_key        = "sensor_id"
    range_key       = "timestamp"
    projection_type = "ALL"
  }
}

resource "aws_dynamodb_table" "device_tracks" {
  name         = "${var.prefix}-device-tracks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_id"
  range_key    = "mac_address"

  attribute {
    name = "session_id"
    type = "S"
  }

  attribute {
    name = "mac_address"
    type = "S"
  }

  attribute {
    name = "device_type"
    type = "S"
  }

  global_secondary_index {
    name            = "device-type-index"
    hash_key        = "device_type"
    range_key       = "session_id"
    projection_type = "ALL"
  }
}

resource "aws_dynamodb_table" "presence_events" {
  name         = "${var.prefix}-presence-events"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_id"
  range_key    = "event_key"

  attribute {
    name = "session_id"
    type = "S"
  }

  attribute {
    name = "event_key"
    type = "S"
  }

  attribute {
    name = "zone"
    type = "S"
  }

  global_secondary_index {
    name            = "zone-index"
    hash_key        = "zone"
    range_key       = "event_key"
    projection_type = "ALL"
  }
}

resource "aws_dynamodb_table" "sessions" {
  name         = "${var.prefix}-sessions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_id"

  attribute {
    name = "session_id"
    type = "S"
  }
}

resource "aws_dynamodb_table" "connections" {
  name         = "${var.prefix}-connections"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "connection_id"

  attribute {
    name = "connection_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}

output "maps_table_name" { value = aws_dynamodb_table.environment_maps.name }
output "maps_table_arn" { value = aws_dynamodb_table.environment_maps.arn }
output "device_table_name" { value = aws_dynamodb_table.device_tracks.name }
output "device_table_arn" { value = aws_dynamodb_table.device_tracks.arn }
output "presence_table_name" { value = aws_dynamodb_table.presence_events.name }
output "presence_table_arn" { value = aws_dynamodb_table.presence_events.arn }
output "sessions_table_name" { value = aws_dynamodb_table.sessions.name }
output "sessions_table_arn" { value = aws_dynamodb_table.sessions.arn }
output "connections_table_name" { value = aws_dynamodb_table.connections.name }
output "connections_table_arn" { value = aws_dynamodb_table.connections.arn }
