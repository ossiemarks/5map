"""RSSI fingerprint database for zone-based indoor positioning.

Collects multi-sensor RSSI fingerprints (one per MAC per time window),
stores calibration data for zone classification, and provides
train/predict interfaces following the BiCN feature engineering approach
(mean, std, skewness, kurtosis per sensor).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class RSSIFingerprint:
    """Single multi-sensor RSSI observation for one device."""

    mac: str
    timestamp: str
    sensor_rssi: dict[str, int]  # sensor_id -> RSSI dBm
    zone_id: str | None = None   # ground-truth label (calibration only)
    statistical_features: dict[str, list[float]] = field(default_factory=dict)


@dataclass(slots=True)
class ZonePrediction:
    """Output of the zone classifier."""

    zone_id: str
    confidence: float
    nlos_detected: bool = False
    zone_center: tuple[float, float] = (0.0, 0.0)


class ZoneGrid:
    """Divides a room into rectangular zones based on sensor geometry."""

    def __init__(
        self,
        room_width: float = 5.0,
        room_depth: float = 5.0,
        zones_x: int = 3,
        zones_y: int = 3,
    ) -> None:
        self.room_width = room_width
        self.room_depth = room_depth
        self.zones_x = zones_x
        self.zones_y = zones_y
        self.zones: dict[str, dict[str, Any]] = {}
        self._build_zones()

    def _build_zones(self) -> None:
        cell_w = self.room_width / self.zones_x
        cell_h = self.room_depth / self.zones_y
        for row in range(self.zones_y):
            for col in range(self.zones_x):
                zone_id = f"zone_{col}_{row}"
                x_min = col * cell_w
                y_min = row * cell_h
                self.zones[zone_id] = {
                    "id": zone_id,
                    "x_min": x_min,
                    "y_min": y_min,
                    "x_max": x_min + cell_w,
                    "y_max": y_min + cell_h,
                    "center": (x_min + cell_w / 2, y_min + cell_h / 2),
                    "label": f"({col},{row})",
                }

    def position_to_zone(self, x: float, y: float) -> str:
        col = min(int(x / (self.room_width / self.zones_x)), self.zones_x - 1)
        row = min(int(y / (self.room_depth / self.zones_y)), self.zones_y - 1)
        return f"zone_{col}_{row}"

    def zone_center(self, zone_id: str) -> tuple[float, float]:
        zone = self.zones.get(zone_id)
        if zone:
            return zone["center"]
        return (self.room_width / 2, self.room_depth / 2)

    @property
    def zone_ids(self) -> list[str]:
        return list(self.zones.keys())

    def to_dict(self) -> dict:
        return {
            "room_width": self.room_width,
            "room_depth": self.room_depth,
            "zones_x": self.zones_x,
            "zones_y": self.zones_y,
            "zones": self.zones,
        }


def compute_statistical_features(
    rssi_values: list[int],
) -> list[float]:
    """Compute BiCN 4-feature vector: mean, std, skewness, kurtosis.

    Per the BiCN paper, these 4 statistical features per sensor capture
    the signal distribution characteristics needed for LOS/NLOS detection
    and position fingerprinting.
    """
    n = len(rssi_values)
    if n == 0:
        return [0.0, 0.0, 0.0, 0.0]

    mean = sum(rssi_values) / n

    if n < 2:
        return [mean, 0.0, 0.0, 0.0]

    variance = sum((x - mean) ** 2 for x in rssi_values) / n
    std = math.sqrt(variance) if variance > 0 else 0.001

    # Skewness: asymmetry of the distribution
    skewness = (
        sum((x - mean) ** 3 for x in rssi_values) / (n * std ** 3)
        if std > 0.001 else 0.0
    )

    # Kurtosis: peakedness (excess kurtosis, subtract 3)
    kurtosis = (
        sum((x - mean) ** 4 for x in rssi_values) / (n * std ** 4) - 3
        if std > 0.001 else 0.0
    )

    return [mean, std, skewness, kurtosis]


class FingerprintDatabase:
    """Stores and manages RSSI fingerprints for zone classification training."""

    def __init__(self, zone_grid: ZoneGrid | None = None) -> None:
        self.zone_grid = zone_grid or ZoneGrid()
        self.fingerprints: list[RSSIFingerprint] = []
        self.sensor_ids: list[str] = []
        self._rssi_history: dict[str, dict[str, list[int]]] = {}

    def add_fingerprint(self, fp: RSSIFingerprint) -> None:
        self.fingerprints.append(fp)

        # Track RSSI history per MAC per sensor for statistical features
        if fp.mac not in self._rssi_history:
            self._rssi_history[fp.mac] = {}
        for sid, rssi in fp.sensor_rssi.items():
            if sid not in self._rssi_history[fp.mac]:
                self._rssi_history[fp.mac][sid] = []
            history = self._rssi_history[fp.mac][sid]
            history.append(rssi)
            # Keep last 20 readings per BiCN (20 RSS values per AP)
            if len(history) > 20:
                history.pop(0)

        # Update known sensor IDs
        for sid in fp.sensor_rssi:
            if sid not in self.sensor_ids:
                self.sensor_ids.append(sid)

    def get_statistical_features(self, mac: str) -> dict[str, list[float]]:
        """Get BiCN 4-feature vector per sensor for a device."""
        features = {}
        history = self._rssi_history.get(mac, {})
        for sid in self.sensor_ids:
            values = history.get(sid, [])
            features[sid] = compute_statistical_features(values)
        return features

    def build_feature_matrix(
        self,
        sensor_ids: list[str] | None = None,
    ) -> tuple[list[list[float]], list[str]]:
        """Build feature matrix and labels for zone classifier training.

        Returns (X, y) where X is a list of feature vectors (3 RSSI +
        12 statistical features = 15-dim for 3 sensors) and y is zone labels.
        """
        sids = sensor_ids or self.sensor_ids
        X: list[list[float]] = []
        y: list[str] = []

        for fp in self.fingerprints:
            if fp.zone_id is None:
                continue

            features: list[float] = []
            # Raw RSSI per sensor
            for sid in sids:
                features.append(float(fp.sensor_rssi.get(sid, -100)))

            # Statistical features per sensor (4 each)
            stats = self.get_statistical_features(fp.mac)
            for sid in sids:
                features.extend(stats.get(sid, [0.0, 0.0, 0.0, 0.0]))

            X.append(features)
            y.append(fp.zone_id)

        return X, y

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "zone_grid": self.zone_grid.to_dict(),
            "sensor_ids": self.sensor_ids,
            "fingerprints": [
                {
                    "mac": fp.mac,
                    "timestamp": fp.timestamp,
                    "sensor_rssi": fp.sensor_rssi,
                    "zone_id": fp.zone_id,
                }
                for fp in self.fingerprints
            ],
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> FingerprintDatabase:
        with open(path) as f:
            data = json.load(f)
        grid_data = data["zone_grid"]
        grid = ZoneGrid(
            room_width=grid_data["room_width"],
            room_depth=grid_data["room_depth"],
            zones_x=grid_data["zones_x"],
            zones_y=grid_data["zones_y"],
        )
        db = cls(zone_grid=grid)
        db.sensor_ids = data["sensor_ids"]
        for fp_data in data["fingerprints"]:
            fp = RSSIFingerprint(
                mac=fp_data["mac"],
                timestamp=fp_data["timestamp"],
                sensor_rssi=fp_data["sensor_rssi"],
                zone_id=fp_data.get("zone_id"),
            )
            db.add_fingerprint(fp)
        return db
