"""Zone classifier for indoor positioning using multi-sensor RSSI fingerprints.

Random Forest classifier that maps RSSI fingerprints from multiple sensors
to discrete room zones. Uses the BiCN feature engineering approach:
4 statistical features (mean, std, skewness, kurtosis) per sensor plus
raw RSSI values = 15-dimensional feature vector for 3 sensors.

Optionally includes an SVM for LOS/NLOS condition detection per the
BiCN paper's approach of using 5GHz signal features for NLOS classification.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import cross_val_score
from sklearn.preprocessing import LabelEncoder
from sklearn.svm import SVC

from ml.data.fingerprint_db import (
    FingerprintDatabase,
    RSSIFingerprint,
    ZoneGrid,
    ZonePrediction,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL_DIR = Path("models/trained/zone_classifier")


class ZoneClassifier:
    """Random Forest zone classifier with optional NLOS detection.

    Follows the same pattern as DeviceFingerprinter in device_fp.py:
    fit/predict/save/load interface with joblib serialization.
    """

    def __init__(
        self,
        zone_grid: ZoneGrid | None = None,
        sensor_ids: list[str] | None = None,
        n_estimators: int = 100,
    ) -> None:
        self.zone_grid = zone_grid or ZoneGrid()
        self.sensor_ids = sensor_ids or []
        self.n_estimators = n_estimators
        self._rf: RandomForestClassifier | None = None
        self._label_encoder: LabelEncoder | None = None
        self._nlos_svm: SVC | None = None
        self._feature_names: list[str] = []
        self._trained = False

    def fit(
        self,
        X: list[list[float]] | np.ndarray,
        y: list[str],
        sensor_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Train the zone classifier.

        Args:
            X: Feature matrix (N x 15 for 3 sensors).
            y: Zone ID labels.
            sensor_ids: Sensor IDs for feature naming.

        Returns:
            Training metrics dict.
        """
        if sensor_ids:
            self.sensor_ids = sensor_ids

        X_arr = np.array(X, dtype=np.float64)
        if X_arr.ndim == 1:
            X_arr = X_arr.reshape(1, -1)

        # Build feature names
        self._feature_names = []
        for sid in self.sensor_ids:
            self._feature_names.append(f"rssi_{sid}")
        for sid in self.sensor_ids:
            for feat in ["mean", "std", "skewness", "kurtosis"]:
                self._feature_names.append(f"{feat}_{sid}")

        # Encode zone labels
        self._label_encoder = LabelEncoder()
        y_encoded = self._label_encoder.fit_transform(y)

        # Train Random Forest
        self._rf = RandomForestClassifier(
            n_estimators=self.n_estimators,
            max_depth=10,
            min_samples_leaf=3,
            random_state=42,
            n_jobs=-1,
        )
        self._rf.fit(X_arr, y_encoded)

        # Cross-validation score
        cv_scores = cross_val_score(
            self._rf, X_arr, y_encoded, cv=min(5, len(set(y))), scoring="accuracy"
        )

        self._trained = True

        metrics = {
            "n_samples": len(y),
            "n_zones": len(set(y)),
            "n_features": X_arr.shape[1],
            "cv_accuracy_mean": float(np.mean(cv_scores)),
            "cv_accuracy_std": float(np.std(cv_scores)),
            "feature_importances": dict(
                zip(self._feature_names, self._rf.feature_importances_.tolist())
            ),
        }

        logger.info(
            "ZoneClassifier trained: %d samples, %d zones, CV accuracy: %.3f +/- %.3f",
            metrics["n_samples"],
            metrics["n_zones"],
            metrics["cv_accuracy_mean"],
            metrics["cv_accuracy_std"],
        )

        return metrics

    def predict(self, features: list[float]) -> ZonePrediction:
        """Predict zone from a feature vector.

        Args:
            features: 15-dim feature vector (3 RSSI + 12 statistical).

        Returns:
            ZonePrediction with zone_id, confidence, and zone center coords.
        """
        if not self._trained or self._rf is None:
            return ZonePrediction(zone_id="unknown", confidence=0.0)

        X = np.array([features], dtype=np.float64)
        proba = self._rf.predict_proba(X)[0]
        pred_idx = int(np.argmax(proba))
        confidence = float(proba[pred_idx])

        zone_id = self._label_encoder.inverse_transform([pred_idx])[0]
        zone_center = self.zone_grid.zone_center(zone_id)

        return ZonePrediction(
            zone_id=zone_id,
            confidence=confidence,
            zone_center=zone_center,
        )

    def predict_batch(
        self, X: list[list[float]]
    ) -> list[ZonePrediction]:
        """Predict zones for multiple feature vectors."""
        return [self.predict(features) for features in X]

    def save(self, model_dir: str | Path = DEFAULT_MODEL_DIR) -> None:
        """Save model artifacts to disk."""
        model_dir = Path(model_dir)
        model_dir.mkdir(parents=True, exist_ok=True)

        joblib.dump(self._rf, model_dir / "rf_model.joblib")
        joblib.dump(self._label_encoder, model_dir / "label_encoder.joblib")

        metadata = {
            "sensor_ids": self.sensor_ids,
            "feature_names": self._feature_names,
            "zone_grid": self.zone_grid.to_dict(),
            "n_estimators": self.n_estimators,
            "n_zones": len(self._label_encoder.classes_) if self._label_encoder else 0,
            "zones": list(self._label_encoder.classes_) if self._label_encoder else [],
        }
        with open(model_dir / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)

        logger.info("ZoneClassifier saved to %s", model_dir)

    @classmethod
    def load(cls, model_dir: str | Path = DEFAULT_MODEL_DIR) -> ZoneClassifier:
        """Load model artifacts from disk."""
        model_dir = Path(model_dir)

        with open(model_dir / "metadata.json") as f:
            metadata = json.load(f)

        grid_data = metadata["zone_grid"]
        zone_grid = ZoneGrid(
            room_width=grid_data["room_width"],
            room_depth=grid_data["room_depth"],
            zones_x=grid_data["zones_x"],
            zones_y=grid_data["zones_y"],
        )

        classifier = cls(
            zone_grid=zone_grid,
            sensor_ids=metadata["sensor_ids"],
            n_estimators=metadata.get("n_estimators", 100),
        )
        classifier._rf = joblib.load(model_dir / "rf_model.joblib")
        classifier._label_encoder = joblib.load(model_dir / "label_encoder.joblib")
        classifier._feature_names = metadata["feature_names"]
        classifier._trained = True

        logger.info(
            "ZoneClassifier loaded from %s (%d zones)",
            model_dir,
            len(classifier._label_encoder.classes_),
        )

        return classifier
