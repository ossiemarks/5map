#!/usr/bin/env bash
# 5map Sensor Startup Script
# Discovers all connected hardware, validates each sensor, starts bridges.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DASHBOARD_DATA="$PROJECT_DIR/dashboard/data.json"
LOG_DIR="/tmp/5map-logs"
mkdir -p "$LOG_DIR"

CYAN='\033[0;36m'
GREEN='\033[0;32m'
RED='\033[0;31m'
ORANGE='\033[0;33m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}[OK]${NC} $1"; }
fail() { echo -e "  ${RED}[FAIL]${NC} $1"; }
warn() { echo -e "  ${ORANGE}[WARN]${NC} $1"; }
info() { echo -e "  ${CYAN}[INFO]${NC} $1"; }

echo -e "${CYAN}╔══════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     5map Sensor Startup Script       ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════╝${NC}"
echo ""

# ── Mode selection ──
echo -e "${CYAN}Where are you?${NC}"
echo "  1) Home (Os1 WiFi, mini router available)"
echo "  2) Field (TP-Link 4G dongle)"
read -rp "Select [1/2]: " MODE_CHOICE
if [ "$MODE_CHOICE" = "2" ]; then
    MODE="field"
    WIFI_SSID="TP-Link_D891"
    WIFI_PASS="61263766"
    info "Field mode — using 4G dongle"
else
    MODE="home"
    WIFI_SSID="VodafoneD521AB"
    WIFI_PASS=""
    info "Home mode — using Vodafone WiFi"
fi
echo ""

# ── Kill existing bridges ──
echo "Stopping existing bridges..."
pkill -f "esp32_bridge\|router_bridge" 2>/dev/null && info "Killed old bridges" || info "No bridges running"
sleep 1
echo ""

# ── 1. Pineapple ──
echo -e "${CYAN}── WiFi Pineapple ──${NC}"
PINEAPPLE_OK=false
if ip link show 2>/dev/null | grep -q "001337"; then
    ok "USB interface detected"
    if ping -c 1 -W 3 172.16.42.1 >/dev/null 2>&1; then
        ok "Reachable at 172.16.42.1"
        # Check monitor mode
        WLAN_MODE=$(ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa root@172.16.42.1 "iwinfo wlan1 info 2>/dev/null | grep Mode" 2>/dev/null || echo "")
        if echo "$WLAN_MODE" | grep -q "Monitor"; then
            ok "wlan1 in Monitor mode"
            PINEAPPLE_OK=true
        else
            warn "wlan1 not in Monitor mode — may need setup"
        fi
        # Check ESP32 on Pineapple
        ESP32_PINE=$(ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa root@172.16.42.1 "ls /dev/ttyUSB0 2>/dev/null && echo YES || echo NO" 2>/dev/null || echo "NO")
        if [ "$ESP32_PINE" = "/dev/ttyUSB0
YES" ] || echo "$ESP32_PINE" | grep -q "YES"; then
            ok "ESP32 detected on Pineapple USB (/dev/ttyUSB0)"
            # Test serial data
            ESP32_DATA=$(ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa root@172.16.42.1 "python3 -c \"
import serial, time, json
ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=3)
ser.reset_input_buffer()
time.sleep(3)
data = ser.read(ser.in_waiting or 2048)
text = data.decode('utf-8', errors='ignore')
for line in text.strip().split(chr(10)):
    if line.startswith('{'):
        d = json.loads(line)
        nets = d.get('networks', [])
        print(len(nets))
        break
else:
    print('0')
\"" 2>/dev/null || echo "0")
            NETS=$(echo "$ESP32_DATA" | tail -1 | tr -d '[:space:]')
            if [ "$NETS" -gt 0 ] 2>/dev/null; then
                ok "ESP32 on Pineapple scanning: $NETS networks"
            else
                warn "ESP32 on Pineapple not producing data"
            fi
        else
            warn "No ESP32 detected on Pineapple USB"
        fi
    else
        fail "USB interface up but Pineapple not responding (still booting?)"
        info "Waiting 30s for Pineapple boot..."
        for i in $(seq 1 6); do
            sleep 5
            if ping -c 1 -W 2 172.16.42.1 >/dev/null 2>&1; then
                ok "Pineapple came up after $((i*5))s"
                PINEAPPLE_OK=true
                break
            fi
        done
        $PINEAPPLE_OK || fail "Pineapple did not respond after 30s"
    fi
else
    fail "Pineapple USB not detected — check cable"
fi
echo ""

# ── 2. ESP32-S2 (Flipper board) ──
echo -e "${CYAN}── ESP32-S2 (Flipper) ──${NC}"
ESP32S2_OK=false
ESP32S2_PORT=""

# Load CDC driver if needed
sudo modprobe cdc_acm 2>/dev/null

if lsusb 2>/dev/null | grep -q "303a:"; then
    ok "Espressif USB device detected"
    # Find the port
    for PORT in /dev/ttyACM0 /dev/ttyACM1 /dev/ttyACM2; do
        if [ -e "$PORT" ]; then
            ESP32S2_PORT="$PORT"
            break
        fi
    done
    if [ -n "$ESP32S2_PORT" ]; then
        ok "Serial port: $ESP32S2_PORT"
        # Test for data
        DATA=$(timeout 10 python3 -c "
import serial, time
ser = serial.Serial('$ESP32S2_PORT', 115200, timeout=1)
ser.reset_input_buffer()
end = time.time() + 8
buf = b''
while time.time() < end:
    chunk = ser.read(ser.in_waiting or 256)
    if chunk: buf += chunk
    time.sleep(0.5)
text = buf.decode('utf-8', errors='ignore')
lines = [l for l in text.split('\n') if l.strip().startswith('{')]
print(len(lines))
" 2>/dev/null || echo "0")
        LINES=$(echo "$DATA" | tail -1 | tr -d '[:space:]')
        if [ "$LINES" -gt 0 ] 2>/dev/null; then
            ok "ESP32-S2 producing data: $LINES JSON lines"
            ESP32S2_OK=true
        else
            warn "ESP32-S2 not producing data — may be in bootloader"
            info "Try unplugging and replugging (no buttons)"
        fi
    else
        fail "Espressif device found but no serial port created"
        info "Run: sudo modprobe cdc_acm"
    fi
else
    fail "ESP32-S2 not detected on USB"
fi
echo ""

# ── 3. Mini Router (GL-MT300N-V2) ──
echo -e "${CYAN}── Mini Router (GL-MT300N) ──${NC}"
ROUTER_OK=false

if [ "$MODE" = "home" ]; then
    # Check if visible on WiFi
    if nmcli device wifi list 2>/dev/null | grep -q "GL-MT300N"; then
        ok "Router WiFi visible"
        # Try SSH
        if ping -c 1 -W 2 192.168.8.1 >/dev/null 2>&1; then
            ok "Router reachable at 192.168.8.1"
            ROUTER_OK=true
        else
            info "Connecting to router WiFi..."
            nmcli device wifi connect GL-MT300N-V2-283 password goodlife >/dev/null 2>&1
            sleep 2
            if ping -c 1 -W 2 192.168.8.1 >/dev/null 2>&1; then
                ok "Connected to router"
                ROUTER_OK=true
            else
                fail "Could not reach router"
            fi
        fi
    else
        warn "Router not visible on WiFi — powered off or out of range"
    fi
else
    warn "Field mode — skipping mini router (not typically available)"
fi
echo ""

# ── Start Bridges ──
echo -e "${CYAN}── Starting Bridges ──${NC}"

if $ESP32S2_OK; then
    cd "$PROJECT_DIR"
    nohup python3 esp32_bridge.py --port "$ESP32S2_PORT" --baud 115200 --dashboard-data "$DASHBOARD_DATA" > "$LOG_DIR/esp32_bridge.log" 2>&1 &
    ok "ESP32-S2 bridge started (PID $!, log: $LOG_DIR/esp32_bridge.log)"
fi

if $ROUTER_OK; then
    cd "$PROJECT_DIR"
    nohup python3 router_bridge.py --ssh 192.168.8.1 --ssh-password goodlife --dashboard-data "$DASHBOARD_DATA" > "$LOG_DIR/router_bridge.log" 2>&1 &
    ok "Router bridge started (PID $!, log: $LOG_DIR/router_bridge.log)"
fi

echo ""

# ── Start Dashboard Server ──
echo -e "${CYAN}── Dashboard ──${NC}"
if pgrep -f "http.server.*8080" >/dev/null 2>&1; then
    ok "Dashboard server already running on :8080"
else
    cd "$PROJECT_DIR/dashboard"
    nohup python3 -m http.server 8080 > "$LOG_DIR/dashboard.log" 2>&1 &
    ok "Dashboard server started on :8080 (PID $!)"
fi
echo ""

# ── Summary ──
echo -e "${CYAN}══════════════════════════════════════${NC}"
echo -e "${CYAN}  SENSOR STATUS SUMMARY${NC}"
echo -e "${CYAN}══════════════════════════════════════${NC}"
$PINEAPPLE_OK && ok "Pineapple: ONLINE (172.16.42.1)" || fail "Pineapple: OFFLINE"
$ESP32S2_OK   && ok "ESP32-S2:  ONLINE ($ESP32S2_PORT)" || fail "ESP32-S2:  OFFLINE"
$ROUTER_OK    && ok "Router:    ONLINE (192.168.8.1 SSH)" || warn "Router:    OFFLINE"
echo ""
echo -e "${CYAN}Dashboard:${NC} http://localhost:8080"
echo -e "${CYAN}Environment:${NC} http://localhost:8080/environment.html"
echo -e "${CYAN}Logs:${NC} $LOG_DIR/"
echo ""
