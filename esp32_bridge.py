#!/usr/bin/env python3
"""5map ESP32 Bridge — reads BLE + CSI JSON from ESP32 serial, feeds the pipeline.

Connects to the ESP32 over USB serial, parses JSON lines, aggregates
observations into windows, and publishes to AWS IoT Core via MQTT.
Also serves the data locally for the dashboard via a simple JSON API.

Usage:
    python3 esp32_bridge.py --port /dev/ttyUSB0 --config /etc/5map/config.yaml
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

import serial
import yaml

from src.sensors.ble_sensor import (
    BLEObservation,
    BLESensor,
    BLEWindowAggregator,
    resolve_manufacturer,
)
from src.sensors.csi_sensor import CSIObservation, CSISensor, CSIWindowAggregator

logger = logging.getLogger("5map-esp32-bridge")

# How often to flush windows (seconds)
BLE_WINDOW_SECONDS = 2.0
CSI_WINDOW_SECONDS = 1.0


class ESP32Bridge:
    """Main bridge between ESP32 serial output and the 5map pipeline."""

    def __init__(self, port: str, baud: int, config: dict):
        self.port = port
        self.baud = baud
        self.config = config
        self.sensor_id = config.get("sensor", {}).get("id", "esp32-001")
        self.running = threading.Event()
        self.running.set()

        # Sensors
        self.ble_sensor = BLESensor()
        self.ble_sensor.configure({"sensor_id": f"{self.sensor_id}-ble"})

        self.csi_sensor = CSISensor()
        self.csi_sensor.configure({"sensor_id": f"{self.sensor_id}-csi"})

        # Aggregators
        self.ble_agg = BLEWindowAggregator(
            sensor_id=f"{self.sensor_id}-ble",
            window_ms=int(BLE_WINDOW_SECONDS * 1000),
        )
        self.csi_agg = CSIWindowAggregator(
            sensor_id=f"{self.sensor_id}-csi",
            window_ms=int(CSI_WINDOW_SECONDS * 1000),
        )

        # MQTT transport (optional, only if config has transport section)
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
            "ble_count": 0,
            "csi_count": 0,
            "heartbeats": 0,
            "errors": 0,
            "last_heartbeat": None,
            "esp32_heap": 0,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

        # Live BLE device cache for dashboard
        self._ble_devices: dict = {}
        self._ble_lock = threading.Lock()

        # Dashboard data export path
        self._dashboard_data_path = config.get("dashboard_data_path", None)

    def _parse_ble_line(self, data: dict) -> None:
        """Parse a BLE JSON line from ESP32."""
        obs = BLEObservation(
            mac=data.get("mac", ""),
            device_name=data.get("name", ""),
            rssi_dbm=int(data.get("rssi", -100)),
            tx_power=int(data["tx"]) if data.get("tx") is not None else None,
            adv_type=int(data.get("adv", 0)),
            service_uuids=data.get("svc", []),
            manufacturer_id=data.get("mfr", ""),
            is_connectable=bool(data.get("conn", 0)),
        )

        self.ble_agg.add(obs)
        self.stats["ble_count"] += 1

        # Update live device cache
        with self._ble_lock:
            existing = self._ble_devices.get(obs.mac)
            now = datetime.now(timezone.utc).isoformat()
            if existing:
                existing["rssi_dbm"] = obs.rssi_dbm
                existing["last_seen"] = now
                if obs.device_name:
                    existing["device_name"] = obs.device_name
                existing["adv_count"] = existing.get("adv_count", 0) + 1
            else:
                device_type = "BLE"
                if not obs.is_connectable:
                    device_type = "Beacon"
                # Heuristic: Classic BT usually doesn't come through BLE scan
                # but ESP32 can detect both

                self._ble_devices[obs.mac] = {
                    "mac_address": obs.mac,
                    "device_name": obs.device_name,
                    "device_type": device_type,
                    "manufacturer": resolve_manufacturer(obs.manufacturer_id),
                    "manufacturer_id": obs.manufacturer_id,
                    "rssi_dbm": obs.rssi_dbm,
                    "tx_power": obs.tx_power,
                    "service_uuids": obs.service_uuids,
                    "is_connectable": obs.is_connectable,
                    "first_seen": now,
                    "last_seen": now,
                    "adv_count": 1,
                }

    def _parse_csi_line(self, data: dict) -> None:
        """Parse a CSI JSON line from ESP32 (with optional raw subcarrier data)."""
        obs = CSIObservation(
            mac=data.get("mac", ""),
            rssi_dbm=int(data.get("rssi", -100)),
            channel=int(data.get("ch", 0)),
            bandwidth=int(data.get("bw", 20)),
            csi_len=int(data.get("ns", data.get("len", 0) // 2)),
            timestamp_ms=int(data.get("ts", 0)),
            raw_data=data.get("data", ""),
            noise_floor=int(data.get("noise", -90)),
            rate=int(data.get("rate", 0)),
        )
        self.csi_agg.add(obs)
        self.stats["csi_count"] += 1
        if obs.raw_data:
            self.stats["csi_raw_count"] = self.stats.get("csi_raw_count", 0) + 1

    def _parse_heartbeat(self, data: dict) -> None:
        """Parse a heartbeat from ESP32."""
        self.stats["heartbeats"] += 1
        self.stats["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
        self.stats["esp32_heap"] = data.get("heap", 0)

    def _serial_read_loop(self) -> None:
        """Main serial reading loop."""
        reconnect_delay = 1

        while self.running.is_set():
            try:
                logger.info("Connecting to ESP32 on %s @ %d baud", self.port, self.baud)
                ser = serial.Serial(self.port, self.baud, timeout=1)
                logger.info("Connected to ESP32")
                reconnect_delay = 1

                while self.running.is_set():
                    line = ser.readline()
                    if not line:
                        continue

                    try:
                        text = line.decode("utf-8", errors="ignore").strip()
                        if not text or not text.startswith("{"):
                            continue

                        data = json.loads(text)
                        msg_type = data.get("t", "")

                        if msg_type == "ble":
                            self._parse_ble_line(data)
                        elif msg_type == "csi":
                            self._parse_csi_line(data)
                        elif msg_type == "hb":
                            self._parse_heartbeat(data)
                        else:
                            logger.debug("Unknown message type: %s", msg_type)

                    except json.JSONDecodeError:
                        self.stats["errors"] += 1
                    except Exception as e:
                        self.stats["errors"] += 1
                        logger.debug("Parse error: %s", e)

            except serial.SerialException as e:
                logger.error("Serial error: %s (retrying in %ds)", e, reconnect_delay)
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 30)
            except Exception as e:
                logger.error("Unexpected error: %s", e)
                time.sleep(reconnect_delay)

    def _flush_loop(self) -> None:
        """Periodically flush aggregation windows and publish."""
        ble_timer = time.monotonic()
        csi_timer = time.monotonic()

        while self.running.is_set():
            time.sleep(0.5)
            now = time.monotonic()

            # Flush BLE window
            if now - ble_timer >= BLE_WINDOW_SECONDS:
                ble_timer = now
                window = self.ble_agg.flush()
                if window.observations:
                    self.ble_sensor.feed_window(window)
                    frame = self.ble_sensor.capture()
                    if frame and self.transport:
                        self.transport.publish(frame)
                    logger.debug("BLE window: %d devices", len(window.observations))

            # Flush CSI window
            if now - csi_timer >= CSI_WINDOW_SECONDS:
                csi_timer = now
                window = self.csi_agg.flush()
                if window.observations:
                    self.csi_sensor.feed_window(window)
                    frame = self.csi_sensor.capture()
                    if frame and self.transport:
                        self.transport.publish(frame)
                    logger.debug("CSI window: %d frames", len(window.observations))

    def _dashboard_export_loop(self) -> None:
        """Export BLE device list to dashboard data.json periodically."""
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

                with self._ble_lock:
                    dashboard_data["bluetooth_devices"] = list(
                        self._ble_devices.values()
                    )

                with open(data_path, "w") as f:
                    json.dump(dashboard_data, f, indent=2)

            except Exception as e:
                logger.debug("Dashboard export error: %s", e)

    def get_ble_devices(self) -> list:
        """Return current BLE device list (for API consumers)."""
        with self._ble_lock:
            return list(self._ble_devices.values())

    def get_stats(self) -> dict:
        """Return bridge statistics."""
        return {
            **self.stats,
            "ble_devices_cached": len(self._ble_devices),
        }

    def start(self) -> None:
        """Start the ESP32 bridge."""
        logger.info("ESP32 Bridge starting (sensor_id=%s, port=%s)",
                     self.sensor_id, self.port)

        # Connect MQTT if available
        if self.transport:
            self.transport.connect()

        # Start threads
        threads = [
            threading.Thread(target=self._serial_read_loop, daemon=True,
                             name="serial-read"),
            threading.Thread(target=self._flush_loop, daemon=True,
                             name="window-flush"),
        ]

        if self._dashboard_data_path:
            threads.append(
                threading.Thread(target=self._dashboard_export_loop, daemon=True,
                                 name="dashboard-export")
            )

        for t in threads:
            t.start()

        logger.info("ESP32 Bridge running")

        try:
            while self.running.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass

    def stop(self) -> None:
        """Stop the bridge."""
        logger.info("Stopping ESP32 Bridge...")
        self.running.clear()

        # Final flush
        ble_window = self.ble_agg.flush()
        if ble_window.observations:
            self.ble_sensor.feed_window(ble_window)
            frame = self.ble_sensor.capture()
            if frame and self.transport:
                self.transport.publish(frame)

        if self.transport:
            self.transport.flush()
            self.transport.disconnect()

        logger.info("ESP32 Bridge stopped. Stats: %s", json.dumps(self.stats))


def detect_esp32_port() -> str:
    """Auto-detect the ESP32 serial port. Prefers /dev/esp32 udev symlink."""
    candidates = [
        "/dev/esp32",
        "/dev/ttyUSB0", "/dev/ttyUSB1",
        "/dev/ttyACM0", "/dev/ttyACM1",
    ]
    for port in candidates:
        if os.path.exists(port):
            logger.info("Auto-detected ESP32 port: %s", port)
            return port
    logger.warning("No ESP32 port found, will retry on /dev/esp32")
    return "/dev/esp32"


def main():
    parser = argparse.ArgumentParser(description="5map ESP32 BLE + CSI Bridge")
    parser.add_argument("--port", default=None,
                        help="Serial port (auto-detect if omitted)")
    parser.add_argument("--baud", type=int, default=921600,
                        help="Baud rate (default: 921600)")
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
        with open(config_path) as f:
            config = yaml.safe_load(f)
    else:
        logger.warning("Config not found at %s, using defaults", args.config)
        config = {"sensor": {"id": "esp32-001"}}

    if args.dashboard_data:
        config["dashboard_data_path"] = args.dashboard_data

    # Auto-detect port
    port = args.port or detect_esp32_port()

    bridge = ESP32Bridge(port=port, baud=args.baud, config=config)

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
