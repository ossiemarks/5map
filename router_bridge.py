#!/usr/bin/env python3
"""5map Router Bridge — reads WiFi data from CH340 mini router, feeds the pipeline.

Connects to the 300m mini net router over USB serial (CH340), polls for
WiFi environment data, and publishes to AWS IoT Core via MQTT.

The router serves dual purpose:
  1. CSI transmitter — its beacons are captured by the ESP32 for CSI analysis
  2. WiFi environment sensor — reports station data, signal levels, channel info

Usage:
    python3 router_bridge.py --port /dev/ttyUSB0
    python3 router_bridge.py --port /dev/ttyUSB0 --dashboard-data dashboard/data.json
"""

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from src.sensors.router_csi_sensor import (
    RouterCSISensor,
    RouterObservation,
    RouterWindowAggregator,
)

logger = logging.getLogger("5map-router-bridge")

WINDOW_SECONDS = 3.0


class RouterBridge:
    """Bridge between the CH340 mini router and the 5map pipeline."""

    def __init__(self, port: str, baud: int, config: dict):
        self.port = port
        self.baud = baud
        self.config = config
        self.sensor_id = config.get("sensor", {}).get("id", "router-001")
        self.running = threading.Event()
        self.running.set()

        # Sensor
        self.sensor = RouterCSISensor()
        sensor_config = {
            "sensor_id": f"{self.sensor_id}-csi",
            "port": port,
            "baud": baud,
        }
        # SSH transport
        sensor_cfg = config.get("sensor", {})
        if sensor_cfg.get("ssh_host"):
            sensor_config["ssh_host"] = sensor_cfg["ssh_host"]
            sensor_config["ssh_user"] = sensor_cfg.get("ssh_user", "root")
            sensor_config["ssh_password"] = sensor_cfg.get("ssh_password", "")
        self.sensor.configure(sensor_config)

        # Aggregator
        self.aggregator = RouterWindowAggregator(
            sensor_id=f"{self.sensor_id}-csi",
            window_ms=int(WINDOW_SECONDS * 1000),
        )

        # MQTT transport (optional)
        self.transport = None
        if "transport" in config:
            try:
                from pineapple.transport.mqtt_client import MQTTTransport
                self.transport = MQTTTransport(
                    config=config["transport"],
                    sensor_id=self.sensor_id,
                )
            except ImportError:
                logger.warning("MQTT transport not available, local-only mode")

        # Stats
        self.stats = {
            "poll_count": 0,
            "observation_count": 0,
            "window_count": 0,
            "errors": 0,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

        # Dashboard export
        self._dashboard_data_path = config.get("dashboard_data_path", None)

    def _poll_loop(self) -> None:
        """Poll the router for WiFi data."""
        reconnect_delay = 1

        while self.running.is_set():
            if not self.sensor.health_check():
                logger.info("Connecting to router on %s...", self.port)
                if self.sensor.connect():
                    reconnect_delay = 1
                    logger.info("Router connected (mode: %s)", self.sensor._mode)
                else:
                    logger.warning("Router not available, retrying in %ds", reconnect_delay)
                    time.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, 30)
                    continue

            try:
                observations = self.sensor.poll()
                for obs in observations:
                    self.aggregator.add(obs)
                    self.stats["observation_count"] += 1

                self.stats["poll_count"] += 1
                time.sleep(WINDOW_SECONDS)

            except Exception as e:
                self.stats["errors"] += 1
                logger.error("Poll error: %s", e)
                self.sensor.disconnect()
                time.sleep(reconnect_delay)

    def _flush_loop(self) -> None:
        """Periodically flush windows and publish."""
        while self.running.is_set():
            time.sleep(WINDOW_SECONDS)

            window = self.aggregator.flush()
            if window.observations:
                self.sensor.feed_window(window)
                frame = self.sensor.capture()
                if frame and self.transport:
                    self.transport.publish(frame)

                self.stats["window_count"] += 1
                logger.debug("Router window: %d observations", len(window.observations))

    def _dashboard_export_loop(self) -> None:
        """Export router data to dashboard data.json."""
        if not self._dashboard_data_path:
            return

        while self.running.is_set():
            time.sleep(5)
            try:
                data_path = Path(self._dashboard_data_path)
                if data_path.exists():
                    with open(data_path) as f:
                        dashboard_data = json.load(f)
                else:
                    dashboard_data = {}

                dashboard_data["router_sensor"] = {
                    "sensor_id": self.sensor_id,
                    "stats": self.sensor.get_stats(),
                    "bridge_stats": dict(self.stats),
                    "last_update": datetime.now(timezone.utc).isoformat(),
                }

                with open(data_path, "w") as f:
                    json.dump(dashboard_data, f, indent=2)

            except Exception as e:
                logger.debug("Dashboard export error: %s", e)

    def start(self) -> None:
        logger.info("Router Bridge starting (sensor_id=%s, port=%s)",
                     self.sensor_id, self.port)

        if self.transport:
            self.transport.connect()

        threads = [
            threading.Thread(target=self._poll_loop, daemon=True, name="router-poll"),
            threading.Thread(target=self._flush_loop, daemon=True, name="router-flush"),
        ]

        if self._dashboard_data_path:
            threads.append(
                threading.Thread(target=self._dashboard_export_loop, daemon=True,
                                 name="router-dashboard")
            )

        for t in threads:
            t.start()

        logger.info("Router Bridge running")

        try:
            while self.running.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass

    def stop(self) -> None:
        logger.info("Stopping Router Bridge...")
        self.running.clear()
        self.sensor.disconnect()

        if self.transport:
            self.transport.flush()
            self.transport.disconnect()

        logger.info("Router Bridge stopped. Stats: %s", json.dumps(self.stats))


def detect_router_port() -> str:
    """Auto-detect the CH340 router serial port."""
    for port in ["/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyUSB2"]:
        if os.path.exists(port):
            logger.info("Auto-detected router port: %s", port)
            return port
    return "/dev/ttyUSB0"


def main():
    parser = argparse.ArgumentParser(description="5map Router CSI Bridge")
    parser.add_argument("--port", default=None,
                        help="Serial port (auto-detect if omitted)")
    parser.add_argument("--baud", type=int, default=115200,
                        help="Baud rate (default: 115200)")
    parser.add_argument("--ssh", default=None,
                        help="SSH host for WiFi transport (e.g. 192.168.8.1)")
    parser.add_argument("--ssh-user", default="root",
                        help="SSH username (default: root)")
    parser.add_argument("--ssh-password", default="",
                        help="SSH password")
    parser.add_argument("--config", default="/etc/5map/config.yaml",
                        help="Path to config.yaml")
    parser.add_argument("--dashboard-data",
                        help="Path to dashboard data.json for live export")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # Load config
    config_path = Path(args.config)
    if config_path.exists():
        import yaml
        with open(config_path) as f:
            config = yaml.safe_load(f)
    else:
        logger.warning("Config not found at %s, using defaults", args.config)
        config = {"sensor": {"id": "router-001"}}

    if args.dashboard_data:
        config["dashboard_data_path"] = args.dashboard_data

    # SSH transport overrides serial
    if args.ssh:
        config.setdefault("sensor", {})["ssh_host"] = args.ssh
        config.setdefault("sensor", {})["ssh_user"] = args.ssh_user
        config.setdefault("sensor", {})["ssh_password"] = args.ssh_password

    port = args.port or detect_router_port()

    bridge = RouterBridge(port=port, baud=args.baud, config=config)

    def signal_handler(signum, frame):
        bridge.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGHUP, signal_handler)

    try:
        bridge.start()
    except Exception as e:
        logger.error("Bridge failed: %s", e)
        bridge.stop()
        sys.exit(1)


if __name__ == "__main__":
    main()
