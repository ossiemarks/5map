"""MQTT transport for streaming RSSI observation windows to AWS IoT Core.

Provides a thread-safe, non-blocking publisher with automatic reconnection
using exponential backoff. Designed for use on WiFi Pineapple Mark VII
hardware streaming data to the 5map cloud pipeline.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import signal
import ssl
import threading
import time
from datetime import datetime
from queue import Empty, Full, Queue
from typing import Any, Dict, Optional

import paho.mqtt.client as mqtt

from pineapple.parsers.rssi_parser import ObservationWindow

logger = logging.getLogger(__name__)

_DEFAULT_BACKOFF_START: float = 1.0
_DEFAULT_BACKOFF_MAX: float = 30.0
_DEFAULT_BACKOFF_FACTOR: float = 2.0
_FLUSH_DRAIN_TIMEOUT: float = 10.0
_PUBLISH_LOOP_INTERVAL: float = 0.05


class MQTTTransportError(Exception):
    """Raised when the MQTT transport encounters a fatal error."""


class MQTTTransport:
    """Non-blocking MQTT publisher for AWS IoT Core.

    Accepts ObservationWindow dataclass instances via ``publish()``, serialises
    them to JSON, and delivers them over a TLS-authenticated MQTT connection.
    Publishing is decoupled from the caller thread via an internal queue so
    that the capture thread is never blocked by network I/O.

    Args:
        config: Transport section of the parsed ``config.yaml``.
        sensor_id: Unique identifier for this sensor node.
    """

    def __init__(self, config: Dict[str, Any], sensor_id: str) -> None:
        mqtt_cfg = config["mqtt"]
        self._broker: str = mqtt_cfg["broker"]
        self._port: int = int(mqtt_cfg["port"])
        self._topic: str = mqtt_cfg["topic"].format(sensor_id=sensor_id)
        self._qos: int = int(mqtt_cfg.get("qos", 1))
        self._keepalive: int = int(mqtt_cfg.get("keepalive", 60))
        self._use_tls: bool = bool(mqtt_cfg.get("tls", True))
        self._sensor_id: str = sensor_id

        cert_dir: str = mqtt_cfg.get("cert_dir", "/etc/5map/certs")
        self._ca_cert: str = os.path.join(cert_dir, mqtt_cfg["ca_cert"])
        self._client_cert: str = os.path.join(cert_dir, mqtt_cfg["client_cert"])
        self._private_key: str = os.path.join(cert_dir, mqtt_cfg["private_key"])

        queue_max: int = int(config.get("queue_max_size", 1000))
        self._queue: Queue[Dict[str, Any]] = Queue(maxsize=queue_max)

        self._connected = threading.Event()
        self._shutting_down = threading.Event()
        self._publish_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        self._backoff: float = _DEFAULT_BACKOFF_START
        self._backoff_max: float = _DEFAULT_BACKOFF_MAX

        self._client: mqtt.Client = mqtt.Client(
            client_id=f"5map-{sensor_id}",
            clean_session=True,
            protocol=mqtt.MQTTv311,
        )
        self._configure_tls()
        self._register_callbacks()
        self._install_signal_handlers()

    def _configure_tls(self) -> None:
        """Set up mutual TLS authentication for AWS IoT Core."""
        if not self._use_tls:
            return

        for path, label in [
            (self._ca_cert, "CA certificate"),
            (self._client_cert, "client certificate"),
            (self._private_key, "private key"),
        ]:
            if not os.path.isfile(path):
                raise MQTTTransportError(f"{label} not found: {path}")

        self._client.tls_set(
            ca_certs=self._ca_cert,
            certfile=self._client_cert,
            keyfile=self._private_key,
            cert_reqs=ssl.CERT_REQUIRED,
            tls_version=ssl.PROTOCOL_TLSv1_2,
        )

    def _register_callbacks(self) -> None:
        """Wire up paho-mqtt v1.x lifecycle callbacks."""
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_publish = self._on_publish

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Dict[str, int],
        rc: int,
    ) -> None:
        if rc == 0:
            logger.info("Connected to %s:%d", self._broker, self._port)
            self._connected.set()
            self._backoff = _DEFAULT_BACKOFF_START
        else:
            logger.error("Connection refused (rc=%d): %s", rc, mqtt.connack_string(rc))
            self._connected.clear()

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        rc: int,
    ) -> None:
        self._connected.clear()
        if rc != 0:
            logger.warning("Unexpected disconnect (rc=%d), will reconnect", rc)
            if not self._shutting_down.is_set():
                self._schedule_reconnect()

    def _on_publish(
        self,
        client: mqtt.Client,
        userdata: Any,
        mid: int,
    ) -> None:
        logger.debug("Message %d acknowledged by broker", mid)

    def _schedule_reconnect(self) -> None:
        """Spawn a one-shot thread that reconnects with exponential backoff."""
        thread = threading.Thread(
            target=self._reconnect_loop,
            name="mqtt-reconnect",
            daemon=True,
        )
        thread.start()

    def _reconnect_loop(self) -> None:
        """Attempt reconnection with exponential backoff until success or shutdown."""
        while not self._shutting_down.is_set():
            wait = self._backoff
            logger.info("Reconnecting in %.1fs ...", wait)
            if self._shutting_down.wait(timeout=wait):
                break
            try:
                self._client.reconnect()
                logger.info("Reconnect succeeded")
                return
            except (OSError, mqtt.MQTTException) as exc:
                logger.warning("Reconnect failed: %s", exc)
                self._backoff = min(self._backoff * _DEFAULT_BACKOFF_FACTOR, self._backoff_max)

    def _install_signal_handlers(self) -> None:
        """Register SIGTERM handler for graceful shutdown from the main thread."""
        try:
            signal.signal(signal.SIGTERM, self._handle_sigterm)
        except (OSError, ValueError):
            # signal() can only be called from the main thread; ignore otherwise
            pass

    def _handle_sigterm(self, signum: int, frame: Any) -> None:
        logger.info("SIGTERM received, initiating graceful shutdown")
        self.disconnect()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Establish connection to the MQTT broker and start the publish loop.

        Raises:
            MQTTTransportError: If the initial connection attempt fails.
        """
        logger.info("Connecting to %s:%d (topic=%s)", self._broker, self._port, self._topic)
        try:
            self._client.connect(self._broker, self._port, self._keepalive)
        except (OSError, mqtt.MQTTException) as exc:
            raise MQTTTransportError(f"Initial connection failed: {exc}") from exc

        self._client.loop_start()

        if not self._connected.wait(timeout=10.0):
            self._client.loop_stop()
            raise MQTTTransportError(
                f"Timed out waiting for CONNACK from {self._broker}:{self._port}"
            )

        self._publish_thread = threading.Thread(
            target=self._publish_loop,
            name="mqtt-publish",
            daemon=True,
        )
        self._publish_thread.start()
        logger.info("MQTT transport ready")

    def publish(self, window: ObservationWindow) -> bool:
        """Enqueue an ObservationWindow for asynchronous publishing.

        This method is thread-safe and non-blocking. If the internal queue is
        full the observation is dropped and a warning is logged.

        Args:
            window: The observation window to publish.

        Returns:
            True if the window was enqueued, False if the queue was full.
        """
        if self._shutting_down.is_set():
            logger.warning("Transport is shutting down, rejecting publish")
            return False

        payload = self._serialise(window)
        try:
            self._queue.put_nowait(payload)
            return True
        except Full:
            logger.warning(
                "Send queue full (%d items), dropping observation window",
                self._queue.qsize(),
            )
            return False

    def disconnect(self) -> None:
        """Flush the remaining queue and tear down the connection cleanly."""
        if self._shutting_down.is_set():
            return
        self._shutting_down.set()
        logger.info("Disconnecting MQTT transport")

        self.flush()

        if self._publish_thread is not None:
            self._publish_thread.join(timeout=5.0)

        try:
            self._client.loop_stop()
            self._client.disconnect()
        except (OSError, mqtt.MQTTException) as exc:
            logger.warning("Error during disconnect: %s", exc)

        self._connected.clear()
        logger.info("MQTT transport disconnected")

    def is_healthy(self) -> bool:
        """Return whether the MQTT connection is currently established.

        Returns:
            True if the broker connection is alive and the transport is not
            shutting down.
        """
        return self._connected.is_set() and not self._shutting_down.is_set()

    def flush(self) -> None:
        """Drain and publish all remaining items in the send queue.

        Blocks until the queue is empty or a timeout of 10 seconds is reached.
        """
        deadline = time.monotonic() + _FLUSH_DRAIN_TIMEOUT
        flushed = 0
        while time.monotonic() < deadline:
            try:
                payload = self._queue.get_nowait()
            except Empty:
                break
            self._do_publish(payload)
            flushed += 1
        if flushed:
            logger.info("Flushed %d queued messages", flushed)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _publish_loop(self) -> None:
        """Background loop that drains the send queue and publishes messages."""
        while not self._shutting_down.is_set():
            try:
                payload = self._queue.get(timeout=_PUBLISH_LOOP_INTERVAL)
            except Empty:
                continue
            self._do_publish(payload)

    def _do_publish(self, payload: Dict[str, Any]) -> None:
        """Publish a single serialised payload to the configured topic."""
        if not self._connected.is_set():
            logger.debug("Not connected, re-queuing message")
            try:
                self._queue.put_nowait(payload)
            except Full:
                logger.warning("Queue full while re-queuing, message dropped")
            return

        try:
            message = json.dumps(payload, default=str)
            info = self._client.publish(self._topic, message, qos=self._qos)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                logger.warning("Publish returned rc=%d", info.rc)
        except (OSError, mqtt.MQTTException, ValueError) as exc:
            logger.error("Publish failed: %s", exc)

    @staticmethod
    def _serialise(window: ObservationWindow) -> Dict[str, Any]:
        """Convert an ObservationWindow dataclass to a JSON-friendly dict.

        Handles nested dataclasses, datetime objects, and optional fields.
        """
        data = dataclasses.asdict(window)
        _convert_datetimes(data)
        return data


def _convert_datetimes(obj: Any) -> None:
    """Recursively convert datetime values to ISO-8601 strings in-place."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, datetime):
                obj[key] = value.isoformat()
            elif isinstance(value, (dict, list)):
                _convert_datetimes(value)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            if isinstance(value, datetime):
                obj[i] = value.isoformat()
            elif isinstance(value, (dict, list)):
                _convert_datetimes(value)
