"""Tests for FrameRouter normalization."""

import pytest

from src.sensors.base import SensorFrame, SensorObservation, SensorType
from src.pipeline.frame_router import FrameRouter, UnifiedFeatures


class TestFrameRouter:
    def setup_method(self):
        self.router = FrameRouter()

    def test_normalize_rssi_frame(self):
        obs = SensorObservation(
            mac="aa:bb:cc:dd:ee:ff",
            rssi_dbm=-45,
            channel=6,
            bandwidth="2.4GHz",
            frame_type="beacon",
        )
        frame = SensorFrame(
            timestamp="2026-04-20T20:00:00Z",
            sensor_id="test-001",
            sensor_type=SensorType.RSSI,
            observations=[obs],
            position={"x": 1.0, "y": 2.0, "label": "A"},
        )
        result = self.router.normalize(frame)
        assert result is not None
        assert result.source_type == SensorType.RSSI
        assert len(result.signal_strength_vector) == 1
        assert result.signal_strength_vector[0] == -45.0
        assert result.mac_addresses[0] == "aa:bb:cc:dd:ee:ff"
        assert result.observation_count == 1
        assert result.position["label"] == "A"

    def test_normalize_empty_rssi_frame(self):
        frame = SensorFrame(
            timestamp="2026-04-20T20:00:00Z",
            sensor_id="test-001",
            sensor_type=SensorType.RSSI,
            observations=[],
        )
        result = self.router.normalize(frame)
        assert result is not None
        assert len(result.signal_strength_vector) == 0
        assert result.observation_count == 0

    def test_normalize_none_returns_none(self):
        assert self.router.normalize(None) is None

    def test_normalize_missing_timestamp_returns_none(self):
        frame = SensorFrame(sensor_id="test-001", sensor_type=SensorType.RSSI)
        assert self.router.normalize(frame) is None

    def test_normalize_missing_sensor_id_returns_none(self):
        frame = SensorFrame(timestamp="2026-04-20T20:00:00Z", sensor_type=SensorType.RSSI)
        assert self.router.normalize(frame) is None

    def test_normalize_multiple_observations(self):
        obs1 = SensorObservation(mac="aa:bb:cc:dd:ee:01", rssi_dbm=-45)
        obs2 = SensorObservation(mac="aa:bb:cc:dd:ee:02", rssi_dbm=-60)
        obs3 = SensorObservation(mac="aa:bb:cc:dd:ee:03", rssi_dbm=-80)
        frame = SensorFrame(
            timestamp="2026-04-20T20:00:00Z",
            sensor_id="test-001",
            sensor_type=SensorType.RSSI,
            observations=[obs1, obs2, obs3],
        )
        result = self.router.normalize(frame)
        assert result.observation_count == 3
        assert result.signal_strength_vector == [-45.0, -60.0, -80.0]

    def test_normalize_preserves_device_features(self):
        obs = SensorObservation(
            mac="aa:bb:cc:dd:ee:ff",
            rssi_dbm=-45,
            noise_dbm=-90,
            channel=6,
            bandwidth="2.4GHz",
            frame_type="beacon",
            ssid="TestNet",
            is_randomized_mac=True,
            count=5,
        )
        frame = SensorFrame(
            timestamp="2026-04-20T20:00:00Z",
            sensor_id="test-001",
            sensor_type=SensorType.RSSI,
            observations=[obs],
        )
        result = self.router.normalize(frame)
        df = result.device_features[0]
        assert df["ssid"] == "TestNet"
        assert df["is_randomized_mac"] is True
        assert df["count"] == 5

    def test_normalize_csi_frame(self):
        frame = SensorFrame(
            timestamp="2026-04-20T20:00:00Z",
            sensor_id="esp32-001",
            sensor_type=SensorType.CSI,
            csi_matrix=[[1 + 2j, 3 + 4j], [5 + 0j, 0 + 6j]],
        )
        result = self.router.normalize(frame)
        assert result is not None
        assert result.source_type == SensorType.CSI
        assert result.amplitude_matrix is not None
        assert len(result.amplitude_matrix) == 2
