"""Tests for Lambda preprocessor."""

import base64
import json
import os
from unittest.mock import patch, MagicMock

import pytest

# Set environment variables before importing handler
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("DYNAMODB_DEVICE_TABLE", "test-devices")
os.environ.setdefault("DYNAMODB_PRESENCE_TABLE", "test-presence")
os.environ.setdefault("WEBSOCKET_API_ENDPOINT", "https://test.execute-api.eu-west-2.amazonaws.com/prod")
os.environ.setdefault("SAGEMAKER_ENDPOINT", "")


def _make_kinesis_event(records_data):
    """Create a Kinesis event with base64-encoded records."""
    records = []
    for data in records_data:
        encoded = base64.b64encode(json.dumps(data).encode()).decode()
        records.append({
            "kinesis": {
                "data": encoded,
                "partitionKey": "test-key",
                "sequenceNumber": "123",
            },
            "eventSource": "aws:kinesis",
        })
    return {"Records": records}


def _make_valid_record():
    return {
        "timestamp": "2026-04-20T20:00:00Z",
        "sensor_id": "pineapple-001",
        "sensor_type": "rssi",
        "window_ms": 1000,
        "observations": [
            {
                "mac": "aa:bb:cc:dd:ee:ff",
                "rssi_dbm": -45,
                "noise_dbm": -90,
                "channel": 6,
                "bandwidth": "2.4GHz",
                "frame_type": "beacon",
                "ssid": "TestNet",
                "is_randomized_mac": False,
                "count": 3,
            }
        ],
        "position": {"x": 1.0, "y": 2.0, "label": "A"},
    }


class TestPreprocessor:
    @patch("backend.handlers.preprocessor.boto3")
    def test_handler_processes_valid_record(self, mock_boto3):
        from backend.handlers.preprocessor import handler

        mock_s3 = MagicMock()
        mock_dynamo = MagicMock()
        mock_dynamo.Table.return_value = MagicMock()
        mock_boto3.client.return_value = mock_s3
        mock_boto3.resource.return_value = mock_dynamo

        event = _make_kinesis_event([_make_valid_record()])
        result = handler(event, {})

        assert result is not None

    @patch("backend.handlers.preprocessor.boto3")
    def test_handler_skips_invalid_json(self, mock_boto3):
        from backend.handlers.preprocessor import handler

        records = [{
            "kinesis": {
                "data": base64.b64encode(b"not-json").decode(),
                "partitionKey": "test",
                "sequenceNumber": "1",
            },
            "eventSource": "aws:kinesis",
        }]
        event = {"Records": records}
        # Should not raise
        result = handler(event, {})
        assert result is not None

    @patch("backend.handlers.preprocessor.boto3")
    def test_handler_skips_record_missing_sensor_id(self, mock_boto3):
        from backend.handlers.preprocessor import handler

        bad_record = _make_valid_record()
        del bad_record["sensor_id"]
        event = _make_kinesis_event([bad_record])
        result = handler(event, {})
        assert result is not None

    @patch("backend.handlers.preprocessor.boto3")
    def test_handler_skips_empty_observations(self, mock_boto3):
        from backend.handlers.preprocessor import handler

        record = _make_valid_record()
        record["observations"] = []
        event = _make_kinesis_event([record])
        result = handler(event, {})
        assert result is not None
