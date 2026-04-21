"""5map ESP32 WiFi Scanner - Captures RSSI data and streams over serial.

This runs on the ESP32-WROOM-32 with MicroPython. It continuously scans
for WiFi networks and devices, outputting structured JSON lines over
the serial port for the Pineapple or Pi to consume.

Output format (one JSON per line):
{"type":"scan","timestamp":12345,"networks":[{"ssid":"...","bssid":"aa:bb:cc:dd:ee:ff","channel":6,"rssi":-45,"auth":"WPA2"},...]}
{"type":"probe","timestamp":12346,"mac":"aa:bb:cc:dd:ee:ff","rssi":-55,"channel":6}
{"type":"status","timestamp":12347,"heap_free":120000,"scan_count":42}
"""

import json
import time
import network
import gc

# Configuration
SCAN_INTERVAL_MS = 2000  # Scan every 2 seconds
STATUS_INTERVAL_MS = 30000  # Status report every 30 seconds
CHANNEL_DWELL_MS = 100  # Dwell time per channel when hopping

def format_mac(bssid):
    """Format BSSID bytes to MAC string."""
    return ":".join("%02x" % b for b in bssid)

def is_randomized_mac(mac_str):
    """Check if MAC has locally administered bit set."""
    try:
        first_octet = int(mac_str.split(":")[0], 16)
        return bool(first_octet & 0x02)
    except (ValueError, IndexError):
        return False

def auth_mode_str(authmode):
    """Convert auth mode int to string."""
    modes = {
        0: "OPEN",
        1: "WEP",
        2: "WPA-PSK",
        3: "WPA2-PSK",
        4: "WPA/WPA2-PSK",
        5: "WPA2-ENTERPRISE",
        6: "WPA3-PSK",
        7: "WPA2/WPA3-PSK",
    }
    return modes.get(authmode, "UNKNOWN")

def scan_networks(wlan):
    """Perform a WiFi scan and return network list."""
    try:
        results = wlan.scan()
        networks = []
        for ssid, bssid, channel, rssi, authmode, hidden in results:
            mac = format_mac(bssid)
            networks.append({
                "ssid": ssid.decode("utf-8", "replace") if ssid else "",
                "bssid": mac,
                "channel": channel,
                "rssi": rssi,
                "auth": auth_mode_str(authmode),
                "hidden": bool(hidden),
                "randomized": is_randomized_mac(mac),
            })
        return networks
    except Exception as e:
        print(json.dumps({"type": "error", "message": str(e)}))
        return []

def main():
    # Initialize WiFi in station mode (for scanning)
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    print(json.dumps({
        "type": "boot",
        "firmware": "5map-esp32-scanner",
        "version": "1.0.0",
        "mac": format_mac(wlan.config("mac")),
        "timestamp": time.ticks_ms(),
    }))

    scan_count = 0
    last_status = time.ticks_ms()

    while True:
        # Scan
        start = time.ticks_ms()
        networks = scan_networks(wlan)
        scan_duration = time.ticks_diff(time.ticks_ms(), start)
        scan_count += 1

        # Output scan results
        if networks:
            print(json.dumps({
                "type": "scan",
                "timestamp": time.ticks_ms(),
                "scan_ms": scan_duration,
                "count": len(networks),
                "networks": networks,
            }))

        # Periodic status
        if time.ticks_diff(time.ticks_ms(), last_status) >= STATUS_INTERVAL_MS:
            gc.collect()
            print(json.dumps({
                "type": "status",
                "timestamp": time.ticks_ms(),
                "heap_free": gc.mem_free(),
                "scan_count": scan_count,
                "uptime_ms": time.ticks_ms(),
            }))
            last_status = time.ticks_ms()

        # Wait before next scan
        elapsed = time.ticks_diff(time.ticks_ms(), start)
        if elapsed < SCAN_INTERVAL_MS:
            time.sleep_ms(SCAN_INTERVAL_MS - elapsed)

main()
