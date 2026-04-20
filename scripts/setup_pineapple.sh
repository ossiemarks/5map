#!/bin/bash
set -euo pipefail

PINEAPPLE_IP="${1:?Usage: $0 <pineapple_ip> [cert_dir]}"
CERT_DIR="${2:-/tmp/5map-certs}"
REMOTE_DIR="/opt/5map"
REMOTE_CERT_DIR="/etc/5map/certs"

log() { echo "[setup-pineapple] $(date '+%H:%M:%S') $1"; }

# Verify SSH connectivity
log "Testing SSH connection to $PINEAPPLE_IP..."
ssh -o ConnectTimeout=5 -o BatchMode=yes "root@$PINEAPPLE_IP" "echo ok" >/dev/null 2>&1 || {
    log "ERROR: Cannot SSH to root@$PINEAPPLE_IP"
    log "Ensure SSH key auth is configured (no password auth)"
    exit 1
}

# Verify certificate files exist
log "Checking certificates in $CERT_DIR..."
for cert_file in AmazonRootCA1.pem certificate.pem.crt private.pem.key; do
    if [[ ! -f "$CERT_DIR/$cert_file" ]]; then
        log "ERROR: Missing certificate: $CERT_DIR/$cert_file"
        log "Run 'terraform output' to get certificate data, then save to $CERT_DIR/"
        exit 1
    fi
done

# Create directories on Pineapple
log "Creating directories on Pineapple..."
ssh "root@$PINEAPPLE_IP" "mkdir -p $REMOTE_DIR $REMOTE_CERT_DIR"

# Copy agent code
log "Copying agent code..."
scp -r pineapple/ "root@$PINEAPPLE_IP:$REMOTE_DIR/"

# Copy certificates with restricted permissions
log "Copying certificates..."
scp "$CERT_DIR"/* "root@$PINEAPPLE_IP:$REMOTE_CERT_DIR/"
ssh "root@$PINEAPPLE_IP" "chmod 600 $REMOTE_CERT_DIR/*"

# Verify certificates on device
log "Verifying certificates..."
ssh "root@$PINEAPPLE_IP" "ls -la $REMOTE_CERT_DIR/" || {
    log "ERROR: Certificate verification failed"
    exit 1
}

# Install Python dependencies (if available)
log "Installing Python dependencies..."
ssh "root@$PINEAPPLE_IP" "opkg update && opkg install python3 python3-pip 2>/dev/null || true"
ssh "root@$PINEAPPLE_IP" "pip3 install scapy paho-mqtt pyyaml 2>/dev/null || true"

# Install init.d script
log "Installing service..."
scp pineapple/init.d/5map-agent "root@$PINEAPPLE_IP:/etc/init.d/5map-agent"
ssh "root@$PINEAPPLE_IP" "chmod +x /etc/init.d/5map-agent && /etc/init.d/5map-agent enable"

log "Setup complete. Start with: ssh root@$PINEAPPLE_IP '/etc/init.d/5map-agent start'"
