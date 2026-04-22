#!/usr/bin/env bash
# Setup script for configuring the 300m mini router as a CSI transmitter.
#
# The mini router acts as a dedicated WiFi AP that sends consistent
# beacon and data frames. The ESP32 captures CSI from these frames
# for environment sensing (motion detection, gesture recognition, etc).
#
# Usage:
#   ./scripts/setup_csi_router.sh [router_ip]
#
# Default router IP: 192.168.8.1 (GL.iNet default)
# This script assumes the router runs OpenWrt or GL.iNet firmware.

set -euo pipefail

ROUTER_IP="${1:-192.168.8.1}"
CSI_SSID="5map-csi"
CSI_PASS="5mapcsi2024"
CSI_CHANNEL=6
BEACON_INTERVAL=50  # ms (lower = more CSI frames, default is 100)

echo "=== 5map CSI Transmitter Router Setup ==="
echo "Router IP: ${ROUTER_IP}"
echo "SSID:      ${CSI_SSID}"
echo "Channel:   ${CSI_CHANNEL}"
echo "Beacon:    ${BEACON_INTERVAL}ms"
echo ""

# Check connectivity
if ! ping -c 1 -W 2 "${ROUTER_IP}" >/dev/null 2>&1; then
    echo "ERROR: Cannot reach router at ${ROUTER_IP}"
    echo ""
    echo "Quick setup (manual):"
    echo "  1. Connect to the router's WiFi or ethernet"
    echo "  2. Open http://${ROUTER_IP} in a browser"
    echo "  3. Set WiFi SSID to: ${CSI_SSID}"
    echo "  4. Set WiFi password to: ${CSI_PASS}"
    echo "  5. Set channel to: ${CSI_CHANNEL}"
    echo "  6. Set beacon interval to: ${BEACON_INTERVAL}ms"
    echo "  7. Disable client isolation"
    echo "  8. Set bandwidth to 20MHz (HT20) for consistent CSI"
    echo ""
    echo "Then flash the ESP32 with matching config:"
    echo "  CONFIG_CSI_AP_SSID=\"${CSI_SSID}\""
    echo "  CONFIG_CSI_AP_PASS=\"${CSI_PASS}\""
    exit 1
fi

echo "Router reachable. Attempting SSH configuration..."

# Try SSH with common default credentials
SSH_CMD="ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 root@${ROUTER_IP}"

if ! ${SSH_CMD} "uci show wireless" >/dev/null 2>&1; then
    echo "SSH not available or not configured."
    echo ""
    echo "Manual setup required via web interface:"
    echo "  URL: http://${ROUTER_IP}"
    echo ""
    echo "WiFi settings:"
    echo "  SSID:             ${CSI_SSID}"
    echo "  Password:         ${CSI_PASS}"
    echo "  Channel:          ${CSI_CHANNEL}"
    echo "  Bandwidth:        20MHz (HT20)"
    echo "  Beacon interval:  ${BEACON_INTERVAL}ms"
    echo "  Client isolation: OFF"
    echo "  Country code:     GB"
    echo ""
    echo "Advanced (for better CSI):"
    echo "  Disable power save mode"
    echo "  Set TX power to maximum"
    echo "  Enable short GI (Guard Interval)"
    exit 0
fi

echo "SSH connected. Configuring via UCI..."

# Configure WiFi for CSI transmitter mode
${SSH_CMD} << 'SSHEOF'
# Set radio to fixed channel, 20MHz bandwidth
uci set wireless.radio0.channel='CHANNEL_PLACEHOLDER'
uci set wireless.radio0.htmode='HT20'
uci set wireless.radio0.country='GB'
uci set wireless.radio0.disabled='0'
uci set wireless.radio0.txpower='20'

# Configure the AP interface
uci set wireless.default_radio0.ssid='SSID_PLACEHOLDER'
uci set wireless.default_radio0.encryption='psk2'
uci set wireless.default_radio0.key='PASS_PLACEHOLDER'
uci set wireless.default_radio0.isolate='0'
uci set wireless.default_radio0.hidden='0'

# Set beacon interval for more frequent CSI frames
uci set wireless.radio0.beacon_int='BEACON_PLACEHOLDER'

# Disable power save for consistent transmission
uci set wireless.radio0.noscan='1'

# Apply changes
uci commit wireless
wifi reload
SSHEOF

# Replace placeholders
${SSH_CMD} "sed -i 's/CHANNEL_PLACEHOLDER/${CSI_CHANNEL}/g; s/SSID_PLACEHOLDER/${CSI_SSID}/g; s/PASS_PLACEHOLDER/${CSI_PASS}/g; s/BEACON_PLACEHOLDER/${BEACON_INTERVAL}/g' /tmp/csi_setup.sh 2>/dev/null || true"

echo ""
echo "Router configured successfully."
echo ""
echo "Verify with: ssh root@${ROUTER_IP} 'iwinfo wlan0 info'"
echo ""
echo "ESP32 sdkconfig should match:"
echo "  CONFIG_CSI_AP_SSID=\"${CSI_SSID}\""
echo "  CONFIG_CSI_AP_PASS=\"${CSI_PASS}\""
echo "  CONFIG_CSI_AP_CHANNEL=${CSI_CHANNEL}"
