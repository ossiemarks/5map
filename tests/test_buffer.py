"""Tests for FrameBuffer with backpressure."""

import time
import threading

import pytest

from src.sensors.base import SensorFrame, SensorType
from src.pipeline.buffer import FrameBuffer


def _make_frame(sensor_id: str = "test-001") -> SensorFrame:
    return SensorFrame(
        timestamp="2026-04-20T20:00:00Z",
        sensor_id=sensor_id,
        sensor_type=SensorType.RSSI,
    )


class TestFrameBuffer:
    def test_add_and_flush(self):
        buf = FrameBuffer(max_size=100)
        buf.add(_make_frame())
        buf.add(_make_frame())
        frames = buf.flush()
        assert len(frames) == 2
        assert buf.size == 0

    def test_flush_empty_returns_empty(self):
        buf = FrameBuffer()
        assert buf.flush() == []

    def test_max_size_drops_oldest(self):
        buf = FrameBuffer(max_size=3)
        for i in range(5):
            buf.add(_make_frame(f"sensor-{i}"))
        assert buf.size == 3
        assert buf.drop_count == 2
        frames = buf.flush()
        # Should have the 3 most recent
        assert frames[-1].sensor_id == "sensor-4"

    def test_add_returns_false_when_full(self):
        buf = FrameBuffer(max_size=2)
        assert buf.add(_make_frame()) is True
        assert buf.add(_make_frame()) is True
        assert buf.add(_make_frame()) is False  # at capacity, dropped oldest

    def test_is_full(self):
        buf = FrameBuffer(max_size=2)
        assert buf.is_full is False
        buf.add(_make_frame())
        buf.add(_make_frame())
        assert buf.is_full is True

    def test_on_flush_callback(self):
        received = []
        buf = FrameBuffer(on_flush=lambda frames: received.extend(frames))
        buf.add(_make_frame())
        buf.add(_make_frame())
        buf.flush()
        assert len(received) == 2

    def test_flush_callback_error_doesnt_crash(self):
        def bad_callback(frames):
            raise RuntimeError("oops")

        buf = FrameBuffer(on_flush=bad_callback)
        buf.add(_make_frame())
        frames = buf.flush()
        assert len(frames) == 1  # still returns frames

    def test_start_and_stop(self):
        flushed = []
        buf = FrameBuffer(
            flush_interval_s=0.05,
            on_flush=lambda frames: flushed.extend(frames),
        )
        buf.start()
        buf.add(_make_frame())
        time.sleep(0.15)  # allow flush
        buf.stop()
        assert len(flushed) >= 1

    def test_concurrent_adds(self):
        buf = FrameBuffer(max_size=1000)
        errors = []

        def add_frames():
            try:
                for _ in range(100):
                    buf.add(_make_frame())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_frames) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # All 1000 should be buffered (max_size=1000)
        assert buf.size == 1000
