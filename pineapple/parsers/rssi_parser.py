"""RSSI parser for WiFi Pineapple Mark VII monitor-mode captures.

Extracts per-frame observations from scapy packets and aggregates them
into fixed time windows suitable for environment mapping.  Designed for
constrained OpenWrt / MIPS hardware (~128 MB RAM).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

from scapy.layers.dot11 import (
    Dot11,
    Dot11Beacon,
    Dot11Elt,
    Dot11ProbeReq,
    Dot11ProbeResp,
    RadioTap,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Channel / frequency tables
# ---------------------------------------------------------------------------

_FREQ_TO_CHANNEL: Dict[int, int] = {}

# 2.4 GHz  (channels 1-14)
for _ch in range(1, 14):
    _FREQ_TO_CHANNEL[2407 + _ch * 5] = _ch
_FREQ_TO_CHANNEL[2484] = 14

# 5 GHz  UNII-1 / UNII-2 / UNII-2e / UNII-3  (common channels)
for _ch in range(36, 65, 4):
    _FREQ_TO_CHANNEL[5000 + _ch * 5] = _ch
for _ch in range(100, 145, 4):
    _FREQ_TO_CHANNEL[5000 + _ch * 5] = _ch
for _ch in (149, 153, 157, 161, 165):
    _FREQ_TO_CHANNEL[5000 + _ch * 5] = _ch


def get_channel_from_freq(freq_mhz: int) -> int:
    """Convert a centre frequency in MHz to its IEEE 802.11 channel number.

    Args:
        freq_mhz: Centre frequency in MHz (e.g. 2412, 5180).

    Returns:
        Channel number, or 0 if the frequency is unrecognised.
    """
    return _FREQ_TO_CHANNEL.get(freq_mhz, 0)


def get_bandwidth_from_freq(freq_mhz: int) -> str:
    """Return ``"2.4GHz"`` or ``"5GHz"`` for a given centre frequency.

    Args:
        freq_mhz: Centre frequency in MHz.

    Returns:
        Band string.  Defaults to ``"2.4GHz"`` for unknown frequencies.
    """
    if freq_mhz >= 5000:
        return "5GHz"
    return "2.4GHz"


# ---------------------------------------------------------------------------
# MAC helpers
# ---------------------------------------------------------------------------

def is_locally_administered(mac: str) -> bool:
    """Check whether a MAC address has the *locally administered* bit set.

    IEEE 802 defines bit 1 (second-least-significant bit) of the first
    octet as the U/L bit.  When set, the address is locally administered
    -- a strong indicator of MAC randomisation on modern client devices.

    Args:
        mac: Colon- or hyphen-separated MAC string (e.g. ``"da:a1:19:…"``).

    Returns:
        ``True`` when the locally administered bit is set.
    """
    try:
        first_octet = int(mac.split(":")[0].replace("-", ""), 16)
    except (ValueError, IndexError):
        return False
    return bool(first_octet & 0x02)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Observation:
    """A single (or deduplicated) observation of a wireless station."""

    mac: str
    rssi_dbm: int
    noise_dbm: Optional[int]
    channel: int
    bandwidth: str          # "2.4GHz" | "5GHz"
    frame_type: str         # beacon | probe_request | probe_response | data | management
    ssid: Optional[str]
    is_randomized_mac: bool
    count: int = 1          # frames seen from this MAC within window


@dataclass
class ObservationWindow:
    """A time-bounded collection of deduplicated observations."""

    timestamp: str           # ISO 8601 UTC
    sensor_id: str
    sensor_type: str         # "rssi"
    window_ms: int
    observations: list[Observation] = field(default_factory=list)
    position: Optional[dict] = None  # {"x": float, "y": float, "label": str}


# ---------------------------------------------------------------------------
# Frame classification
# ---------------------------------------------------------------------------

_FRAME_TYPES = {
    0: {  # management
        0: "management",       # association request
        1: "management",       # association response
        4: "probe_request",
        5: "probe_response",
        8: "beacon",
        10: "management",      # disassociation
        11: "management",      # authentication
        12: "management",      # deauthentication
    },
    1: {},  # control -- rarely useful for mapping
    2: {},  # data
}


def _classify_frame(packet: object) -> Optional[str]:
    """Return a human-readable frame type string or ``None`` if irrelevant."""
    if not packet.haslayer(Dot11):
        return None

    dot11 = packet.getlayer(Dot11)
    frame_type: int = dot11.type
    frame_subtype: int = dot11.subtype

    if frame_type == 0:
        return _FRAME_TYPES[0].get(frame_subtype, "management")
    if frame_type == 2:
        return "data"
    # Control frames (type 1) are not useful for environment mapping.
    return None


# ---------------------------------------------------------------------------
# SSID extraction
# ---------------------------------------------------------------------------

def _extract_ssid(packet: object) -> Optional[str]:
    """Pull the SSID from an information element, if present."""
    if packet.haslayer(Dot11Elt):
        elt = packet.getlayer(Dot11Elt)
        # Walk the IE chain looking for ID 0 (SSID)
        while elt:
            if elt.ID == 0:
                try:
                    ssid = elt.info.decode("utf-8", errors="replace").strip("\x00")
                    return ssid if ssid else None
                except Exception:
                    return None
            elt = elt.payload.getlayer(Dot11Elt) if elt.payload else None
    return None


# ---------------------------------------------------------------------------
# Source MAC extraction
# ---------------------------------------------------------------------------

def _extract_source_mac(packet: object) -> Optional[str]:
    """Return the transmitter / source MAC from a Dot11 header.

    Priority: ``addr2`` (transmitter) → ``addr1`` (receiver, fallback).
    """
    dot11 = packet.getlayer(Dot11)
    if dot11 is None:
        return None
    mac = dot11.addr2 or dot11.addr1
    if mac and mac.lower() != "ff:ff:ff:ff:ff:ff":
        return mac.lower()
    return None


# ---------------------------------------------------------------------------
# Single-frame parser
# ---------------------------------------------------------------------------

def parse_frame(packet: object) -> Optional[Observation]:
    """Parse a single scapy packet captured in monitor mode.

    Extracts RSSI, noise floor, channel, source MAC, frame type, and
    SSID (when available) from the RadioTap + Dot11 layers.

    Args:
        packet: A scapy packet object (typically from ``sniff()``).

    Returns:
        An :class:`Observation` or ``None`` when the frame cannot be
        parsed (e.g. missing RadioTap header, control frames).
    """
    # -- RadioTap is mandatory for RSSI / channel info
    if not packet.haslayer(RadioTap):
        return None

    frame_type = _classify_frame(packet)
    if frame_type is None:
        return None

    mac = _extract_source_mac(packet)
    if mac is None:
        return None

    radiotap = packet.getlayer(RadioTap)

    # RSSI -- scapy exposes as ``dBm_AntSignal``
    rssi: Optional[int] = getattr(radiotap, "dBm_AntSignal", None)
    if rssi is None:
        return None

    # Noise floor (may not be present on all hardware)
    noise: Optional[int] = getattr(radiotap, "dBm_AntNoise", None)

    # Frequency → channel + band
    freq: Optional[int] = getattr(radiotap, "ChannelFrequency", None)
    if freq is None:
        # Fallback: some drivers use ``Channel`` directly
        channel = getattr(radiotap, "Channel", 0)
        bandwidth = "2.4GHz" if channel <= 14 else "5GHz"
    else:
        channel = get_channel_from_freq(freq)
        bandwidth = get_bandwidth_from_freq(freq)

    ssid = _extract_ssid(packet)
    randomised = is_locally_administered(mac)

    return Observation(
        mac=mac,
        rssi_dbm=int(rssi),
        noise_dbm=int(noise) if noise is not None else None,
        channel=channel,
        bandwidth=bandwidth,
        frame_type=frame_type,
        ssid=ssid,
        is_randomized_mac=randomised,
    )


# ---------------------------------------------------------------------------
# Window aggregator
# ---------------------------------------------------------------------------

class WindowAggregator:
    """Collect :class:`Observation` instances into fixed time windows.

    Deduplicates by MAC address within each window, keeping the
    strongest RSSI and incrementing the observation count.  The number
    of unique MACs per window is capped at *max_observations* to bound
    memory usage on constrained devices.

    Args:
        sensor_id: Unique identifier for this sensor (from config).
        window_ms: Window duration in milliseconds (default 1000).
        max_observations: Maximum unique MACs per window (default 10000).
        position: Optional fixed position dict for this sensor.
    """

    def __init__(
        self,
        sensor_id: str,
        window_ms: int = 1000,
        max_observations: int = 10_000,
        position: Optional[dict] = None,
    ) -> None:
        self._sensor_id = sensor_id
        self._window_ms = window_ms
        self._max_observations = max_observations
        self._position = position

        # Internal aggregation state
        self._observations: Dict[str, Observation] = {}
        self._window_start: float = time.monotonic()
        self._dropped: int = 0

    @property
    def dropped_count(self) -> int:
        """Number of unique MACs dropped in the current window due to cap."""
        return self._dropped

    def _window_expired(self) -> bool:
        elapsed_ms = (time.monotonic() - self._window_start) * 1000.0
        return elapsed_ms >= self._window_ms

    def add(self, obs: Observation) -> Optional[ObservationWindow]:
        """Ingest an observation, returning a completed window when the
        time boundary is crossed.

        Args:
            obs: A parsed :class:`Observation`.

        Returns:
            A sealed :class:`ObservationWindow` if the window has elapsed,
            otherwise ``None``.
        """
        result: Optional[ObservationWindow] = None

        if self._window_expired():
            result = self.flush()

        key = obs.mac
        existing = self._observations.get(key)

        if existing is not None:
            # Deduplicate: keep strongest RSSI, merge count & SSID
            existing.count += 1
            if obs.rssi_dbm > existing.rssi_dbm:
                existing.rssi_dbm = obs.rssi_dbm
                existing.noise_dbm = obs.noise_dbm
            if obs.ssid and not existing.ssid:
                existing.ssid = obs.ssid
        else:
            if len(self._observations) >= self._max_observations:
                self._dropped += 1
                if self._dropped == 1:
                    logger.warning(
                        "Window capacity reached (%d); dropping new MACs",
                        self._max_observations,
                    )
            else:
                self._observations[key] = obs

        return result

    def flush(self) -> ObservationWindow:
        """Seal the current window and start a new one.

        Returns:
            The completed :class:`ObservationWindow`.
        """
        window = ObservationWindow(
            timestamp=datetime.now(timezone.utc).isoformat(),
            sensor_id=self._sensor_id,
            sensor_type="rssi",
            window_ms=self._window_ms,
            observations=list(self._observations.values()),
            position=self._position,
        )

        if self._dropped > 0:
            logger.info(
                "Window sealed: %d observations, %d dropped",
                len(window.observations),
                self._dropped,
            )

        # Reset for next window
        self._observations = {}
        self._window_start = time.monotonic()
        self._dropped = 0

        return window
