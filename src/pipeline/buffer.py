"""Frame buffer with time-window flushing and backpressure.

Buffers SensorFrames into time windows and flushes them to the transport
layer. Enforces a max size cap and drops oldest frames under pressure.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Callable, Deque, List, Optional

from src.sensors.base import SensorFrame

logger = logging.getLogger(__name__)


class FrameBuffer:
    """Thread-safe frame buffer with configurable flush and backpressure.

    Args:
        flush_interval_s: Seconds between automatic flushes.
        max_size: Maximum frames to buffer. Oldest dropped when exceeded.
        on_flush: Callback invoked with list of frames when flushing.
    """

    def __init__(
        self,
        flush_interval_s: float = 1.0,
        max_size: int = 10000,
        on_flush: Optional[Callable[[List[SensorFrame]], None]] = None,
    ) -> None:
        self._flush_interval = flush_interval_s
        self._max_size = max_size
        self._on_flush = on_flush

        self._buffer: Deque[SensorFrame] = deque(maxlen=max_size)
        self._lock = threading.Lock()
        self._drop_count = 0

        self._flush_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def add(self, frame: SensorFrame) -> bool:
        """Add a frame to the buffer.

        Args:
            frame: The sensor frame to buffer.

        Returns:
            True if the frame was added, False if buffer is at capacity
            (oldest frame was dropped to make room).
        """
        with self._lock:
            was_full = len(self._buffer) >= self._max_size
            if was_full:
                self._drop_count += 1
                if self._drop_count % 100 == 1:
                    logger.warning(
                        "Buffer at capacity (%d). Dropping oldest frames. "
                        "Total dropped: %d",
                        self._max_size,
                        self._drop_count,
                    )
            self._buffer.append(frame)
            return not was_full

    def flush(self) -> List[SensorFrame]:
        """Flush all buffered frames.

        Returns:
            List of frames that were in the buffer.
        """
        with self._lock:
            frames = list(self._buffer)
            self._buffer.clear()

        if frames and self._on_flush:
            try:
                self._on_flush(frames)
            except Exception as e:
                logger.error("Flush callback failed: %s", e)

        return frames

    def start(self) -> None:
        """Start the automatic flush timer thread."""
        if self._flush_thread and self._flush_thread.is_alive():
            return

        self._stop_event.clear()
        self._flush_thread = threading.Thread(
            target=self._flush_loop,
            daemon=True,
            name="frame-buffer-flush",
        )
        self._flush_thread.start()
        logger.info(
            "Frame buffer started (interval=%.1fs, max_size=%d)",
            self._flush_interval,
            self._max_size,
        )

    def stop(self) -> None:
        """Stop the flush timer and do a final flush."""
        self._stop_event.set()
        if self._flush_thread:
            self._flush_thread.join(timeout=5.0)
        self.flush()

    def _flush_loop(self) -> None:
        """Periodic flush loop running in background thread."""
        while not self._stop_event.wait(timeout=self._flush_interval):
            if self._buffer:
                self.flush()

    @property
    def size(self) -> int:
        """Current number of frames in buffer."""
        with self._lock:
            return len(self._buffer)

    @property
    def drop_count(self) -> int:
        """Total number of frames dropped due to backpressure."""
        return self._drop_count

    @property
    def is_full(self) -> bool:
        """Whether buffer is at max capacity."""
        with self._lock:
            return len(self._buffer) >= self._max_size
