"""Tests for zone classifier and fingerprint data structures."""

import tempfile
from pathlib import Path

import numpy as np
import pytest

from ml.data.fingerprint_db import (
    FingerprintDatabase,
    RSSIFingerprint,
    ZoneGrid,
    ZonePrediction,
    compute_statistical_features,
)
from ml.data.synthetic import generate_synthetic_fingerprint_data
from ml.models.zone_classifier import ZoneClassifier


class TestStatisticalFeatures:
    def test_empty_returns_zeros(self):
        result = compute_statistical_features([])
        assert result == [0.0, 0.0, 0.0, 0.0]

    def test_single_value(self):
        result = compute_statistical_features([-50])
        assert result[0] == -50.0  # mean
        assert result[1] == 0.0    # std

    def test_known_distribution(self):
        values = [-50, -50, -50, -50, -50]
        result = compute_statistical_features(values)
        assert result[0] == -50.0  # mean
        assert abs(result[1]) < 0.01  # std ~0

    def test_variance_detected(self):
        values = [-40, -50, -60, -70, -80]
        result = compute_statistical_features(values)
        assert result[0] == -60.0  # mean
        assert result[1] > 10.0    # significant std


class TestZoneGrid:
    def test_creates_correct_zones(self):
        grid = ZoneGrid(5.0, 5.0, 3, 3)
        assert len(grid.zones) == 9
        assert "zone_0_0" in grid.zones
        assert "zone_2_2" in grid.zones

    def test_position_to_zone(self):
        grid = ZoneGrid(6.0, 6.0, 3, 3)
        assert grid.position_to_zone(0.5, 0.5) == "zone_0_0"
        assert grid.position_to_zone(5.5, 5.5) == "zone_2_2"
        assert grid.position_to_zone(3.0, 3.0) == "zone_1_1"

    def test_zone_center(self):
        grid = ZoneGrid(6.0, 6.0, 3, 3)
        cx, cy = grid.zone_center("zone_1_1")
        assert abs(cx - 3.0) < 0.01
        assert abs(cy - 3.0) < 0.01

    def test_zone_ids(self):
        grid = ZoneGrid(5.0, 5.0, 2, 2)
        assert len(grid.zone_ids) == 4


class TestFingerprintDatabase:
    def test_add_and_retrieve(self):
        db = FingerprintDatabase()
        fp = RSSIFingerprint(
            mac="AA:BB:CC:DD:EE:FF",
            timestamp="2026-01-01T00:00:00",
            sensor_rssi={"s1": -50, "s2": -60, "s3": -70},
            zone_id="zone_1_1",
        )
        db.add_fingerprint(fp)
        assert len(db.fingerprints) == 1
        assert "s1" in db.sensor_ids

    def test_statistical_features_accumulated(self):
        db = FingerprintDatabase()
        for i in range(5):
            fp = RSSIFingerprint(
                mac="AA:BB:CC:DD:EE:FF",
                timestamp=f"2026-01-01T00:00:{i:02d}",
                sensor_rssi={"s1": -50 - i, "s2": -60},
            )
            db.add_fingerprint(fp)

        features = db.get_statistical_features("AA:BB:CC:DD:EE:FF")
        assert "s1" in features
        assert len(features["s1"]) == 4  # mean, std, skew, kurt

    def test_build_feature_matrix(self):
        db = FingerprintDatabase()
        sids = ["s1", "s2", "s3"]
        db.sensor_ids = sids
        for i in range(10):
            fp = RSSIFingerprint(
                mac=f"AA:BB:CC:DD:EE:{i:02X}",
                timestamp=f"2026-01-01T00:00:{i:02d}",
                sensor_rssi={"s1": -50, "s2": -60, "s3": -70},
                zone_id=f"zone_{i % 3}_0",
            )
            db.add_fingerprint(fp)

        X, y = db.build_feature_matrix(sids)
        assert len(X) == 10
        assert len(X[0]) == 15  # 3 RSSI + 12 statistical
        assert len(y) == 10

    def test_save_load_roundtrip(self):
        db = FingerprintDatabase(ZoneGrid(5.0, 5.0, 3, 3))
        fp = RSSIFingerprint(
            mac="AA:BB:CC:DD:EE:FF",
            timestamp="2026-01-01T00:00:00",
            sensor_rssi={"s1": -50, "s2": -60},
            zone_id="zone_1_1",
        )
        db.add_fingerprint(fp)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "fp_db.json"
            db.save(path)
            loaded = FingerprintDatabase.load(path)
            assert len(loaded.fingerprints) == 1
            assert loaded.fingerprints[0].mac == "AA:BB:CC:DD:EE:FF"


class TestSyntheticData:
    def test_generates_correct_shape(self):
        X, y, sids = generate_synthetic_fingerprint_data(
            samples_per_zone=5, readings_per_sample=3
        )
        assert len(X) == 9 * 5  # 9 zones * 5 samples
        assert len(X[0]) == 15  # 3 RSSI + 12 stats
        assert len(y) == len(X)
        assert len(sids) == 3

    def test_zone_labels_present(self):
        X, y, _ = generate_synthetic_fingerprint_data(samples_per_zone=3)
        unique_zones = set(y)
        assert len(unique_zones) == 9  # 3x3 grid

    def test_rssi_in_valid_range(self):
        X, y, _ = generate_synthetic_fingerprint_data(samples_per_zone=10)
        for features in X:
            for rssi in features[:3]:  # First 3 are raw RSSI
                assert -100 <= rssi <= -10


class TestZoneClassifier:
    def test_fit_predict_roundtrip(self):
        X, y, sids = generate_synthetic_fingerprint_data(
            samples_per_zone=30, readings_per_sample=5
        )
        clf = ZoneClassifier(sensor_ids=sids)
        metrics = clf.fit(X, y, sensor_ids=sids)

        assert metrics["cv_accuracy_mean"] > 0.5
        assert metrics["n_zones"] == 9

        pred = clf.predict(X[0])
        assert pred.zone_id in set(y)
        assert 0 <= pred.confidence <= 1

    def test_save_load(self):
        X, y, sids = generate_synthetic_fingerprint_data(samples_per_zone=20)
        clf = ZoneClassifier(sensor_ids=sids)
        clf.fit(X, y, sensor_ids=sids)

        with tempfile.TemporaryDirectory() as tmpdir:
            clf.save(tmpdir)
            loaded = ZoneClassifier.load(tmpdir)
            pred = loaded.predict(X[0])
            assert pred.zone_id in set(y)

    def test_accuracy_above_threshold(self):
        """Zone classifier should achieve >60% accuracy on synthetic data.

        9-zone classification with noisy RSSI from 3 sensors is inherently
        limited. Real-world accuracy improves with calibration data.
        """
        X, y, sids = generate_synthetic_fingerprint_data(
            samples_per_zone=80, readings_per_sample=15, noise_std=2.0
        )
        clf = ZoneClassifier(sensor_ids=sids, n_estimators=200)
        metrics = clf.fit(X, y, sensor_ids=sids)
        assert metrics["cv_accuracy_mean"] > 0.60, (
            f"Accuracy {metrics['cv_accuracy_mean']:.3f} below 60% threshold"
        )
