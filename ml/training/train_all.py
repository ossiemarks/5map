#!/usr/bin/env python3
"""Train all 5map ML models using synthetic data.

Bridges the synthetic data generators with model interfaces,
trains all 3 models, validates them, and optionally uploads
to the S3 model registry.

Usage:
    python -m ml.training.train_all --output-dir ./models/trained
    python -m ml.training.train_all --output-dir ./models/trained --upload
"""

from __future__ import annotations

import argparse
import logging
import os
import statistics
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


def train_env_mapper(output_dir: str) -> str:
    """Train environment mapper on synthetic RSSI grid data.

    Bridges synthetic data format (position tuple + rssi_readings dict)
    to EnvironmentMapper format (x, y, rssi_values list).
    """
    from ml.data.synthetic import generate_synthetic_rssi_grid
    from ml.models.env_mapper import EnvironmentMapper

    logger.info("Generating synthetic RSSI grid (50 positions, 6 APs)...")
    raw_positions = generate_synthetic_rssi_grid(
        num_positions=50, num_aps=6, grid_size=10.0, noise_std=3.0
    )

    positions = []
    for raw in raw_positions:
        x, y = raw["position"]
        rssi_values = list(raw["rssi_readings"].values())
        positions.append({"x": x, "y": y, "rssi_values": rssi_values})

    logger.info("Training environment mapper on %d positions...", len(positions))
    mapper = EnvironmentMapper(grid_size=50)
    mapper.fit(positions)

    result = mapper.predict_heatmap()
    logger.info(
        "  Heatmap: %dx%d, walls: %d, confidence: %.2f",
        len(result["heatmap"]),
        len(result["heatmap"][0]) if result["heatmap"] else 0,
        len(result["walls"]),
        result["confidence"],
    )

    path = os.path.join(output_dir, "env_mapper.pkl")
    mapper.save(path)
    logger.info("Saved environment mapper to %s", path)
    return path


def train_device_fingerprinter(output_dir: str) -> str:
    """Train device fingerprinter on synthetic device profiles.

    Bridges synthetic data format (mac_address, vendor_oui, probe_requests, etc.)
    to DeviceFingerprinter format (features dict + label).
    """
    from ml.data.synthetic import generate_synthetic_device_data
    from ml.models.device_fp import DeviceFingerprinter

    logger.info("Generating synthetic device profiles (200 devices)...")
    raw_devices = generate_synthetic_device_data(num_devices=200)

    fp = DeviceFingerprinter()
    training_data = []

    for device in raw_devices:
        signal = device["signal_pattern"]
        probes = device["probe_requests"]
        device_type = device["device_type"]

        # Map wearable -> phone for the 5-class model
        if device_type == "wearable":
            device_type = "phone"
        if device_type == "tablet":
            device_type = "laptop"

        # Simulate observation-like features from synthetic profile
        is_randomized = bool(int(device["mac_address"].split(":")[0], 16) & 0x02)
        probe_frequency = len(probes) * 2.0  # probes per minute estimate
        rssi_variance = signal["variance"]
        mobility = signal["mobility"]

        # Simulate frame type distribution based on device type
        if device_type == "ap":
            beacon_pct, probe_pct, data_pct, mgmt_pct = 0.7, 0.05, 0.2, 0.05
        elif device_type == "phone":
            beacon_pct, probe_pct, data_pct, mgmt_pct = 0.0, 0.4, 0.4, 0.2
        elif device_type == "laptop":
            beacon_pct, probe_pct, data_pct, mgmt_pct = 0.0, 0.15, 0.7, 0.15
        elif device_type == "iot":
            beacon_pct, probe_pct, data_pct, mgmt_pct = 0.1, 0.05, 0.8, 0.05
        else:
            beacon_pct, probe_pct, data_pct, mgmt_pct = 0.1, 0.2, 0.5, 0.2

        # Add noise to frame distributions
        rng = np.random.default_rng()
        noise = rng.uniform(-0.05, 0.05, 4)
        vals = np.clip([beacon_pct + noise[0], probe_pct + noise[1],
                       data_pct + noise[2], mgmt_pct + noise[3]], 0, 1)
        total = vals.sum()
        if total > 0:
            vals = vals / total

        vendor_oui = device["vendor_oui"]
        # Map synthetic OUIs to known vendors for one-hot encoding
        vendor_map = {
            "AA:BB:CC": "Apple", "11:22:33": "Samsung", "44:55:66": "Intel",
            "77:88:99": "Google", "DE:AD:BE": "Cisco", "CA:FE:00": "TP-Link",
            "B0:B0:B0": "Espressif", "F0:0D:00": "Broadcom",
        }
        vendor_name = vendor_map.get(vendor_oui, "unknown")

        features = {
            "oui_vendor": vendor_name,
            "is_randomized_mac": is_randomized,
            "probe_frequency": probe_frequency,
            "rssi_variance": rssi_variance,
            "num_unique_channels": int(rng.integers(1, 5)),
            "frame_type_distribution": {
                "beacon_pct": float(vals[0]),
                "probe_pct": float(vals[1]),
                "data_pct": float(vals[2]),
                "mgmt_pct": float(vals[3]),
            },
            "supported_rates_count": int(rng.integers(4, 12)),
            "ssid_probe_count": len(probes),
        }

        training_data.append({"features": features, "label": device_type})

    logger.info("Training device fingerprinter on %d samples...", len(training_data))
    fp.fit(training_data)

    # Validate with a sample prediction
    sample_obs = [{"mac": "AA:BB:CC:11:22:33", "rssi": -55, "channel": 6,
                    "frame_type": "probe", "ssid": "test_wifi", "window_ms": 60000}]
    pred = fp.predict(sample_obs)
    logger.info(
        "  Validation: type=%s, confidence=%.2f, risk=%.2f",
        pred["device_type"], pred["confidence"], pred["risk_score"],
    )

    path = os.path.join(output_dir, "device_fp")
    fp.save(path)
    logger.info("Saved device fingerprinter to %s/", path)
    return path


def train_presence_detector(output_dir: str) -> str:
    """Train presence LSTM on synthetic time-series data.

    Synthetic data format already matches PresenceDetector.fit() interface.
    """
    from ml.data.synthetic import generate_augmented_presence_data
    from ml.models.presence_lstm import PresenceDetector

    logger.info("Generating augmented presence data (500 base + augmented)...")
    sequences, labels = generate_augmented_presence_data(
        num_sequences=500, seq_len=5, noise_factor=0.15
    )
    logger.info("  Total training sequences: %d", len(sequences))

    label_dist = {}
    for label in labels:
        label_dist[label] = label_dist.get(label, 0) + 1
    logger.info("  Class distribution: %s", label_dist)

    logger.info("Training presence LSTM (50 epochs)...")
    detector = PresenceDetector()
    history = detector.fit(sequences, labels, epochs=50, batch_size=32)

    final_val_acc = history["val_accuracy"][-1]
    final_val_loss = history["val_loss"][-1]
    best_val_acc = max(history["val_accuracy"])
    logger.info(
        "  Final: val_loss=%.4f, val_acc=%.2f%%, best_acc=%.2f%%",
        final_val_loss, final_val_acc * 100, best_val_acc * 100,
    )
    logger.info("  Parameters: %d", detector.parameter_count())

    # Validate with a sample prediction
    sample_windows = [
        {"mean_rssi": -45.0, "rssi_variance": 3.0, "device_count": 5.0, "new_device_count": 0.0},
        {"mean_rssi": -44.0, "rssi_variance": 2.5, "device_count": 5.0, "new_device_count": 0.0},
        {"mean_rssi": -46.0, "rssi_variance": 4.0, "device_count": 5.0, "new_device_count": 0.0},
        {"mean_rssi": -43.0, "rssi_variance": 2.0, "device_count": 5.0, "new_device_count": 0.0},
        {"mean_rssi": -45.0, "rssi_variance": 3.5, "device_count": 5.0, "new_device_count": 0.0},
    ]
    pred = detector.predict(sample_windows)
    logger.info(
        "  Validation: event=%s, confidence=%.2f",
        pred["event"], pred["confidence"],
    )

    path = os.path.join(output_dir, "presence_lstm.pt")
    detector.save(path)
    logger.info("Saved presence detector to %s", path)
    return path


def upload_to_registry(paths: dict, version: int) -> None:
    """Upload trained models to S3 model registry."""
    try:
        from ml.serving.model_registry import ModelRegistry
        registry = ModelRegistry()

        for name, path in paths.items():
            logger.info("Uploading %s v%d to S3...", name, version)
            registry.upload(name, path, version)

        logger.info("All models uploaded to S3 (version %d)", version)
    except Exception as e:
        logger.error("S3 upload failed: %s", e)
        logger.info("Models saved locally. Upload manually when AWS is available.")


def main():
    parser = argparse.ArgumentParser(description="Train all 5map ML models")
    parser.add_argument(
        "--output-dir",
        default="./models/trained",
        help="Directory for saved model artifacts",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload trained models to S3 registry",
    )
    parser.add_argument(
        "--version",
        type=int,
        default=1,
        help="Model version number for registry",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("5map ML Model Training Pipeline")
    logger.info("Output: %s", output_dir.resolve())
    logger.info("=" * 60)

    paths = {}

    logger.info("\n[1/3] Environment Mapper (Gaussian Process)")
    paths["env_mapper"] = train_env_mapper(str(output_dir))

    logger.info("\n[2/3] Device Fingerprinter (Random Forest)")
    paths["device_fp"] = train_device_fingerprinter(str(output_dir))

    logger.info("\n[3/3] Presence Detector (LSTM)")
    paths["presence"] = train_presence_detector(str(output_dir))

    logger.info("\n" + "=" * 60)
    logger.info("All models trained successfully:")
    for name, path in paths.items():
        if os.path.isdir(path):
            total = sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file())
            size_str = f"{total / 1024:.1f} KB (directory)"
        else:
            size_str = f"{os.path.getsize(path) / 1024:.1f} KB"
        logger.info("  %s: %s (%s)", name, path, size_str)
    logger.info("=" * 60)

    if args.upload:
        upload_to_registry(paths, args.version)


if __name__ == "__main__":
    main()
