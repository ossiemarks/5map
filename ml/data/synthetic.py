"""Synthetic data generation for 5map ML model training.

Generates realistic synthetic RSSI, device fingerprint, and presence detection
training data. Designed for bootstrapping models before real-world data collection.
"""

from __future__ import annotations

import random
from typing import Any

import numpy as np


def generate_synthetic_rssi_grid(
    num_positions: int = 20,
    grid_size: float = 10.0,
    num_aps: int = 4,
    noise_std: float = 3.0,
) -> list[dict[str, Any]]:
    """Generate synthetic position-tagged RSSI data for environment mapper.

    Simulates a grid of measurement positions in a room with multiple
    access points. RSSI values follow log-distance path loss model with
    Gaussian noise.

    Args:
        num_positions: Number of measurement positions to generate.
        grid_size: Physical size of the area in meters (grid_size x grid_size).
        num_aps: Number of simulated access points.
        noise_std: Standard deviation of RSSI measurement noise (dBm).

    Returns:
        List of dictionaries, each containing:
            - position: (x, y) coordinates in meters.
            - rssi_readings: Dict mapping AP BSSID to RSSI value (dBm).
            - timestamp: Simulated measurement timestamp.
            - room_id: Assigned room identifier.
    """
    rng = np.random.default_rng()

    # Place access points at random positions
    ap_positions = rng.uniform(0, grid_size, size=(num_aps, 2))
    ap_bssids = [f"AA:BB:CC:DD:EE:{i:02X}" for i in range(num_aps)]
    ap_tx_power = rng.uniform(-30, -20, size=num_aps)  # dBm at 1 meter

    # Path loss exponent (typical indoor: 2.0-4.0)
    path_loss_exponent = 3.0

    # Generate measurement positions
    positions = rng.uniform(0.5, grid_size - 0.5, size=(num_positions, 2))

    results: list[dict[str, Any]] = []
    base_timestamp = 1700000000.0

    for idx, pos in enumerate(positions):
        rssi_readings: dict[str, float] = {}

        for ap_idx in range(num_aps):
            distance = np.linalg.norm(pos - ap_positions[ap_idx])
            distance = max(distance, 0.1)  # Avoid log(0)

            # Log-distance path loss model
            rssi = float(
                ap_tx_power[ap_idx] - 10 * path_loss_exponent * np.log10(distance)
                + rng.normal(0, noise_std)
            )
            rssi = max(-100.0, min(0.0, rssi))  # Clamp to valid range
            rssi_readings[ap_bssids[ap_idx]] = round(rssi, 1)

        # Assign room based on grid quadrant
        room_x = int(pos[0] / (grid_size / 2))
        room_y = int(pos[1] / (grid_size / 2))
        room_id = f"room_{room_x}_{room_y}"

        results.append({
            "position": (round(float(pos[0]), 2), round(float(pos[1]), 2)),
            "rssi_readings": rssi_readings,
            "timestamp": base_timestamp + idx * 2.0,
            "room_id": room_id,
        })

    return results


def generate_synthetic_device_data(
    num_devices: int = 50,
    num_vendors: int = 8,
) -> list[dict[str, Any]]:
    """Generate synthetic device fingerprint training data.

    Creates realistic device profiles with MAC addresses, vendor OUIs,
    probe request patterns, and behavioral characteristics for device
    classification model training.

    Args:
        num_devices: Number of synthetic device profiles to generate.
        num_vendors: Number of distinct device vendors to simulate.

    Returns:
        List of dictionaries, each containing:
            - mac_address: Randomized MAC address.
            - vendor_oui: First 3 octets identifying the vendor.
            - device_type: Category (phone, laptop, iot, tablet, wearable).
            - probe_requests: List of probed SSIDs.
            - signal_pattern: Typical RSSI behavior characteristics.
            - first_seen: Simulated first detection timestamp.
            - session_duration: Typical session length in seconds.
    """
    rng = np.random.default_rng()

    vendor_ouis = [
        "AA:BB:CC", "11:22:33", "44:55:66", "77:88:99",
        "DE:AD:BE", "CA:FE:00", "B0:B0:B0", "F0:0D:00",
    ][:num_vendors]

    device_types = ["phone", "laptop", "iot", "tablet", "wearable"]
    device_type_weights = [0.4, 0.25, 0.2, 0.1, 0.05]

    common_ssids = [
        "home_wifi", "office_net", "guest", "IoT_Network",
        "CoffeeShop_Free", "Airport_WiFi", "Hotel_Guest",
        "eduroam", "AndroidAP", "iPhone_Hotspot",
    ]

    results: list[dict[str, Any]] = []
    base_timestamp = 1700000000.0

    for i in range(num_devices):
        vendor_idx = rng.integers(0, num_vendors)
        oui = vendor_ouis[vendor_idx]
        mac_suffix = f"{rng.integers(0, 256):02X}:{rng.integers(0, 256):02X}:{rng.integers(0, 256):02X}"
        mac_address = f"{oui}:{mac_suffix}"

        device_type = rng.choice(device_types, p=device_type_weights)

        # Probe request patterns vary by device type
        num_probes = {
            "phone": rng.integers(2, 8),
            "laptop": rng.integers(1, 5),
            "iot": rng.integers(0, 2),
            "tablet": rng.integers(1, 4),
            "wearable": rng.integers(0, 2),
        }[device_type]

        probes = list(rng.choice(common_ssids, size=min(num_probes, len(common_ssids)), replace=False))

        # Signal pattern characteristics by type
        signal_patterns = {
            "phone": {"mean_rssi": float(rng.uniform(-70, -40)), "variance": float(rng.uniform(5, 25)), "mobility": "high"},
            "laptop": {"mean_rssi": float(rng.uniform(-65, -35)), "variance": float(rng.uniform(2, 10)), "mobility": "low"},
            "iot": {"mean_rssi": float(rng.uniform(-80, -50)), "variance": float(rng.uniform(1, 5)), "mobility": "static"},
            "tablet": {"mean_rssi": float(rng.uniform(-70, -40)), "variance": float(rng.uniform(3, 15)), "mobility": "medium"},
            "wearable": {"mean_rssi": float(rng.uniform(-75, -45)), "variance": float(rng.uniform(5, 20)), "mobility": "high"},
        }

        # Session duration varies by device type
        duration_ranges = {
            "phone": (60, 7200),
            "laptop": (300, 28800),
            "iot": (3600, 86400),
            "tablet": (120, 3600),
            "wearable": (30, 1800),
        }
        dur_min, dur_max = duration_ranges[device_type]

        results.append({
            "mac_address": mac_address,
            "vendor_oui": oui,
            "device_type": device_type,
            "probe_requests": probes,
            "signal_pattern": signal_patterns[device_type],
            "first_seen": base_timestamp + float(rng.uniform(0, 3600)),
            "session_duration": float(rng.uniform(dur_min, dur_max)),
        })

    return results


def generate_synthetic_presence_data(
    num_sequences: int = 200,
    seq_len: int = 5,
) -> tuple[list[list[dict[str, float]]], list[str]]:
    """Generate synthetic RSSI time-series with presence labels.

    Creates labelled training data for the PresenceLSTM model. Each sequence
    represents a sliding window of RSSI observations with a corresponding
    presence event label.

    Event generation logic:
        - empty: No devices, very low RSSI, zero counts.
        - stationary: Stable RSSI with consistent device count.
        - moving: Fluctuating RSSI with periodic variance pattern.
        - entry: RSSI jumps from absent to present, new_device_count > 0.
        - exit: RSSI drops from present to absent, device_count decreases.

    Args:
        num_sequences: Total number of labelled sequences to generate.
        seq_len: Number of 1-second windows per sequence.

    Returns:
        Tuple of (training_data, labels) where:
            - training_data: List of sequences, each a list of window dicts.
            - labels: List of presence event class names.
    """
    rng = np.random.default_rng()

    classes = ["empty", "stationary", "moving", "entry", "exit"]
    class_weights = [0.2, 0.25, 0.25, 0.15, 0.15]

    training_data: list[list[dict[str, float]]] = []
    labels: list[str] = []

    for _ in range(num_sequences):
        event_class = rng.choice(classes, p=class_weights)
        sequence = _generate_sequence_for_class(event_class, seq_len, rng)
        training_data.append(sequence)
        labels.append(event_class)

    return training_data, labels


def _generate_sequence_for_class(
    event_class: str,
    seq_len: int,
    rng: np.random.Generator,
) -> list[dict[str, float]]:
    """Generate a single RSSI sequence for a given presence class.

    Args:
        event_class: Target presence event class.
        seq_len: Number of time steps in the sequence.
        rng: NumPy random generator instance.

    Returns:
        List of observation window dictionaries.
    """
    sequence: list[dict[str, float]] = []

    if event_class == "empty":
        for _ in range(seq_len):
            sequence.append({
                "mean_rssi": float(rng.uniform(-100, -90)),
                "rssi_variance": float(rng.uniform(0, 2)),
                "device_count": 0.0,
                "new_device_count": 0.0,
            })

    elif event_class == "stationary":
        base_rssi = float(rng.uniform(-65, -35))
        device_count = float(rng.integers(1, 6))
        for _ in range(seq_len):
            sequence.append({
                "mean_rssi": base_rssi + float(rng.normal(0, 2)),
                "rssi_variance": float(rng.uniform(1, 5)),
                "device_count": device_count,
                "new_device_count": 0.0,
            })

    elif event_class == "moving":
        base_rssi = float(rng.uniform(-70, -40))
        device_count = float(rng.integers(1, 4))
        for t in range(seq_len):
            # Periodic RSSI fluctuation simulating movement
            rssi_shift = 10.0 * np.sin(2.0 * np.pi * t / seq_len)
            sequence.append({
                "mean_rssi": base_rssi + float(rssi_shift) + float(rng.normal(0, 3)),
                "rssi_variance": float(rng.uniform(10, 30)),
                "device_count": device_count,
                "new_device_count": 0.0,
            })

    elif event_class == "entry":
        device_count_start = float(rng.integers(0, 3))
        entry_point = rng.integers(1, max(2, seq_len - 1))
        for t in range(seq_len):
            if t < entry_point:
                # Before entry: low/no signal
                sequence.append({
                    "mean_rssi": float(rng.uniform(-95, -85)),
                    "rssi_variance": float(rng.uniform(0, 3)),
                    "device_count": device_count_start,
                    "new_device_count": 0.0,
                })
            else:
                # After entry: signal appears
                new_devices = 1.0 if t == entry_point else 0.0
                sequence.append({
                    "mean_rssi": float(rng.uniform(-65, -40)),
                    "rssi_variance": float(rng.uniform(5, 15)),
                    "device_count": device_count_start + 1.0,
                    "new_device_count": new_devices,
                })

    elif event_class == "exit":
        device_count_start = float(rng.integers(2, 6))
        exit_point = rng.integers(1, max(2, seq_len - 1))
        for t in range(seq_len):
            if t < exit_point:
                # Before exit: normal presence
                sequence.append({
                    "mean_rssi": float(rng.uniform(-60, -35)),
                    "rssi_variance": float(rng.uniform(3, 10)),
                    "device_count": device_count_start,
                    "new_device_count": 0.0,
                })
            else:
                # After exit: signal drops
                sequence.append({
                    "mean_rssi": float(rng.uniform(-95, -80)),
                    "rssi_variance": float(rng.uniform(0, 3)),
                    "device_count": device_count_start - 1.0,
                    "new_device_count": 0.0,
                })

    return sequence


def generate_augmented_presence_data(
    num_sequences: int = 500,
    seq_len: int = 5,
    noise_factor: float = 0.1,
    time_shift_prob: float = 0.3,
) -> tuple[list[list[dict[str, float]]], list[str]]:
    """Generate augmented presence data with noise injection and time shifting.

    Extends the base synthetic generator with data augmentation techniques
    for more robust model training.

    Args:
        num_sequences: Total number of sequences to generate.
        seq_len: Number of time steps per sequence.
        noise_factor: Scale factor for additive Gaussian noise augmentation.
        time_shift_prob: Probability of applying temporal shift augmentation.

    Returns:
        Tuple of (augmented_data, labels).
    """
    rng = np.random.default_rng()
    base_data, base_labels = generate_synthetic_presence_data(num_sequences, seq_len)

    augmented_data: list[list[dict[str, float]]] = []
    augmented_labels: list[str] = []

    for sequence, label in zip(base_data, base_labels):
        # Original
        augmented_data.append(sequence)
        augmented_labels.append(label)

        # Noise-augmented copy
        noisy_sequence: list[dict[str, float]] = []
        for window in sequence:
            noisy_sequence.append({
                "mean_rssi": window["mean_rssi"] + float(rng.normal(0, noise_factor * 5)),
                "rssi_variance": max(0.0, window["rssi_variance"] + float(rng.normal(0, noise_factor * 2))),
                "device_count": window["device_count"],
                "new_device_count": window["new_device_count"],
            })
        augmented_data.append(noisy_sequence)
        augmented_labels.append(label)

        # Time-shifted copy (with probability)
        if rng.random() < time_shift_prob and len(sequence) > 2:
            shift = rng.integers(1, max(2, len(sequence) // 2))
            shifted_sequence = sequence[shift:] + sequence[:shift]
            # Only keep if label still makes sense (stationary/moving/empty)
            if label in ("stationary", "moving", "empty"):
                augmented_data.append(shifted_sequence)
                augmented_labels.append(label)

    return augmented_data, augmented_labels


def generate_synthetic_fingerprint_data(
    room_width: float = 5.0,
    room_depth: float = 5.0,
    zones_x: int = 3,
    zones_y: int = 3,
    sensor_positions: list[tuple[float, float]] | None = None,
    sensor_ids: list[str] | None = None,
    samples_per_zone: int = 30,
    readings_per_sample: int = 5,
    noise_std: float = 3.0,
    nlos_probability: float = 0.3,
) -> tuple[list[list[float]], list[str], list[str]]:
    """Generate synthetic RSSI fingerprint data for zone classifier training.

    Simulates multi-sensor RSSI observations at positions throughout a room,
    applying log-distance path loss with LOS/NLOS variation per the BiCN paper.

    Args:
        room_width: Room width in metres.
        room_depth: Room depth in metres.
        zones_x: Number of zones along X axis.
        zones_y: Number of zones along Y axis.
        sensor_positions: (x, y) for each sensor. Defaults to 5map layout.
        sensor_ids: Sensor ID strings.
        samples_per_zone: Training samples per zone.
        readings_per_sample: RSSI readings averaged per sample (per BiCN: 20).
        noise_std: Gaussian noise std for RSSI (dBm).
        nlos_probability: Probability a sensor-position pair is NLOS.

    Returns:
        Tuple of (X, y, sensor_ids) where:
            X: Feature matrix (N x 15 for 3 sensors).
            y: Zone labels.
            sensor_ids: Sensor ID list used.
    """
    from ml.data.fingerprint_db import ZoneGrid, compute_statistical_features

    rng = np.random.default_rng()

    if sensor_positions is None:
        sensor_positions = [(0.5, 2.5), (4.5, 2.5), (2.5, 4.5)]
    if sensor_ids is None:
        sensor_ids = ["router-001", "esp32s2-001", "pineapple-001"]

    n_sensors = len(sensor_positions)
    tx_power = -30.0  # dBm at 1 metre reference
    path_loss_n_los = 2.0  # LOS path loss exponent
    path_loss_n_nlos = 3.5  # NLOS path loss exponent (walls, obstacles)

    grid = ZoneGrid(room_width, room_depth, zones_x, zones_y)

    X: list[list[float]] = []
    y: list[str] = []

    for zone_id, zone_info in grid.zones.items():
        cx, cy = zone_info["center"]
        zone_w = room_width / zones_x
        zone_h = room_depth / zones_y

        for _ in range(samples_per_zone):
            # Random position within zone
            px = cx + rng.uniform(-zone_w / 2 * 0.8, zone_w / 2 * 0.8)
            py = cy + rng.uniform(-zone_h / 2 * 0.8, zone_h / 2 * 0.8)

            features: list[float] = []
            all_stats: list[list[float]] = []

            for si, (sx, sy) in enumerate(sensor_positions):
                dist = max(0.3, np.sqrt((px - sx) ** 2 + (py - sy) ** 2))
                is_nlos = rng.random() < nlos_probability

                # BiCN: 2.4GHz better in NLOS, 5GHz better in LOS
                n = path_loss_n_nlos if is_nlos else path_loss_n_los
                # NLOS adds extra attenuation
                nlos_attenuation = rng.uniform(3, 8) if is_nlos else 0

                # Generate multiple readings per sample
                readings = []
                for _ in range(readings_per_sample):
                    rssi = (
                        tx_power
                        - 10 * n * np.log10(dist)
                        - nlos_attenuation
                        + rng.normal(0, noise_std)
                    )
                    rssi = max(-100.0, min(-10.0, rssi))
                    readings.append(int(round(rssi)))

                avg_rssi = int(round(sum(readings) / len(readings)))
                features.append(float(avg_rssi))

                # BiCN statistical features
                stats = compute_statistical_features(readings)
                all_stats.append(stats)

            # Append statistical features per sensor
            for stats in all_stats:
                features.extend(stats)

            X.append(features)
            y.append(zone_id)

    return X, y, sensor_ids
