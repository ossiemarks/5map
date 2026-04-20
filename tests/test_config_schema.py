"""Tests for pydantic configuration schema."""

import pytest
from pydantic import ValidationError

from src.config.schema import (
    CaptureConfig,
    FiveMapConfig,
    LoggingConfig,
    MQTTConfig,
    RadioConfig,
    SensorConfig,
    TransportConfig,
)


class TestRadioConfig:
    def test_valid_config(self):
        cfg = RadioConfig(interface="wlan0", band="5GHz", channels=[36, 40])
        assert cfg.interface == "wlan0"

    def test_empty_channels_raises(self):
        with pytest.raises(ValidationError, match="cannot be empty"):
            RadioConfig(interface="wlan0", band="5GHz", channels=[])

    def test_invalid_band_raises(self):
        with pytest.raises(ValidationError, match="band must be"):
            RadioConfig(interface="wlan0", band="6GHz", channels=[1])


class TestCaptureConfig:
    def test_defaults(self):
        cfg = CaptureConfig()
        assert cfg.window_seconds == 1.0
        assert cfg.max_observations_per_window == 10000

    def test_negative_window_raises(self):
        with pytest.raises(ValidationError, match="must be positive"):
            CaptureConfig(window_seconds=-1)


class TestLoggingConfig:
    def test_valid_level(self):
        cfg = LoggingConfig(level="debug")
        assert cfg.level == "DEBUG"

    def test_invalid_level_raises(self):
        with pytest.raises(ValidationError, match="level must be"):
            LoggingConfig(level="verbose")


class TestSensorConfig:
    def test_required_id(self):
        cfg = SensorConfig(id="pineapple-001")
        assert cfg.id == "pineapple-001"
        assert cfg.type == "rssi"


class TestFiveMapConfig:
    def test_minimal_valid(self):
        cfg = FiveMapConfig(sensor=SensorConfig(id="test"))
        assert cfg.schema_version == 1
        assert cfg.sensor.id == "test"

    def test_from_dict(self):
        data = {
            "sensor": {"id": "pineapple-mk7-001"},
            "radios": {
                "radio_5ghz": {
                    "interface": "wlan0",
                    "band": "5GHz",
                    "channels": [36, 40, 44],
                },
            },
            "capture": {"window_seconds": 2.0},
        }
        cfg = FiveMapConfig.model_validate(data)
        assert cfg.sensor.id == "pineapple-mk7-001"
        assert cfg.radios["radio_5ghz"].band == "5GHz"
        assert cfg.capture.window_seconds == 2.0

    def test_from_yaml(self, tmp_path):
        yaml_content = """
sensor:
  id: test-from-yaml
  type: rssi
radios:
  radio_5ghz:
    interface: wlan0
    band: "5GHz"
    channels: [36, 40]
capture:
  window_seconds: 1.5
"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content)
        cfg = FiveMapConfig.from_yaml(str(config_file))
        assert cfg.sensor.id == "test-from-yaml"
        assert cfg.capture.window_seconds == 1.5

    def test_from_yaml_missing_file(self):
        with pytest.raises(FileNotFoundError):
            FiveMapConfig.from_yaml("/nonexistent/config.yaml")

    def test_schema_version_default(self):
        cfg = FiveMapConfig(sensor=SensorConfig(id="test"))
        assert cfg.schema_version == 1
