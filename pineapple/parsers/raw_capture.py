"""Lightweight raw socket WiFi frame capture for OpenWrt.

Uses raw sockets with AF_PACKET to capture WiFi frames in monitor mode
without requiring scapy or ctypes. Parses radiotap headers and 802.11
frame headers using struct for RSSI extraction.
"""

from __future__ import annotations

import logging
import socket
import struct
import time
from dataclasses import dataclass
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)

# Radiotap header constants
RADIOTAP_HEADER_REVISION = 0
RADIOTAP_PRESENT_TSFT = 0
RADIOTAP_PRESENT_FLAGS = 1
RADIOTAP_PRESENT_RATE = 2
RADIOTAP_PRESENT_CHANNEL = 3
RADIOTAP_PRESENT_DBM_ANTSIGNAL = 5
RADIOTAP_PRESENT_DBM_ANTNOISE = 6

# 802.11 frame type/subtype
FRAME_TYPE_MGMT = 0
FRAME_TYPE_CTRL = 1
FRAME_TYPE_DATA = 2

SUBTYPE_BEACON = 8
SUBTYPE_PROBE_REQ = 4
SUBTYPE_PROBE_RESP = 5


@dataclass
class RawObservation:
    """Parsed observation from a raw WiFi frame."""
    mac: str
    rssi_dbm: int
    noise_dbm: Optional[int]
    channel: int
    bandwidth: str
    frame_type: str
    ssid: Optional[str]
    is_randomized_mac: bool
    count: int = 1


def is_locally_administered(mac: str) -> bool:
    """Check if MAC has locally administered bit set (randomized)."""
    try:
        first_octet = int(mac.split(":")[0], 16)
        return bool(first_octet & 0x02)
    except (ValueError, IndexError):
        return False


def freq_to_channel(freq: int) -> int:
    """Convert frequency in MHz to WiFi channel number."""
    if 2412 <= freq <= 2484:
        if freq == 2484:
            return 14
        return (freq - 2407) // 5
    elif 5180 <= freq <= 5825:
        return (freq - 5000) // 5
    return 0


def freq_to_band(freq: int) -> str:
    """Convert frequency to band string."""
    return "2.4GHz" if freq < 5000 else "5GHz"


def _classify_frame(frame_type: int, subtype: int) -> Optional[str]:
    """Classify 802.11 frame type."""
    if frame_type == FRAME_TYPE_MGMT:
        if subtype == SUBTYPE_BEACON:
            return "beacon"
        elif subtype == SUBTYPE_PROBE_REQ:
            return "probe_request"
        elif subtype == SUBTYPE_PROBE_RESP:
            return "probe_response"
        return "management"
    elif frame_type == FRAME_TYPE_DATA:
        return "data"
    elif frame_type == FRAME_TYPE_CTRL:
        return None  # skip control frames
    return None


def _parse_radiotap(data: bytes) -> Tuple[int, Optional[int], Optional[int], Optional[int]]:
    """Parse radiotap header, return (header_len, rssi, noise, freq)."""
    if len(data) < 8:
        return 0, None, None, None

    version, pad, header_len, present = struct.unpack_from("<BBhI", data, 0)
    if version != 0 or header_len > len(data):
        return 0, None, None, None

    rssi = None
    noise = None
    freq = None

    offset = 8
    # Walk through present flags
    bit = 0
    while bit < 32 and offset < header_len:
        if not (present & (1 << bit)):
            bit += 1
            continue

        if bit == RADIOTAP_PRESENT_TSFT:
            # TSFT is 8 bytes, aligned to 8
            offset = (offset + 7) & ~7
            offset += 8
        elif bit == RADIOTAP_PRESENT_FLAGS:
            offset += 1
        elif bit == RADIOTAP_PRESENT_RATE:
            offset += 1
        elif bit == RADIOTAP_PRESENT_CHANNEL:
            # Channel is 2 bytes freq + 2 bytes flags, aligned to 2
            offset = (offset + 1) & ~1
            if offset + 4 <= header_len:
                freq = struct.unpack_from("<H", data, offset)[0]
            offset += 4
        elif bit == 4:
            # FHSS - 2 bytes
            offset += 2
        elif bit == RADIOTAP_PRESENT_DBM_ANTSIGNAL:
            if offset < header_len:
                rssi = struct.unpack_from("<b", data, offset)[0]
            offset += 1
        elif bit == RADIOTAP_PRESENT_DBM_ANTNOISE:
            if offset < header_len:
                noise = struct.unpack_from("<b", data, offset)[0]
            offset += 1
        else:
            offset += 1

        bit += 1

    return header_len, rssi, noise, freq


def _extract_ssid(data: bytes, offset: int) -> Optional[str]:
    """Extract SSID from beacon/probe tagged parameters."""
    try:
        # Skip fixed parameters (12 bytes for beacon, 0 for probe req)
        pos = offset
        while pos + 2 < len(data):
            tag_id = data[pos]
            tag_len = data[pos + 1]
            if tag_id == 0:  # SSID element
                if tag_len == 0:
                    return None
                ssid_bytes = data[pos + 2:pos + 2 + tag_len]
                return ssid_bytes.decode("utf-8", errors="replace")
            pos += 2 + tag_len
    except (IndexError, struct.error):
        pass
    return None


def parse_raw_frame(data: bytes) -> Optional[RawObservation]:
    """Parse a raw WiFi frame from a monitor mode socket.

    Args:
        data: Raw bytes from AF_PACKET socket.

    Returns:
        RawObservation or None if frame can't be parsed.
    """
    rt_len, rssi, noise, freq = _parse_radiotap(data)
    if rt_len == 0 or rssi is None:
        return None

    # 802.11 header starts after radiotap
    dot11_start = rt_len
    if dot11_start + 24 > len(data):
        return None

    # Frame control: 2 bytes
    fc = struct.unpack_from("<H", data, dot11_start)[0]
    frame_type = (fc >> 2) & 0x03
    subtype = (fc >> 4) & 0x0F

    ftype_str = _classify_frame(frame_type, subtype)
    if ftype_str is None:
        return None

    # Source address (addr2) at offset +10 from dot11 header
    addr2_offset = dot11_start + 10
    if addr2_offset + 6 > len(data):
        return None

    mac_bytes = data[addr2_offset:addr2_offset + 6]
    mac = ":".join("%02x" % b for b in mac_bytes)

    if mac == "ff:ff:ff:ff:ff:ff":
        return None

    channel = freq_to_channel(freq) if freq else 0
    bandwidth = freq_to_band(freq) if freq else "2.4GHz"

    # Try to extract SSID from beacon/probe frames
    ssid = None
    if ftype_str in ("beacon", "probe_response"):
        # Fixed params (timestamp=8, interval=2, capability=2) = 12 bytes after header
        ssid_offset = dot11_start + 24 + 12
        ssid = _extract_ssid(data, ssid_offset)
    elif ftype_str == "probe_request":
        ssid_offset = dot11_start + 24
        ssid = _extract_ssid(data, ssid_offset)

    return RawObservation(
        mac=mac,
        rssi_dbm=rssi,
        noise_dbm=noise,
        channel=channel,
        bandwidth=bandwidth,
        frame_type=ftype_str,
        ssid=ssid,
        is_randomized_mac=is_locally_administered(mac),
    )


def create_monitor_socket(interface: str) -> socket.socket:
    """Create a raw socket bound to a monitor mode interface."""
    ETH_P_ALL = 0x0003
    sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
    sock.bind((interface, 0))
    sock.settimeout(1.0)
    return sock


def capture_frames(
    interface: str,
    count: int = 0,
    timeout: float = 5.0,
) -> List[RawObservation]:
    """Capture and parse WiFi frames from a monitor mode interface.

    Args:
        interface: Network interface in monitor mode.
        count: Max frames to capture (0 = unlimited until timeout).
        timeout: Capture timeout in seconds.

    Returns:
        List of parsed observations.
    """
    sock = create_monitor_socket(interface)
    observations = []
    deadline = time.monotonic() + timeout

    try:
        while time.monotonic() < deadline:
            if count > 0 and len(observations) >= count:
                break
            try:
                data = sock.recv(65535)
                obs = parse_raw_frame(data)
                if obs:
                    observations.append(obs)
            except socket.timeout:
                continue
            except OSError as e:
                logger.warning("Capture error: %s", e)
                break
    finally:
        sock.close()

    return observations
