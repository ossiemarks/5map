"""Sensor plugin registry.

Allows sensor implementations to register themselves by type,
enabling new sensors to be added without modifying existing code.
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional, Type

from src.sensors.base import SensorBase, SensorType

logger = logging.getLogger(__name__)


class SensorRegistry:
    """Thread-safe registry for sensor implementations.

    Usage:
        registry = SensorRegistry()
        registry.register("rssi", RSSISensor)
        sensor_cls = registry.get("rssi")
        sensor = sensor_cls()
    """

    def __init__(self) -> None:
        self._registry: Dict[str, Type[SensorBase]] = {}
        self._lock = threading.Lock()

    def register(self, name: str, sensor_cls: Type[SensorBase]) -> None:
        """Register a sensor implementation.

        Args:
            name: Unique name for this sensor type (e.g., "rssi", "csi_esp32").
            sensor_cls: Class that implements SensorBase.

        Raises:
            TypeError: If sensor_cls does not subclass SensorBase.
            ValueError: If name is already registered.
        """
        if not (isinstance(sensor_cls, type) and issubclass(sensor_cls, SensorBase)):
            raise TypeError(
                f"{sensor_cls} must be a subclass of SensorBase"
            )

        with self._lock:
            if name in self._registry:
                raise ValueError(
                    f"Sensor '{name}' is already registered as {self._registry[name]}"
                )
            self._registry[name] = sensor_cls
            logger.info("Registered sensor: %s -> %s", name, sensor_cls.__name__)

    def get(self, name: str) -> Type[SensorBase]:
        """Retrieve a registered sensor class.

        Args:
            name: The registered sensor name.

        Returns:
            The sensor class.

        Raises:
            KeyError: If no sensor is registered with this name.
        """
        with self._lock:
            if name not in self._registry:
                available = ", ".join(self._registry.keys()) or "(none)"
                raise KeyError(
                    f"No sensor registered as '{name}'. Available: {available}"
                )
            return self._registry[name]

    def remove(self, name: str) -> None:
        """Remove a sensor from the registry.

        Args:
            name: The registered sensor name.

        Raises:
            KeyError: If no sensor is registered with this name.
        """
        with self._lock:
            if name not in self._registry:
                raise KeyError(f"No sensor registered as '{name}'")
            del self._registry[name]
            logger.info("Removed sensor: %s", name)

    def list_sensors(self) -> List[str]:
        """Return all registered sensor names."""
        with self._lock:
            return list(self._registry.keys())

    def __contains__(self, name: str) -> bool:
        with self._lock:
            return name in self._registry

    def __len__(self) -> int:
        with self._lock:
            return len(self._registry)
