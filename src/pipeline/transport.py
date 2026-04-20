"""Abstract transport layer for streaming sensor data to backends.

Provides a common interface for MQTT, Kinesis, or other transport
mechanisms. The Pineapple uses MQTT; future cloud-native deployments
may use Kinesis directly.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from src.sensors.base import SensorFrame

logger = logging.getLogger(__name__)


class TransportBase(ABC):
    """Abstract transport for sending sensor frames to backends."""

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to the backend."""

    @abstractmethod
    def send(self, frames: List[SensorFrame]) -> bool:
        """Send a batch of frames to the backend.

        Args:
            frames: List of sensor frames to send.

        Returns:
            True if all frames were accepted for delivery.
        """

    @abstractmethod
    def disconnect(self) -> None:
        """Gracefully disconnect from the backend."""

    @abstractmethod
    def is_healthy(self) -> bool:
        """Check if the transport connection is alive."""


class MQTTSensorTransport(TransportBase):
    """Adapter wrapping the Pineapple MQTTTransport for SensorFrames.

    Bridges the generic SensorFrame format with the Pineapple-specific
    MQTT transport that expects ObservationWindow payloads.
    """

    def __init__(self, mqtt_transport: Any) -> None:
        """Wrap an existing MQTTTransport instance.

        Args:
            mqtt_transport: A pineapple.transport.mqtt_client.MQTTTransport instance.
        """
        self._mqtt = mqtt_transport

    def connect(self) -> None:
        self._mqtt.connect()

    def send(self, frames: List[SensorFrame]) -> bool:
        all_ok = True
        for frame in frames:
            payload = self._serialize_frame(frame)
            try:
                topic = f"5map/{frame.sensor_type.value}/{frame.sensor_id}"
                result = self._mqtt._client.publish(
                    topic,
                    json.dumps(payload),
                    qos=1,
                )
                if result.rc != 0:
                    all_ok = False
                    logger.warning("MQTT publish failed for frame: rc=%d", result.rc)
            except Exception as e:
                logger.error("Failed to send frame: %s", e)
                all_ok = False
        return all_ok

    def disconnect(self) -> None:
        self._mqtt.flush()
        self._mqtt.disconnect()

    def is_healthy(self) -> bool:
        return self._mqtt.is_healthy()

    @staticmethod
    def _serialize_frame(frame: SensorFrame) -> Dict[str, Any]:
        """Convert SensorFrame to JSON-serializable dict."""
        data = dataclasses.asdict(frame)
        # Convert SensorType enum to string
        data["sensor_type"] = frame.sensor_type.value
        return data
