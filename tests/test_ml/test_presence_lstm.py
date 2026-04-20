"""Tests for presence detector LSTM model."""

import os
import pytest


def _needs_torch():
    try:
        import torch
        return False
    except ImportError:
        return True


pytestmark = pytest.mark.skipif(_needs_torch(), reason="PyTorch not installed")


class TestPresenceDetector:
    def test_predict_from_windows(self):
        from ml.models.presence_lstm import PresenceDetector

        detector = PresenceDetector()
        # Simulate 5 windows of "stationary" pattern
        windows = [
            {"mean_rssi": -50.0, "rssi_variance": 2.0, "device_count": 3, "new_device_count": 0}
            for _ in range(5)
        ]
        result = detector.predict(windows)
        assert "event" in result
        assert "confidence" in result
        assert result["event"] in ("empty", "stationary", "moving", "entry", "exit")
        assert 0 <= result["confidence"] <= 1.0

    def test_fit_on_synthetic_data(self):
        from ml.models.presence_lstm import PresenceDetector
        from ml.data.synthetic import generate_synthetic_presence_data

        sequences, labels = generate_synthetic_presence_data(num_sequences=50)
        detector = PresenceDetector()
        detector.fit(sequences, labels, epochs=5)

        # After training, predict should work
        result = detector.predict(sequences[0])
        assert "event" in result

    def test_save_and_load(self, tmp_path):
        from ml.models.presence_lstm import PresenceDetector

        detector = PresenceDetector()
        path = str(tmp_path / "presence.pt")
        detector.save(path)
        assert os.path.exists(path)

        loaded = PresenceDetector.load(path)
        windows = [
            {"mean_rssi": -60.0, "rssi_variance": 5.0, "device_count": 2, "new_device_count": 0}
            for _ in range(5)
        ]
        result = loaded.predict(windows)
        assert "event" in result

    def test_model_param_count(self):
        from ml.models.presence_lstm import PresenceDetector

        detector = PresenceDetector()
        total_params = sum(
            p.numel() for p in detector.model.parameters()
        )
        # Should be lightweight (~50K params)
        assert total_params < 200000, f"Model has {total_params} params, expected <200K"


class TestSyntheticPresenceData:
    def test_generate_data(self):
        from ml.data.synthetic import generate_synthetic_presence_data

        sequences, labels = generate_synthetic_presence_data(num_sequences=10)
        assert len(sequences) == 10
        assert len(labels) == 10
        assert all(len(seq) == 5 for seq in sequences)
        assert all(label in ("empty", "stationary", "moving", "entry", "exit") for label in labels)

    def test_window_structure(self):
        from ml.data.synthetic import generate_synthetic_presence_data

        sequences, _ = generate_synthetic_presence_data(num_sequences=1)
        window = sequences[0][0]
        assert "mean_rssi" in window
        assert "rssi_variance" in window
        assert "device_count" in window
        assert "new_device_count" in window
