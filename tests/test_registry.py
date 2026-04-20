"""Tests for sensor plugin registry."""

import pytest

from src.sensors.base import SensorBase, SensorType
from src.sensors.registry import SensorRegistry


class MockSensor(SensorBase):
    def configure(self, config):
        pass

    def capture(self):
        return None

    def health_check(self):
        return True

    @property
    def sensor_id(self):
        return "mock"

    @property
    def sensor_type(self):
        return SensorType.RSSI


class AnotherMockSensor(SensorBase):
    def configure(self, config):
        pass

    def capture(self):
        return None

    def health_check(self):
        return True

    @property
    def sensor_id(self):
        return "another"

    @property
    def sensor_type(self):
        return SensorType.CSI


class TestSensorRegistry:
    def test_register_and_get(self):
        registry = SensorRegistry()
        registry.register("rssi", MockSensor)
        assert registry.get("rssi") is MockSensor

    def test_register_duplicate_raises(self):
        registry = SensorRegistry()
        registry.register("rssi", MockSensor)
        with pytest.raises(ValueError, match="already registered"):
            registry.register("rssi", AnotherMockSensor)

    def test_register_non_sensor_raises(self):
        registry = SensorRegistry()
        with pytest.raises(TypeError, match="subclass of SensorBase"):
            registry.register("bad", dict)

    def test_get_unknown_raises(self):
        registry = SensorRegistry()
        with pytest.raises(KeyError, match="No sensor registered"):
            registry.get("nonexistent")

    def test_remove(self):
        registry = SensorRegistry()
        registry.register("rssi", MockSensor)
        registry.remove("rssi")
        assert "rssi" not in registry

    def test_remove_unknown_raises(self):
        registry = SensorRegistry()
        with pytest.raises(KeyError):
            registry.remove("nonexistent")

    def test_list_sensors(self):
        registry = SensorRegistry()
        registry.register("rssi", MockSensor)
        registry.register("csi", AnotherMockSensor)
        names = registry.list_sensors()
        assert "rssi" in names
        assert "csi" in names

    def test_contains(self):
        registry = SensorRegistry()
        registry.register("rssi", MockSensor)
        assert "rssi" in registry
        assert "csi" not in registry

    def test_len(self):
        registry = SensorRegistry()
        assert len(registry) == 0
        registry.register("rssi", MockSensor)
        assert len(registry) == 1

    def test_thread_safety(self):
        """Register from multiple threads without corruption."""
        import threading

        registry = SensorRegistry()
        errors = []

        def register_sensor(name, cls):
            try:
                registry.register(name, cls)
            except ValueError:
                pass  # duplicate is expected from concurrent registration
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=register_sensor, args=(f"sensor_{i}", MockSensor))
            for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(registry) == 20
