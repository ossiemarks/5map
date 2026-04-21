"""BLE sensor implementation for ESP32 Bluetooth scan data.

Receives BLE advertisement data from the ESP32 bridge and converts it
to SensorFrames for the unified 5map pipeline. Bluetooth observations
are stored alongside WiFi RSSI data for comprehensive RF mapping.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.sensors.base import SensorBase, SensorFrame, SensorObservation, SensorType

logger = logging.getLogger(__name__)


# Company ID -> manufacturer name (common BLE manufacturers)
_COMPANY_IDS: Dict[str, str] = {
    "004C": "Apple",
    "0075": "Samsung",
    "0006": "Microsoft",
    "00E0": "Google",
    "0059": "Nordic Semiconductor",
    "000D": "Texas Instruments",
    "0087": "Garmin",
    "038F": "Xiaomi",
    "0157": "Huawei",
    "0310": "Fitbit",
    "0822": "Tile",
    "FFFF": "Test/Development",
}


def resolve_manufacturer(company_hex: str) -> str:
    """Resolve a BLE company ID hex string to a manufacturer name."""
    return _COMPANY_IDS.get(company_hex.upper(), f"Unknown ({company_hex})")


@dataclass(slots=True)
class BLEObservation:
    """Single BLE advertisement observation from ESP32."""

    mac: str
    device_name: str
    rssi_dbm: int
    tx_power: Optional[int]
    adv_type: int
    service_uuids: List[str]
    manufacturer_id: str
    is_connectable: bool
    count: int = 1


@dataclass
class BLEWindow:
    """Time-bounded collection of BLE observations."""

    timestamp: str
    sensor_id: str
    window_ms: int
    observations: List[BLEObservation] = field(default_factory=list)


class BLEWindowAggregator:
    """Aggregate BLE observations into fixed time windows.

    Deduplicates by MAC address, keeping the strongest RSSI and
    merging metadata (name, services) across advertisements.
    """

    def __init__(self, sensor_id: str, window_ms: int = 2000,
                 max_observations: int = 500) -> None:
        self._sensor_id = sensor_id
        self._window_ms = window_ms
        self._max_observations = max_observations
        self._observations: Dict[str, BLEObservation] = {}
        self._window_start: float = 0.0

    def add(self, obs: BLEObservation) -> None:
        """Add an observation to the current window."""
        existing = self._observations.get(obs.mac)
        if existing is not None:
            existing.count += 1
            if obs.rssi_dbm > existing.rssi_dbm:
                existing.rssi_dbm = obs.rssi_dbm
            if obs.device_name and not existing.device_name:
                existing.device_name = obs.device_name
            if obs.tx_power is not None and existing.tx_power is None:
                existing.tx_power = obs.tx_power
            for svc in obs.service_uuids:
                if svc not in existing.service_uuids:
                    existing.service_uuids.append(svc)
        else:
            if len(self._observations) < self._max_observations:
                self._observations[obs.mac] = obs

    def flush(self) -> BLEWindow:
        """Seal and return the current window, resetting for the next."""
        window = BLEWindow(
            timestamp=datetime.now(timezone.utc).isoformat(),
            sensor_id=self._sensor_id,
            window_ms=self._window_ms,
            observations=list(self._observations.values()),
        )
        self._observations.clear()
        return window


class BLESensor(SensorBase):
    """ESP32 BLE sensor that converts BLE windows to SensorFrames."""

    def __init__(self) -> None:
        self._sensor_id: str = ""
        self._config: Dict[str, Any] = {}
        self._healthy: bool = False
        self._pending_window: Optional[BLEWindow] = None

    def configure(self, config: Dict[str, Any]) -> None:
        if "sensor_id" not in config:
            raise ValueError("Config must contain 'sensor_id'")
        self._sensor_id = config["sensor_id"]
        self._config = config
        self._healthy = True
        logger.info("BLESensor configured: %s", self._sensor_id)

    def feed_window(self, window: BLEWindow) -> None:
        """Feed a BLEWindow from the ESP32 bridge."""
        self._pending_window = window

    def capture(self) -> Optional[SensorFrame]:
        """Convert a pending BLEWindow to a SensorFrame."""
        window = self._pending_window
        if window is None:
            return None

        self._pending_window = None

        observations = [
            SensorObservation(
                mac=obs.mac,
                rssi_dbm=obs.rssi_dbm,
                noise_dbm=None,
                channel=0,
                bandwidth="BLE",
                frame_type="ble_adv",
                ssid=obs.device_name or None,
                is_randomized_mac=_is_ble_random_addr(obs.mac),
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
            metadata={
                "source": "ble",
                "ble_details": [
                    {
                        "mac": obs.mac,
                        "name": obs.device_name,
                        "tx_power": obs.tx_power,
                        "services": obs.service_uuids,
                        "manufacturer": resolve_manufacturer(obs.manufacturer_id),
                        "manufacturer_id": obs.manufacturer_id,
                        "connectable": obs.is_connectable,
                        "adv_count": obs.count,
                    }
                    for obs in window.observations
                ],
            },
        )

    def health_check(self) -> bool:
        return self._healthy

    @property
    def sensor_id(self) -> str:
        return self._sensor_id

    @property
    def sensor_type(self) -> SensorType:
        return SensorType.RSSI


def _is_ble_random_addr(mac: str) -> bool:
    """Check if a BLE MAC is a random address (top 2 bits of first octet)."""
    try:
        first_octet = int(mac.split(":")[0], 16)
        return bool(first_octet & 0xC0)
    except (ValueError, IndexError):
        return False
