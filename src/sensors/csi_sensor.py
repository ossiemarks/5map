"""CSI sensor implementation for ESP32 WiFi Channel State Information.

Receives CSI data from the ESP32 bridge and converts it to SensorFrames
for the unified 5map pipeline. CSI provides subcarrier-level amplitude
and phase data for high-resolution environment mapping.

Now includes full subcarrier data processing via CSIProcessor for
motion detection, breathing detection, and activity recognition.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.sensors.base import SensorBase, SensorFrame, SensorObservation, SensorType
from src.sensors.csi_processor import (
    CSIFrame,
    CSIProcessor,
    features_to_dict,
    parse_csi_json,
)

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
    raw_data: str = ""   # base64-encoded CSI buffer (empty for legacy frames)
    noise_floor: int = -90
    rate: int = 0


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
    """ESP32 CSI sensor that converts CSI windows to SensorFrames.

    Now processes raw subcarrier data through CSIProcessor to extract
    amplitude/phase features, motion scores, and breathing detection.
    """

    def __init__(self) -> None:
        self._sensor_id: str = ""
        self._config: Dict[str, Any] = {}
        self._healthy: bool = False
        self._pending_window: Optional[CSIWindow] = None
        self._processor = CSIProcessor(
            window_size=100,
            feature_interval_ms=500,
            subcarrier_selection="data",
        )

    def configure(self, config: Dict[str, Any]) -> None:
        if "sensor_id" not in config:
            raise ValueError("Config must contain 'sensor_id'")
        self._sensor_id = config["sensor_id"]
        self._config = config
        self._healthy = True

        # Allow processor tuning via config
        if "csi_window_size" in config:
            self._processor._window_size = int(config["csi_window_size"])
        if "csi_feature_interval_ms" in config:
            self._processor._feature_interval_ms = int(config["csi_feature_interval_ms"])

        logger.info("CSISensor configured: %s (processor enabled)", self._sensor_id)

    def feed_window(self, window: CSIWindow) -> None:
        """Feed a CSIWindow from the ESP32 bridge."""
        self._pending_window = window

    def capture(self) -> Optional[SensorFrame]:
        """Convert a pending CSIWindow to a SensorFrame with full CSI data."""
        window = self._pending_window
        if window is None:
            return None

        self._pending_window = None

        observations = []
        csi_matrix_rows = []
        latest_features = None

        for obs in window.observations:
            observations.append(
                SensorObservation(
                    mac=obs.mac,
                    rssi_dbm=obs.rssi_dbm,
                    channel=obs.channel,
                    bandwidth=f"{obs.bandwidth}MHz",
                    frame_type="csi",
                    count=1,
                )
            )

            # Process raw CSI data if available
            if obs.raw_data:
                json_data = {
                    "t": "csi",
                    "mac": obs.mac,
                    "rssi": obs.rssi_dbm,
                    "ch": obs.channel,
                    "bw": obs.bandwidth,
                    "len": obs.csi_len * 2,
                    "ns": obs.csi_len,
                    "noise": obs.noise_floor,
                    "rate": obs.rate,
                    "ts": obs.timestamp_ms,
                    "data": obs.raw_data,
                }
                frame = parse_csi_json(json_data)
                if frame:
                    # Build csi_matrix row: [complex(real, imag), ...]
                    row = [
                        complex(float(frame.raw_iq[i, 1]), float(frame.raw_iq[i, 0]))
                        for i in range(frame.num_subcarriers)
                    ]
                    csi_matrix_rows.append(row)

                    # Feed processor for feature extraction
                    features = self._processor.add_frame(frame)
                    if features:
                        latest_features = features

        metadata: Dict[str, Any] = {
            "source": "esp32_csi",
            "csi_summary": {
                "total_frames": len(window.observations),
                "unique_macs": len(set(o.mac for o in window.observations)),
                "channels": list(set(o.channel for o in window.observations)),
                "raw_frames": len(csi_matrix_rows),
            },
            "processor_stats": self._processor.get_buffer_stats(),
        }

        if latest_features:
            metadata["csi_features"] = features_to_dict(latest_features)

        return SensorFrame(
            version=2,
            timestamp=window.timestamp,
            sensor_id=window.sensor_id,
            sensor_type=SensorType.CSI,
            window_ms=window.window_ms,
            observations=observations,
            csi_matrix=csi_matrix_rows if csi_matrix_rows else None,
            metadata=metadata,
        )

    def get_processor(self) -> CSIProcessor:
        """Access the underlying CSI processor for direct queries."""
        return self._processor

    def health_check(self) -> bool:
        return self._healthy

    @property
    def sensor_id(self) -> str:
        return self._sensor_id

    @property
    def sensor_type(self) -> SensorType:
        return SensorType.CSI
