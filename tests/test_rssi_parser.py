"""Tests for RSSI parser module."""

import pytest
from unittest.mock import MagicMock
from pineapple.parsers.rssi_parser import (
    Observation,
    ObservationWindow,
    parse_frame,
    is_locally_administered,
    get_channel_from_freq,
)


class TestIsLocallyAdministered:
    """Test MAC randomization detection."""

    def test_normal_mac_not_randomized(self):
        assert is_locally_administered("00:11:22:33:44:55") is False

    def test_randomized_mac_detected(self):
        # Bit 1 of first octet set = locally administered
        assert is_locally_administered("02:11:22:33:44:55") is True
        assert is_locally_administered("06:11:22:33:44:55") is True
        assert is_locally_administered("0a:11:22:33:44:55") is True
        assert is_locally_administered("0e:11:22:33:44:55") is True

    def test_broadcast_mac_is_locally_administered(self):
        assert is_locally_administered("ff:ff:ff:ff:ff:ff") is True

    def test_empty_mac_returns_false(self):
        assert is_locally_administered("") is False

    def test_invalid_mac_returns_false(self):
        assert is_locally_administered("not-a-mac") is False


class TestGetChannelFromFreq:
    """Test frequency to channel conversion."""

    def test_2ghz_channel_1(self):
        assert get_channel_from_freq(2412) == 1

    def test_2ghz_channel_6(self):
        assert get_channel_from_freq(2437) == 6

    def test_2ghz_channel_11(self):
        assert get_channel_from_freq(2462) == 11

    def test_5ghz_channel_36(self):
        assert get_channel_from_freq(5180) == 36

    def test_5ghz_channel_149(self):
        assert get_channel_from_freq(5745) == 149

    def test_unknown_freq_returns_zero(self):
        assert get_channel_from_freq(9999) == 0

    def test_zero_freq_returns_zero(self):
        assert get_channel_from_freq(0) == 0


class TestParseFrame:
    """Test scapy frame parsing."""

    def _make_mock_packet(
        self,
        addr2="aa:bb:cc:dd:ee:ff",
        rssi=-45,
        freq=2437,
        has_beacon=True,
        ssid="TestNetwork",
        noise=None,
    ):
        """Create a mock scapy packet with radiotap + Dot11 layers."""
        pkt = MagicMock()

        # Radiotap layer
        radiotap = MagicMock()
        radiotap.dBm_AntSignal = rssi
        radiotap.dBm_AntNoise = noise
        radiotap.ChannelFrequency = freq
        pkt.haslayer = lambda layer_name: True
        pkt.getlayer = lambda layer_name: radiotap if layer_name == "RadioTap" else None

        # Dot11 layer
        dot11 = MagicMock()
        dot11.addr2 = addr2
        dot11.type = 0  # management
        dot11.subtype = 8 if has_beacon else 4  # beacon or probe request

        # Dot11Beacon/Dot11Elt for SSID
        if ssid:
            elt = MagicMock()
            elt.ID = 0
            elt.info = ssid.encode()
        else:
            elt = None

        pkt.Dot11 = dot11
        pkt.RadioTap = radiotap

        # Make hasattr work for layers
        def mock_haslayer(layer):
            layer_name = layer if isinstance(layer, str) else layer.__name__
            return layer_name in ("RadioTap", "Dot11", "Dot11Beacon", "Dot11Elt")

        pkt.haslayer = mock_haslayer

        def mock_getlayer(layer):
            layer_name = layer if isinstance(layer, str) else layer.__name__
            if layer_name == "RadioTap":
                return radiotap
            if layer_name == "Dot11":
                return dot11
            if layer_name == "Dot11Elt":
                return elt
            return None

        pkt.getlayer = mock_getlayer

        return pkt

    def test_parse_valid_beacon(self):
        pkt = self._make_mock_packet()
        obs = parse_frame(pkt)
        assert obs is not None
        assert obs.mac == "aa:bb:cc:dd:ee:ff"
        assert obs.rssi_dbm == -45
        assert obs.channel == 6
        assert obs.bandwidth == "2.4GHz"

    def test_parse_returns_none_for_no_dot11(self):
        pkt = MagicMock()
        pkt.haslayer = lambda x: False
        assert parse_frame(pkt) is None

    def test_parse_no_source_mac_returns_none(self):
        """When addr2 is None and addr1 is broadcast, parse should return None."""
        pkt = MagicMock()
        radiotap = MagicMock()
        radiotap.dBm_AntSignal = -45
        radiotap.ChannelFrequency = 2437

        dot11 = MagicMock()
        dot11.addr2 = None
        dot11.addr1 = "ff:ff:ff:ff:ff:ff"
        dot11.type = 0
        dot11.subtype = 8

        from scapy.layers.dot11 import RadioTap, Dot11

        pkt.haslayer = lambda layer: True
        pkt.getlayer = lambda layer: radiotap if layer == RadioTap else dot11 if layer == Dot11 else None

        assert parse_frame(pkt) is None

    def test_parse_5ghz_bandwidth_detected(self):
        pkt = self._make_mock_packet(freq=5180)
        obs = parse_frame(pkt)
        assert obs is not None
        assert obs.bandwidth == "5GHz"
        assert obs.channel == 36

    def test_randomized_mac_flagged(self):
        pkt = self._make_mock_packet(addr2="02:bb:cc:dd:ee:ff")
        obs = parse_frame(pkt)
        assert obs is not None
        assert obs.is_randomized_mac is True

    def test_normal_mac_not_flagged(self):
        pkt = self._make_mock_packet(addr2="00:bb:cc:dd:ee:ff")
        obs = parse_frame(pkt)
        assert obs is not None
        assert obs.is_randomized_mac is False


class TestObservationWindow:
    """Test ObservationWindow dataclass."""

    def test_create_empty_window(self):
        window = ObservationWindow(
            timestamp="2026-04-20T20:00:00+00:00",
            sensor_id="test-001",
            sensor_type="rssi",
            window_ms=1000,
            observations=[],
            position=None,
        )
        assert len(window.observations) == 0
        assert window.sensor_type == "rssi"

    def test_create_window_with_observations(self):
        obs = Observation(
            mac="aa:bb:cc:dd:ee:ff",
            rssi_dbm=-45,
            noise_dbm=-90,
            channel=6,
            bandwidth="2.4GHz",
            frame_type="beacon",
            ssid="TestNet",
            is_randomized_mac=False,
            count=5,
        )
        window = ObservationWindow(
            timestamp="2026-04-20T20:00:00+00:00",
            sensor_id="test-001",
            sensor_type="rssi",
            window_ms=1000,
            observations=[obs],
            position={"x": 1.0, "y": 2.0, "label": "point_A"},
        )
        assert len(window.observations) == 1
        assert window.observations[0].mac == "aa:bb:cc:dd:ee:ff"
        assert window.position["label"] == "point_A"

    def test_window_serialization(self):
        """Ensure window can be serialized to JSON via dataclasses.asdict."""
        import dataclasses
        import json

        obs = Observation(
            mac="aa:bb:cc:dd:ee:ff",
            rssi_dbm=-45,
            noise_dbm=None,
            channel=6,
            bandwidth="2.4GHz",
            frame_type="beacon",
            ssid="TestNet",
            is_randomized_mac=False,
            count=1,
        )
        window = ObservationWindow(
            timestamp="2026-04-20T20:00:00+00:00",
            sensor_id="test-001",
            sensor_type="rssi",
            window_ms=1000,
            observations=[obs],
            position=None,
        )
        data = dataclasses.asdict(window)
        json_str = json.dumps(data)
        assert '"mac": "aa:bb:cc:dd:ee:ff"' in json_str
        assert '"rssi_dbm": -45' in json_str
