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

## Component Roles

### WiFi Pineapple Mark VII — The Sensor
The Pineapple is the **data collection** device. It captures raw WiFi frames in monitor mode across dual radios (2.4GHz + 5GHz), extracting RSSI, MAC addresses, SSIDs, and frame types from every WiFi device in range. It detects MAC randomization, hops across channels, and streams observation windows to AWS via MQTT. It is a portable, battery-powered dumb pipe — captures and forwards with no ML processing (128MB RAM, MIPS CPU can't handle inference).

### Raspberry Pi — The Edge Brain
The Pi is the **local processing** node. It receives CSI data from the ESP32 array via USB serial, runs local ML inference (environment mapper, presence detector) for low-latency decisions (<100ms vs ~500ms to AWS), and relays results to the cloud. It also provides internet connectivity to the Pineapple in the field (via LTE hotspot or site WiFi), hosts ESP-IDF for flashing ESP32 firmware, and can run the dashboard server for offline audits. With the Pi, no laptop is needed — it's a self-contained field kit.

### ESP32 Array — The CSI Receivers
3-4 ESP32 modules (~$5 each) positioned around the space capture WiFi Channel State Information — per-subcarrier amplitude and phase data at 64 subcarriers per device. This is far richer than RSSI (a single number) and enables gesture recognition, centimeter-level positioning, and fine-grained activity detection. They connect to the Pi via USB serial, streaming raw CSI frames.

### AWS Cloud — The Backend
AWS handles heavy ML processing, persistent storage, API serving, and multi-client access. IoT Core ingests MQTT from the Pineapple/Pi, Kinesis buffers the stream, Lambda preprocesses and routes data, SageMaker runs ML inference, DynamoDB stores results, and API Gateway serves the mobile app and web dashboard.

### Field Deployment (Current vs Future)

**Now** (Pineapple only):
```
Pineapple ──(USB to laptop)──► laptop internet ──► AWS ──► Dashboard/App
```

**Future** (full kit, no laptop needed):
```
ESP32 array ──(serial CSI)──► Raspberry Pi ──(WiFi/LTE)──► AWS
                                    ▲
Pineapple ──(MQTT via Pi WiFi)──────┘
                                    │
                              React Native App
                              (connects to Pi or AWS)
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

## Reading the Dashboard

### Signal Map (top-left)
- **Green** = strong signal (-30 to -50 dBm) — you're close to an AP
- **Yellow** = medium signal (-50 to -70 dBm) — moderate distance
- **Red** = weak signal (-70 to -90 dBm) — far from AP or behind walls
- **Dashed lines** = inferred walls/obstacles (detected by sharp signal drop-offs)
- **Confidence %** = how reliable the map is (more tagged positions = higher confidence)

### Device List (top-right)
- **Type icons**: 📡 AP, 📱 phone, 💻 laptop, 🏠 IoT, ❓ unknown
- **[R] badge** = randomized MAC (device is hiding its real identity — common on modern phones)
- **Risk badges**: `LOW` (green, known vendor, normal behavior), `MED` (yellow, suspicious patterns), `HIGH` (red, potential rogue AP or attacker)
- **RSSI bar** = visual signal strength. Longer = stronger signal = device is closer
- Sort by clicking column headers

### Presence Timeline (bottom-left)
- **Green dot / Entry** = new device(s) appeared in zone
- **Red dot / Exit** = device(s) left the zone
- **Cyan dot / Moving** = devices detected moving (RSSI fluctuating periodically)
- **Gray dot / Stationary** = devices present but not moving
- **Confidence %** = how certain the classification is
- Most recent events at top

### Stats Panel (bottom-right)
- **Total Devices** = unique MACs seen in this session
- **Rogue Devices** = devices with risk score >= 0.6 (investigate these)
- **Randomized MACs** = devices hiding real identity (normal for phones, suspicious for APs)
- **Active Zones** = number of distinct zones with activity
- **WebSocket dot** = green when real-time updates are flowing, red when polling

## Visual Indicators Dashboard

A dedicated signal intelligence page (`dashboard/visual-indicators.html`) providing rich real-time visual representations of WiFi and Bluetooth RF data.

```bash
cd dashboard && python3 -m http.server 8080
# Open http://localhost:8080/visual-indicators.html
```

Navigate between dashboards using the header nav links.

### Device Radar (top-left, wide)
- Polar/radar display with all WiFi + Bluetooth devices positioned by estimated distance from the Pineapple
- Distance estimated using log-distance path loss model: `d = 10^((TxPower - RSSI) / (10 * n))`, n=2.7 indoor
- Concentric rings at 1m, 3m, 5m, 10m, 15m
- Devices grouped by band: 2.4GHz top-right quadrant, 5GHz top-left, Bluetooth bottom half
- Color by risk score: green (low), amber (medium), red (high)
- Size by device type: AP largest, phone medium, IoT/unknown smallest
- Animated cyan radar sweep line (4-second rotation)
- Hover for device details, click to highlight across all panels

### Signal Strength Gauges (top-right)
- One 270-degree arc gauge per detected AP
- Color gradient: red (weak) through amber to green (strong)
- RSSI mapped to percentage: -30 dBm = 100%, -50 = 70%, -70 = 40%, -90 = 10%
- Quality labels: Excellent / Good / Fair / Weak / Dead
- SSID displayed below each gauge ("Hidden" for cloaked networks)
- Subtle animated glow proportional to signal strength

### Channel Utilization (middle-left)
- Stacked bar chart showing device count per WiFi channel
- Color-coded by device type: AP (cyan), Phone (amber), IoT (green), Unknown (gray)
- Vertical dashed separator between 2.4GHz and 5GHz bands
- Only channels with active devices are shown
- Bar opacity increases with congestion

### Bluetooth Proximity Rings (middle-right)
- Four concentric sonar-style rings with animated ripple effects
- **Immediate** (green, <1m): RSSI > -50 dBm
- **Near** (cyan, 1-3m): RSSI -50 to -70 dBm
- **Far** (amber, 3-10m): RSSI -70 to -85 dBm
- **Remote** (red, >10m): RSSI < -85 dBm
- Device names displayed (e.g., "iPhone 15 Pro", "AirPods Pro 2")
- Solid dot = connectable, dashed border = non-connectable

### Risk Overview (bottom-left)
- Donut chart with total device count in center
- Segments: Low (green), Medium (amber), High (red) risk tiers
- High-risk device cards with pulsing red glow borders showing MAC, SSID, risk score
- Horizontal risk distribution bar

### ESP32 CSI Preview (bottom-right)
- Synthetic 64-subcarrier OFDM amplitude waveform (future-ready visualization)
- Phase rotation gradient strip below
- Animated oscillation to simulate live CSI data
- Status badge: "STANDBY - Awaiting Hardware"
- Will display real CSI data once ESP32 array is connected

### Real-Time Updates
- **WebSocket**: Connects to `wss://ep8zonl28l.execute-api.eu-west-2.amazonaws.com/prod` for instant push updates
- **Fallback polling**: 1-second interval from `data.json` when WebSocket is disconnected
- **Status indicator**: Green "Live" dot when streaming via WebSocket, red "Polling" when falling back
- **Animation**: All visualizations run at 60fps via `requestAnimationFrame`
- **Signal jitter**: Adds realistic +/-2 dBm RSSI noise for live feel on static data

### Signal Processing Library
`dashboard/signal-processing.js` (1505 lines) provides reusable algorithms:
- RSSI-to-distance estimation (log-distance path loss model)
- Polar radar plot data generation
- Signal strength gauge calculations
- Channel utilization analysis with congestion scoring
- Bluetooth proximity ring classification
- Device risk heatmap generation (Gaussian kernel)
- Signal trend simulation with realistic jitter
- ESP32 CSI waveform generation (64 OFDM subcarriers)

## Future Roadmap

- **ESP32 CSI module** - Add 3-4 ESP32s for Channel State Information capture, enabling gesture recognition and centimeter-level positioning
- **Raspberry Pi edge node** - Local ML inference before streaming to AWS, reducing latency and bandwidth
- **Cognito auth** - Replace MVP token auth with proper user management
- **Push notifications** - Firebase/APNs alerts when app is backgrounded
- **Multi-site support** - Multiple Pineapples streaming to the same dashboard
- **PDF export** - Server-side report generation with map, device inventory, presence timeline
