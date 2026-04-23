#!/usr/bin/env python3
"""5map BLE Scanner — scans for Bluetooth Low Energy devices using the
host Bluetooth adapter and feeds data into the 5map pipeline.

Outputs BLE device discoveries to:
  1. Dashboard data.json (live update for the web UI)
  2. MQTT to AWS IoT Core (for cloud pipeline processing)
  3. Console logging

Usage:
    python3 ble_scanner.py
    python3 ble_scanner.py --dashboard-data dashboard/data.json
    python3 ble_scanner.py --mqtt --config /etc/5map/config.yaml
"""

import argparse
import asyncio
import fcntl
import json
import logging
import signal
import ssl
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

logger = logging.getLogger("5map-ble")

# BLE company IDs -> manufacturer names
COMPANY_IDS = {
    0x004C: "Apple",
    0x0006: "Microsoft",
    0x0075: "Samsung",
    0x00E0: "Google",
    0x0059: "Nordic Semiconductor",
    0x000D: "Texas Instruments",
    0x0087: "Garmin",
    0x038F: "Xiaomi",
    0x0157: "Huawei",
    0x0310: "Fitbit",
    0x0822: "Tile",
    0x02FF: "Bose",
    0x00D2: "Beats (Apple)",
    0x0131: "Jabra",
    0x0301: "Sony",
    0x00F0: "Philips",
    0x0171: "Amazon",
    0x0499: "Ruuvi",
    0x0397: "WHOOP",
}


def resolve_manufacturer(manufacturer_data: dict) -> tuple:
    """Resolve manufacturer from BLE advertisement data."""
    if not manufacturer_data:
        return "", ""
    company_id = next(iter(manufacturer_data.keys()), 0)
    name = COMPANY_IDS.get(company_id, "")
    hex_id = f"{company_id:04X}"
    return name, hex_id


def classify_device(name: str, services: list, manufacturer: str,
                    connectable: bool) -> str:
    """Classify BLE device type from advertisement data."""
    name_lower = (name or "").lower()
    svc_str = " ".join(services).lower()

    # Beacons
    if not connectable and not name:
        return "Beacon"
    if "ibeacon" in name_lower or "eddystone" in svc_str:
        return "Beacon"

    # Wearables / fitness
    wearable_keywords = ["watch", "band", "fit", "whoop", "garmin",
                         "charge", "versa", "sense", "pixel watch"]
    if any(k in name_lower for k in wearable_keywords):
        return "BLE"

    # Audio
    audio_keywords = ["airpod", "buds", "pods", "jbl", "bose",
                      "headphone", "speaker", "flip", "charge"]
    if any(k in name_lower for k in audio_keywords):
        return "BLE"

    # Peripherals
    peripheral_keywords = ["keyboard", "mouse", "logitech", "mx keys",
                           "trackpad", "controller"]
    if any(k in name_lower for k in peripheral_keywords):
        return "Classic"

    # Phones/tablets tend to not broadcast names
    if manufacturer in ("Apple", "Samsung", "Google", "Xiaomi", "Huawei"):
        return "BLE"

    return "BLE"


class BLEScanner:
    """Continuous BLE scanner with dashboard and MQTT output."""

    def __init__(self, scan_duration: float = 5.0,
                 dashboard_path: str = None,
                 mqtt_config: dict = None):
        self.scan_duration = scan_duration
        self.dashboard_path = dashboard_path
        self.mqtt_config = mqtt_config
        self.mqtt_client = None
        self.devices: dict[str, dict] = {}
        self.scan_count = 0
        self.total_discoveries = 0
        self.running = True

    def _setup_mqtt(self) -> None:
        """Connect to AWS IoT Core for cloud pipeline."""
        if not self.mqtt_config:
            return
        try:
            import paho.mqtt.client as mqtt
            cfg = self.mqtt_config["mqtt"]
            self.mqtt_client = mqtt.Client(
                client_id=f"fivemap-prod-ble-scanner",
                protocol=mqtt.MQTTv311,
            )
            cert_dir = cfg.get("cert_dir", "/etc/5map/certs")
            self.mqtt_client.tls_set(
                ca_certs=f"{cert_dir}/{cfg['ca_cert']}",
                certfile=f"{cert_dir}/{cfg['client_cert']}",
                keyfile=f"{cert_dir}/{cfg['private_key']}",
                tls_version=ssl.PROTOCOL_TLSv1_2,
            )
            self.mqtt_client.connect(cfg["broker"], int(cfg["port"]), 60)
            self.mqtt_client.loop_start()
            logger.info("MQTT connected to %s", cfg["broker"])
        except Exception as e:
            logger.warning("MQTT setup failed: %s (continuing local-only)", e)
            self.mqtt_client = None

    def _process_device(self, device: BLEDevice,
                        adv: AdvertisementData) -> dict:
        """Process a single BLE advertisement into a device record."""
        mac = device.address
        name = device.name or adv.local_name or ""
        manufacturer, mfr_id = resolve_manufacturer(adv.manufacturer_data)
        services = [str(s) for s in adv.service_uuids]
        tx_power = adv.tx_power
        connectable = getattr(adv, "connectable", True)
        device_type = classify_device(name, services, manufacturer, connectable)
        now = datetime.now(timezone.utc).isoformat()

        existing = self.devices.get(mac)
        if existing:
            existing["rssi_dbm"] = adv.rssi
            existing["last_seen"] = now
            existing["adv_count"] = existing.get("adv_count", 0) + 1
            if name and not existing.get("device_name"):
                existing["device_name"] = name
            if manufacturer and not existing.get("manufacturer"):
                existing["manufacturer"] = manufacturer
            if services:
                for s in services:
                    if s not in existing.get("service_uuids", []):
                        existing.setdefault("service_uuids", []).append(s)
            return existing
        else:
            record = {
                "mac_address": mac,
                "device_name": name,
                "device_type": device_type,
                "manufacturer": manufacturer or f"Unknown ({mfr_id})" if mfr_id else "Unknown",
                "manufacturer_id": mfr_id,
                "rssi_dbm": adv.rssi,
                "tx_power": tx_power,
                "service_uuids": services,
                "is_connectable": connectable,
                "first_seen": now,
                "last_seen": now,
                "adv_count": 1,
            }
            self.devices[mac] = record
            self.total_discoveries += 1
            return record

    def _export_dashboard(self) -> None:
        """Write BLE devices to dashboard data.json."""
        if not self.dashboard_path:
            return
        try:
            path = Path(self.dashboard_path)
            lock_path = path.with_suffix(".lock")
            with open(lock_path, "w") as lockf:
                fcntl.flock(lockf, fcntl.LOCK_EX)
                if path.exists():
                    with open(path) as f:
                        data = json.load(f)
                else:
                    data = {}

                data["bluetooth_devices"] = list(self.devices.values())

                tmp_path = path.with_suffix(".tmp")
                with open(tmp_path, "w") as f:
                    json.dump(data, f, indent=2)
                tmp_path.rename(path)
        except Exception as e:
            logger.debug("Dashboard export error: %s", e)

    def _publish_mqtt(self, window: dict) -> None:
        """Publish BLE window to MQTT."""
        if not self.mqtt_client:
            return
        try:
            topic = "5map/ble/ble-scanner"
            self.mqtt_client.publish(topic, json.dumps(window), qos=1)
        except Exception as e:
            logger.debug("MQTT publish error: %s", e)

    async def _scan_loop(self) -> None:
        """Main scanning loop."""
        logger.info("Starting BLE scan loop (%.1fs per scan)", self.scan_duration)

        while self.running:
            try:
                discovered = await BleakScanner.discover(
                    timeout=self.scan_duration,
                    return_adv=True,
                )

                self.scan_count += 1
                window_devices = []

                for addr, (dev, adv) in discovered.items():
                    record = self._process_device(dev, adv)
                    window_devices.append({
                        "mac": addr,
                        "name": record["device_name"],
                        "rssi": adv.rssi,
                        "type": record["device_type"],
                        "manufacturer": record["manufacturer"],
                    })

                # Build MQTT window
                window = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "sensor_id": "ble-scanner",
                    "sensor_type": "ble",
                    "window_ms": int(self.scan_duration * 1000),
                    "device_count": len(discovered),
                    "observations": window_devices,
                }

                self._publish_mqtt(window)
                self._export_dashboard()

                if self.scan_count % 6 == 1:
                    logger.info(
                        "Scan #%d: %d devices this window, %d total cached, "
                        "%d unique discovered",
                        self.scan_count, len(discovered),
                        len(self.devices), self.total_discoveries,
                    )

                # Prune stale devices (not seen in 5 minutes)
                cutoff = time.time() - 300
                stale = [
                    mac for mac, d in self.devices.items()
                    if datetime.fromisoformat(
                        d["last_seen"].replace("Z", "+00:00")
                    ).timestamp() < cutoff
                ]
                for mac in stale:
                    del self.devices[mac]

            except Exception as e:
                logger.error("Scan error: %s", e)
                await asyncio.sleep(2)

    def start(self) -> None:
        """Start the BLE scanner."""
        logger.info("5map BLE Scanner starting")
        logger.info("  Dashboard: %s", self.dashboard_path or "disabled")
        logger.info("  MQTT: %s", "enabled" if self.mqtt_config else "disabled")

        self._setup_mqtt()

        loop = asyncio.new_event_loop()

        def handle_signal(sig, frame):
            self.running = False
            logger.info("Shutting down...")

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        try:
            loop.run_until_complete(self._scan_loop())
        except KeyboardInterrupt:
            pass
        finally:
            if self.mqtt_client:
                self.mqtt_client.disconnect()
                self.mqtt_client.loop_stop()
            loop.close()

        logger.info("BLE Scanner stopped. %d scans, %d unique devices",
                     self.scan_count, self.total_discoveries)


def main():
    parser = argparse.ArgumentParser(description="5map BLE Scanner")
    parser.add_argument("--dashboard-data",
                        help="Path to dashboard data.json for live export")
    parser.add_argument("--mqtt", action="store_true",
                        help="Enable MQTT publishing to AWS IoT Core")
    parser.add_argument("--config", default="/etc/5map/config.yaml",
                        help="Path to config.yaml (for MQTT settings)")
    parser.add_argument("--scan-duration", type=float, default=5.0,
                        help="Seconds per scan cycle (default: 5)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    mqtt_config = None
    if args.mqtt:
        import yaml
        config_path = Path(args.config)
        if config_path.exists():
            with open(config_path) as f:
                cfg = yaml.safe_load(f)
            mqtt_config = cfg.get("transport")
        else:
            logger.warning("Config not found: %s, MQTT disabled", args.config)

    scanner = BLEScanner(
        scan_duration=args.scan_duration,
        dashboard_path=args.dashboard_data,
        mqtt_config=mqtt_config,
    )
    scanner.start()


if __name__ == "__main__":
    main()
