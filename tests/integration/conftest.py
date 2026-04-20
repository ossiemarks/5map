"""Integration test fixtures and helpers."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List

import pytest


def make_rssi_payload(
    sensor_id: str = "pineapple-mk7-001",
    num_observations: int = 5,
    session_id: str = "test-session-001",
) -> Dict[str, Any]:
    """Create a valid RSSI observation window payload."""
    observations = []
    for i in range(num_observations):
        observations.append({
            "mac": f"aa:bb:cc:dd:ee:{i:02x}",
            "rssi_dbm": -45 - (i * 5),
            "noise_dbm": -90,
            "channel": 6,
            "bandwidth": "2.4GHz",
            "frame_type": "beacon" if i % 2 == 0 else "probe_request",
            "ssid": f"TestNet-{i}" if i % 3 == 0 else None,
            "is_randomized_mac": i % 4 == 0,
            "count": i + 1,
        })

    return {
        "timestamp": f"2026-04-20T20:{i:02d}:00Z",
        "sensor_id": sensor_id,
        "sensor_type": "rssi",
        "window_ms": 1000,
        "observations": observations,
        "position": {"x": float(i), "y": float(i), "label": f"point_{i}"},
    }


def make_kinesis_event(payloads: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Wrap payloads in a Kinesis event structure."""
    import base64

    records = []
    for payload in payloads:
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        records.append({
            "kinesis": {
                "data": encoded,
                "partitionKey": payload.get("sensor_id", "unknown"),
                "sequenceNumber": str(int(time.time() * 1000)),
            },
            "eventSource": "aws:kinesis",
        })
    return {"Records": records}


def make_api_event(
    method: str,
    path: str,
    path_params: Dict[str, str] | None = None,
    body: Any = None,
) -> Dict[str, Any]:
    """Create an API Gateway proxy event."""
    return {
        "httpMethod": method,
        "path": path,
        "requestContext": {
            "http": {"method": method, "path": path},
        },
        "pathParameters": path_params or {},
        "body": json.dumps(body) if body else None,
        "headers": {"Authorization": "Bearer test-token"},
    }


@pytest.fixture
def sample_rssi_payload():
    return make_rssi_payload()


@pytest.fixture
def sample_kinesis_event():
    payloads = [make_rssi_payload(num_observations=i + 3) for i in range(3)]
    return make_kinesis_event(payloads)
