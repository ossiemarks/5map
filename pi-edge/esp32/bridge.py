#!/usr/bin/env python3
"""
ESP32 RX -> AWS REST API bridge (raw forward).

POSTs every BLE_COUNT and CSI_DATA row from the RX serial port to the API
as it arrives. One HTTP request per serial row.
"""
import json
import sys
import time
import urllib.error
import urllib.request

import serial

PORT = "/dev/cu.usbserial-1440"
BAUD = 115200
URL  = "https://api.voicechatbox.com/api/sessions"


def post(payload: dict):
    req = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode(errors="replace")[:120]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:120]
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def parse_ble(text: str):
    # BLE_COUNT,<window_ms>,<unique>,<total>
    parts = text.split(",")
    if len(parts) < 4:
        return None
    try:
        return {
            "type": "ble",
            "window_ms": int(parts[1]),
            "ble_unique": int(parts[2]),
            "ble_total": int(parts[3]),
        }
    except ValueError:
        return None


def parse_csi(text: str):
    # Non-C5/C6 ESP32 format:
    # CSI_DATA,id,mac,rssi,rate,sig_mode,mcs,bw,smoothing,not_sounding,aggregation,
    # stbc,fec_coding,sgi,noise_floor,ampdu_cnt,channel,secondary_channel,
    # local_timestamp,ant,sig_len,rx_state,len,first_word,"[v1,v2,...]"
    lb = text.find('"[')
    rb = text.rfind(']"')
    if lb < 0 or rb < 0:
        return None
    head = text[:lb].rstrip(",").split(",")
    arr_str = text[lb + 2 : rb]
    if len(head) < 23:
        return None
    try:
        csi = [int(x) for x in arr_str.split(",") if x]
        return {
            "type": "csi",
            "id": int(head[1]),
            "mac": head[2],
            "rssi": int(head[3]),
            "rate": int(head[4]),
            "channel": int(head[16]),
            "local_timestamp": int(head[18]),
            "sig_len": int(head[20]),
            "len": int(head[22]),
            "csi": csi,
        }
    except (ValueError, IndexError):
        return None


def main():
    s = serial.Serial(PORT, BAUD, timeout=0.5)
    print(f"bridge: {PORT} @ {BAUD} -> {URL}", flush=True)

    sent = {"ble": 0, "csi": 0, "fail": 0}
    last_summary = time.time()

    while True:
        line = s.readline()
        if not line:
            continue
        text = line.decode("utf-8", errors="replace").rstrip()

        payload = None
        if text.startswith("BLE_COUNT,"):
            payload = parse_ble(text)
        elif text.startswith("CSI_DATA"):
            payload = parse_csi(text)
        else:
            continue
        if payload is None:
            continue

        payload["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        status, body = post(payload)

        if status and 200 <= status < 300:
            sent[payload["type"]] += 1
        else:
            sent["fail"] += 1
            print(
                f"[{time.strftime('%H:%M:%S')}] {payload['type']:3s} FAIL {status} {body}",
                flush=True,
            )

        now = time.time()
        if now - last_summary >= 2.0:
            print(
                f"[{time.strftime('%H:%M:%S')}] sent: ble={sent['ble']} csi={sent['csi']} fail={sent['fail']}",
                flush=True,
            )
            last_summary = now


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
        sys.exit(0)
