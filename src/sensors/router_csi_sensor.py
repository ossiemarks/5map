"""Router CSI sensor for 300m mini net router via CH340 USB serial.

The mini router acts as both a CSI transmitter (AP beacons for ESP32 to
capture) and an independent CSI receiver. Connected via CH340 USB-serial
adapter on /dev/ttyUSB0, it reports WiFi environment data including
signal strength, channel utilization, and connected station metrics.

Supports routers running OpenWrt or stock firmware with serial console.
Falls back to periodic AT-style polling if no shell is available.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import re
import subprocess

try:
    import serial
except ImportError:
    serial = None

from src.sensors.base import SensorBase, SensorFrame, SensorObservation, SensorType

logger = logging.getLogger(__name__)

# Common baud rates for mini router serial consoles
ROUTER_BAUD_RATES = [115200, 57600, 9600, 38400, 230400, 460800, 921600]

# Default polling interval for station/signal data
POLL_INTERVAL_S = 3.0


@dataclass(slots=True)
class RouterObservation:
    """Single observation from the mini router."""

    mac: str
    rssi_dbm: int
    channel: int
    bandwidth: str
    noise_floor: int = -90
    tx_rate: int = 0
    rx_rate: int = 0
    connected: bool = False
    ssid: str = ""
    signal_quality: int = 0  # 0-100


@dataclass
class RouterWindow:
    """Time-bounded collection of router observations."""

    timestamp: str
    sensor_id: str
    window_ms: int
    observations: List[RouterObservation] = field(default_factory=list)
    router_info: Dict[str, Any] = field(default_factory=dict)


class RouterWindowAggregator:
    """Aggregate router observations into fixed time windows."""

    def __init__(self, sensor_id: str, window_ms: int = 3000,
                 max_observations: int = 200) -> None:
        self._sensor_id = sensor_id
        self._window_ms = window_ms
        self._max_observations = max_observations
        self._observations: List[RouterObservation] = []
        self._router_info: Dict[str, Any] = {}

    def add(self, obs: RouterObservation) -> None:
        if len(self._observations) < self._max_observations:
            self._observations.append(obs)

    def set_router_info(self, info: Dict[str, Any]) -> None:
        self._router_info = info

    def flush(self) -> RouterWindow:
        window = RouterWindow(
            timestamp=datetime.now(timezone.utc).isoformat(),
            sensor_id=self._sensor_id,
            window_ms=self._window_ms,
            observations=list(self._observations),
            router_info=dict(self._router_info),
        )
        self._observations.clear()
        return window


class RouterCSISensor(SensorBase):
    """Mini router sensor that captures WiFi environment data via CH340 serial.

    Operates in three modes depending on what the router supports:
    1. JSON mode: Router firmware outputs JSON lines (custom firmware)
    2. Shell mode: OpenWrt shell — polls iwinfo/iw for station data
    3. Passive mode: Listens for any serial output and parses what it can
    """

    def __init__(self) -> None:
        self._sensor_id: str = ""
        self._config: Dict[str, Any] = {}
        self._healthy: bool = False
        self._pending_window: Optional[RouterWindow] = None
        self._mode: str = "detect"  # detect, json, shell, passive, ssh
        self._port: str = "/dev/ttyUSB0"
        self._baud: int = 115200
        self._serial: Optional[Any] = None
        self._running = threading.Event()
        # SSH transport
        self._ssh_host: str = ""
        self._ssh_user: str = "root"
        self._ssh_password: str = ""
        self._ssh_opts: List[str] = [
            "-o", "StrictHostKeyChecking=no",
            "-o", "HostKeyAlgorithms=+ssh-rsa",
            "-o", "PubkeyAcceptedAlgorithms=+ssh-rsa",
            "-o", "ConnectTimeout=5",
        ]
        self._stats: Dict[str, int] = {
            "observations": 0,
            "polls": 0,
            "errors": 0,
            "reconnects": 0,
        }

    def configure(self, config: Dict[str, Any]) -> None:
        if "sensor_id" not in config:
            raise ValueError("Config must contain 'sensor_id'")
        self._sensor_id = config["sensor_id"]
        self._config = config
        self._port = config.get("port", "/dev/ttyUSB0")
        self._baud = config.get("baud", 115200)
        # SSH transport config
        self._ssh_host = config.get("ssh_host", "")
        self._ssh_user = config.get("ssh_user", "root")
        self._ssh_password = config.get("ssh_password", "")
        # Start unhealthy so connect() gets called by the poll loop
        self._healthy = False
        if self._ssh_host:
            logger.info("RouterCSISensor configured: %s via SSH %s@%s",
                         self._sensor_id, self._ssh_user, self._ssh_host)
        else:
            logger.info("RouterCSISensor configured: %s on %s @ %d",
                         self._sensor_id, self._port, self._baud)

    def feed_window(self, window: RouterWindow) -> None:
        self._pending_window = window

    def capture(self) -> Optional[SensorFrame]:
        window = self._pending_window
        if window is None:
            return None

        self._pending_window = None

        observations = [
            SensorObservation(
                mac=obs.mac,
                rssi_dbm=obs.rssi_dbm,
                channel=obs.channel,
                bandwidth=obs.bandwidth,
                frame_type="router_csi",
                ssid=obs.ssid or None,
                count=1,
            )
            for obs in window.observations
        ]

        return SensorFrame(
            version=1,
            timestamp=window.timestamp,
            sensor_id=window.sensor_id,
            sensor_type=SensorType.ROUTER_CSI,
            window_ms=window.window_ms,
            observations=observations,
            metadata={
                "source": "router_ch340",
                "mode": self._mode,
                "router_info": window.router_info,
                "router_summary": {
                    "total_observations": len(window.observations),
                    "unique_macs": len(set(o.mac for o in window.observations)),
                    "channels": list(set(o.channel for o in window.observations)),
                },
                "stats": dict(self._stats),
            },
        )

    def _ssh_exec(self, cmd: str) -> str:
        """Execute a command on the router via SSH using sshpass."""
        full_cmd = ["sshpass", "-p", self._ssh_password, "ssh"] + self._ssh_opts + [
            f"{self._ssh_user}@{self._ssh_host}", cmd
        ]
        try:
            result = subprocess.run(full_cmd, capture_output=True, text=True, timeout=10)
            return result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.debug("SSH exec error: %s", e)
            return ""

    def connect(self) -> bool:
        """Connect to the router via SSH or serial."""
        if self._ssh_host:
            return self._connect_ssh()
        return self._connect_serial()

    def _connect_ssh(self) -> bool:
        """Test SSH connectivity to the router."""
        output = self._ssh_exec("echo ok")
        if "ok" in output:
            self._mode = "ssh"
            self._healthy = True
            logger.info("Router connected via SSH to %s", self._ssh_host)
            return True
        logger.warning("SSH connection to %s failed", self._ssh_host)
        return False

    def _connect_serial(self) -> bool:
        """Connect to the router's serial interface and detect mode."""
        if not os.path.exists(self._port):
            logger.warning("Router port %s not found", self._port)
            return False

        if serial is None:
            logger.error("pyserial not installed, cannot use serial transport")
            return False

        # Try baud rates to find the right one
        for baud in ([self._baud] + ROUTER_BAUD_RATES):
            try:
                ser = serial.Serial(self._port, baud, timeout=2)
                time.sleep(0.3)
                ser.reset_input_buffer()

                # Send wake-up
                ser.write(b"\r\n")
                time.sleep(1.0)
                data = ser.read(ser.in_waiting or 256)

                if data:
                    text = data.decode("utf-8", errors="ignore").strip()
                    self._baud = baud
                    self._serial = ser

                    # Detect mode
                    if text.startswith("{"):
                        self._mode = "json"
                        logger.info("Router in JSON mode at %d baud", baud)
                    elif "#" in text or "$" in text or "root@" in text:
                        self._mode = "shell"
                        logger.info("Router in shell mode at %d baud", baud)
                    else:
                        self._mode = "passive"
                        logger.info("Router in passive mode at %d baud", baud)

                    self._healthy = True
                    return True

                ser.close()
            except serial.SerialException:
                continue

        # No response — try default and go passive
        try:
            self._serial = serial.Serial(self._port, self._baud, timeout=1)
            self._mode = "passive"
            self._healthy = True
            logger.info("Router connected (passive) on %s @ %d", self._port, self._baud)
            return True
        except serial.SerialException as e:
            logger.error("Cannot connect to router: %s", e)
            return False

    def poll(self) -> List[RouterObservation]:
        """Poll the router for current WiFi environment data."""
        if self._mode == "ssh":
            self._stats["polls"] += 1
            try:
                return self._poll_ssh()
            except Exception as e:
                self._stats["errors"] += 1
                logger.debug("SSH poll error: %s", e)
                return []

        if not self._serial or not self._serial.is_open:
            return []

        self._stats["polls"] += 1

        try:
            if self._mode == "json":
                return self._poll_json()
            elif self._mode == "shell":
                return self._poll_shell()
            else:
                return self._poll_passive()
        except Exception as e:
            self._stats["errors"] += 1
            logger.debug("Router poll error: %s", e)
            return []

    def _poll_ssh(self) -> List[RouterObservation]:
        """Poll router over SSH using MediaTek iwpriv commands."""
        observations = []

        # Trigger scan and get results
        scan_cmd = (
            "iwpriv ra0 set SiteSurvey=1; sleep 2; iwpriv ra0 get_site_survey 2>/dev/null; "
            "echo '===STATS==='; iwpriv ra0 stat 2>/dev/null | grep -E 'RSSI|Temp'"
        )
        output = self._ssh_exec(scan_cmd)
        if not output:
            return observations

        # Parse site survey — use regex to find BSSID and signal
        # Format: "Ch  SSID  LEN  BSSID  Security  Signal(%)  W-Mode  ExtCH  NT"
        # Example: "1   Os1   3   24:5a:4c:50:14:bf   WPA2PSK/AES  100  11b/g/n NONE In"
        survey_re = re.compile(
            r"^\s*(\d{1,2})\s+"           # channel
            r"(.{0,33}?)\s+"              # SSID (up to 33 chars)
            r"\d+\s+"                     # LEN
            r"([0-9a-fA-F:]{17})\s+"      # BSSID (full MAC)
            r"(\S+)\s+"                   # Security
            r"(\d+)\s+"                   # Signal %
            r"(.+)$"                      # rest (W-Mode, ExtCH, NT)
        )

        in_survey = False
        for line in output.split("\n"):
            if "===STATS===" in line:
                break
            if "BSSID" in line and "Ch" in line:
                in_survey = True
                continue
            if not in_survey or not line.strip():
                continue

            m = survey_re.match(line)
            if not m:
                continue

            try:
                channel = int(m.group(1))
                ssid = m.group(2).strip()
                bssid = m.group(3).lower()
                signal_pct = int(m.group(5))

                # Convert signal percentage to approximate dBm
                # MediaTek reports 0-100%, roughly maps to -100 to -30 dBm
                rssi_dbm = int(-100 + (signal_pct * 0.7)) if signal_pct > 0 else -100

                obs = RouterObservation(
                    mac=bssid,
                    rssi_dbm=rssi_dbm,
                    channel=channel,
                    bandwidth="20MHz",
                    ssid=ssid,
                    signal_quality=signal_pct,
                )
                observations.append(obs)
                self._stats["observations"] += 1
            except (ValueError, IndexError):
                continue

        return observations

    def _poll_json(self) -> List[RouterObservation]:
        """Read JSON lines from custom router firmware."""
        observations = []
        self._serial.reset_input_buffer()
        time.sleep(0.5)
        while self._serial.in_waiting:
            line = self._serial.readline()
            if not line:
                break
            try:
                text = line.decode("utf-8", errors="ignore").strip()
                if not text.startswith("{"):
                    continue
                data = json.loads(text)
                obs = RouterObservation(
                    mac=data.get("mac", ""),
                    rssi_dbm=int(data.get("rssi", -100)),
                    channel=int(data.get("ch", 0)),
                    bandwidth=data.get("bw", "20MHz"),
                    noise_floor=int(data.get("noise", -90)),
                    tx_rate=int(data.get("tx_rate", 0)),
                    rx_rate=int(data.get("rx_rate", 0)),
                    connected=bool(data.get("conn", False)),
                    ssid=data.get("ssid", ""),
                    signal_quality=int(data.get("quality", 0)),
                )
                observations.append(obs)
                self._stats["observations"] += 1
            except (json.JSONDecodeError, ValueError):
                continue
        return observations

    def _poll_shell(self) -> List[RouterObservation]:
        """Poll OpenWrt shell for iwinfo/iw station data."""
        observations = []

        # Get station list
        self._serial.write(b"iwinfo wlan0 assoclist 2>/dev/null\r\n")
        time.sleep(1.5)
        data = self._serial.read(self._serial.in_waiting or 4096)
        text = data.decode("utf-8", errors="ignore")

        # Parse iwinfo assoclist output
        # Format: "AA:BB:CC:DD:EE:FF  -55 dBm / -90 dBm (SNR 35)  120 ms ago"
        current_mac = ""
        for line in text.split("\n"):
            line = line.strip()
            if len(line) >= 17 and line[2] == ":" and line[5] == ":":
                parts = line.split()
                current_mac = parts[0]
                rssi = -100
                noise = -90
                for i, p in enumerate(parts):
                    if p == "dBm" and i > 0:
                        try:
                            rssi = int(parts[i - 1])
                        except ValueError:
                            pass
                        break

                obs = RouterObservation(
                    mac=current_mac,
                    rssi_dbm=rssi,
                    channel=0,
                    bandwidth="20MHz",
                    noise_floor=noise,
                    connected=True,
                )
                observations.append(obs)
                self._stats["observations"] += 1

        # Get channel info
        self._serial.write(b"iwinfo wlan0 info 2>/dev/null | grep -E 'Channel|Signal'\r\n")
        time.sleep(1.0)
        data = self._serial.read(self._serial.in_waiting or 1024)
        info_text = data.decode("utf-8", errors="ignore")

        channel = 0
        for line in info_text.split("\n"):
            if "Channel:" in line:
                try:
                    channel = int(line.split("Channel:")[1].strip().split()[0])
                except (ValueError, IndexError):
                    pass

        # Apply channel to all observations
        for obs in observations:
            obs.channel = channel

        return observations

    def _poll_passive(self) -> List[RouterObservation]:
        """Read whatever the router outputs and try to parse it."""
        observations = []
        self._serial.reset_input_buffer()
        time.sleep(1.0)
        data = self._serial.read(self._serial.in_waiting or 2048)
        if not data:
            return observations

        text = data.decode("utf-8", errors="ignore")
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            # Try JSON
            if line.startswith("{"):
                try:
                    d = json.loads(line)
                    if "mac" in d:
                        obs = RouterObservation(
                            mac=d.get("mac", ""),
                            rssi_dbm=int(d.get("rssi", -100)),
                            channel=int(d.get("ch", 0)),
                            bandwidth=d.get("bw", "20MHz"),
                        )
                        observations.append(obs)
                        self._stats["observations"] += 1
                except (json.JSONDecodeError, ValueError):
                    pass
        return observations

    def disconnect(self) -> None:
        if self._mode == "ssh":
            self._healthy = False
            logger.info("Router SSH disconnected")
            return
        if self._serial and self._serial.is_open:
            self._serial.close()
            self._serial = None
            logger.info("Router disconnected")

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "mode": self._mode,
            "port": self._port,
            "baud": self._baud,
            "connected": self._serial is not None and self._serial.is_open,
        }

    def health_check(self) -> bool:
        if not self._healthy:
            return False
        if self._mode == "ssh":
            return True
        if self._mode != "detect" and self._serial and not self._serial.is_open:
            self._healthy = False
        return self._healthy

    @property
    def sensor_id(self) -> str:
        return self._sensor_id

    @property
    def sensor_type(self) -> SensorType:
        return SensorType.ROUTER_CSI
