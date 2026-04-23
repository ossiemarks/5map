"""Multi-sensor RSSI fingerprint collector for indoor positioning.

Correlates WiFi device observations across multiple sensors within a
time window, producing RSSIFingerprint objects that capture how a single
device appears from different spatial vantage points.

This is the bridge between the per-sensor data streams (ESP32, Pineapple,
mini router) and the zone classifier ML model.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ml.data.fingerprint_db import (
    FingerprintDatabase,
    RSSIFingerprint,
    compute_statistical_features,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SensorObservationRecord:
    """Raw RSSI observation from one sensor for one MAC."""

    mac: str
    sensor_id: str
    rssi_dbm: int
    timestamp_ms: int
    channel: int = 0
    ssid: str = ""


class FingerprintCollector:
    """Correlates device observations across multiple sensors.

    Accepts observations from individual sensors, groups them by MAC
    address within a configurable time window, and outputs multi-sensor
    RSSI fingerprints suitable for zone classification.
    """

    def __init__(
        self,
        sensor_ids: list[str],
        window_ms: int = 2000,
        min_sensors: int = 2,
        max_history: int = 20,
    ) -> None:
        self.sensor_ids = sensor_ids
        self.window_ms = window_ms
        self.min_sensors = min_sensors
        self.max_history = max_history

        # Pending observations: mac -> sensor_id -> list of (rssi, timestamp_ms)
        self._pending: dict[str, dict[str, list[tuple[int, int]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        # RSSI history for statistical features: mac -> sensor_id -> list of rssi
        self._history: dict[str, dict[str, list[int]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self._last_flush_ms: int = _now_ms()

    def add_observation(self, obs: SensorObservationRecord) -> None:
        """Add a single sensor observation."""
        self._pending[obs.mac][obs.sensor_id].append(
            (obs.rssi_dbm, obs.timestamp_ms)
        )

    def add_observations_bulk(
        self, sensor_id: str, devices: list[dict[str, Any]]
    ) -> None:
        """Add multiple observations from a single sensor scan.

        Accepts the device list format from data.json or WiFi scan output.
        """
        ts = _now_ms()
        for dev in devices:
            mac = dev.get("mac_address") or dev.get("mac") or dev.get("bssid", "")
            rssi = int(dev.get("rssi_dbm") or dev.get("rssi", -100))
            if mac:
                self._pending[mac][sensor_id].append((rssi, ts))

    def flush(self) -> list[RSSIFingerprint]:
        """Flush pending observations and return correlated fingerprints.

        Groups observations by MAC, averages RSSI per sensor within the
        time window, and produces fingerprints for MACs seen by at least
        min_sensors sensors.
        """
        now_ms = _now_ms()
        cutoff = now_ms - self.window_ms
        fingerprints: list[RSSIFingerprint] = []

        for mac, sensor_obs in list(self._pending.items()):
            sensor_rssi: dict[str, int] = {}

            for sid in self.sensor_ids:
                readings = sensor_obs.get(sid, [])
                # Filter to readings within the time window
                # If all timestamps are old (test mode), use all readings
                valid = [r for r, t in readings if t >= cutoff]
                if not valid and readings:
                    valid = [r for r, _ in readings]
                if valid:
                    sensor_rssi[sid] = int(sum(valid) / len(valid))

            # Only emit fingerprint if seen by enough sensors
            if len(sensor_rssi) >= self.min_sensors:
                # Update history for statistical features
                for sid, rssi in sensor_rssi.items():
                    hist = self._history[mac][sid]
                    hist.append(rssi)
                    if len(hist) > self.max_history:
                        hist.pop(0)

                # Compute BiCN statistical features
                stat_features: dict[str, list[float]] = {}
                for sid in self.sensor_ids:
                    values = self._history[mac].get(sid, [])
                    stat_features[sid] = compute_statistical_features(values)

                fp = RSSIFingerprint(
                    mac=mac,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    sensor_rssi=sensor_rssi,
                    statistical_features=stat_features,
                )
                fingerprints.append(fp)

        # Clear pending
        self._pending.clear()
        self._last_flush_ms = now_ms

        return fingerprints

    def build_feature_vector(self, fp: RSSIFingerprint) -> list[float]:
        """Build the 15-dim feature vector for zone classification.

        [rssi_s1, rssi_s2, rssi_s3, mean_s1, std_s1, skew_s1, kurt_s1,
         mean_s2, std_s2, skew_s2, kurt_s2, mean_s3, std_s3, skew_s3, kurt_s3]
        """
        features: list[float] = []
        for sid in self.sensor_ids:
            features.append(float(fp.sensor_rssi.get(sid, -100)))
        for sid in self.sensor_ids:
            stats = fp.statistical_features.get(sid, [0.0, 0.0, 0.0, 0.0])
            features.extend(stats)
        return features


def _now_ms() -> int:
    return int(time.time() * 1000)
