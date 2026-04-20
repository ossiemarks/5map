#!/bin/sh
# Setup WiFi Pineapple Mark VII radios for monitor mode
# Run as root on the Pineapple

set -e

IFACE_5GHZ="${1:-wlan0}"
IFACE_2GHZ="${2:-wlan1}"

log() {
    echo "[5map-setup] $(date '+%Y-%m-%d %H:%M:%S') $1"
}

check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        log "ERROR: Must run as root"
        exit 1
    fi
}

check_interface() {
    iface="$1"
    if ! iw dev "$iface" info >/dev/null 2>&1; then
        log "ERROR: Interface $iface not found"
        exit 1
    fi
}

setup_monitor() {
    iface="$1"
    log "Setting $iface to monitor mode..."

    # Bring interface down
    ip link set "$iface" down 2>/dev/null || true

    # Kill any processes using the interface
    airmon-ng check kill 2>/dev/null || true

    # Set monitor mode
    iw dev "$iface" set type monitor 2>/dev/null || {
        log "WARN: iw set type failed, trying iwconfig..."
        iwconfig "$iface" mode monitor 2>/dev/null || {
            log "ERROR: Failed to set $iface to monitor mode"
            return 1
        }
    }

    # Bring interface back up
    ip link set "$iface" up

    # Verify monitor mode
    mode=$(iw dev "$iface" info 2>/dev/null | grep type | awk '{print $2}')
    if [ "$mode" = "monitor" ]; then
        log "SUCCESS: $iface is in monitor mode"
    else
        log "ERROR: $iface mode is '$mode', expected 'monitor'"
        return 1
    fi
}

restore_managed() {
    iface="$1"
    log "Restoring $iface to managed mode..."
    ip link set "$iface" down 2>/dev/null || true
    iw dev "$iface" set type managed 2>/dev/null || true
    ip link set "$iface" up 2>/dev/null || true
    log "Restored $iface to managed mode"
}

# Handle cleanup on exit
cleanup() {
    if [ "${RESTORE_ON_EXIT:-0}" = "1" ]; then
        log "Restoring interfaces..."
        restore_managed "$IFACE_5GHZ"
        restore_managed "$IFACE_2GHZ"
    fi
}

trap cleanup EXIT

# Main
case "${3:-setup}" in
    setup)
        check_root
        check_interface "$IFACE_5GHZ"
        check_interface "$IFACE_2GHZ"
        setup_monitor "$IFACE_5GHZ"
        setup_monitor "$IFACE_2GHZ"
        log "Both radios ready for capture"
        ;;
    restore)
        check_root
        RESTORE_ON_EXIT=1
        exit 0
        ;;
    status)
        for iface in "$IFACE_5GHZ" "$IFACE_2GHZ"; do
            mode=$(iw dev "$iface" info 2>/dev/null | grep type | awk '{print $2}')
            log "$iface: mode=$mode"
        done
        ;;
    *)
        echo "Usage: $0 [5ghz_iface] [2ghz_iface] [setup|restore|status]"
        exit 1
        ;;
esac
