variable "prefix" { type = string }
variable "shard_count" {
  type    = number
  default = 1
}

resource "aws_kinesis_stream" "rssi" {
  name             = "${var.prefix}-rssi-stream"
  shard_count      = var.shard_count
  retention_period = 24

  stream_mode_details {
    stream_mode = "PROVISIONED"
  }
}

resource "aws_kinesis_stream" "csi" {
  name             = "${var.prefix}-csi-stream"
  shard_count      = var.shard_count
  retention_period = 24

  stream_mode_details {
    stream_mode = "PROVISIONED"
  }
}

output "stream_arn" {
  value = aws_kinesis_stream.rssi.arn
}

output "stream_name" {
  value = aws_kinesis_stream.rssi.name
}

output "csi_stream_arn" {
  value = aws_kinesis_stream.csi.arn
}

output "csi_stream_name" {
  value = aws_kinesis_stream.csi.name
}
