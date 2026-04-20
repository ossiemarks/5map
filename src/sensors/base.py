"""Sensor base classes and universal data containers.

Defines the SensorBase ABC that all sensor implementations must follow,
and the SensorFrame universal data container for both RSSI and future CSI data.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class SensorType(enum.Enum):
    """Supported sensor data types."""

    RSSI = "rssi"
    CSI = "csi"


@dataclass(slots=True)
class SensorObservation:
    """Single observation from any sensor type."""

    mac: str
    rssi_dbm: int
    noise_dbm: Optional[int] = None
    channel: int = 0
    bandwidth: str = ""
    frame_type: str = ""
    ssid: Optional[str] = None
    is_randomized_mac: bool = False
    count: int = 1


@dataclass
class SensorFrame:
    """Universal data container for all sensor types.

    Both RSSI and CSI data fit in this structure. ML models consume
    the same schema regardless of sensor source.

    Attributes:
        version: Schema version for forward compatibility.
        timestamp: ISO 8601 timestamp of the frame.
        sensor_id: Unique identifier for the sensor device.
        sensor_type: Type of sensor (rssi or csi).
        window_ms: Duration of the observation window in milliseconds.
        observations: List of RSSI observations (populated for RSSI sensors).
        csi_matrix: Raw CSI amplitude/phase data (populated for CSI sensors, None for RSSI).
        position: Optional position tag from the mobile app.
        metadata: Arbitrary key-value pairs for sensor-specific data.
    """

    version: int = 1
    timestamp: str = ""
    sensor_id: str = ""
    sensor_type: SensorType = SensorType.RSSI
    window_ms: int = 1000
    observations: List[SensorObservation] = field(default_factory=list)
    csi_matrix: Optional[List[List[complex]]] = None
    position: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class SensorBase(ABC):
    """Abstract base class for all sensor implementations.

    Every sensor (RSSI Pineapple, future ESP32 CSI, etc.) must implement
    this interface to plug into the 5map pipeline.
    """

    @abstractmethod
    def configure(self, config: Dict[str, Any]) -> None:
        """Apply configuration to the sensor.

        Args:
            config: Sensor-specific configuration dict.

        Raises:
            ValueError: If configuration is invalid.
        """

    @abstractmethod
    def capture(self) -> Optional[SensorFrame]:
        """Capture a single frame of sensor data.

        Returns:
            A SensorFrame containing the captured data, or None if no data
            is available in this capture cycle.
        """

    @abstractmethod
    def health_check(self) -> bool:
        """Check if the sensor is operational.

        Returns:
            True if the sensor is functioning correctly.
        """

    @property
    @abstractmethod
    def sensor_id(self) -> str:
        """Unique identifier for this sensor instance."""

    @property
    @abstractmethod
    def sensor_type(self) -> SensorType:
        """The type of data this sensor produces."""
