"""CSI signal processor for 5map WiFi Channel State Information.

Decodes raw ESP32 CSI data (base64-encoded int8 I/Q pairs) into
amplitude and phase arrays per subcarrier, then extracts features
for environment sensing, gesture detection, and activity recognition.

ESP32 CSI buffer format:
    [imag_0, real_0, imag_1, real_1, ..., imag_N, real_N]
    Each value is int8 (-128 to 127).
    For 20MHz: 64 subcarriers (128 bytes)
    For 40MHz: 128 subcarriers (256 bytes)
"""

from __future__ import annotations

import base64
import logging
import math
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ESP32 subcarrier indices for useful data (skip null/pilot subcarriers)
# 20MHz OFDM: 64 subcarriers, indices -26 to -1 and 1 to 26 are data
SUBCARRIER_DATA_20MHZ = list(range(6, 32)) + list(range(33, 59))
# 40MHz OFDM: 128 subcarriers
SUBCARRIER_DATA_40MHZ = list(range(6, 64)) + list(range(65, 123))


@dataclass(slots=True)
class CSIFrame:
    """Decoded CSI frame with amplitude and phase per subcarrier."""

    mac: str
    rssi_dbm: int
    channel: int
    bandwidth: int
    noise_floor: int
    rate: int
    timestamp_ms: int
    num_subcarriers: int
    amplitude: np.ndarray       # shape: (num_subcarriers,)
    phase: np.ndarray           # shape: (num_subcarriers,)
    raw_iq: np.ndarray          # shape: (num_subcarriers, 2) -> [imag, real]


@dataclass
class CSIFeatures:
    """Extracted features from a window of CSI frames."""

    mac: str
    channel: int
    bandwidth: int
    window_frames: int
    timestamp_ms: int

    # Amplitude features
    amp_mean: np.ndarray            # Mean amplitude per subcarrier
    amp_std: np.ndarray             # Std deviation per subcarrier
    amp_max: np.ndarray             # Max amplitude per subcarrier
    amp_range: np.ndarray           # Max - min per subcarrier
    amp_variance_ratio: float       # Overall variance ratio (activity indicator)

    # Phase features
    phase_mean: np.ndarray          # Mean phase per subcarrier
    phase_std: np.ndarray           # Phase stability per subcarrier

    # Temporal features
    amp_diff_mean: np.ndarray       # Mean frame-to-frame amplitude change
    correlation_matrix: Optional[np.ndarray] = None  # Subcarrier correlation

    # Derived metrics
    motion_score: float = 0.0       # 0-1 motion detection confidence
    breathing_indicator: float = 0.0  # Periodic motion at ~0.2-0.5Hz


def decode_csi_buffer(b64_data: str, num_subcarriers: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Decode base64-encoded CSI buffer into amplitude, phase, and raw I/Q.

    Args:
        b64_data: Base64-encoded string of int8 [imag, real] pairs.
        num_subcarriers: Expected number of subcarriers.

    Returns:
        Tuple of (amplitude, phase, raw_iq) numpy arrays.
    """
    raw = base64.b64decode(b64_data)
    iq = np.frombuffer(raw, dtype=np.int8).reshape(-1, 2).astype(np.float32)

    # iq[:, 0] = imaginary, iq[:, 1] = real
    imag = iq[:, 0]
    real = iq[:, 1]

    amplitude = np.sqrt(real ** 2 + imag ** 2)
    phase = np.arctan2(imag, real)

    return amplitude, phase, iq


def parse_csi_json(data: dict) -> Optional[CSIFrame]:
    """Parse a CSI JSON message from ESP32 serial into a CSIFrame.

    Args:
        data: Parsed JSON dict with keys: t, mac, rssi, ch, bw, len, ns, noise, rate, ts, data

    Returns:
        CSIFrame or None if parsing fails.
    """
    if data.get("t") != "csi" or "data" not in data:
        return None

    try:
        ns = int(data.get("ns", data.get("len", 0) // 2))
        amplitude, phase, raw_iq = decode_csi_buffer(data["data"], ns)

        return CSIFrame(
            mac=data.get("mac", ""),
            rssi_dbm=int(data.get("rssi", -100)),
            channel=int(data.get("ch", 0)),
            bandwidth=int(data.get("bw", 20)),
            noise_floor=int(data.get("noise", -90)),
            rate=int(data.get("rate", 0)),
            timestamp_ms=int(data.get("ts", 0)),
            num_subcarriers=ns,
            amplitude=amplitude,
            phase=phase,
            raw_iq=raw_iq,
        )
    except Exception as e:
        logger.debug("Failed to parse CSI frame: %s", e)
        return None


class CSIProcessor:
    """Sliding window CSI processor that extracts features from frame streams.

    Maintains a per-MAC deque of recent CSI frames and computes features
    over configurable time windows for motion detection, activity sensing,
    and environment characterization.
    """

    def __init__(
        self,
        window_size: int = 100,
        feature_interval_ms: int = 500,
        subcarrier_selection: str = "data",
    ) -> None:
        """Initialize CSI processor.

        Args:
            window_size: Max frames to keep per MAC in sliding window.
            feature_interval_ms: Minimum interval between feature extractions.
            subcarrier_selection: 'all' for all subcarriers, 'data' for data-only.
        """
        self._window_size = window_size
        self._feature_interval_ms = feature_interval_ms
        self._subcarrier_selection = subcarrier_selection
        self._buffers: dict[str, deque[CSIFrame]] = {}
        self._last_feature_ts: dict[str, int] = {}
        self._frame_count = 0

    def add_frame(self, frame: CSIFrame) -> Optional[CSIFeatures]:
        """Add a CSI frame and optionally extract features.

        Returns CSIFeatures if enough time has passed since the last extraction
        and there are enough frames in the buffer.

        Args:
            frame: Decoded CSI frame.

        Returns:
            CSIFeatures if ready, None otherwise.
        """
        mac = frame.mac
        if mac not in self._buffers:
            self._buffers[mac] = deque(maxlen=self._window_size)
            self._last_feature_ts[mac] = 0

        self._buffers[mac].append(frame)
        self._frame_count += 1

        # Check if we should extract features
        elapsed = frame.timestamp_ms - self._last_feature_ts[mac]
        if elapsed >= self._feature_interval_ms and len(self._buffers[mac]) >= 5:
            self._last_feature_ts[mac] = frame.timestamp_ms
            return self.extract_features(mac)

        return None

    def extract_features(self, mac: str) -> Optional[CSIFeatures]:
        """Extract features from the current window for a given MAC.

        Args:
            mac: MAC address to extract features for.

        Returns:
            CSIFeatures or None if insufficient data.
        """
        buf = self._buffers.get(mac)
        if not buf or len(buf) < 3:
            return None

        frames = list(buf)
        n_frames = len(frames)

        # Select subcarrier indices
        bw = frames[0].bandwidth
        if self._subcarrier_selection == "data":
            indices = SUBCARRIER_DATA_20MHZ if bw == 20 else SUBCARRIER_DATA_40MHZ
            max_idx = frames[0].num_subcarriers
            indices = [i for i in indices if i < max_idx]
        else:
            indices = list(range(frames[0].num_subcarriers))

        if not indices:
            indices = list(range(frames[0].num_subcarriers))

        # Stack amplitude and phase matrices: (n_frames, n_subcarriers)
        amp_matrix = np.array([f.amplitude[indices] for f in frames])
        phase_matrix = np.array([f.phase[indices] for f in frames])

        # Amplitude features
        amp_mean = np.mean(amp_matrix, axis=0)
        amp_std = np.std(amp_matrix, axis=0)
        amp_max = np.max(amp_matrix, axis=0)
        amp_min = np.min(amp_matrix, axis=0)
        amp_range = amp_max - amp_min

        # Overall variance ratio (high = motion, low = static)
        total_var = np.mean(amp_std ** 2)
        mean_power = np.mean(amp_mean ** 2) + 1e-10
        amp_variance_ratio = float(total_var / mean_power)

        # Phase features
        phase_mean = np.mean(phase_matrix, axis=0)
        phase_std = np.std(phase_matrix, axis=0)

        # Temporal features: frame-to-frame amplitude difference
        if n_frames >= 2:
            amp_diff = np.diff(amp_matrix, axis=0)
            amp_diff_mean = np.mean(np.abs(amp_diff), axis=0)
        else:
            amp_diff_mean = np.zeros_like(amp_mean)

        # Motion score: normalized variance ratio [0, 1]
        motion_score = min(1.0, amp_variance_ratio * 10.0)

        # Breathing indicator: look for periodic motion at 0.2-0.5 Hz
        breathing = 0.0
        if n_frames >= 20:
            breathing = self._detect_periodic_motion(amp_matrix, frames)

        return CSIFeatures(
            mac=mac,
            channel=frames[0].channel,
            bandwidth=bw,
            window_frames=n_frames,
            timestamp_ms=frames[-1].timestamp_ms,
            amp_mean=amp_mean,
            amp_std=amp_std,
            amp_max=amp_max,
            amp_range=amp_range,
            amp_variance_ratio=amp_variance_ratio,
            phase_mean=phase_mean,
            phase_std=phase_std,
            amp_diff_mean=amp_diff_mean,
            motion_score=motion_score,
            breathing_indicator=breathing,
        )

    def _detect_periodic_motion(
        self, amp_matrix: np.ndarray, frames: list[CSIFrame]
    ) -> float:
        """Detect periodic motion (breathing/gestures) using FFT on amplitude variance.

        Args:
            amp_matrix: (n_frames, n_subcarriers) amplitude data.
            frames: List of CSI frames for timestamp info.

        Returns:
            Breathing indicator score [0, 1].
        """
        n_frames = amp_matrix.shape[0]
        if n_frames < 20:
            return 0.0

        # Estimate sample rate from timestamps
        dt_ms = frames[-1].timestamp_ms - frames[0].timestamp_ms
        if dt_ms <= 0:
            return 0.0
        sample_rate = (n_frames - 1) / (dt_ms / 1000.0)

        # Use mean amplitude across subcarriers as signal
        signal = np.mean(amp_matrix, axis=1)
        signal = signal - np.mean(signal)  # Remove DC

        # FFT
        fft_vals = np.abs(np.fft.rfft(signal))
        freqs = np.fft.rfftfreq(len(signal), d=1.0 / sample_rate)

        # Look for peaks in breathing range (0.15 - 0.5 Hz)
        breathing_mask = (freqs >= 0.15) & (freqs <= 0.5)
        if not np.any(breathing_mask):
            return 0.0

        breathing_power = np.max(fft_vals[breathing_mask])
        total_power = np.sum(fft_vals[1:]) + 1e-10  # Skip DC

        return float(min(1.0, breathing_power / total_power * 5.0))

    def get_active_macs(self) -> list[str]:
        """Return MACs with frames in the buffer."""
        return [mac for mac, buf in self._buffers.items() if len(buf) > 0]

    def get_buffer_stats(self) -> dict:
        """Return processor statistics."""
        return {
            "total_frames": self._frame_count,
            "active_macs": len(self._buffers),
            "buffer_sizes": {mac: len(buf) for mac, buf in self._buffers.items()},
        }

    def clear(self, mac: Optional[str] = None) -> None:
        """Clear frame buffers."""
        if mac:
            self._buffers.pop(mac, None)
            self._last_feature_ts.pop(mac, None)
        else:
            self._buffers.clear()
            self._last_feature_ts.clear()


def features_to_dict(features: CSIFeatures) -> dict:
    """Convert CSIFeatures to a JSON-serializable dict.

    Args:
        features: Extracted CSI features.

    Returns:
        Dict suitable for JSON serialization or pipeline transport.
    """
    return {
        "mac": features.mac,
        "channel": features.channel,
        "bandwidth": features.bandwidth,
        "window_frames": features.window_frames,
        "timestamp_ms": features.timestamp_ms,
        "motion_score": round(features.motion_score, 4),
        "breathing_indicator": round(features.breathing_indicator, 4),
        "amp_variance_ratio": round(features.amp_variance_ratio, 6),
        "amp_mean": features.amp_mean.tolist(),
        "amp_std": features.amp_std.tolist(),
        "amp_range": features.amp_range.tolist(),
        "phase_std": features.phase_std.tolist(),
        "amp_diff_mean": features.amp_diff_mean.tolist(),
        "num_subcarriers": len(features.amp_mean),
    }
