#!/usr/bin/env python3
"""5map WiFi RSSI Capture Agent for WiFi Pineapple Mark VII.

Captures WiFi frames in monitor mode from both radios, extracts RSSI
and metadata, and streams observation windows to AWS IoT Core via MQTT.
"""

import argparse
import json
import logging
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from pineapple.channel_hopper import ChannelHopper
from pineapple.parsers.rssi_parser import Observation, ObservationWindow, parse_frame
from pineapple.transport.mqtt_client import MQTTTransport

logger = logging.getLogger("5map-agent")


class CaptureAgent:
    """Main capture agent coordinating radios, parsing, and transport."""

    def __init__(self, config_path: str):
        self.config = self._load_config(config_path)
        self.sensor_id = self.config["sensor"]["id"]
        self.running = threading.Event()
        self.running.set()

        self._current_observations: dict[str, Observation] = {}
        self._obs_lock = threading.Lock()
        self._window_start = time.monotonic()
        self._position: dict | None = None

        self._window_seconds = self.config["capture"]["window_seconds"]
        self._max_obs = self.config["capture"]["max_observations_per_window"]

        self.transport = MQTTTransport(
            config=self.config["transport"],
            sensor_id=self.sensor_id,
        )
        self.hoppers: list[ChannelHopper] = []
        self._capture_threads: list[threading.Thread] = []

    def _load_config(self, path: str) -> dict:
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config not found: {path}")
        with open(config_path) as f:
            return yaml.safe_load(f)

    def _setup_logging(self) -> None:
        log_cfg = self.config.get("logging", {})
        level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)

        formatter = logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
        )

        console = logging.StreamHandler()
        console.setFormatter(formatter)
        logger.addHandler(console)

        log_file = log_cfg.get("file")
        if log_file:
            from logging.handlers import RotatingFileHandler

            handler = RotatingFileHandler(
                log_file,
                maxBytes=log_cfg.get("max_bytes", 5 * 1024 * 1024),
                backupCount=log_cfg.get("backup_count", 3),
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        logger.setLevel(level)

    def _handle_packet(self, packet) -> None:
        """Process a single captured packet."""
        obs = parse_frame(packet)
        if obs is None:
            return

        with self._obs_lock:
            if len(self._current_observations) >= self._max_obs:
                return

            existing = self._current_observations.get(obs.mac)
            if existing:
                existing.count += obs.count
                if obs.rssi_dbm > existing.rssi_dbm:
                    existing.rssi_dbm = obs.rssi_dbm
            else:
                self._current_observations[obs.mac] = obs

    def _flush_window(self) -> ObservationWindow | None:
        """Collect current observations into a window and reset."""
        with self._obs_lock:
            if not self._current_observations:
                return None

            observations = list(self._current_observations.values())
            self._current_observations.clear()
            self._window_start = time.monotonic()

        return ObservationWindow(
            timestamp=datetime.now(timezone.utc).isoformat(),
            sensor_id=self.sensor_id,
            sensor_type="rssi",
            window_ms=int(self._window_seconds * 1000),
            observations=observations,
            position=self._position,
        )

    def _capture_loop(self, interface: str) -> None:
        """Capture packets on a single interface using scapy."""
        try:
            from scapy.all import sniff
        except ImportError:
            logger.error("scapy not installed. Install with: pip install scapy")
            return

        logger.info(f"Starting capture on {interface}")
        try:
            sniff(
                iface=interface,
                prn=self._handle_packet,
                store=False,
                stop_filter=lambda _: not self.running.is_set(),
            )
        except PermissionError:
            logger.error(f"Permission denied on {interface}. Run as root.")
        except OSError as e:
            logger.error(f"Capture error on {interface}: {e}")

    def _window_flush_loop(self) -> None:
        """Periodically flush observation windows and publish."""
        while self.running.is_set():
            time.sleep(self._window_seconds)
            window = self._flush_window()
            if window:
                success = self.transport.publish(window)
                if success:
                    logger.debug(
                        f"Published window: {len(window.observations)} observations"
                    )
                else:
                    logger.warning("Failed to queue window for publishing")

    def set_position(self, x: float, y: float, label: str) -> None:
        """Update the current position tag (set from mobile app)."""
        self._position = {"x": x, "y": y, "label": label}

    def start(self) -> None:
        """Start the capture agent."""
        self._setup_logging()
        logger.info(f"5map Agent starting (sensor_id={self.sensor_id})")

        # Connect transport
        self.transport.connect()

        # Start channel hoppers for each radio
        for radio_name, radio_cfg in self.config.get("radios", {}).items():
            interface = radio_cfg["interface"]
            channels = radio_cfg["channels"]
            dwell_ms = self.config["capture"].get("channel_dwell_ms", 200)

            hopper = ChannelHopper(interface, channels, dwell_ms)
            hopper.start()
            self.hoppers.append(hopper)
            logger.info(f"Channel hopper started for {interface} ({radio_name})")

            # Start capture thread for this interface
            t = threading.Thread(
                target=self._capture_loop,
                args=(interface,),
                daemon=True,
                name=f"capture-{interface}",
            )
            t.start()
            self._capture_threads.append(t)

        # Start window flush loop
        flush_thread = threading.Thread(
            target=self._window_flush_loop,
            daemon=True,
            name="window-flush",
        )
        flush_thread.start()

        logger.info("Capture agent running. Press Ctrl+C to stop.")

        # Block until stop signal
        try:
            while self.running.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass

    def stop(self) -> None:
        """Gracefully stop the capture agent."""
        logger.info("Stopping capture agent...")
        self.running.clear()

        # Stop channel hoppers
        for hopper in self.hoppers:
            hopper.stop()

        # Flush remaining data
        window = self._flush_window()
        if window:
            self.transport.publish(window)

        # Disconnect transport
        self.transport.flush()
        self.transport.disconnect()

        logger.info("Capture agent stopped")


def main():
    parser = argparse.ArgumentParser(description="5map WiFi RSSI Capture Agent")
    parser.add_argument(
        "--config",
        default="/opt/5map/pineapple/config.yaml",
        help="Path to config.yaml",
    )
    args = parser.parse_args()

    agent = CaptureAgent(args.config)

    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}")
        agent.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGHUP, signal_handler)

    try:
        agent.start()
    except Exception as e:
        logger.error(f"Agent failed: {e}")
        agent.stop()
        sys.exit(1)


if __name__ == "__main__":
    main()
