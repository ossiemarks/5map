"""Tests for the multi-sensor fingerprint collector."""

import pytest

from src.pipeline.fingerprint_collector import (
    FingerprintCollector,
    SensorObservationRecord,
)


class TestFingerprintCollector:
    def setup_method(self):
        self.sensor_ids = ["router", "esp32", "pineapple"]
        self.collector = FingerprintCollector(
            sensor_ids=self.sensor_ids,
            window_ms=5000,
            min_sensors=2,
        )

    def test_single_sensor_not_enough(self):
        """Device seen by only 1 sensor should not produce a fingerprint."""
        self.collector.add_observation(
            SensorObservationRecord(
                mac="AA:BB:CC:DD:EE:FF",
                sensor_id="router",
                rssi_dbm=-50,
                timestamp_ms=1000,
            )
        )
        fps = self.collector.flush()
        assert len(fps) == 0

    def test_two_sensors_produces_fingerprint(self):
        """Device seen by 2+ sensors should produce a fingerprint."""
        self.collector.add_observation(
            SensorObservationRecord(
                mac="AA:BB:CC:DD:EE:FF",
                sensor_id="router",
                rssi_dbm=-50,
                timestamp_ms=1000,
            )
        )
        self.collector.add_observation(
            SensorObservationRecord(
                mac="AA:BB:CC:DD:EE:FF",
                sensor_id="esp32",
                rssi_dbm=-60,
                timestamp_ms=1000,
            )
        )
        fps = self.collector.flush()
        assert len(fps) == 1
        assert fps[0].mac == "AA:BB:CC:DD:EE:FF"
        assert fps[0].sensor_rssi["router"] == -50
        assert fps[0].sensor_rssi["esp32"] == -60

    def test_multiple_devices(self):
        """Multiple devices should each get their own fingerprint."""
        for mac in ["AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02"]:
            for sid in ["router", "esp32"]:
                self.collector.add_observation(
                    SensorObservationRecord(
                        mac=mac, sensor_id=sid, rssi_dbm=-55, timestamp_ms=1000,
                    )
                )
        fps = self.collector.flush()
        assert len(fps) == 2

    def test_rssi_averaging(self):
        """Multiple readings from same sensor should be averaged."""
        for rssi in [-40, -50, -60]:
            self.collector.add_observation(
                SensorObservationRecord(
                    mac="AA:BB:CC:DD:EE:FF",
                    sensor_id="router",
                    rssi_dbm=rssi,
                    timestamp_ms=1000,
                )
            )
        self.collector.add_observation(
            SensorObservationRecord(
                mac="AA:BB:CC:DD:EE:FF",
                sensor_id="esp32",
                rssi_dbm=-55,
                timestamp_ms=1000,
            )
        )
        fps = self.collector.flush()
        assert len(fps) == 1
        assert fps[0].sensor_rssi["router"] == -50  # avg of -40,-50,-60

    def test_statistical_features_computed(self):
        """BiCN statistical features should be present."""
        for i in range(5):
            for sid in ["router", "esp32"]:
                self.collector.add_observation(
                    SensorObservationRecord(
                        mac="AA:BB:CC:DD:EE:FF",
                        sensor_id=sid,
                        rssi_dbm=-50 - i,
                        timestamp_ms=1000 + i * 1000,
                    )
                )
            self.collector.flush()  # Flush each cycle to accumulate history

        # Add final observations
        for sid in ["router", "esp32"]:
            self.collector.add_observation(
                SensorObservationRecord(
                    mac="AA:BB:CC:DD:EE:FF",
                    sensor_id=sid,
                    rssi_dbm=-55,
                    timestamp_ms=10000,
                )
            )
        fps = self.collector.flush()
        assert len(fps) == 1
        stats = fps[0].statistical_features
        assert "router" in stats
        assert len(stats["router"]) == 4  # mean, std, skew, kurt

    def test_bulk_add(self):
        """Bulk add from device list format."""
        devices = [
            {"mac_address": "AA:BB:CC:DD:EE:01", "rssi_dbm": -50},
            {"mac_address": "AA:BB:CC:DD:EE:02", "rssi_dbm": -60},
        ]
        self.collector.add_observations_bulk("router", devices)
        self.collector.add_observations_bulk("esp32", devices)
        fps = self.collector.flush()
        assert len(fps) == 2

    def test_feature_vector_correct_dim(self):
        """Feature vector should be 15-dim for 3 sensors."""
        for sid in self.sensor_ids:
            self.collector.add_observation(
                SensorObservationRecord(
                    mac="AA:BB:CC:DD:EE:FF",
                    sensor_id=sid,
                    rssi_dbm=-55,
                    timestamp_ms=1000,
                )
            )
        fps = self.collector.flush()
        vec = self.collector.build_feature_vector(fps[0])
        assert len(vec) == 15  # 3 RSSI + 12 statistical

    def test_flush_clears_pending(self):
        """Flush should clear pending observations."""
        for sid in ["router", "esp32"]:
            self.collector.add_observation(
                SensorObservationRecord(
                    mac="AA:BB:CC:DD:EE:FF",
                    sensor_id=sid,
                    rssi_dbm=-55,
                    timestamp_ms=1000,
                )
            )
        self.collector.flush()
        fps2 = self.collector.flush()
        assert len(fps2) == 0
