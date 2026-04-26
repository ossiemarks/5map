#!/usr/bin/env python3
"""Live bridge: pulls WiFi scan data from Pineapple ESP32 over SSH,
writes to dashboard/data.json for the environment monitor."""

import fcntl
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

PINEAPPLE_HOST = "172.16.42.1"
PINEAPPLE_USER = "root"
PINEAPPLE_PASS = "hak5pineapple"
DASHBOARD_DATA = Path(__file__).resolve().parent.parent / "dashboard" / "data.json"
POLL_INTERVAL = 5

SSH_BASE = [
    "sshpass", "-p", PINEAPPLE_PASS,
    "ssh", "-o", "ConnectTimeout=5",
    "-o", "StrictHostKeyChecking=no",
    "-o", "HostKeyAlgorithms=+ssh-rsa",
    "-o", "PubkeyAcceptedAlgorithms=+ssh-rsa",
    f"{PINEAPPLE_USER}@{PINEAPPLE_HOST}",
]

READ_SERIAL_CMD = """python3 -c "
import serial, time, json
ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=4)
ser.reset_input_buffer()
time.sleep(4)
data = ser.read(ser.in_waiting or 8192)
text = data.decode('utf-8', errors='ignore')
for line in text.strip().split(chr(10)):
    if line.startswith('{'):
        print(line)
        break
"
"""


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def pull_scan():
    """Pull one WiFi scan from Pineapple ESP32 over SSH."""
    try:
        result = subprocess.run(
            SSH_BASE + [READ_SERIAL_CMD],
            capture_output=True, text=True, timeout=20,
        )
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line.startswith("{"):
                return json.loads(line)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        log(f"Pull error: {e}")
    return None


def update_dashboard(scan_data, devices_cache):
    """Merge scan into dashboard data.json, preserving router data."""
    networks = scan_data.get("networks", [])
    now = datetime.now(timezone.utc).isoformat()

    # Load existing data.json to preserve router bridge entries
    router_devices = {}
    router_sensor = None
    if DASHBOARD_DATA.exists():
        try:
            with open(DASHBOARD_DATA) as f:
                existing = json.load(f)
            router_sensor = existing.get("router_sensor")
            for dev in existing.get("devices", []):
                mac = dev.get("mac_address", "")
                if dev.get("source") == "router" and mac:
                    router_devices[mac] = dev
                # Preserve per-sensor RSSI from router
                if mac and "rssi_router" in dev:
                    if mac in devices_cache:
                        devices_cache[mac]["rssi_router"] = dev["rssi_router"]
        except Exception:
            pass

    for net in networks:
        mac = net.get("bssid", "")
        if not mac:
            continue
        rssi = int(net.get("rssi", -100))
        ssid = net.get("ssid", "-") or "-"
        channel = int(net.get("channel", 0))

        if mac in devices_cache:
            devices_cache[mac]["rssi_dbm"] = rssi
            devices_cache[mac]["rssi_pineapple"] = rssi
            devices_cache[mac]["last_seen"] = now
            devices_cache[mac]["scan_count"] = devices_cache[mac].get("scan_count", 0) + 1
            if ssid and ssid != "-":
                devices_cache[mac]["ssid"] = ssid
            # Preserve router RSSI if this device was also seen by router
            if mac in router_devices:
                devices_cache[mac]["rssi_router"] = router_devices[mac].get("rssi_dbm", -100)
        else:
            devices_cache[mac] = {
                "mac_address": mac,
                "ssid": ssid,
                "rssi_dbm": rssi,
                "rssi_pineapple": rssi,
                "channel": channel,
                "auth": net.get("auth", "unknown"),
                "device_type": "ap",
                "source": "pineapple-esp32",
                "hidden": net.get("hidden", False),
                "randomized": net.get("randomized", False),
                "first_seen": now,
                "last_seen": now,
                "scan_count": 1,
                "vendor": "Unknown",
                "risk_score": 0.1,
                "is_randomized_mac": net.get("randomized", False),
            }
            if mac in router_devices:
                devices_cache[mac]["rssi_router"] = router_devices[mac].get("rssi_dbm", -100)

    # Merge router-only devices into cache
    for mac, rdev in router_devices.items():
        if mac not in devices_cache:
            rdev["rssi_router"] = rdev.get("rssi_dbm", -100)
            devices_cache[mac] = rdev

    # Prune stale (>5 min)
    cutoff = time.time() - 300
    stale = []
    for mac, dev in devices_cache.items():
        try:
            ls = datetime.fromisoformat(dev["last_seen"].replace("Z", "+00:00"))
            if ls.timestamp() < cutoff:
                stale.append(mac)
        except (ValueError, KeyError):
            pass
    for mac in stale:
        del devices_cache[mac]

    # Write — preserve router_sensor data from router bridge
    dashboard = {
        "session": {"session_id": "live-home", "name": "Live Home Audit"},
        "devices": list(devices_cache.values()),
        "last_update": now,
        "sensor_status": {
            "pineapple_esp32": {"status": "online", "last_scan": now, "networks": len(networks)},
        },
    }
    if router_sensor:
        dashboard["router_sensor"] = router_sensor

    lock_path = DASHBOARD_DATA.with_suffix(".lock")
    try:
        with open(lock_path, "w") as lockf:
            fcntl.flock(lockf, fcntl.LOCK_EX)
            tmp = DASHBOARD_DATA.parent / ".data_pine.tmp"
            with open(tmp, "w") as f:
                json.dump(dashboard, f, indent=2)
            tmp.rename(DASHBOARD_DATA)
    except Exception as e:
        log(f"Write error: {e}")

    return len(networks)


def main():
    log("Pineapple Live Bridge starting")
    log(f"  Host: {PINEAPPLE_HOST}")
    log(f"  Dashboard: {DASHBOARD_DATA}")

    devices_cache = {}

    # Load existing
    if DASHBOARD_DATA.exists():
        try:
            with open(DASHBOARD_DATA) as f:
                existing = json.load(f)
            for dev in existing.get("devices", []):
                mac = dev.get("mac_address", "")
                if mac:
                    devices_cache[mac] = dev
            log(f"  Loaded {len(devices_cache)} existing devices")
        except Exception:
            pass

    scan_count = 0
    while True:
        scan = pull_scan()
        if scan:
            count = update_dashboard(scan, devices_cache)
            scan_count += 1
            if scan_count % 3 == 1:
                log(f"Scan #{scan_count}: {count} networks, {len(devices_cache)} cached devices")
        else:
            log("No data from Pineapple (retrying)")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
