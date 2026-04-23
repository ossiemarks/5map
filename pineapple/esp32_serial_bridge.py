#!/usr/bin/env python3
"""5map ESP32 Serial Bridge for WiFi Pineapple Mark VII.

Reads WiFi scan JSON from ESP32 over serial, batches results,
and POSTs to the 5map API Gateway ingest endpoint.

Uses only Python stdlib (no pip packages required).
"""

import json
import os
import sys
import termios
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError

# ── Configuration ──
SERIAL_PORT = os.environ.get("SERIAL_PORT", "/dev/ttyUSB0")
BAUD_RATE = int(os.environ.get("BAUD_RATE", "115200"))
SESSION_ID = os.environ.get("SESSION_ID", "e8076d73-ce66-4ed8-85fb-ef715f8844cf")
SENSOR_ID = os.environ.get("SENSOR_ID", "pineapple-esp32")
API_URL = os.environ.get("API_URL", "https://api.voicechatbox.com/api/ingest")
AUTH_TOKEN = os.environ.get("AUTH_TOKEN", "mvp-token")
BATCH_INTERVAL = int(os.environ.get("BATCH_INTERVAL", "5"))

# Baud rate constants
BAUD_MAP = {
    9600: termios.B9600,
    19200: termios.B19200,
    38400: termios.B38400,
    57600: termios.B57600,
    115200: termios.B115200,
}


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def open_serial(port, baud):
    """Open serial port at specified baud rate using termios."""
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
    attrs = termios.tcgetattr(fd)

    baud_const = BAUD_MAP.get(baud, termios.B115200)
    attrs[4] = baud_const  # ispeed
    attrs[5] = baud_const  # ospeed

    # Raw mode
    attrs[0] = 0  # iflag
    attrs[1] = 0  # oflag
    attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    attrs[3] = 0  # lflag
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 10  # 1 second timeout

    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    return fd


def read_line(fd):
    """Read a complete line from the serial port."""
    buf = b""
    while True:
        chunk = os.read(fd, 256)
        if not chunk:
            if buf:
                return buf.decode("utf-8", errors="replace").strip()
            return None
        buf += chunk
        if b"\n" in buf:
            line, _ = buf.split(b"\n", 1)
            return line.decode("utf-8", errors="replace").strip()


def post_to_api(networks, timestamp):
    """POST scan data to the 5map API Gateway."""
    payload = {
        "session_id": SESSION_ID,
        "sensor_id": SENSOR_ID,
        "timestamp": timestamp,
        "networks": networks,
    }

    data = json.dumps(payload).encode("utf-8")
    req = Request(API_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {AUTH_TOKEN}")

    try:
        with urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            return result.get("ingested", 0)
    except URLError as e:
        log(f"API error: {e}")
        return 0
    except Exception as e:
        log(f"POST failed: {e}")
        return 0


def main():
    log(f"5map ESP32 Bridge starting")
    log(f"  Port: {SERIAL_PORT}")
    log(f"  Baud: {BAUD_RATE}")
    log(f"  Session: {SESSION_ID}")
    log(f"  API: {API_URL}")
    log(f"  Batch interval: {BATCH_INTERVAL}s")

    # Retry serial connection
    fd = None
    while fd is None:
        try:
            fd = open_serial(SERIAL_PORT, BAUD_RATE)
            log(f"Serial port opened: {SERIAL_PORT}")
        except OSError as e:
            log(f"Serial open failed: {e} (retrying in 5s)")
            time.sleep(5)

    scan_count = 0
    total_ingested = 0
    last_post = time.monotonic()
    pending_networks = []

    log("Reading scans...")

    try:
        while True:
            line = read_line(fd)
            if not line or not line.startswith("{"):
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type", "")

            if msg_type == "scan":
                networks = data.get("networks", [])
                pending_networks.extend(networks)
                scan_count += 1

                if scan_count % 10 == 0:
                    log(f"Scans: {scan_count} | Pending: {len(pending_networks)} | Ingested: {total_ingested}")

            elif msg_type == "status":
                heap = data.get("heap_free", 0)
                uptime = data.get("uptime_ms", 0) // 1000
                log(f"ESP32 status: heap={heap} uptime={uptime}s scans={data.get('scan_count', 0)}")

            elif msg_type == "boot":
                log(f"ESP32 boot: {data.get('firmware', '?')} v{data.get('version', '?')} MAC={data.get('mac', '?')}")

            # Batch POST at interval
            now = time.monotonic()
            if pending_networks and (now - last_post) >= BATCH_INTERVAL:
                # Deduplicate by bssid, keep strongest RSSI
                seen = {}
                for net in pending_networks:
                    bssid = net.get("bssid", "")
                    if bssid not in seen or net.get("rssi", -100) > seen[bssid].get("rssi", -100):
                        seen[bssid] = net
                unique = list(seen.values())

                timestamp = datetime.now(timezone.utc).isoformat()
                ingested = post_to_api(unique, timestamp)
                total_ingested += ingested
                log(f"Posted {ingested}/{len(unique)} devices to API")

                pending_networks = []
                last_post = now

    except KeyboardInterrupt:
        log("Shutting down...")
    finally:
        if fd is not None:
            os.close(fd)
        log(f"Total scans: {scan_count} | Total ingested: {total_ingested}")


if __name__ == "__main__":
    main()
