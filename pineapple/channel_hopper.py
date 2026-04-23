"""Channel hopper for WiFi Pineapple Mark VII monitor-mode interfaces.

Cycles through a configured list of WiFi channels on a given interface,
switching frequencies via ``iw`` in a background thread with configurable
dwell time per channel.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from typing import Dict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Channel <-> frequency lookup tables
# ---------------------------------------------------------------------------

_CHANNEL_TO_FREQ: Dict[int, int] = {
    # 2.4 GHz band
    1: 2412,
    2: 2417,
    3: 2422,
    4: 2427,
    5: 2432,
    6: 2437,
    7: 2442,
    8: 2447,
    9: 2452,
    10: 2457,
    11: 2462,
    # 5 GHz UNII-1
    36: 5180,
    40: 5200,
    44: 5220,
    48: 5240,
    # 5 GHz UNII-2 (DFS)
    52: 5260,
    56: 5280,
    60: 5300,
    64: 5320,
    # 5 GHz UNII-2 Extended (DFS)
    100: 5500,
    104: 5520,
    108: 5540,
    112: 5560,
    116: 5580,
    120: 5600,
    124: 5620,
    128: 5640,
    132: 5660,
    136: 5680,
    140: 5700,
    144: 5720,
    # 5 GHz UNII-3
    149: 5745,
    153: 5765,
    157: 5785,
    161: 5805,
    165: 5825,
}

_FREQ_TO_CHANNEL: Dict[int, int] = {freq: ch for ch, freq in _CHANNEL_TO_FREQ.items()}


class ChannelHopperError(Exception):
    """Raised for unrecoverable channel-hopper configuration errors."""


class ChannelHopper:
    """Hop across WiFi channels on a monitor-mode interface.

    The hopper runs in a daemon thread and can be stopped gracefully via
    :meth:`stop`.  Channel switches are performed with::

        iw dev {interface} set freq {freq_mhz}

    Args:
        interface: Wireless interface name (e.g. ``wlan0``).
        channels: Ordered list of channel numbers to cycle through.
        dwell_ms: Time in milliseconds to dwell on each channel before
            switching.  Defaults to ``200``.

    Raises:
        ChannelHopperError: If *channels* is empty or contains an
            unknown channel number.
    """

    def __init__(
        self,
        interface: str,
        channels: list[int],
        dwell_ms: int = 200,
    ) -> None:
        if not channels:
            raise ChannelHopperError("channels list must not be empty")

        unknown = [ch for ch in channels if ch not in _CHANNEL_TO_FREQ]
        if unknown:
            raise ChannelHopperError(f"unknown channel numbers: {unknown}")

        self._interface = interface
        self._channels = list(channels)
        self._dwell_s = dwell_ms / 1000.0
        self._current_channel: int = self._channels[0]
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the channel-hopping thread.

        The thread is created as a daemon so it will not prevent interpreter
        shutdown if :meth:`stop` is never called.
        """
        if self._thread is not None and self._thread.is_alive():
            logger.warning("channel hopper already running on %s", self._interface)
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._hop_loop,
            name=f"channel-hopper-{self._interface}",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "channel hopper started on %s  channels=%s  dwell=%dms",
            self._interface,
            self._channels,
            int(self._dwell_s * 1000),
        )

    def stop(self) -> None:
        """Signal the hopper thread to stop and wait for it to finish."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(self._dwell_s * 2, 2.0))
            if self._thread.is_alive():
                logger.warning(
                    "channel hopper thread on %s did not exit cleanly",
                    self._interface,
                )
            self._thread = None
        logger.info("channel hopper stopped on %s", self._interface)

    def current_channel(self) -> int:
        """Return the channel the hopper most recently switched to."""
        with self._lock:
            return self._current_channel

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def channel_to_freq(channel: int) -> int:
        """Convert a WiFi channel number to its centre frequency in MHz.

        Args:
            channel: Channel number (e.g. ``6`` or ``36``).

        Returns:
            Frequency in MHz.

        Raises:
            ValueError: If the channel number is not in the lookup table.
        """
        try:
            return _CHANNEL_TO_FREQ[channel]
        except KeyError:
            raise ValueError(f"unknown WiFi channel: {channel}") from None

    @staticmethod
    def freq_to_channel(freq: int) -> int:
        """Convert a centre frequency in MHz to its WiFi channel number.

        Args:
            freq: Frequency in MHz (e.g. ``2437`` or ``5180``).

        Returns:
            Channel number.

        Raises:
            ValueError: If the frequency is not in the lookup table.
        """
        try:
            return _FREQ_TO_CHANNEL[freq]
        except KeyError:
            raise ValueError(f"unknown WiFi frequency: {freq} MHz") from None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _set_channel(self, channel: int) -> bool:
        """Switch the interface to *channel* via ``iw``.

        Returns:
            ``True`` if the switch succeeded, ``False`` otherwise.
        """
        freq = _CHANNEL_TO_FREQ[channel]
        cmd = ["iw", "dev", self._interface, "set", "freq", str(freq)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=5)  # noqa: S603
        except subprocess.CalledProcessError as exc:
            logger.warning(
                "failed to set %s to channel %d (%d MHz): %s",
                self._interface,
                channel,
                freq,
                exc.stderr.decode(errors="replace").strip() if exc.stderr else str(exc),
            )
            return False
        except subprocess.TimeoutExpired:
            logger.warning(
                "timeout setting %s to channel %d (%d MHz)",
                self._interface,
                channel,
                freq,
            )
            return False
        except OSError as exc:
            logger.warning(
                "OS error setting %s to channel %d (%d MHz): %s",
                self._interface,
                channel,
                freq,
                exc,
            )
            return False

        logger.debug(
            "%s -> channel %d (%d MHz)",
            self._interface,
            channel,
            freq,
        )
        return True

    def _hop_loop(self) -> None:
        """Main loop executed in the hopper thread."""
        idx = 0
        num_channels = len(self._channels)

        while not self._stop_event.is_set():
            channel = self._channels[idx]

            if self._set_channel(channel):
                with self._lock:
                    self._current_channel = channel

            idx = (idx + 1) % num_channels

            # Use Event.wait so we can be interrupted mid-dwell.
            self._stop_event.wait(timeout=self._dwell_s)
