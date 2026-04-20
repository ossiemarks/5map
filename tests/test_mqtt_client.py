"""Tests for MQTT transport module."""

import json
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from pineapple.parsers.rssi_parser import Observation, ObservationWindow
from pineapple.transport.mqtt_client import MQTTTransport


def _make_test_config():
    return {
        "type": "mqtt",
        "mqtt": {
            "broker": "test.voicechatbox.com",
            "port": 8883,
            "topic": "5map/rssi/{sensor_id}",
            "qos": 1,
            "keepalive": 60,
            "tls": False,
            "cert_dir": "/tmp/certs",
            "ca_cert": "ca.pem",
            "client_cert": "cert.pem",
            "private_key": "key.pem",
        },
        "queue_max_size": 100,
    }


def _make_test_window():
    obs = Observation(
        mac="aa:bb:cc:dd:ee:ff",
        rssi_dbm=-45,
        noise_dbm=-90,
        channel=6,
        bandwidth="2.4GHz",
        frame_type="beacon",
        ssid="TestNet",
        is_randomized_mac=False,
        count=3,
    )
    return ObservationWindow(
        timestamp="2026-04-20T20:00:00+00:00",
        sensor_id="test-001",
        sensor_type="rssi",
        window_ms=1000,
        observations=[obs],
        position=None,
    )


class TestMQTTTransport:
    """Test MQTT transport."""

    @patch("pineapple.transport.mqtt_client.mqtt.Client")
    def test_init_creates_client(self, mock_client_cls):
        transport = MQTTTransport(_make_test_config(), "test-001")
        assert transport._sensor_id == "test-001"
        assert transport._topic == "5map/rssi/test-001"

    @patch("pineapple.transport.mqtt_client.mqtt.Client")
    def test_publish_queues_message(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.is_connected.return_value = True

        transport = MQTTTransport(_make_test_config(), "test-001")
        transport._connected = True

        window = _make_test_window()
        result = transport.publish(window)
        assert result is True

    @patch("pineapple.transport.mqtt_client.mqtt.Client")
    def test_publish_rejects_when_queue_full(self, mock_client_cls):
        config = _make_test_config()
        config["queue_max_size"] = 1

        transport = MQTTTransport(config, "test-001")
        transport._connected = True

        window = _make_test_window()
        # Fill the queue
        transport.publish(window)
        # Second should fail (queue full)
        result = transport.publish(window)
        assert result is False

    @patch("pineapple.transport.mqtt_client.mqtt.Client")
    def test_is_healthy_when_connected(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        transport = MQTTTransport(_make_test_config(), "test-001")
        transport._connected.set()
        assert transport.is_healthy() is True

    @patch("pineapple.transport.mqtt_client.mqtt.Client")
    def test_is_unhealthy_when_disconnected(self, mock_client_cls):
        transport = MQTTTransport(_make_test_config(), "test-001")
        transport._connected.clear()
        assert transport.is_healthy() is False

    @patch("pineapple.transport.mqtt_client.mqtt.Client")
    def test_topic_substitution(self, mock_client_cls):
        transport = MQTTTransport(_make_test_config(), "my-pineapple")
        assert transport._topic == "5map/rssi/my-pineapple"
