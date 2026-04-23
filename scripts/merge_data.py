#!/usr/bin/env python3
"""Merges wifi_data.json and ble_data.json into data.json for the dashboard.
Runs as a background daemon, polling every 3 seconds."""
import json
import time
import sys
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"
WIFI_PATH = DASHBOARD_DIR / "wifi_data.json"
BLE_PATH = DASHBOARD_DIR / "ble_data.json"
OUT_PATH = DASHBOARD_DIR / "data.json"
TMP_PATH = OUT_PATH.with_suffix(".tmp")

def load_safe(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}

while True:
    try:
        wifi = load_safe(WIFI_PATH)
        ble = load_safe(BLE_PATH)

        merged = {
            "session": wifi.get("session", ble.get("session", {"session_id": "live", "name": "Live Audit"})),
            "devices": wifi.get("devices", []),
            "bluetooth_devices": ble.get("bluetooth_devices", []),
            "events": wifi.get("events", ble.get("events", [])),
            "router_sensor": wifi.get("router_sensor", {}),
        }

        with open(TMP_PATH, "w") as f:
            json.dump(merged, f, indent=2)
        TMP_PATH.rename(OUT_PATH)

    except Exception as e:
        print(f"merge error: {e}", file=sys.stderr)

    time.sleep(3)
