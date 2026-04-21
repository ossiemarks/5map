# ESP32 CSI + BLE Sensor

ESP32 firmware and serial-to-REST bridge used for the 5map BLE-device-count
and Wi-Fi CSI demo.

## Hardware

- 2x ESP32 dev boards (NodeMCU-style, CH340 USB-serial). CH340 driver is
  built into macOS ≥ 11 — no download needed.
- Board roles:
  - **TX** — flashed elsewhere (MicroPython CSI transmitter).
  - **RX** — flashed with `firmware/csi_recv_ble/`, connects to host via USB.

## RX firmware: `firmware/csi_recv_ble/`

Forked from `espressif/esp-csi examples/get-started/csi_recv` (commit
`e8cbdb3`) with two changes:

1. **Console UART baud forced to 115200** (`sdkconfig.defaults`). The
   upstream 921600 default is unreadable through the CH340 chip on macOS.
   Tradeoff: CSI frame rate capped at ~9/s by UART throughput (each CSV row
   is ~1 KB).
2. **NimBLE passive scanner added alongside CSI** (`main/app_main.c`). Runs
   concurrently with Wi-Fi via the ESP32 SW coex layer. Reports a unique +
   total device count every 2 s.

Output on UART0 at 115200 8N1, two row types:

```
CSI_DATA,<id>,<mac>,<rssi>,<rate>,<sig_mode>,<mcs>,<bw>,...,<first_word>,"[v1,v2,...]"
BLE_COUNT,<elapsed_ms>,<unique_macs>,<total_ads>
BLE_INFO,scanner_started
```

### Build + flash

Requires ESP-IDF **v5.3.2** (not v4.4.x — its install.sh is broken on
Python ≥ 3.12). Install once:

```bash
mkdir -p ~/esp && cd ~/esp
git clone -b v5.3.2 --recursive --depth 1 --shallow-submodules \
    https://github.com/espressif/esp-idf.git
cd esp-idf && ./install.sh esp32
```

Then from this directory:

```bash
source ~/esp/esp-idf/export.sh
cd firmware/csi_recv_ble
idf.py set-target esp32
idf.py build
idf.py -p /dev/cu.usbserial-XXXX flash
```

Port name is USB-slot-specific — use `ls /dev/cu.usbserial*` to find it.

## Bridge: `bridge.py`

Reads the RX serial stream and POSTs each `BLE_COUNT` / `CSI_DATA` row to
the 5map ingest API as a JSON event.

```bash
pip3 install pyserial        # one-time (or use a venv)
python3 bridge.py
```

Configurable at the top of the script:

- `PORT` — serial device path.
- `BAUD` — must match firmware (115200).
- `URL`  — API endpoint. Currently points at the MVP API at
  `…/api/sessions`. This is known-broken: `POST /api/sessions` creates a
  new session rather than logging an event. The session-scoped event route
  (`POST /api/sessions/<id>/events` or similar) needs to be wired in before
  the dashboard shows live data.

Output rows are small JSON objects. For CSI, the full subcarrier array is
included as `"csi": [...]` (~200 ints per row).

## Known issues / next steps

- **Bridge posts to the wrong endpoint.** See the note above on
  `/api/sessions`. Needs: create one session on startup, then post events to
  the per-session route.
- **CSI rate throttled by UART baud.** 115200 caps throughput at ~9 CSI
  rows/s. Options if higher rate becomes necessary: swap to an FT232-based
  dev board (handles 921600 reliably on macOS) and raise the baud, or use
  an ESP32-S3/C6 with native USB-CDC.
- **Motion detection is not implemented.** Raw CSI is forwarded; the
  classifier that turns subcarrier flux into motion/no-motion lives elsewhere.
