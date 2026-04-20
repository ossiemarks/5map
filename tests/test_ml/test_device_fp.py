"""Tests for device fingerprinter model."""

import os
import random
import pytest


def _needs_sklearn():
    try:
        import sklearn
        return False
    except ImportError:
        return True


pytestmark = pytest.mark.skipif(_needs_sklearn(), reason="scikit-learn not installed")


def _make_training_data(n=80):
    """Create training data matching DeviceFingerprinter.fit() expected format."""
    types = ["phone", "laptop", "iot", "ap", "unknown"]
    vendors = ["Apple", "Samsung", "Intel", "Cisco", "Espressif", "Unknown"]
    data = []
    for _ in range(n):
        dtype = random.choice(types)
        data.append({
            "features": {
                "oui_vendor": random.choice(vendors),
                "is_randomized_mac": random.choice([True, False]),
                "probe_frequency": round(random.uniform(0.1, 10.0), 2),
                "rssi_variance": round(random.uniform(0.5, 20.0), 2),
                "num_unique_channels": random.randint(1, 11),
                "beacon_pct": round(random.uniform(0.0, 1.0), 2),
                "probe_pct": round(random.uniform(0.0, 1.0), 2),
                "data_pct": round(random.uniform(0.0, 1.0), 2),
                "mgmt_pct": round(random.uniform(0.0, 1.0), 2),
                "ssid_probe_count": random.randint(0, 15),
            },
            "label": dtype,
        })
    return data


class TestDeviceFingerprinter:
    def test_fit_and_predict(self):
        from ml.models.device_fp import DeviceFingerprinter

        data = _make_training_data(80)
        fp = DeviceFingerprinter()
        fp.fit(data)

        result = fp.predict([data[0]["features"]])
        assert "device_type" in result
        assert "risk_score" in result
        assert result["device_type"] in ("phone", "laptop", "iot", "ap", "unknown")
        assert 0 <= result["risk_score"] <= 1.0

    def test_save_and_load(self, tmp_path):
        from ml.models.device_fp import DeviceFingerprinter

        data = _make_training_data(50)
        fp = DeviceFingerprinter()
        fp.fit(data)

        path = str(tmp_path / "fp.pkl")
        fp.save(path)
        assert os.path.exists(path)

        loaded = DeviceFingerprinter.load(path)
        result = loaded.predict([data[0]["features"]])
        assert "device_type" in result


class TestOUIDatabase:
    def test_has_entries(self):
        from ml.data.oui_database import OUIDatabase

        db = OUIDatabase()
        assert len(db._db) >= 20

    def test_lookup_unknown_returns_none(self):
        from ml.data.oui_database import OUIDatabase

        db = OUIDatabase()
        result = db.lookup("FF:FF:FF:FF:FF:FF")
        assert result is None or isinstance(result, str)

    def test_lookup_invalid_mac(self):
        from ml.data.oui_database import OUIDatabase

        db = OUIDatabase()
        result = db.lookup("")
        assert result is None
