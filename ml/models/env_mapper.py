"""Environment mapper model for 5map WiFi mapping tool.

Uses Gaussian Process regression to spatially interpolate RSSI observations
and infer wall/obstacle positions from signal attenuation patterns.
"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import Matern, WhiteKernel
from sklearn.kernel_approximation import Nystroem
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline


class EnvironmentMapper:
    """Spatial signal strength mapper with wall/obstacle inference.

    Fits a Gaussian Process model on position-tagged RSSI data to produce
    interpolated heatmaps and inferred wall positions based on gradient
    analysis of signal attenuation patterns.

    Args:
        grid_size: Resolution of the output heatmap grid (grid_size x grid_size).
        use_approximation: When True, uses Nystroem approximation for datasets
            with >50 points to maintain inference under 200ms.
    """

    _N_THRESHOLD: int = 50

    def __init__(self, grid_size: int = 50, use_approximation: bool = True) -> None:
        self.grid_size = grid_size
        self.use_approximation = use_approximation
        self._positions: NDArray[np.float64] | None = None
        self._rssi_mean: NDArray[np.float64] | None = None
        self._model: GaussianProcessRegressor | Pipeline | None = None
        self._grid_bounds: dict[str, float] | None = None
        self._is_fitted: bool = False

    def fit(self, positions: list[dict[str, Any]]) -> None:
        """Fit the GP model on position-tagged RSSI data.

        Args:
            positions: List of dicts with keys:
                - x: float, physical x coordinate
                - y: float, physical y coordinate
                - rssi_values: list[float], RSSI readings from multiple APs

        Raises:
            ValueError: If fewer than 3 valid positions provided.
            ValueError: If all positions are identical.
        """
        coords, rssi_means = self._validate_and_extract(positions)

        n_samples = coords.shape[0]

        if n_samples < 3:
            raise ValueError(
                f"At least 3 valid positions required, got {n_samples}."
            )

        if np.all(coords == coords[0]):
            raise ValueError(
                "All positions are identical; cannot fit spatial model."
            )

        self._positions = coords
        self._rssi_mean = rssi_means

        x_min, y_min = coords.min(axis=0)
        x_max, y_max = coords.max(axis=0)
        margin = max((x_max - x_min), (y_max - y_min)) * 0.05
        self._grid_bounds = {
            "x_min": float(x_min - margin),
            "x_max": float(x_max + margin),
            "y_min": float(y_min - margin),
            "y_max": float(y_max + margin),
        }

        if self.use_approximation and n_samples > self._N_THRESHOLD:
            self._fit_approximated(coords, rssi_means, n_samples)
        else:
            self._fit_exact(coords, rssi_means)

        self._is_fitted = True

    def predict_heatmap(self) -> dict[str, Any]:
        """Generate heatmap and wall predictions.

        Returns:
            Dict containing:
                - heatmap: 2D list of floats (grid_size x grid_size)
                - walls: list of dicts with start, end, confidence
                - grid_bounds: dict with x_min, x_max, y_min, y_max
                - confidence: float, overall model confidence [0, 1]

        Raises:
            RuntimeError: If model has not been fitted.
        """
        if not self._is_fitted or self._model is None or self._grid_bounds is None:
            raise RuntimeError("Model must be fitted before prediction. Call fit() first.")

        grid_x = np.linspace(
            self._grid_bounds["x_min"],
            self._grid_bounds["x_max"],
            self.grid_size,
        )
        grid_y = np.linspace(
            self._grid_bounds["y_min"],
            self._grid_bounds["y_max"],
            self.grid_size,
        )
        xx, yy = np.meshgrid(grid_x, grid_y)
        grid_points = np.column_stack([xx.ravel(), yy.ravel()])

        if isinstance(self._model, Pipeline):
            predictions = self._model.predict(grid_points)
            confidence = self._estimate_confidence_approximate(grid_points)
        else:
            predictions, std = self._model.predict(grid_points, return_std=True)
            confidence = self._estimate_confidence_exact(std)

        heatmap = predictions.reshape(self.grid_size, self.grid_size)
        walls = self._detect_walls(heatmap, grid_x, grid_y)

        return {
            "heatmap": heatmap.tolist(),
            "walls": walls,
            "grid_bounds": self._grid_bounds,
            "confidence": float(confidence),
        }

    def save(self, path: str) -> None:
        """Serialize model to file.

        Args:
            path: Filesystem path to write the serialized model.
        """
        state = {
            "grid_size": self.grid_size,
            "use_approximation": self.use_approximation,
            "positions": self._positions,
            "rssi_mean": self._rssi_mean,
            "model": self._model,
            "grid_bounds": self._grid_bounds,
            "is_fitted": self._is_fitted,
        }
        filepath = Path(path)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "wb") as f:
            pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)

    @classmethod
    def load(cls, path: str) -> "EnvironmentMapper":
        """Load model from file.

        Args:
            path: Filesystem path to read the serialized model.

        Returns:
            Restored EnvironmentMapper instance.

        Raises:
            FileNotFoundError: If path does not exist.
        """
        filepath = Path(path)
        if not filepath.exists():
            raise FileNotFoundError(f"Model file not found: {path}")

        with open(filepath, "rb") as f:
            state = pickle.load(f)  # noqa: S301

        instance = cls(
            grid_size=state["grid_size"],
            use_approximation=state["use_approximation"],
        )
        instance._positions = state["positions"]
        instance._rssi_mean = state["rssi_mean"]
        instance._model = state["model"]
        instance._grid_bounds = state["grid_bounds"]
        instance._is_fitted = state["is_fitted"]
        return instance

    def _validate_and_extract(
        self, positions: list[dict[str, Any]]
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Validate input and extract coordinate/RSSI arrays.

        Filters out entries with NaN RSSI values or empty RSSI lists.

        Returns:
            Tuple of (coordinates array [N, 2], mean RSSI array [N]).

        Raises:
            ValueError: If fewer than 3 valid positions after filtering.
        """
        coords_list: list[list[float]] = []
        rssi_list: list[float] = []

        for pos in positions:
            x = pos.get("x")
            y = pos.get("y")
            rssi_values = pos.get("rssi_values", [])

            if x is None or y is None:
                continue

            try:
                x_val = float(x)
                y_val = float(y)
            except (TypeError, ValueError):
                continue

            if np.isnan(x_val) or np.isnan(y_val):
                continue

            valid_rssi = [
                float(v) for v in rssi_values
                if v is not None and not np.isnan(float(v))
            ]

            if not valid_rssi:
                continue

            coords_list.append([x_val, y_val])
            rssi_list.append(float(np.mean(valid_rssi)))

        if len(coords_list) < 3:
            raise ValueError(
                f"At least 3 valid positions required, got {len(coords_list)}."
            )

        coords = np.array(coords_list, dtype=np.float64)
        rssi_means = np.array(rssi_list, dtype=np.float64)
        return coords, rssi_means

    def _fit_exact(
        self, coords: NDArray[np.float64], targets: NDArray[np.float64]
    ) -> None:
        """Fit standard GP regressor (exact, O(n^3))."""
        kernel = Matern(nu=2.5, length_scale=1.0, length_scale_bounds=(0.1, 100.0)) + WhiteKernel(
            noise_level=1.0, noise_level_bounds=(1e-5, 100.0)
        )
        self._model = GaussianProcessRegressor(
            kernel=kernel,
            n_restarts_optimizer=3,
            normalize_y=True,
            alpha=1e-6,
        )
        self._model.fit(coords, targets)

    def _fit_approximated(
        self,
        coords: NDArray[np.float64],
        targets: NDArray[np.float64],
        n_samples: int,
    ) -> None:
        """Fit Nystroem-approximated model for large datasets.

        Uses Nystroem kernel approximation with Ridge regression to
        maintain O(n * k^2) complexity where k << n.
        """
        n_components = min(self._N_THRESHOLD, n_samples)

        self._model = Pipeline([
            (
                "nystroem",
                Nystroem(
                    kernel="rbf",
                    gamma=None,
                    n_components=n_components,
                    random_state=42,
                ),
            ),
            ("ridge", Ridge(alpha=1.0)),
        ])
        self._model.fit(coords, targets)

    def _estimate_confidence_exact(self, std: NDArray[np.float64]) -> float:
        """Estimate overall confidence from GP predictive standard deviation."""
        mean_std = float(np.mean(std))
        if self._rssi_mean is None:
            return 0.5
        rssi_range = float(np.ptp(self._rssi_mean))
        if rssi_range == 0:
            return 0.5
        normalized_uncertainty = mean_std / rssi_range
        confidence = float(np.clip(1.0 - normalized_uncertainty, 0.0, 1.0))
        return confidence

    def _estimate_confidence_approximate(
        self, grid_points: NDArray[np.float64]
    ) -> float:
        """Estimate confidence for approximated model using training residuals."""
        if self._positions is None or self._rssi_mean is None or self._model is None:
            return 0.5

        train_pred = self._model.predict(self._positions)
        residuals = self._rssi_mean - train_pred
        rmse = float(np.sqrt(np.mean(residuals**2)))
        rssi_range = float(np.ptp(self._rssi_mean))
        if rssi_range == 0:
            return 0.5
        confidence = float(np.clip(1.0 - (rmse / rssi_range), 0.0, 1.0))
        return confidence

    def _detect_walls(
        self,
        heatmap: NDArray[np.float64],
        grid_x: NDArray[np.float64],
        grid_y: NDArray[np.float64],
    ) -> list[dict[str, Any]]:
        """Detect wall/obstacle positions from signal attenuation gradients.

        Computes gradient magnitude of the heatmap and identifies regions
        with gradient > 2 standard deviations above the mean as likely
        wall/obstacle locations. Adjacent high-gradient cells are connected
        into line segments.

        Args:
            heatmap: 2D array of interpolated RSSI values.
            grid_x: X-axis grid coordinates.
            grid_y: Y-axis grid coordinates.

        Returns:
            List of wall segment dicts with start, end, and confidence.
        """
        grad_y, grad_x = np.gradient(heatmap)
        gradient_magnitude = np.sqrt(grad_x**2 + grad_y**2)

        mean_grad = float(np.mean(gradient_magnitude))
        std_grad = float(np.std(gradient_magnitude))

        if std_grad < 1e-10:
            return []

        threshold = mean_grad + 2.0 * std_grad
        high_gradient_mask = gradient_magnitude > threshold

        walls = self._connect_gradient_cells(
            high_gradient_mask, gradient_magnitude, grid_x, grid_y, threshold
        )
        return walls

    def _connect_gradient_cells(
        self,
        mask: NDArray[np.bool_],
        gradient_mag: NDArray[np.float64],
        grid_x: NDArray[np.float64],
        grid_y: NDArray[np.float64],
        threshold: float,
    ) -> list[dict[str, Any]]:
        """Connect adjacent high-gradient cells into wall line segments.

        Uses connected component labeling to group adjacent cells, then
        fits line segments through each component using PCA for direction.

        Args:
            mask: Boolean mask of high-gradient cells.
            gradient_mag: Gradient magnitude array for confidence scoring.
            grid_x: X-axis grid coordinates.
            grid_y: Y-axis grid coordinates.
            threshold: Gradient threshold used for detection.

        Returns:
            List of wall segments with start/end coordinates and confidence.
        """
        labeled = self._label_connected_components(mask)
        n_labels = int(labeled.max())

        if n_labels == 0:
            return []

        max_grad = float(gradient_mag.max())
        walls: list[dict[str, Any]] = []

        for label_id in range(1, n_labels + 1):
            component_mask = labeled == label_id
            cell_indices = np.argwhere(component_mask)

            if len(cell_indices) < 2:
                continue

            world_coords = np.column_stack([
                grid_x[cell_indices[:, 1]],
                grid_y[cell_indices[:, 0]],
            ])

            centroid = world_coords.mean(axis=0)
            centered = world_coords - centroid

            cov = np.cov(centered.T)
            if cov.ndim < 2:
                continue

            eigenvalues, eigenvectors = np.linalg.eigh(cov)
            principal_dir = eigenvectors[:, -1]

            projections = centered @ principal_dir
            min_proj = float(projections.min())
            max_proj = float(projections.max())

            start = centroid + principal_dir * min_proj
            end = centroid + principal_dir * max_proj

            component_gradients = gradient_mag[component_mask]
            mean_component_grad = float(np.mean(component_gradients))
            confidence = float(np.clip(mean_component_grad / max_grad, 0.0, 1.0))

            walls.append({
                "start": [float(start[0]), float(start[1])],
                "end": [float(end[0]), float(end[1])],
                "confidence": round(confidence, 4),
            })

        return walls

    def _label_connected_components(
        self, mask: NDArray[np.bool_]
    ) -> NDArray[np.int32]:
        """Label connected components in a binary mask using flood fill.

        Uses 4-connectivity (up, down, left, right).

        Args:
            mask: 2D boolean array.

        Returns:
            2D integer array with component labels (0 = background).
        """
        labeled = np.zeros_like(mask, dtype=np.int32)
        current_label = 0
        rows, cols = mask.shape

        for i in range(rows):
            for j in range(cols):
                if mask[i, j] and labeled[i, j] == 0:
                    current_label += 1
                    stack = [(i, j)]
                    while stack:
                        r, c = stack.pop()
                        if (
                            r < 0
                            or r >= rows
                            or c < 0
                            or c >= cols
                            or not mask[r, c]
                            or labeled[r, c] != 0
                        ):
                            continue
                        labeled[r, c] = current_label
                        stack.extend([(r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)])

        return labeled
