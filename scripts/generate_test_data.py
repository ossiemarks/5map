#!/usr/bin/env python3
"""Generate synthetic test data for integration testing.

Creates sample RSSI payloads, device fingerprints, and presence
sequences as JSON files for offline testing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def main():
    output_dir = Path("tests/integration/fixtures")
    output_dir.mkdir(parents=True, exist_ok=True)

    # RSSI observation windows
    from tests.integration.conftest import make_rssi_payload
    windows = [make_rssi_payload(num_observations=i + 3) for i in range(10)]
    with open(output_dir / "rssi_windows.json", "w") as f:
        json.dump(windows, f, indent=2)
    print(f"Generated {len(windows)} RSSI windows -> {output_dir}/rssi_windows.json")

    # Device fingerprints
    from ml.data.synthetic import generate_synthetic_device_data
    devices = generate_synthetic_device_data(num_devices=30)
    with open(output_dir / "device_fingerprints.json", "w") as f:
        json.dump(devices, f, indent=2, default=str)
    print(f"Generated {len(devices)} device fingerprints -> {output_dir}/device_fingerprints.json")

    # Presence sequences
    from ml.data.synthetic import generate_synthetic_presence_data
    sequences, labels = generate_synthetic_presence_data(num_sequences=20)
    presence_data = [{"sequence": seq, "label": label} for seq, label in zip(sequences, labels)]
    with open(output_dir / "presence_sequences.json", "w") as f:
        json.dump(presence_data, f, indent=2)
    print(f"Generated {len(presence_data)} presence sequences -> {output_dir}/presence_sequences.json")

    print("Done.")


if __name__ == "__main__":
    main()
