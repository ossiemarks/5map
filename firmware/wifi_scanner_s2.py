"""5map WiFi Scanner for ESP32-S2 — scans nearby APs and outputs JSON over USB serial.

Runs on MicroPython. Outputs one JSON line per AP per scan cycle.
Format: {"t":"wifi","mac":"AA:BB:CC:DD:EE:FF","ssid":"Name","rssi":-65,"ch":6,"auth":3,"bw":"2.4GHz","hidden":false}
Heartbeat: {"t":"hb","heap":123456,"scans":10,"aps":25,"uptime":60}
"""

import gc
import json
import sys
import time

import network


SCAN_INTERVAL_S = 3
SENSOR_ID = "esp32s2-001"

wlan = network.WLAN(network.STA_IF)
wlan.active(True)

AUTH_NAMES = {
    0: "open",
    1: "WEP",
    2: "WPA-PSK",
    3: "WPA2-PSK",
    4: "WPA/WPA2-PSK",
    5: "WPA2-Enterprise",
    6: "WPA3-PSK",
    7: "WPA2/WPA3-PSK",
}

scan_count = 0
start_time = time.ticks_ms()


def format_mac(bssid):
    return ":".join("{:02X}".format(b) for b in bssid)


def scan_and_report():
    global scan_count
    try:
        results = wlan.scan()
    except Exception as e:
        print(json.dumps({"t": "err", "msg": str(e)}))
        return 0

    scan_count += 1
    ap_count = 0

    for ap in results:
        ssid_raw, bssid, channel, rssi, authmode, hidden = ap
        try:
            ssid = ssid_raw.decode("utf-8", "replace")
        except Exception:
            ssid = ""

        msg = {
            "t": "wifi",
            "sid": SENSOR_ID,
            "mac": format_mac(bssid),
            "ssid": ssid if ssid else "-",
            "rssi": rssi,
            "ch": channel,
            "auth": AUTH_NAMES.get(authmode, str(authmode)),
            "bw": "2.4GHz" if channel <= 14 else "5GHz",
            "hidden": bool(hidden),
        }
        print(json.dumps(msg))
        ap_count += 1

    return ap_count


def heartbeat(ap_count):
    uptime_s = time.ticks_diff(time.ticks_ms(), start_time) // 1000
    msg = {
        "t": "hb",
        "sid": SENSOR_ID,
        "heap": gc.mem_free(),
        "scans": scan_count,
        "aps": ap_count,
        "uptime": uptime_s,
    }
    print(json.dumps(msg))


def main():
    print(json.dumps({"t": "boot", "sid": SENSOR_ID, "fw": "wifi_scanner_s2", "ver": "1.0.0"}))

    while True:
        gc.collect()
        ap_count = scan_and_report()
        heartbeat(ap_count)
        time.sleep(SCAN_INTERVAL_S)


main()
