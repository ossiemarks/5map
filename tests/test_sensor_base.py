"""Tests for SensorBase ABC and SensorFrame."""

import dataclasses
import json

import pytest

from src.sensors.base import SensorBase, SensorFrame, SensorObservation, SensorType


class TestSensorType:
    def test_rssi_value(self):
        assert SensorType.RSSI.value == "rssi"

    def test_csi_value(self):
        assert SensorType.CSI.value == "csi"


class TestSensorObservation:
    def test_create_with_defaults(self):
        obs = SensorObservation(mac="aa:bb:cc:dd:ee:ff", rssi_dbm=-45)
        assert obs.count == 1
        assert obs.noise_dbm is None
        assert obs.is_randomized_mac is False

    def test_create_full(self):
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
        assert obs.rssi_dbm == -45
        assert obs.is_randomized_mac is True


class TestSensorFrame:
    def test_default_version(self):
        frame = SensorFrame()
        assert frame.version == 1

    def test_empty_frame(self):
        frame = SensorFrame(
            timestamp="2026-04-20T20:00:00Z",
            sensor_id="test-001",
            sensor_type=SensorType.RSSI,
        )
        assert len(frame.observations) == 0
        assert frame.csi_matrix is None
        assert frame.position is None

    def test_frame_with_observations(self):
        obs = SensorObservation(mac="aa:bb:cc:dd:ee:ff", rssi_dbm=-45)
        frame = SensorFrame(
            timestamp="2026-04-20T20:00:00Z",
            sensor_id="test-001",
            sensor_type=SensorType.RSSI,
            observations=[obs],
            position={"x": 1.0, "y": 2.0, "label": "A"},
        )
        assert len(frame.observations) == 1
        assert frame.position["label"] == "A"

    def test_frame_serialization(self):
        obs = SensorObservation(mac="aa:bb:cc:dd:ee:ff", rssi_dbm=-45)
        frame = SensorFrame(
            timestamp="2026-04-20T20:00:00Z",
            sensor_id="test-001",
            sensor_type=SensorType.RSSI,
            observations=[obs],
        )
        data = dataclasses.asdict(frame)
        json_str = json.dumps(data, default=str)
        assert "aa:bb:cc:dd:ee:ff" in json_str

    def test_frame_with_metadata(self):
        frame = SensorFrame(metadata={"firmware": "1.2.3"})
        assert frame.metadata["firmware"] == "1.2.3"


class TestSensorBaseABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            SensorBase()

    def test_subclass_must_implement_all(self):
        class IncompleteSensor(SensorBase):
            pass

        with pytest.raises(TypeError):
            IncompleteSensor()

    def test_complete_subclass_works(self):
        class MockSensor(SensorBase):
            def configure(self, config):
                pass

            def capture(self):
                return None

            def health_check(self):
                return True

            @property
            def sensor_id(self):
                return "mock-001"

            @property
            def sensor_type(self):
                return SensorType.RSSI

        sensor = MockSensor()
        assert sensor.sensor_id == "mock-001"
        assert sensor.sensor_type == SensorType.RSSI
        assert sensor.health_check() is True
        assert sensor.capture() is None
