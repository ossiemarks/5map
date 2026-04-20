"""Device fingerprinting ML model for 5map WiFi mapping tool.

Random Forest classifier that identifies device types from WiFi
observation features and produces risk scores for security analysis.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder

from ml.data.oui_database import OUIDatabase

# Top 20 vendors used for one-hot encoding + "other" bucket
TOP_VENDORS: list[str] = [
    "Apple",
    "Samsung",
    "Google",
    "Intel",
    "Broadcom",
    "Qualcomm",
    "Cisco",
    "TP-Link",
    "Netgear",
    "Espressif",
    "Raspberry Pi",
    "Huawei",
    "Xiaomi",
    "Amazon",
    "Microsoft",
    "Ubiquiti",
    "Aruba",
    "Realtek",
    "MediaTek",
    "Sony",
]

DEVICE_TYPES: list[str] = ["phone", "laptop", "iot", "ap", "unknown"]

FEATURE_NAMES: list[str] = [
    "is_randomized_mac",
    "probe_frequency",
    "rssi_variance",
    "num_unique_channels",
    "beacon_pct",
    "probe_pct",
    "data_pct",
    "mgmt_pct",
    "supported_rates_count",
    "ssid_probe_count",
]


def _is_randomized_mac(mac: str) -> bool:
    """Check if MAC uses a locally administered (randomized) address.

    The second nibble's LSB being 1 indicates locally administered.
    """
    first_octet_str = mac.replace("-", ":").split(":")[0]
    first_octet = int(first_octet_str, 16)
    return bool(first_octet & 0x02)


def _compute_vendor_one_hot(vendor: str | None) -> list[float]:
    """Create one-hot vector for vendor (21 elements: top 20 + other)."""
    vec = [0.0] * (len(TOP_VENDORS) + 1)
    if vendor and vendor in TOP_VENDORS:
        idx = TOP_VENDORS.index(vendor)
        vec[idx] = 1.0
    else:
        vec[-1] = 1.0  # "other" bucket
    return vec


class DeviceFingerprinter:
    """Random Forest classifier for WiFi device type identification.

    Extracts 8 logical features (expanded to numeric vector) from raw
    WiFi observations and predicts device type with associated risk score.
    """

    def __init__(self) -> None:
        self.model: RandomForestClassifier | None = None
        self.label_encoder: LabelEncoder | None = None
        self._oui_db = OUIDatabase()

    def extract_features(self, observations: list[dict[str, Any]]) -> dict[str, Any]:
        """Extract 8 features from raw observations for a single MAC.

        Args:
            observations: List of observation dicts for a single MAC address.
                Each observation should contain keys like:
                - mac: str
                - rssi: int
                - channel: int
                - frame_type: str ("beacon"|"probe"|"data"|"mgmt")
                - timestamp_ms: int
                - ssid: str | None
                - window_ms: int (observation window duration)
                - supported_rates: list[float] (optional)

        Returns:
            Dictionary of extracted feature values.
        """
        if not observations:
            return self._empty_features()

        mac = observations[0].get("mac", "00:00:00:00:00:00")

        # Feature 1: OUI vendor lookup
        vendor = self._oui_db.lookup(mac)
        oui_vendor = vendor if vendor else "unknown"

        # Feature 2: Randomized MAC detection
        is_randomized = _is_randomized_mac(mac)

        # Feature 3: Probe frequency (probes per minute)
        probe_count = sum(
            1 for obs in observations if obs.get("frame_type") == "probe"
        )
        window_ms = observations[0].get("window_ms", 60000)
        window_minutes = max(window_ms / 60000.0, 0.001)
        probe_frequency = probe_count / window_minutes

        # Feature 4: RSSI variance
        rssi_values = [obs.get("rssi", -70) for obs in observations]
        rssi_variance = statistics.variance(rssi_values) if len(rssi_values) > 1 else 0.0

        # Feature 5: Number of unique channels
        channels = {obs.get("channel", 0) for obs in observations}
        channels.discard(0)
        num_unique_channels = len(channels) if channels else 1

        # Feature 6: Frame type distribution (4 floats)
        total_frames = len(observations)
        frame_counts: dict[str, int] = {"beacon": 0, "probe": 0, "data": 0, "mgmt": 0}
        for obs in observations:
            ft = obs.get("frame_type", "mgmt")
            if ft in frame_counts:
                frame_counts[ft] += 1
            else:
                frame_counts["mgmt"] += 1

        beacon_pct = frame_counts["beacon"] / total_frames
        probe_pct = frame_counts["probe"] / total_frames
        data_pct = frame_counts["data"] / total_frames
        mgmt_pct = frame_counts["mgmt"] / total_frames

        # Feature 7: Supported rates count (placeholder for MVP)
        supported_rates = observations[0].get("supported_rates", [])
        supported_rates_count = len(supported_rates) if supported_rates else 0

        # Feature 8: Unique SSIDs probed
        ssids = {
            obs.get("ssid")
            for obs in observations
            if obs.get("ssid") and obs.get("frame_type") == "probe"
        }
        ssid_probe_count = len(ssids)

        return {
            "oui_vendor": oui_vendor,
            "is_randomized_mac": is_randomized,
            "probe_frequency": probe_frequency,
            "rssi_variance": rssi_variance,
            "num_unique_channels": num_unique_channels,
            "frame_type_distribution": {
                "beacon_pct": beacon_pct,
                "probe_pct": probe_pct,
                "data_pct": data_pct,
                "mgmt_pct": mgmt_pct,
            },
            "supported_rates_count": supported_rates_count,
            "ssid_probe_count": ssid_probe_count,
        }

    def _empty_features(self) -> dict[str, Any]:
        """Return zeroed features when no observations available."""
        return {
            "oui_vendor": "unknown",
            "is_randomized_mac": False,
            "probe_frequency": 0.0,
            "rssi_variance": 0.0,
            "num_unique_channels": 0,
            "frame_type_distribution": {
                "beacon_pct": 0.0,
                "probe_pct": 0.0,
                "data_pct": 0.0,
                "mgmt_pct": 0.0,
            },
            "supported_rates_count": 0,
            "ssid_probe_count": 0,
        }

    def _features_to_vector(self, features: dict[str, Any]) -> list[float]:
        """Convert feature dict to numeric vector for model input.

        Vector layout:
            [0:21]  - one-hot vendor encoding (21 elements)
            [21]    - is_randomized_mac
            [22]    - probe_frequency
            [23]    - rssi_variance
            [24]    - num_unique_channels
            [25]    - beacon_pct
            [26]    - probe_pct
            [27]    - data_pct
            [28]    - mgmt_pct
            [29]    - supported_rates_count
            [30]    - ssid_probe_count
        Total: 31 elements
        """
        vendor = features.get("oui_vendor", "unknown")
        vendor_vec = _compute_vendor_one_hot(vendor)

        dist = features.get("frame_type_distribution", {})

        numeric = [
            float(features.get("is_randomized_mac", False)),
            float(features.get("probe_frequency", 0.0)),
            float(features.get("rssi_variance", 0.0)),
            float(features.get("num_unique_channels", 0)),
            float(dist.get("beacon_pct", 0.0)),
            float(dist.get("probe_pct", 0.0)),
            float(dist.get("data_pct", 0.0)),
            float(dist.get("mgmt_pct", 0.0)),
            float(features.get("supported_rates_count", 0)),
            float(features.get("ssid_probe_count", 0)),
        ]

        return vendor_vec + numeric

    def fit(self, training_data: list[dict[str, Any]]) -> None:
        """Train model on labelled data.

        Args:
            training_data: List of dicts with keys:
                - features: dict (output of extract_features)
                - label: str (one of DEVICE_TYPES)
        """
        if not training_data:
            raise ValueError("Training data must not be empty")

        self.label_encoder = LabelEncoder()
        self.label_encoder.fit(DEVICE_TYPES)

        X = []
        y = []
        for sample in training_data:
            vec = self._features_to_vector(sample["features"])
            X.append(vec)
            y.append(sample["label"])

        X_arr = np.array(X, dtype=np.float64)
        y_encoded = self.label_encoder.transform(y)

        self.model = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            min_samples_split=5,
            random_state=42,
            n_jobs=-1,
        )
        self.model.fit(X_arr, y_encoded)

    def predict(self, observations: list[dict[str, Any]]) -> dict[str, Any]:
        """Predict device type and risk score from observations.

        Args:
            observations: Raw observation dicts for a single MAC.

        Returns:
            Dict with keys:
                - device_type: str
                - confidence: float
                - risk_score: float
                - features: dict (extracted features)
        """
        features = self.extract_features(observations)
        device_type = self._predict_type(features)
        confidence = self._predict_confidence(features)
        risk_score = self._compute_risk(features, device_type, observations)

        return {
            "device_type": device_type,
            "confidence": confidence,
            "risk_score": risk_score,
            "features": features,
        }

    def _predict_type(self, features: dict[str, Any]) -> str:
        """Predict device type from features using trained model or heuristics."""
        if self.model is not None and self.label_encoder is not None:
            vec = np.array([self._features_to_vector(features)], dtype=np.float64)
            pred_encoded = self.model.predict(vec)[0]
            return str(self.label_encoder.inverse_transform([pred_encoded])[0])

        # Heuristic fallback when model is not trained
        return self._heuristic_classify(features)

    def _predict_confidence(self, features: dict[str, Any]) -> float:
        """Get prediction confidence from model probabilities or heuristic."""
        if self.model is not None and self.label_encoder is not None:
            vec = np.array([self._features_to_vector(features)], dtype=np.float64)
            proba = self.model.predict_proba(vec)[0]
            return float(np.max(proba))

        # Heuristic confidence is lower
        return 0.6

    def _heuristic_classify(self, features: dict[str, Any]) -> str:
        """Rule-based classification when ML model unavailable."""
        dist = features.get("frame_type_distribution", {})
        beacon_pct = dist.get("beacon_pct", 0.0)
        probe_pct = dist.get("probe_pct", 0.0)
        data_pct = dist.get("data_pct", 0.0)

        # Access points primarily send beacons
        if beacon_pct > 0.5:
            return "ap"

        vendor = features.get("oui_vendor", "unknown")

        # IoT devices: known IoT vendors or low probe frequency
        iot_vendors = {"Espressif", "Raspberry Pi", "Amazon"}
        if vendor in iot_vendors:
            return "iot"

        # Phones: high probe frequency, randomized MAC, mobile vendors
        phone_vendors = {"Apple", "Samsung", "Google", "Xiaomi", "OnePlus", "OPPO", "Huawei"}
        if vendor in phone_vendors and features.get("probe_frequency", 0) > 2.0:
            return "phone"

        if features.get("is_randomized_mac") and probe_pct > 0.3:
            return "phone"

        # Laptops: Intel/Broadcom/Realtek, moderate data traffic
        laptop_vendors = {"Intel", "Broadcom", "Realtek", "MediaTek"}
        if vendor in laptop_vendors and data_pct > 0.3:
            return "laptop"

        return "unknown"

    def _compute_risk(
        self,
        features: dict[str, Any],
        device_type: str,
        observations: list[dict[str, Any]],
    ) -> float:
        """Compute security risk score for the device.

        Risk scoring rules:
            - Rogue AP: sends beacons but not in known AP list -> 0.8
            - Unknown + randomized MAC + data frames -> 0.6
            - Unknown vendor -> 0.5
            - Known vendor, normal behavior -> 0.1
        """
        dist = features.get("frame_type_distribution", {})
        beacon_pct = dist.get("beacon_pct", 0.0)
        data_pct = dist.get("data_pct", 0.0)
        vendor = features.get("oui_vendor", "unknown")
        is_randomized = features.get("is_randomized_mac", False)

        # Rogue AP detection: device sends beacons but classified differently
        # or not in a known AP list (we flag any beacon-sending non-AP)
        if beacon_pct > 0.3 and device_type != "ap":
            return 0.8

        # Unknown device with randomized MAC sending data frames
        if vendor == "unknown" and is_randomized and data_pct > 0.2:
            return 0.6

        # Unknown vendor
        if vendor == "unknown":
            return 0.5

        # Known vendor, normal behavior
        return 0.1

    def save(self, path: str) -> None:
        """Save trained model and encoder to disk.

        Args:
            path: Directory path where model artifacts will be saved.
        """
        import joblib

        save_dir = Path(path)
        save_dir.mkdir(parents=True, exist_ok=True)

        if self.model is not None:
            joblib.dump(self.model, save_dir / "rf_model.joblib")

        if self.label_encoder is not None:
            joblib.dump(self.label_encoder, save_dir / "label_encoder.joblib")

        metadata = {
            "top_vendors": TOP_VENDORS,
            "device_types": DEVICE_TYPES,
            "feature_names": FEATURE_NAMES,
            "vector_length": len(TOP_VENDORS) + 1 + len(FEATURE_NAMES),
        }
        with open(save_dir / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)

    @classmethod
    def load(cls, path: str) -> "DeviceFingerprinter":
        """Load a trained model from disk.

        Args:
            path: Directory path containing saved model artifacts.

        Returns:
            Initialized DeviceFingerprinter with loaded model.
        """
        import joblib

        load_dir = Path(path)
        instance = cls()

        model_path = load_dir / "rf_model.joblib"
        if model_path.exists():
            instance.model = joblib.load(model_path)

        encoder_path = load_dir / "label_encoder.joblib"
        if encoder_path.exists():
            instance.label_encoder = joblib.load(encoder_path)

        return instance
