"""Integration tests for the full data pipeline.

Tests the flow: RSSI data -> preprocessor -> DynamoDB -> API -> response
using mocked AWS services (no real AWS calls).
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from tests.integration.conftest import make_rssi_payload, make_kinesis_event, make_api_event

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("DYNAMODB_DEVICE_TABLE", "test-devices")
os.environ.setdefault("DYNAMODB_PRESENCE_TABLE", "test-presence")
os.environ.setdefault("DYNAMODB_MAPS_TABLE", "test-maps")
os.environ.setdefault("DYNAMODB_SESSIONS_TABLE", "test-sessions")
os.environ.setdefault("WEBSOCKET_API_ENDPOINT", "https://test.execute-api.eu-west-2.amazonaws.com/prod")
os.environ.setdefault("SAGEMAKER_ENDPOINT", "")


class TestPreprocessorPipeline:
    """Test preprocessor Lambda with realistic Kinesis input."""

    @patch("backend.handlers.preprocessor.boto3")
    def test_processes_batch_of_windows(self, mock_boto3):
        for mod in list(sys.modules):
            if "preprocessor" in mod:
                del sys.modules[mod]
        from backend.handlers.preprocessor import handler

        mock_s3 = MagicMock()
        mock_table = MagicMock()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3.client.return_value = mock_s3
        mock_boto3.resource.return_value = mock_resource

        payloads = [make_rssi_payload(num_observations=i + 2) for i in range(5)]
        event = make_kinesis_event(payloads)

        result = handler(event, {})
        assert result is not None

    @patch("backend.handlers.preprocessor.boto3")
    def test_handles_mixed_valid_invalid(self, mock_boto3):
        for mod in list(sys.modules):
            if "preprocessor" in mod:
                del sys.modules[mod]
        from backend.handlers.preprocessor import handler

        valid = make_rssi_payload(num_observations=5)
        invalid_no_sensor = {"timestamp": "2026-04-20T20:00:00Z", "observations": []}
        invalid_empty = {"sensor_id": "test", "timestamp": "2026-04-20T20:00:00Z", "observations": []}

        event = make_kinesis_event([valid, invalid_no_sensor, invalid_empty])

        mock_boto3.client.return_value = MagicMock()
        mock_boto3.resource.return_value = MagicMock()

        result = handler(event, {})
        assert result is not None


class TestAPIPipeline:
    """Test API handler with realistic requests."""

    @patch("boto3.resource")
    def test_create_session_and_query(self, mock_resource):
        mock_table = MagicMock()
        mock_table.put_item.return_value = {}
        mock_table.query.return_value = {"Items": []}
        mock_resource.return_value.Table.return_value = mock_table

        for mod in list(sys.modules):
            if "api_handler" in mod:
                del sys.modules[mod]
        from backend.handlers.api_handler import handler

        # Create session
        create_event = make_api_event("POST", "/api/sessions", body={"name": "Integration Test"})
        create_result = handler(create_event, {})
        assert create_result["statusCode"] in (200, 201)
        session = json.loads(create_result["body"])
        assert "session_id" in session

        # Query devices
        devices_event = make_api_event(
            "GET",
            f"/api/devices/{session['session_id']}",
            {"session_id": session["session_id"]},
        )
        devices_result = handler(devices_event, {})
        assert devices_result["statusCode"] == 200


class TestMLPipeline:
    """Test ML model inference pipeline."""

    def test_env_mapper_end_to_end(self):
        from ml.models.env_mapper import EnvironmentMapper
        from ml.data.synthetic import generate_synthetic_rssi_grid

        raw = generate_synthetic_rssi_grid(num_positions=15)
        positions = []
        for item in raw:
            pos = item.get("position", (0, 0))
            readings = item.get("rssi_readings", {})
            positions.append({
                "x": pos[0] if isinstance(pos, (tuple, list)) else 0,
                "y": pos[1] if isinstance(pos, (tuple, list)) else 0,
                "rssi_values": list(readings.values()) if isinstance(readings, dict) else [],
            })

        mapper = EnvironmentMapper(grid_size=20)
        mapper.fit(positions)
        result = mapper.predict_heatmap()

        assert "heatmap" in result
        assert len(result["heatmap"]) > 0
        assert result["confidence"] > 0

    def test_device_fp_end_to_end(self):
        import random
        from ml.models.device_fp import DeviceFingerprinter

        training = []
        for _ in range(60):
            dtype = random.choice(["phone", "laptop", "iot", "ap", "unknown"])
            training.append({
                "features": {
                    "oui_vendor": random.choice(["Apple", "Intel", "Cisco"]),
                    "is_randomized_mac": random.choice([True, False]),
                    "probe_frequency": round(random.uniform(0.1, 10), 2),
                    "rssi_variance": round(random.uniform(0.5, 20), 2),
                    "num_unique_channels": random.randint(1, 11),
                    "beacon_pct": round(random.uniform(0, 1), 2),
                    "probe_pct": round(random.uniform(0, 1), 2),
                    "data_pct": round(random.uniform(0, 1), 2),
                    "mgmt_pct": round(random.uniform(0, 1), 2),
                    "ssid_probe_count": random.randint(0, 10),
                },
                "label": dtype,
            })

        fp = DeviceFingerprinter()
        fp.fit(training)
        result = fp.predict([training[0]["features"]])
        assert "device_type" in result
        assert "risk_score" in result

    def test_presence_detector_end_to_end(self):
        from ml.models.presence_lstm import PresenceDetector

        detector = PresenceDetector()
        windows = [
            {"mean_rssi": -50, "rssi_variance": 2, "device_count": 3, "new_device_count": 0}
            for _ in range(5)
        ]
        result = detector.predict(windows)
        assert result["event"] in ("empty", "stationary", "moving", "entry", "exit")
        assert 0 <= result["confidence"] <= 1
