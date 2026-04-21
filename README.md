# 5map - WiFi Environment Mapper & Security Audit Tool

WiFi-based environment mapping, device tracking, and presence detection tool for security audits. Uses a WiFi Pineapple Mark VII to capture RSSI data from the surrounding environment, processes it through ML models on AWS, and visualizes results in a real-time dashboard and React Native mobile app.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        FIELD DEPLOYMENT                          │
│                                                                  │
│  WiFi Pineapple Mark VII          React Native App               │
│  ┌─────────────────────┐          ┌──────────────┐              │
│  │ Radio 1 (5GHz)  MON │          │ Signal Map   │              │
│  │ Radio 2 (2.4G)  MON │          │ Device List  │              │
│  │ raw_capture.py      │          │ Presence     │              │
│  │ channel_hopper.py   │          │ Settings     │              │
│  └────────┬────────────┘          └──────┬───────┘              │
│           │ MQTT/TLS                     │ REST + WebSocket      │
└───────────┼──────────────────────────────┼──────────────────────┘
            │                              │
┌───────────▼──────────────────────────────▼──────────────────────┐
│                         AWS (eu-west-2)                          │
│                                                                  │
│  IoT Core ──► Kinesis ──► Lambda ──► SageMaker                  │
│                              │          │                        │
│                              ▼          ▼                        │
│                          DynamoDB   S3 Archive                   │
│                              │                                   │
│                              ▼                                   │
│                    API Gateway (REST + WS)                       │
│                   api.voicechatbox.com                           │
│                   ws.voicechatbox.com                            │
└──────────────────────────────────────────────────────────────────┘
```

## What It Does

**Environment Mapping** - Walk through a space with the Pineapple, tag positions in the app, and 5map builds a signal strength heatmap with inferred wall positions using Gaussian Process regression.

**Device Discovery** - Identifies every WiFi device in range: phones, laptops, IoT devices, access points. Classifies device types using a Random Forest model trained on probe patterns, RSSI variance, and OUI vendor data. Flags rogue APs and suspicious devices with risk scores.

**Presence Detection** - Monitors zones for entry/exit events, movement patterns, and occupancy using an LSTM model that analyzes RSSI time-series fluctuations.

**MAC Randomization Detection** - Identifies devices using randomized MAC addresses (modern iOS/Android behavior) by checking the locally administered bit and fingerprinting probe request patterns.

## Design Decisions

### Why WiFi Pineapple?

The Mark VII was chosen because it has dual radios (MT7612EN 5GHz + MT7628 2.4GHz) that can operate in monitor mode simultaneously, capturing traffic across multiple channels. It runs OpenWrt with Python support, making it programmable for custom capture agents.

**Limitation discovered**: The Pineapple's stripped-down Python 3.9 lacks `ctypes`, which scapy requires. Solution: built a lightweight raw socket capture module (`raw_capture.py`) using `AF_PACKET` sockets with `struct`-based radiotap header parsing. Zero external dependencies.

### Why RSSI Instead of CSI?

Full WiFi Channel State Information (CSI) extraction requires either:
- Custom firmware patches for MediaTek chipsets (untested on MT7612/MT7628)
- Nexmon CSI patches (Broadcom only, not compatible with Pineapple)
- ESP32 companion devices

RSSI was chosen as the immediately viable approach. The architecture includes a **pluggable sensor interface** (`SensorBase` ABC) so ESP32 CSI modules can be added later without refactoring the pipeline.

### Why AWS Over Local Processing?

The Pineapple has ~128MB RAM on a MIPS CPU. Running ML inference locally would exceed memory limits. AWS provides:
- **IoT Core** for secure MQTT ingestion with X.509 certificate auth
- **Kinesis** for ordered streaming with replay capability
- **SageMaker** for ML inference (Sparse GP, Random Forest, LSTM)
- **DynamoDB** for schemaless storage that scales with evolving sensor data

Estimated cost: $15-30/month depending on usage.

### Why Sparse GP for Environment Mapping?

Standard Gaussian Process regression is O(n^3) time and O(n^2) memory, which becomes unusable above ~100 survey points. The Sparse GP with Nystroem approximation keeps inference under 200ms regardless of dataset size by using a fixed number of inducing points.

### Why LSTM for Presence Detection?

RSSI time-series have temporal patterns that distinguish stationary devices from moving ones. An LSTM (2 layers, 64 hidden units, ~50K parameters) captures these patterns while remaining lightweight enough for SageMaker real-time inference.

### Why React Native + Web Dashboard?

Two interfaces serve different workflows:
- **React Native app**: Field use during audits. Tag positions, view real-time devices, receive alerts on your phone while walking the site.
- **Web dashboard**: Command center view. Monitor multiple sessions, analyze captured data, generate reports from a laptop.

## Project Structure

```
5map/
├── pineapple/                 # WiFi Pineapple capture agent
│   ├── capture_agent.py       # Main daemon - orchestrates capture + MQTT
│   ├── channel_hopper.py      # Background channel cycling for both radios
│   ├── config.yaml            # Channels, MQTT broker, scan intervals
│   ├── setup_monitor.sh       # Configure radios for monitor mode
│   ├── init.d/5map-agent      # OpenWrt procd service script
│   ├── parsers/
│   │   ├── rssi_parser.py     # Scapy-based frame parsing (for full Python)
│   │   └── raw_capture.py     # Raw socket parser (for stripped OpenWrt Python)
│   └── transport/
│       └── mqtt_client.py     # AWS IoT Core MQTT with TLS + cert auth
│
├── src/                       # Data abstraction layer
│   ├── sensors/
│   │   ├── base.py            # SensorBase ABC + SensorFrame dataclass
│   │   ├── registry.py        # Pluggable sensor registration
│   │   └── rssi_sensor.py     # Pineapple RSSI adapter
│   ├── pipeline/
│   │   ├── frame_router.py    # Normalize sensor data for ML consumption
│   │   ├── buffer.py          # Time-window buffering with backpressure
│   │   └── transport.py       # Abstract transport (MQTT/Kinesis)
│   └── config/
│       └── schema.py          # Pydantic config validation
│
├── backend/                   # AWS Lambda functions
│   └── handlers/
│       ├── preprocessor.py    # Kinesis-triggered: validate, enrich, archive
│       ├── api_handler.py     # REST API: map, devices, presence, sessions
│       ├── ws_handler.py      # WebSocket: connect, disconnect, subscribe
│       └── authorizer.py      # Token-based WebSocket auth
│
├── ml/                        # Machine learning models
│   ├── models/
│   │   ├── env_mapper.py      # Sparse GP environment mapping + wall detection
│   │   ├── device_fp.py       # Random Forest device fingerprinting
│   │   └── presence_lstm.py   # PyTorch LSTM presence detection
│   ├── data/
│   │   ├── oui_database.py    # 82-entry IEEE OUI vendor lookup
│   │   └── synthetic.py       # Synthetic data generators for training
│   ├── training/
│   │   └── train_all.py       # Train all 3 models
│   └── serving/
│       ├── sagemaker_handler.py # Multi-model SageMaker endpoint
│       └── model_registry.py   # Versioned S3 model artifact management
│
├── terraform/                 # AWS infrastructure (46 resources)
│   ├── main.tf                # Module composition
│   ├── backend.tf             # S3 state backend
│   ├── variables.tf           # Configurable parameters
│   └── modules/
│       ├── iot/               # IoT Core thing, cert, policy, Kinesis rule
│       ├── kinesis/           # Data stream (1 shard, 24h retention)
│       ├── dynamodb/          # 5 tables (maps, devices, presence, sessions, connections)
│       ├── lambda/            # 4 functions + DLQ + S3 data bucket
│       ├── api/               # API Gateway REST + WebSocket
│       ├── sagemaker/         # Model bucket + IAM role
│       └── monitoring/        # CloudWatch alarms + SNS + billing alert
│
├── app/                       # React Native mobile app (Expo)
│   ├── App.tsx                # Tab navigation + WebSocket setup
│   └── src/
│       ├── screens/           # Map, Devices, Presence, Settings
│       ├── components/        # HeatmapOverlay, DeviceCard, PresenceTimeline
│       ├── services/          # REST API, WebSocket, AsyncStorage
│       ├── hooks/             # useMap, useDevices, usePresence
│       ├── store/             # Zustand global state
│       └── types/             # TypeScript interfaces
│
├── dashboard/                 # Web dashboard (single HTML file)
│   ├── index.html             # Real-time 4-panel dashboard
│   ├── data.json              # Live capture data from Pineapple
│   └── server.py              # Local Python proxy server
│
├── scripts/                   # Deployment and setup
│   ├── deploy.sh              # Terraform deploy with S3 state bootstrap
│   ├── teardown.sh            # Terraform destroy with confirmation
│   ├── setup_pineapple.sh     # Configure Pineapple via SSH
│   └── generate_test_data.py  # Create synthetic test fixtures
│
├── pi-edge/                   # Raspberry Pi edge node (future)
│   └── firstboot.sh           # First-boot setup: 5map + ESP-IDF + CSI tools
│
├── tests/                     # 117 passing tests
│   ├── test_rssi_parser.py    # RSSI extraction, MAC detection, channel mapping
│   ├── test_channel_hopper.py # Channel cycling, frequency conversion
│   ├── test_mqtt_client.py    # MQTT transport, queue, reconnect
│   ├── test_sensor_base.py    # ABC contract, SensorFrame serialization
│   ├── test_registry.py       # Plugin registration, thread safety
│   ├── test_frame_router.py   # RSSI/CSI normalization
│   ├── test_buffer.py         # Backpressure, concurrent writes
│   ├── test_config_schema.py  # Pydantic validation
│   ├── test_lambda/           # Lambda preprocessor + API handler
│   ├── test_ml/               # GP mapper, RF fingerprinter, LSTM detector
│   └── integration/           # End-to-end pipeline tests
│
└── pyproject.toml             # Python project config
```

## Hardware

### Current: WiFi Pineapple Mark VII
- **Chipsets**: MT7612EN (5GHz) + MT7628 (2.4GHz)
- **Firmware**: 2.1.3
- **Connection**: USB-C to laptop (172.16.42.1)
- **Radios**: wlan0 (AP mode - honeypots), wlan1 (monitor mode - capture), wlan2 (managed)

### Future: ESP32 CSI Array
- 3-4x ESP32 modules (~$5 each) for WiFi Channel State Information extraction
- 64 subcarriers per ESP32 at 20MHz bandwidth
- Connected to Raspberry Pi edge node via serial/WiFi
- Enables gesture recognition, fine-grained mapping, activity detection

## Quick Start

### Prerequisites
- WiFi Pineapple Mark VII connected via USB
- AWS account with CLI configured (`aws configure`)
- Terraform >= 1.5
- Python >= 3.9
- Node.js >= 18

### 1. Deploy AWS Infrastructure
```bash
./scripts/deploy.sh
```
This bootstraps the S3 state backend, runs `terraform plan`, and applies after confirmation. Creates 46 AWS resources.

### 2. Configure Pineapple
```bash
./scripts/setup_pineapple.sh 172.16.42.1
```
Copies the capture agent, IoT certificates, and Python dependencies to the Pineapple. Installs the init.d service.

### 3. Start Capture
```bash
ssh root@172.16.42.1 '/etc/init.d/5map-agent start'
```

### 4. View Dashboard
```bash
cd dashboard && python3 -m http.server 8080
# Open http://localhost:8080
```

### 5. Mobile App
```bash
cd app && npm install && npx expo start
# Scan QR code with Expo Go
```

### 6. Run Tests
```bash
pip install -e ".[dev,ml]"
pytest tests/ -v
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/sessions` | Create new audit session |
| `GET` | `/api/map/{session_id}` | Get environment map data |
| `GET` | `/api/devices/{session_id}` | List discovered devices |
| `GET` | `/api/presence/{session_id}` | Get presence events |
| `POST` | `/api/positions` | Tag a physical position |
| `WSS` | `ws.voicechatbox.com` | Real-time updates |

**Live endpoints:**
- REST: `https://dqbhaw5wki.execute-api.eu-west-2.amazonaws.com`
- WebSocket: `wss://ep8zonl28l.execute-api.eu-west-2.amazonaws.com/prod`
- IoT: `a2qz7dpyqsh35h-ats.iot.eu-west-2.amazonaws.com`

## ML Models

### Environment Mapper (Sparse Gaussian Process)
- **Input**: RSSI observations tagged with x,y positions
- **Output**: 2D signal heatmap + inferred wall positions
- **Algorithm**: Sparse GP with Nystroem approximation for O(1) inference
- **Wall detection**: Gradient magnitude thresholding on heatmap

### Device Fingerprinter (Random Forest)
- **Input**: 8 features per device (OUI vendor, MAC randomization flag, probe frequency, RSSI variance, channel count, frame type distribution, SSID probe count)
- **Output**: Device type (phone/laptop/IoT/AP/unknown) + risk score
- **Risk scoring**: Rogue AP detection (0.8), unknown+randomized (0.6), unknown vendor (0.5), known normal (0.1)
- **OUI database**: 82 entries covering Apple, Samsung, Google, Intel, Broadcom, Cisco, TP-Link, Espressif, etc.

### Presence Detector (PyTorch LSTM)
- **Input**: 5-second sliding window of RSSI statistics (mean, variance, device count, new device count)
- **Output**: Presence event classification (empty/stationary/moving/entry/exit) with confidence
- **Architecture**: 2 layers, 64 hidden units, dropout 0.2 (~50K parameters)

## AWS Resources (46 total)

| Service | Resources | Purpose |
|---------|-----------|---------|
| IoT Core | Thing, certificate, policy, topic rule | Pineapple MQTT ingestion |
| Kinesis | 1-shard data stream | Ordered event buffering |
| Lambda | 4 functions + DLQ | Preprocessing, API, WebSocket, auth |
| DynamoDB | 5 tables (on-demand) | Maps, devices, presence, sessions, connections |
| API Gateway | REST API + WebSocket API | App and dashboard access |
| S3 | 2 buckets (data + models) | Raw archive + ML model artifacts |
| CloudWatch | 3 alarms + SNS topic | Lambda errors, Kinesis lag, billing ($50 threshold) |
| SageMaker | IAM role + model bucket | ML model serving (endpoint created on demand) |

## Field Deployment Workflow

1. Power on Pineapple, connect phone to management WiFi
2. Open 5map app, create new audit session
3. Walk the perimeter tagging positions (minimum 10 for useful map)
4. Station Pineapple centrally for continuous monitoring
5. Monitor device list for rogue APs and suspicious devices
6. Review presence timeline for zone activity
7. Export PDF audit report

## Security Considerations

- IoT Core uses X.509 certificate authentication (not password)
- Certificates stored with 600 permissions on Pineapple
- API Gateway uses token-based auth (Cognito planned for production)
- No passwords with exclamation marks (ALB compatibility)
- DynamoDB on-demand billing prevents cost spikes
- CloudWatch billing alarm at $50/month threshold
- Terraform state encrypted in S3 with versioning

## Credentials

- **Pineapple**: `root@172.16.42.1` / `hak5pineapple` (SSH key auth configured)
- **Pineapple Web UI**: `http://172.16.42.1:1471` / `root` / `hak5pineapple`
- **AWS Account**: 835661413889 (eu-west-2)
- **Session ID**: `e8076d73-ce66-4ed8-85fb-ef715f8844cf`

## Future Roadmap

- **ESP32 CSI module** - Add 3-4 ESP32s for Channel State Information capture, enabling gesture recognition and centimeter-level positioning
- **Raspberry Pi edge node** - Local ML inference before streaming to AWS, reducing latency and bandwidth
- **Cognito auth** - Replace MVP token auth with proper user management
- **Push notifications** - Firebase/APNs alerts when app is backgrounded
- **Multi-site support** - Multiple Pineapples streaming to the same dashboard
- **PDF export** - Server-side report generation with map, device inventory, presence timeline
