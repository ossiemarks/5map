"""Movement tracker for indoor zone-based device tracking.

Tracks device movement across zones over time, handling observation gaps
up to 30 seconds. Uses zone transition detection with confirmation
(2+ consecutive observations in new zone before committing transition).

Works with the ZoneClassifier output to build device trajectories
suitable for dashboard rendering.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ml.data.fingerprint_db import ZoneGrid, ZonePrediction

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TrackObservation:
    """Single zone observation for a tracked device."""

    timestamp: str
    zone_id: str
    confidence: float
    rssi_vector: list[float] = field(default_factory=list)


@dataclass
class ZoneVisit:
    """A completed or ongoing visit to a zone."""

    zone_id: str
    entered_at: str
    left_at: str | None = None
    avg_confidence: float = 0.0
    observation_count: int = 0


@dataclass
class DeviceTrack:
    """Complete movement track for a single device."""

    device_id: str
    mac_address: str
    current_zone: str = "unknown"
    current_confidence: float = 0.0
    observations: list[TrackObservation] = field(default_factory=list)
    zone_history: list[ZoneVisit] = field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""
    mac_history: list[str] = field(default_factory=list)
    is_active: bool = True

    # Internal: pending zone change (needs confirmation)
    _pending_zone: str = ""
    _pending_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "mac_address": self.mac_address,
            "current_zone": self.current_zone,
            "confidence": round(self.current_confidence, 3),
            "zone_history": [
                {
                    "zone": v.zone_id,
                    "entered_at": v.entered_at,
                    "left_at": v.left_at,
                    "observations": v.observation_count,
                }
                for v in self.zone_history[-20:]  # Last 20 zone visits
            ],
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "is_active": self.is_active,
        }


class MovementTracker:
    """Tracks device movement across zones with transition confirmation.

    Zone transitions require 2+ consecutive observations in the new zone
    before being committed, reducing noise from single misclassifications.
    """

    CONFIRM_COUNT = 2  # Observations needed to confirm zone change
    ACTIVE_TIMEOUT_S = 60  # Seconds before marking device inactive
    MAX_OBSERVATIONS = 500  # Per device, rolling window

    def __init__(self, zone_grid: ZoneGrid | None = None) -> None:
        self.zone_grid = zone_grid or ZoneGrid()
        self._tracks: dict[str, DeviceTrack] = {}
        self._mac_to_device: dict[str, str] = {}
        self._next_id = 1

    def update(
        self,
        mac: str,
        prediction: ZonePrediction,
        rssi_vector: list[float] | None = None,
    ) -> DeviceTrack:
        """Update tracking for a device based on zone prediction.

        Args:
            mac: Device MAC address.
            prediction: Zone prediction from classifier.
            rssi_vector: Raw RSSI values from sensors (for track detail).

        Returns:
            Updated DeviceTrack.
        """
        now = datetime.now(timezone.utc).isoformat()

        # Get or create track
        device_id = self._mac_to_device.get(mac)
        if device_id is None:
            device_id = f"dev_{self._next_id:04d}"
            self._next_id += 1
            self._mac_to_device[mac] = device_id
            self._tracks[device_id] = DeviceTrack(
                device_id=device_id,
                mac_address=mac,
                first_seen=now,
                mac_history=[mac],
            )

        track = self._tracks[device_id]
        track.last_seen = now
        track.is_active = True
        track.current_confidence = prediction.confidence

        # Add observation
        obs = TrackObservation(
            timestamp=now,
            zone_id=prediction.zone_id,
            confidence=prediction.confidence,
            rssi_vector=rssi_vector or [],
        )
        track.observations.append(obs)
        if len(track.observations) > self.MAX_OBSERVATIONS:
            track.observations.pop(0)

        # Zone transition logic
        if track.current_zone == "unknown":
            # First observation — set zone immediately
            track.current_zone = prediction.zone_id
            track.zone_history.append(
                ZoneVisit(
                    zone_id=prediction.zone_id,
                    entered_at=now,
                    observation_count=1,
                )
            )
        elif prediction.zone_id != track.current_zone:
            # Different zone — check if pending transition
            if prediction.zone_id == track._pending_zone:
                track._pending_count += 1
                if track._pending_count >= self.CONFIRM_COUNT:
                    # Confirmed zone transition
                    self._commit_transition(track, prediction.zone_id, now)
            else:
                # New pending zone
                track._pending_zone = prediction.zone_id
                track._pending_count = 1
        else:
            # Same zone — clear any pending transition
            track._pending_zone = ""
            track._pending_count = 0
            # Update current visit observation count
            if track.zone_history:
                track.zone_history[-1].observation_count += 1

        return track

    def _commit_transition(
        self, track: DeviceTrack, new_zone: str, timestamp: str
    ) -> None:
        """Commit a confirmed zone transition."""
        # Close current visit
        if track.zone_history:
            track.zone_history[-1].left_at = timestamp

        # Start new visit
        track.zone_history.append(
            ZoneVisit(
                zone_id=new_zone,
                entered_at=timestamp,
                observation_count=1,
            )
        )

        old_zone = track.current_zone
        track.current_zone = new_zone
        track._pending_zone = ""
        track._pending_count = 0

        logger.info(
            "Zone transition: %s (%s) %s -> %s",
            track.device_id, track.mac_address, old_zone, new_zone,
        )

    def link_mac(self, old_mac: str, new_mac: str) -> None:
        """Link a new MAC to an existing device (MAC randomization)."""
        device_id = self._mac_to_device.get(old_mac)
        if device_id and device_id in self._tracks:
            self._mac_to_device[new_mac] = device_id
            track = self._tracks[device_id]
            if new_mac not in track.mac_history:
                track.mac_history.append(new_mac)
            logger.info("Linked MAC %s -> device %s", new_mac, device_id)

    def get_track(self, mac: str) -> DeviceTrack | None:
        device_id = self._mac_to_device.get(mac)
        if device_id:
            return self._tracks.get(device_id)
        return None

    def get_active_tracks(self, max_age_s: int = ACTIVE_TIMEOUT_S) -> list[DeviceTrack]:
        """Return all recently-active device tracks."""
        now = datetime.now(timezone.utc)
        active = []
        for track in self._tracks.values():
            if not track.last_seen:
                continue
            try:
                last = datetime.fromisoformat(track.last_seen)
                age = (now - last).total_seconds()
                if age <= max_age_s:
                    track.is_active = True
                    active.append(track)
                else:
                    track.is_active = False
            except (ValueError, TypeError):
                continue
        return active

    def get_all_tracks(self) -> list[DeviceTrack]:
        return list(self._tracks.values())

    def export_tracks_json(self) -> list[dict[str, Any]]:
        """Export active tracks in dashboard-ready format."""
        return [t.to_dict() for t in self.get_active_tracks()]
