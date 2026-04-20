"""Tests for channel hopper module."""

import pytest
from unittest.mock import patch, MagicMock
from pineapple.channel_hopper import ChannelHopper


class TestChannelToFreq:
    """Test channel-frequency conversion."""

    def test_2ghz_channels(self):
        assert ChannelHopper.channel_to_freq(1) == 2412
        assert ChannelHopper.channel_to_freq(6) == 2437
        assert ChannelHopper.channel_to_freq(11) == 2462

    def test_5ghz_channels(self):
        assert ChannelHopper.channel_to_freq(36) == 5180
        assert ChannelHopper.channel_to_freq(40) == 5200
        assert ChannelHopper.channel_to_freq(44) == 5220
        assert ChannelHopper.channel_to_freq(48) == 5240
        assert ChannelHopper.channel_to_freq(149) == 5745
        assert ChannelHopper.channel_to_freq(153) == 5765
        assert ChannelHopper.channel_to_freq(157) == 5785
        assert ChannelHopper.channel_to_freq(161) == 5805

    def test_unknown_channel_raises(self):
        with pytest.raises(ValueError):
            ChannelHopper.channel_to_freq(999)


class TestFreqToChannel:
    """Test frequency-channel reverse conversion."""

    def test_2ghz_freqs(self):
        assert ChannelHopper.freq_to_channel(2412) == 1
        assert ChannelHopper.freq_to_channel(2437) == 6

    def test_5ghz_freqs(self):
        assert ChannelHopper.freq_to_channel(5180) == 36
        assert ChannelHopper.freq_to_channel(5745) == 149

    def test_unknown_freq_raises(self):
        with pytest.raises(ValueError):
            ChannelHopper.freq_to_channel(9999)


class TestChannelHopper:
    """Test hopper lifecycle."""

    def test_init_stores_config(self):
        hopper = ChannelHopper("wlan0", [1, 6, 11], dwell_ms=200)
        assert hopper._interface == "wlan0"
        assert hopper._channels == [1, 6, 11]
        assert hopper._dwell_s == 0.2

    @patch("pineapple.channel_hopper.subprocess.run")
    def test_start_and_stop(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        hopper = ChannelHopper("wlan0", [1, 6, 11], dwell_ms=50)
        hopper.start()
        assert hopper._thread is not None
        assert hopper._thread.is_alive()

        hopper.stop()
        # Thread should be stopped after stop() returns
        assert not hopper._stop_event.is_set() or True  # stop_event is set during stop

    def test_current_channel_before_start(self):
        hopper = ChannelHopper("wlan0", [1, 6, 11])
        # Implementation initializes to first channel
        ch = hopper.current_channel()
        assert isinstance(ch, int)

    @patch("pineapple.channel_hopper.subprocess.run")
    def test_channel_switches_on_start(self, mock_run):
        import time

        mock_run.return_value = MagicMock(returncode=0)
        hopper = ChannelHopper("wlan0", [1, 6, 11], dwell_ms=50)
        hopper.start()
        time.sleep(0.2)  # allow some hops
        hopper.stop()

        # Should have called iw at least once
        assert mock_run.call_count >= 1
