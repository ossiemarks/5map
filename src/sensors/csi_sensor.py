"""CSI sensor implementation for ESP32 WiFi Channel State Information.

Receives CSI data from the ESP32 bridge and converts it to SensorFrames
for the unified 5map pipeline. CSI provides subcarrier-level amplitude
and phase data for high-resolution environment mapping.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.sensors.base import SensorBase, SensorFrame, SensorObservation, SensorType

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CSIObservation:
    """Single CSI frame observation from ESP32."""

    mac: str
    rssi_dbm: int
    channel: int
    bandwidth: int       # 20 or 40 MHz
    csi_len: int         # number of subcarriers
    timestamp_ms: int    # ESP32 uptime timestamp


@dataclass
class CSIWindow:
    """Time-bounded collection of CSI observations."""

    timestamp: str
    sensor_id: str
    window_ms: int
    observations: List[CSIObservation] = field(default_factory=list)


class CSIWindowAggregator:
    """Aggregate CSI observations into fixed time windows."""

    def __init__(self, sensor_id: str, window_ms: int = 1000,
                 max_observations: int = 5000) -> None:
        self._sensor_id = sensor_id
        self._window_ms = window_ms
        self._max_observations = max_observations
        self._observations: List[CSIObservation] = []

    def add(self, obs: CSIObservation) -> None:
        """Add a CSI observation to the current window."""
        if len(self._observations) < self._max_observations:
            self._observations.append(obs)

    def flush(self) -> CSIWindow:
        """Seal and return the current window."""
        window = CSIWindow(
            timestamp=datetime.now(timezone.utc).isoformat(),
            sensor_id=self._sensor_id,
            window_ms=self._window_ms,
            observations=list(self._observations),
        )
        self._observations.clear()
        return window


class CSISensor(SensorBase):
    """ESP32 CSI sensor that converts CSI windows to SensorFrames."""

    def __init__(self) -> None:
        self._sensor_id: str = ""
        self._config: Dict[str, Any] = {}
        self._healthy: bool = False
        self._pending_window: Optional[CSIWindow] = None

    def configure(self, config: Dict[str, Any]) -> None:
        if "sensor_id" not in config:
            raise ValueError("Config must contain 'sensor_id'")
        self._sensor_id = config["sensor_id"]
        self._config = config
        self._healthy = True
        logger.info("CSISensor configured: %s", self._sensor_id)

    def feed_window(self, window: CSIWindow) -> None:
        """Feed a CSIWindow from the ESP32 bridge."""
        self._pending_window = window

    def capture(self) -> Optional[SensorFrame]:
        """Convert a pending CSIWindow to a SensorFrame."""
        window = self._pending_window
        if window is None:
            return None

        self._pending_window = None

        observations = [
            SensorObservation(
                mac=obs.mac,
                rssi_dbm=obs.rssi_dbm,
                channel=obs.channel,
                bandwidth=f"{obs.bandwidth}MHz",
                frame_type="csi",
                count=1,
            )
            for obs in window.observations
        ]

        return SensorFrame(
            version=1,
            timestamp=window.timestamp,
            sensor_id=window.sensor_id,
            sensor_type=SensorType.CSI,
            window_ms=window.window_ms,
            observations=observations,
            metadata={
                "source": "esp32_csi",
                "csi_summary": {
                    "total_frames": len(window.observations),
                    "unique_macs": len(set(o.mac for o in window.observations)),
                    "channels": list(set(o.channel for o in window.observations)),
                },
            },
        )

    def health_check(self) -> bool:
        return self._healthy

    @property
    def sensor_id(self) -> str:
        return self._sensor_id

    @property
    def sensor_type(self) -> SensorType:
        return SensorType.CSI
