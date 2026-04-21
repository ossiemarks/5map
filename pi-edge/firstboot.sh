#!/bin/bash
# 5map Pi Edge Node - First boot configuration
# This runs once on first boot to configure the Pi as a 5map edge node

set -e
LOG="/var/log/5map-firstboot.log"
exec > >(tee -a "$LOG") 2>&1

echo "[5map] First boot setup starting at $(date)"

# Wait for network
for i in $(seq 1 30); do
    if ping -c 1 8.8.8.8 >/dev/null 2>&1; then
        echo "[5map] Network available"
        break
    fi
    echo "[5map] Waiting for network... ($i/30)"
    sleep 2
done

# Update and install dependencies
echo "[5map] Installing system packages..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git mosquitto-clients \
    bluetooth bluez libbluetooth-dev \
    i2c-tools python3-smbus \
    build-essential cmake 2>&1 | tail -5

# Install Python packages
echo "[5map] Installing Python packages..."
pip3 install --break-system-packages scapy paho-mqtt pyyaml pydantic numpy scikit-learn boto3 2>&1 | tail -5

# Clone 5map repo
echo "[5map] Cloning 5map..."
git clone https://github.com/ossiemarks/5map.git /opt/5map 2>&1 | tail -3

# Setup ESP32 CSI tools
echo "[5map] Setting up ESP-IDF for ESP32 CSI..."
mkdir -p /opt/esp
cd /opt/esp
git clone --depth 1 --branch v5.1.2 https://github.com/espressif/esp-idf.git 2>&1 | tail -3
cd esp-idf
./install.sh esp32 2>&1 | tail -5

# Install ESP32 CSI tool
cd /opt
git clone --depth 1 https://github.com/espressif/esp-csi.git 2>&1 | tail -3

# Create 5map edge service
cat > /etc/systemd/system/5map-edge.service << 'SVC'
[Unit]
Description=5map Edge Node Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/5map/pineapple/capture_agent.py --config /etc/5map/config.yaml
Restart=always
RestartSec=10
User=root
WorkingDirectory=/opt/5map

[Install]
WantedBy=multi-user.target
SVC

# Create edge node config
mkdir -p /etc/5map/certs
cat > /etc/5map/config.yaml << 'CFG'
sensor:
  id: pi-edge-001
  type: rssi

radios:
  radio_monitor:
    interface: wlan1
    band: 2.4GHz
    channels: [1, 6, 11]
    mode: monitor

capture:
  window_seconds: 1
  max_observations_per_window: 10000
  channel_dwell_ms: 200
  buffer_max_size: 50000

transport:
  type: mqtt
  mqtt:
    broker: a2qz7dpyqsh35h-ats.iot.eu-west-2.amazonaws.com
    port: 8883
    topic: 5map/rssi/{sensor_id}
    qos: 1
    keepalive: 60
    tls: true
    cert_dir: /etc/5map/certs
    ca_cert: AmazonRootCA1.pem
    client_cert: certificate.pem.crt
    private_key: private.pem.key
  queue_max_size: 1000

logging:
  level: INFO
  file: /var/log/5map-agent.log
  max_bytes: 5242880
  backup_count: 3
CFG

# Enable I2C and SPI for ESP32 communication
raspi-config nonint do_i2c 0
raspi-config nonint do_spi 0

# Enable serial for ESP32 UART
raspi-config nonint do_serial_hw 0
raspi-config nonint do_serial_cons 1

# Set hostname
hostnamectl set-hostname 5map-edge

# Enable the service (don't start yet - needs certs)
systemctl daemon-reload
systemctl enable 5map-edge.service

# Create ESP32 flash helper script
cat > /usr/local/bin/5map-flash-esp32 << 'FLASH'
#!/bin/bash
# Flash ESP32 with CSI firmware via USB
set -e
PORT="${1:-/dev/ttyUSB0}"
echo "[5map] Flashing ESP32 CSI firmware on $PORT..."
source /opt/esp/esp-idf/export.sh
cd /opt/esp-csi/examples/get-started/csi_recv
idf.py -p "$PORT" flash monitor
FLASH
chmod +x /usr/local/bin/5map-flash-esp32

# Create ESP32 CSI receiver script
cat > /opt/5map/esp32_csi_bridge.py << 'BRIDGE'
#!/usr/bin/env python3
"""Bridge ESP32 CSI serial data to the 5map pipeline."""
import json
import logging
import serial
import time
import sys

logger = logging.getLogger("5map-csi-bridge")

def read_csi_from_serial(port="/dev/ttyUSB0", baud=921600):
    """Read CSI data from ESP32 over serial."""
    ser = serial.Serial(port, baud, timeout=1)
    logger.info("Connected to ESP32 on %s", port)

    while True:
        try:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if line.startswith("CSI_DATA"):
                parts = line.split(",")
                if len(parts) >= 10:
                    yield {
                        "type": "csi",
                        "mac": parts[2],
                        "rssi": int(parts[3]),
                        "channel": int(parts[4]),
                        "timestamp": time.time(),
                        "csi_raw": parts[6:],
                    }
        except serial.SerialException as e:
            logger.error("Serial error: %s", e)
            time.sleep(1)
        except KeyboardInterrupt:
            break

    ser.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
    for frame in read_csi_from_serial(port):
        print(json.dumps(frame))
BRIDGE
chmod +x /opt/5map/esp32_csi_bridge.py

# Remove this script from running again
rm -f /etc/5map-firstboot.sh
echo "[5map] First boot setup complete at $(date)"
echo "[5map] Reboot to apply all changes"
