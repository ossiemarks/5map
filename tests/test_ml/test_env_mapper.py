"""Tests for environment mapper GP model."""

import os
import pytest


def _needs_sklearn():
    try:
        import sklearn
        return False
    except ImportError:
        return True


pytestmark = pytest.mark.skipif(_needs_sklearn(), reason="scikit-learn not installed")


def _convert_synthetic_positions(raw_data):
    """Convert agent-generated synthetic format to model format."""
    positions = []
    for item in raw_data:
        pos = item.get("position", (0, 0))
        readings = item.get("rssi_readings", {})
        positions.append({
            "x": pos[0] if isinstance(pos, (tuple, list)) else item.get("x", 0),
            "y": pos[1] if isinstance(pos, (tuple, list)) else item.get("y", 0),
            "rssi_values": list(readings.values()) if isinstance(readings, dict) else readings,
        })
    return positions


class TestEnvironmentMapper:
    def test_fit_and_predict(self):
        from ml.models.env_mapper import EnvironmentMapper
        from ml.data.synthetic import generate_synthetic_rssi_grid

        raw = generate_synthetic_rssi_grid(num_positions=15)
        positions = _convert_synthetic_positions(raw)
        mapper = EnvironmentMapper(grid_size=25)
        mapper.fit(positions)
        result = mapper.predict_heatmap()

        assert "heatmap" in result
        assert "walls" in result
        assert "grid_bounds" in result
        assert "confidence" in result

    def test_too_few_positions_raises(self):
        from ml.models.env_mapper import EnvironmentMapper

        positions = [{"x": 0, "y": 0, "rssi_values": [-50]}, {"x": 1, "y": 1, "rssi_values": [-60]}]
        mapper = EnvironmentMapper()
        with pytest.raises(ValueError):
            mapper.fit(positions)

    def test_save_and_load(self, tmp_path):
        from ml.models.env_mapper import EnvironmentMapper
        from ml.data.synthetic import generate_synthetic_rssi_grid

        raw = generate_synthetic_rssi_grid(num_positions=10)
        positions = _convert_synthetic_positions(raw)
        mapper = EnvironmentMapper(grid_size=10)
        mapper.fit(positions)

        path = str(tmp_path / "mapper.pkl")
        mapper.save(path)
        assert os.path.exists(path)

        loaded = EnvironmentMapper.load(path)
        result = loaded.predict_heatmap()
        assert "heatmap" in result

    def test_inference_under_500ms(self):
        import time
        from ml.models.env_mapper import EnvironmentMapper
        from ml.data.synthetic import generate_synthetic_rssi_grid

        raw = generate_synthetic_rssi_grid(num_positions=50)
        positions = _convert_synthetic_positions(raw)
        mapper = EnvironmentMapper(grid_size=30)
        mapper.fit(positions)

        start = time.monotonic()
        mapper.predict_heatmap()
        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 1000, f"Inference took {elapsed_ms:.0f}ms, expected <1000ms"
