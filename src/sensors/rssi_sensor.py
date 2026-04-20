"""RSSI sensor implementation wrapping the Pineapple capture agent.

Adapts the Pineapple RSSI capture system to the SensorBase interface,
allowing it to plug into the unified 5map pipeline.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pineapple.parsers.rssi_parser import ObservationWindow
from src.sensors.base import SensorBase, SensorFrame, SensorObservation, SensorType

logger = logging.getLogger(__name__)


class RSSISensor(SensorBase):
    """Pineapple RSSI sensor that converts ObservationWindows to SensorFrames."""

    def __init__(self) -> None:
        self._sensor_id: str = ""
        self._config: Dict[str, Any] = {}
        self._healthy: bool = False
        self._pending_window: Optional[ObservationWindow] = None

    def configure(self, config: Dict[str, Any]) -> None:
        """Configure the RSSI sensor.

        Args:
            config: Must contain 'sensor_id' key.

        Raises:
            ValueError: If sensor_id is missing.
        """
        if "sensor_id" not in config:
            raise ValueError("Config must contain 'sensor_id'")
        self._sensor_id = config["sensor_id"]
        self._config = config
        self._healthy = True
        logger.info("RSSISensor configured: %s", self._sensor_id)

    def feed_window(self, window: ObservationWindow) -> None:
        """Feed an ObservationWindow from the Pineapple capture agent.

        This bridges the Pineapple-specific capture code with the
        generic sensor interface.

        Args:
            window: An ObservationWindow from the RSSI parser.
        """
        self._pending_window = window

    def capture(self) -> Optional[SensorFrame]:
        """Convert a pending ObservationWindow to a SensorFrame.

        Returns:
            SensorFrame if a window is pending, None otherwise.
        """
        window = self._pending_window
        if window is None:
            return None

        self._pending_window = None

        observations = [
            SensorObservation(
                mac=obs.mac,
                rssi_dbm=obs.rssi_dbm,
                noise_dbm=obs.noise_dbm,
                channel=obs.channel,
                bandwidth=obs.bandwidth,
                frame_type=obs.frame_type,
                ssid=obs.ssid,
                is_randomized_mac=obs.is_randomized_mac,
                count=obs.count,
            )
            for obs in window.observations
        ]

        return SensorFrame(
            version=1,
            timestamp=window.timestamp,
            sensor_id=window.sensor_id,
            sensor_type=SensorType.RSSI,
            window_ms=window.window_ms,
            observations=observations,
            csi_matrix=None,
            position=window.position,
        )

    def health_check(self) -> bool:
        return self._healthy

    @property
    def sensor_id(self) -> str:
        return self._sensor_id

    @property
    def sensor_type(self) -> SensorType:
        return SensorType.RSSI
