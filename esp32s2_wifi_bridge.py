#!/usr/bin/env python3
"""5map ESP32-S2 WiFi Bridge — reads WiFi scan JSON from ESP32-S2, feeds the dashboard.

Connects to the ESP32-S2 over USB serial (/dev/ttyACM0), parses JSON lines,
and updates dashboard/data.json with live WiFi AP data.

Usage:
    python3 esp32s2_wifi_bridge.py
    python3 esp32s2_wifi_bridge.py --port /dev/ttyACM0
    python3 esp32s2_wifi_bridge.py --dashboard-data dashboard/data.json
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

logger = logging.getLogger("5map-esp32s2-wifi")

DASHBOARD_EXPORT_INTERVAL = 5


class WiFiBridge:
    """Bridge between ESP32-S2 WiFi scanner and 5map dashboard."""

    def __init__(self, port: str, baud: int, dashboard_data_path: str | None = None):
        self.port = port
        self.baud = baud
        self.dashboard_data_path = dashboard_data_path
        self.running = threading.Event()
        self.running.set()

        self._devices: dict = {}
        self._lock = threading.Lock()

        self.stats = {
            "wifi_count": 0,
            "heartbeats": 0,
            "errors": 0,
            "scans": 0,
            "last_heartbeat": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

    def _parse_wifi(self, data: dict) -> None:
        mac = data.get("mac", "")
        if not mac:
            return

        now = datetime.now(timezone.utc).isoformat()
        rssi = int(data.get("rssi", -100))
        ssid = data.get("ssid", "-")
        channel = int(data.get("ch", 0))

        with self._lock:
            existing = self._devices.get(mac)
            if existing:
                existing["rssi_dbm"] = rssi
                existing["last_seen"] = now
                existing["scan_count"] = existing.get("scan_count", 0) + 1
                if ssid and ssid != "-":
                    existing["ssid"] = ssid
                if channel:
                    existing["channel"] = channel
            else:
                self._devices[mac] = {
                    "mac_address": mac,
                    "ssid": ssid,
                    "rssi_dbm": rssi,
                    "channel": channel,
                    "auth": data.get("auth", "unknown"),
                    "bandwidth": data.get("bw", "2.4GHz"),
                    "hidden": data.get("hidden", False),
                    "device_type": "ap",
                    "source": "esp32s2",
                    "sensor_id": data.get("sid", "esp32s2-001"),
                    "first_seen": now,
                    "last_seen": now,
                    "scan_count": 1,
                }

        self.stats["wifi_count"] += 1

    def _parse_heartbeat(self, data: dict) -> None:
        self.stats["heartbeats"] += 1
        self.stats["scans"] = data.get("scans", 0)
        self.stats["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
        logger.info(
            "Heartbeat: scans=%d aps=%d heap=%d uptime=%ds",
            data.get("scans", 0),
            data.get("aps", 0),
            data.get("heap", 0),
            data.get("uptime", 0),
        )

    def _serial_read_loop(self) -> None:
        reconnect_delay = 1

        while self.running.is_set():
            try:
                logger.info("Connecting to ESP32-S2 on %s @ %d baud", self.port, self.baud)
                ser = serial.Serial(self.port, self.baud, timeout=1)
                logger.info("Connected to ESP32-S2")
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

                        if msg_type == "wifi":
                            self._parse_wifi(data)
                        elif msg_type == "hb":
                            self._parse_heartbeat(data)
                        elif msg_type == "boot":
                            logger.info(
                                "ESP32-S2 booted: sensor=%s fw=%s v=%s",
                                data.get("sid"), data.get("fw"), data.get("ver"),
                            )
                        elif msg_type == "err":
                            logger.warning("ESP32-S2 error: %s", data.get("msg"))
                            self.stats["errors"] += 1

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

    def _dashboard_export_loop(self) -> None:
        if not self.dashboard_data_path:
            return

        while self.running.is_set():
            time.sleep(DASHBOARD_EXPORT_INTERVAL)
            try:
                data_path = Path(self.dashboard_data_path)
                if data_path.exists():
                    with open(data_path) as f:
                        dashboard_data = json.load(f)
                else:
                    dashboard_data = {}

                with self._lock:
                    # Merge S2 WiFi devices into existing devices list
                    existing_devices = dashboard_data.get("devices", [])
                    existing_macs = {d["mac_address"] for d in existing_devices if d.get("source") != "esp32s2"}
                    non_s2 = [d for d in existing_devices if d.get("source") != "esp32s2"]
                    s2_devices = list(self._devices.values())

                dashboard_data["devices"] = non_s2 + s2_devices

                with open(data_path, "w") as f:
                    json.dump(dashboard_data, f, indent=2)

                logger.debug(
                    "Dashboard export: %d S2 devices, %d total",
                    len(s2_devices),
                    len(dashboard_data["devices"]),
                )

            except Exception as e:
                logger.debug("Dashboard export error: %s", e)

    def get_devices(self) -> list:
        with self._lock:
            return list(self._devices.values())

    def get_stats(self) -> dict:
        return {**self.stats, "devices_cached": len(self._devices)}

    def start(self) -> None:
        logger.info("ESP32-S2 WiFi Bridge starting (port=%s)", self.port)

        threads = [
            threading.Thread(target=self._serial_read_loop, daemon=True, name="s2-serial"),
        ]

        if self.dashboard_data_path:
            threads.append(
                threading.Thread(target=self._dashboard_export_loop, daemon=True, name="s2-dashboard")
            )

        for t in threads:
            t.start()

        logger.info("ESP32-S2 WiFi Bridge running")

        try:
            while self.running.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass

    def stop(self) -> None:
        logger.info("Stopping ESP32-S2 WiFi Bridge...")
        self.running.clear()
        logger.info("ESP32-S2 WiFi Bridge stopped. Stats: %s", json.dumps(self.stats))


def main():
    parser = argparse.ArgumentParser(description="5map ESP32-S2 WiFi Bridge")
    parser.add_argument("--port", default="/dev/ttyACM0",
                        help="Serial port (default: /dev/ttyACM0)")
    parser.add_argument("--baud", type=int, default=115200,
                        help="Baud rate (default: 115200)")
    parser.add_argument("--dashboard-data", default="dashboard/data.json",
                        help="Path to dashboard data.json")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    bridge = WiFiBridge(
        port=args.port,
        baud=args.baud,
        dashboard_data_path=args.dashboard_data,
    )

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
