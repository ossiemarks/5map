#!/usr/bin/env python3
"""Train all 5map ML models using synthetic data.

Usage:
    python -m ml.training.train_all --output-dir ./models/trained
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def train_env_mapper(output_dir: str) -> str:
    """Train environment mapper on synthetic data."""
    from ml.data.synthetic import generate_synthetic_rssi_grid
    from ml.models.env_mapper import EnvironmentMapper

    logger.info("Training environment mapper...")
    positions = generate_synthetic_rssi_grid(num_positions=30)
    mapper = EnvironmentMapper(grid_size=50)
    mapper.fit(positions)

    path = os.path.join(output_dir, "env_mapper.pkl")
    mapper.save(path)
    logger.info("Saved environment mapper to %s", path)
    return path


def train_device_fingerprinter(output_dir: str) -> str:
    """Train device fingerprinter on synthetic data."""
    from ml.data.synthetic import generate_synthetic_device_data
    from ml.models.device_fp import DeviceFingerprinter

    logger.info("Training device fingerprinter...")
    training_data = generate_synthetic_device_data(num_devices=100)
    fp = DeviceFingerprinter()
    fp.fit(training_data)

    path = os.path.join(output_dir, "device_fp.pkl")
    fp.save(path)
    logger.info("Saved device fingerprinter to %s", path)
    return path


def train_presence_detector(output_dir: str) -> str:
    """Train presence detector on synthetic data."""
    from ml.data.synthetic import generate_synthetic_presence_data
    from ml.models.presence_lstm import PresenceDetector

    logger.info("Training presence detector...")
    sequences, labels = generate_synthetic_presence_data(num_sequences=500)
    detector = PresenceDetector()
    detector.fit(sequences, labels, epochs=30)

    path = os.path.join(output_dir, "presence_lstm.pt")
    detector.save(path)
    logger.info("Saved presence detector to %s", path)
    return path


def main():
    parser = argparse.ArgumentParser(description="Train all 5map ML models")
    parser.add_argument(
        "--output-dir",
        default="./models/trained",
        help="Directory for saved model artifacts",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = {}
    paths["env_mapper"] = train_env_mapper(str(output_dir))
    paths["device_fp"] = train_device_fingerprinter(str(output_dir))
    paths["presence"] = train_presence_detector(str(output_dir))

    logger.info("All models trained successfully:")
    for name, path in paths.items():
        size = os.path.getsize(path) / 1024
        logger.info("  %s: %s (%.1f KB)", name, path, size)


if __name__ == "__main__":
    main()
