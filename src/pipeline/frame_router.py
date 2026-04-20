"""Frame router for normalizing sensor data into ML-ready features.

Converts sensor-specific SensorFrames into unified feature representations
that ML models can consume regardless of sensor source.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.sensors.base import SensorFrame, SensorType

logger = logging.getLogger(__name__)


@dataclass
class UnifiedFeatures:
    """ML-ready feature representation from any sensor type.

    For RSSI sensors: signal_strength_vector contains per-MAC RSSI values.
    For CSI sensors: amplitude_matrix and phase_matrix contain subcarrier data.
    """

    timestamp: str = ""
    sensor_id: str = ""
    source_type: SensorType = SensorType.RSSI
    position: Optional[Dict[str, Any]] = None

    # RSSI features
    signal_strength_vector: List[float] = field(default_factory=list)
    mac_addresses: List[str] = field(default_factory=list)
    device_features: List[Dict[str, Any]] = field(default_factory=list)

    # CSI features (future)
    amplitude_matrix: Optional[List[List[float]]] = None
    phase_matrix: Optional[List[List[float]]] = None

    # Metadata
    observation_count: int = 0
    window_ms: int = 1000


class FrameRouter:
    """Normalizes SensorFrames into UnifiedFeatures for ML consumption.

    The normalize method is stateless and safe for concurrent calls.
    """

    def normalize(self, frame: SensorFrame) -> Optional[UnifiedFeatures]:
        """Convert a SensorFrame to UnifiedFeatures.

        Args:
            frame: The sensor frame to normalize.

        Returns:
            UnifiedFeatures ready for ML pipeline, or None if frame is invalid.
        """
        if frame is None:
            logger.warning("Received None frame, skipping")
            return None

        if not frame.timestamp or not frame.sensor_id:
            logger.warning(
                "Frame missing timestamp or sensor_id, skipping: %s", frame.sensor_id
            )
            return None

        if frame.sensor_type == SensorType.RSSI:
            return self._normalize_rssi(frame)
        elif frame.sensor_type == SensorType.CSI:
            return self._normalize_csi(frame)
        else:
            logger.warning("Unknown sensor type: %s", frame.sensor_type)
            return None

    def _normalize_rssi(self, frame: SensorFrame) -> UnifiedFeatures:
        """Normalize RSSI frame to unified features."""
        signal_strengths = []
        mac_addresses = []
        device_features = []

        for obs in frame.observations:
            signal_strengths.append(float(obs.rssi_dbm))
            mac_addresses.append(obs.mac)
            device_features.append({
                "mac": obs.mac,
                "rssi_dbm": obs.rssi_dbm,
                "noise_dbm": obs.noise_dbm,
                "channel": obs.channel,
                "bandwidth": obs.bandwidth,
                "frame_type": obs.frame_type,
                "ssid": obs.ssid,
                "is_randomized_mac": obs.is_randomized_mac,
                "count": obs.count,
            })

        return UnifiedFeatures(
            timestamp=frame.timestamp,
            sensor_id=frame.sensor_id,
            source_type=SensorType.RSSI,
            position=frame.position,
            signal_strength_vector=signal_strengths,
            mac_addresses=mac_addresses,
            device_features=device_features,
            observation_count=len(frame.observations),
            window_ms=frame.window_ms,
        )

    def _normalize_csi(self, frame: SensorFrame) -> UnifiedFeatures:
        """Normalize CSI frame to unified features (future implementation)."""
        amplitude = []
        phase = []

        if frame.csi_matrix:
            for row in frame.csi_matrix:
                amplitude.append([abs(c) for c in row])
                phase.append([
                    __import__("cmath").phase(c) if c != 0 else 0.0
                    for c in row
                ])

        return UnifiedFeatures(
            timestamp=frame.timestamp,
            sensor_id=frame.sensor_id,
            source_type=SensorType.CSI,
            position=frame.position,
            amplitude_matrix=amplitude or None,
            phase_matrix=phase or None,
            observation_count=len(frame.observations),
            window_ms=frame.window_ms,
        )
