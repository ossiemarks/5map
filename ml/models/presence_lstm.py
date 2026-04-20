"""Presence detection LSTM model for 5map WiFi mapping tool.

Lightweight PyTorch LSTM that detects presence events from RSSI time-series data.
Designed for deployment on AWS SageMaker with minimal resource footprint (~50K params).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset


class PresenceLSTM(nn.Module):
    """PyTorch LSTM network for presence detection from RSSI time-series.

    Architecture:
        - Input: [batch, seq_len, 4] (mean_rssi, rssi_variance, device_count, new_device_count)
        - LSTM: 2 layers, 64 hidden units, dropout 0.2
        - Linear: 64 -> 5 classes
        - Output: log-softmax probabilities over presence event classes

    Total parameters: ~50K (suitable for SageMaker lightweight inference).
    """

    def __init__(
        self,
        input_size: int = 4,
        hidden_size: int = 64,
        num_layers: int = 2,
        num_classes: int = 5,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()
        self.hidden_size = hidden_size
        self.num_layers = num_layers

        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden_size, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass through LSTM and classification head.

        Args:
            x: Input tensor of shape [batch, seq_len, input_size].

        Returns:
            Log-softmax probabilities of shape [batch, num_classes].
        """
        # LSTM output: [batch, seq_len, hidden_size]
        lstm_out, _ = self.lstm(x)

        # Use the last time step output for classification
        last_output = lstm_out[:, -1, :]
        last_output = self.dropout(last_output)

        # Classification
        logits = self.fc(last_output)
        return torch.log_softmax(logits, dim=-1)


class PresenceDetector:
    """High-level presence detection interface for 5map.

    Wraps the PresenceLSTM model with preprocessing, prediction, training,
    and serialization utilities. Designed for integration with the 5map
    WiFi mapping pipeline.

    Attributes:
        model: The underlying PresenceLSTM neural network.
        classes: Ordered list of presence event class names.
        device: Torch device for inference (cpu/cuda).
    """

    CLASSES = ["empty", "stationary", "moving", "entry", "exit"]

    def __init__(
        self,
        hidden_size: int = 64,
        num_layers: int = 2,
        dropout: float = 0.2,
        device: str | None = None,
    ) -> None:
        """Initialize the presence detector.

        Args:
            hidden_size: Number of LSTM hidden units.
            num_layers: Number of stacked LSTM layers.
            dropout: Dropout probability between layers.
            device: Torch device string. Auto-detected if None.
        """
        self.classes = self.CLASSES
        self.device = torch.device(
            device if device else ("cuda" if torch.cuda.is_available() else "cpu")
        )
        self.model = PresenceLSTM(
            input_size=4,
            hidden_size=hidden_size,
            num_layers=num_layers,
            num_classes=len(self.classes),
            dropout=dropout,
        ).to(self.device)
        self._hidden_size = hidden_size
        self._num_layers = num_layers
        self._dropout = dropout

    def preprocess(self, rssi_windows: list[dict[str, float]]) -> torch.Tensor:
        """Convert RSSI observation windows to model input tensor.

        Each dict should contain:
            - mean_rssi: Average RSSI value in the window (dBm, typically -100 to 0)
            - rssi_variance: Variance of RSSI readings in the window
            - device_count: Number of detected devices
            - new_device_count: Number of newly appeared devices

        Args:
            rssi_windows: List of observation window dictionaries.

        Returns:
            Tensor of shape [1, seq_len, 4] ready for model input.

        Raises:
            ValueError: If rssi_windows is empty or missing required keys.
        """
        if not rssi_windows:
            raise ValueError("rssi_windows must contain at least one observation window")

        required_keys = {"mean_rssi", "rssi_variance", "device_count", "new_device_count"}
        features = []

        for window in rssi_windows:
            missing = required_keys - set(window.keys())
            if missing:
                raise ValueError(f"Window missing required keys: {missing}")

            features.append([
                self._normalize_rssi(window["mean_rssi"]),
                self._normalize_variance(window["rssi_variance"]),
                self._normalize_count(window["device_count"]),
                self._normalize_count(window["new_device_count"]),
            ])

        tensor = torch.tensor([features], dtype=torch.float32, device=self.device)
        return tensor

    def predict(self, rssi_windows: list[dict[str, float]]) -> dict[str, Any]:
        """Predict presence event with confidence score.

        Args:
            rssi_windows: List of observation window dictionaries.
                Each dict has: mean_rssi, rssi_variance, device_count, new_device_count.

        Returns:
            Dictionary containing:
                - event: Predicted presence event class name.
                - confidence: Probability of the predicted class (0.0 to 1.0).
                - details: Per-class probability breakdown.
        """
        self.model.eval()
        input_tensor = self.preprocess(rssi_windows)

        with torch.no_grad():
            log_probs = self.model(input_tensor)
            probs = torch.exp(log_probs).squeeze(0)

        probs_np = probs.cpu().numpy()
        predicted_idx = int(np.argmax(probs_np))

        return {
            "event": self.classes[predicted_idx],
            "confidence": float(probs_np[predicted_idx]),
            "details": {
                cls: float(prob) for cls, prob in zip(self.classes, probs_np)
            },
        }

    def predict_batch(self, batch_windows: list[list[dict[str, float]]]) -> list[dict[str, Any]]:
        """Predict presence events for a batch of sequences.

        Args:
            batch_windows: List of sequences, each a list of observation windows.

        Returns:
            List of prediction dictionaries.
        """
        self.model.eval()
        tensors = []

        for windows in batch_windows:
            tensor = self.preprocess(windows)
            tensors.append(tensor.squeeze(0))

        batch_tensor = torch.stack(tensors, dim=0)

        with torch.no_grad():
            log_probs = self.model(batch_tensor)
            probs = torch.exp(log_probs)

        results = []
        for i in range(probs.shape[0]):
            probs_np = probs[i].cpu().numpy()
            predicted_idx = int(np.argmax(probs_np))
            results.append({
                "event": self.classes[predicted_idx],
                "confidence": float(probs_np[predicted_idx]),
                "details": {
                    cls: float(prob) for cls, prob in zip(self.classes, probs_np)
                },
            })

        return results

    def fit(
        self,
        training_data: list[list[dict[str, float]]],
        labels: list[int | str],
        epochs: int = 50,
        batch_size: int = 32,
        learning_rate: float = 1e-3,
        validation_split: float = 0.1,
    ) -> dict[str, list[float]]:
        """Train on labelled presence data.

        Args:
            training_data: List of sequences, each a list of observation window dicts.
            labels: List of labels (class index or class name string).
            epochs: Number of training epochs.
            batch_size: Mini-batch size for training.
            learning_rate: Adam optimizer learning rate.
            validation_split: Fraction of data used for validation.

        Returns:
            Training history with 'train_loss', 'val_loss', and 'val_accuracy' per epoch.
        """
        # Convert labels to indices
        label_indices = []
        for label in labels:
            if isinstance(label, str):
                label_indices.append(self.classes.index(label))
            else:
                label_indices.append(int(label))

        # Build input tensors
        all_features = []
        for sequence in training_data:
            seq_features = []
            for window in sequence:
                seq_features.append([
                    self._normalize_rssi(window["mean_rssi"]),
                    self._normalize_variance(window["rssi_variance"]),
                    self._normalize_count(window["device_count"]),
                    self._normalize_count(window["new_device_count"]),
                ])
            all_features.append(seq_features)

        x_tensor = torch.tensor(all_features, dtype=torch.float32, device=self.device)
        y_tensor = torch.tensor(label_indices, dtype=torch.long, device=self.device)

        # Train/validation split
        n_samples = len(x_tensor)
        n_val = max(1, int(n_samples * validation_split))
        indices = torch.randperm(n_samples)
        val_indices = indices[:n_val]
        train_indices = indices[n_val:]

        x_train, y_train = x_tensor[train_indices], y_tensor[train_indices]
        x_val, y_val = x_tensor[val_indices], y_tensor[val_indices]

        train_dataset = TensorDataset(x_train, y_train)
        train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)

        # Training setup
        criterion = nn.NLLLoss()
        optimizer = optim.Adam(self.model.parameters(), lr=learning_rate)
        scheduler = optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode="min", patience=5, factor=0.5
        )

        history: dict[str, list[float]] = {
            "train_loss": [],
            "val_loss": [],
            "val_accuracy": [],
        }

        self.model.train()
        for epoch in range(epochs):
            epoch_loss = 0.0
            num_batches = 0

            for x_batch, y_batch in train_loader:
                optimizer.zero_grad()
                output = self.model(x_batch)
                loss = criterion(output, y_batch)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
                optimizer.step()
                epoch_loss += loss.item()
                num_batches += 1

            avg_train_loss = epoch_loss / max(num_batches, 1)

            # Validation
            self.model.eval()
            with torch.no_grad():
                val_output = self.model(x_val)
                val_loss = criterion(val_output, y_val).item()
                val_preds = val_output.argmax(dim=1)
                val_accuracy = (val_preds == y_val).float().mean().item()
            self.model.train()

            scheduler.step(val_loss)

            history["train_loss"].append(avg_train_loss)
            history["val_loss"].append(val_loss)
            history["val_accuracy"].append(val_accuracy)

        self.model.eval()
        return history

    def save(self, path: str) -> None:
        """Save model state and configuration to disk.

        Args:
            path: File path for the saved model (.pt file).
        """
        save_path = Path(path)
        save_path.parent.mkdir(parents=True, exist_ok=True)

        checkpoint = {
            "model_state_dict": self.model.state_dict(),
            "config": {
                "hidden_size": self._hidden_size,
                "num_layers": self._num_layers,
                "dropout": self._dropout,
            },
            "classes": self.classes,
        }
        torch.save(checkpoint, save_path)

    @classmethod
    def load(cls, path: str, device: str | None = None) -> "PresenceDetector":
        """Load a saved PresenceDetector from disk.

        Args:
            path: File path to the saved model (.pt file).
            device: Torch device string. Auto-detected if None.

        Returns:
            Loaded PresenceDetector instance ready for inference.

        Raises:
            FileNotFoundError: If the model file does not exist.
        """
        save_path = Path(path)
        if not save_path.exists():
            raise FileNotFoundError(f"Model file not found: {path}")

        map_location = device if device else ("cuda" if torch.cuda.is_available() else "cpu")
        checkpoint = torch.load(save_path, map_location=map_location, weights_only=False)

        config = checkpoint["config"]
        detector = cls(
            hidden_size=config["hidden_size"],
            num_layers=config["num_layers"],
            dropout=config["dropout"],
            device=device,
        )
        detector.model.load_state_dict(checkpoint["model_state_dict"])
        detector.classes = checkpoint["classes"]
        detector.model.eval()

        return detector

    def parameter_count(self) -> int:
        """Return total number of trainable parameters."""
        return sum(p.numel() for p in self.model.parameters() if p.requires_grad)

    @staticmethod
    def _normalize_rssi(rssi: float) -> float:
        """Normalize RSSI from dBm range [-100, 0] to [0, 1]."""
        return (rssi + 100.0) / 100.0

    @staticmethod
    def _normalize_variance(variance: float) -> float:
        """Normalize RSSI variance to [0, 1] range. Cap at 500."""
        return min(variance, 500.0) / 500.0

    @staticmethod
    def _normalize_count(count: float) -> float:
        """Normalize device count to [0, 1] range. Cap at 50."""
        return min(count, 50.0) / 50.0
