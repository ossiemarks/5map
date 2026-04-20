"""SageMaker Multi-Model Endpoint inference handler.

Handles inference requests for all 3 models:
- env-mapper: Environment mapping from RSSI positions
- device-fp: Device fingerprinting and classification
- presence: Presence detection from RSSI time-series
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Models loaded lazily on first request
_models: Dict[str, Any] = {}


def _load_model(model_name: str, model_dir: str) -> Any:
    """Load a model from the SageMaker model directory."""
    if model_name in _models:
        return _models[model_name]

    model_path = Path(model_dir)

    if model_name == "env-mapper":
        from ml.models.env_mapper import EnvironmentMapper
        model = EnvironmentMapper.load(str(model_path / "env_mapper.pkl"))

    elif model_name == "device-fp":
        from ml.models.device_fp import DeviceFingerprinter
        model = DeviceFingerprinter.load(str(model_path / "device_fp.pkl"))

    elif model_name == "presence":
        from ml.models.presence_lstm import PresenceDetector
        model = PresenceDetector.load(str(model_path / "presence_lstm.pt"))

    else:
        raise ValueError(f"Unknown model: {model_name}")

    _models[model_name] = model
    logger.info("Loaded model: %s", model_name)
    return model


def model_fn(model_dir: str) -> Dict[str, str]:
    """SageMaker model loading callback.

    Returns the model directory path for lazy loading.
    """
    logger.info("model_fn called with dir: %s", model_dir)
    return {"model_dir": model_dir}


def input_fn(request_body: str, content_type: str) -> Dict[str, Any]:
    """SageMaker input deserialization."""
    if content_type != "application/json":
        raise ValueError(f"Unsupported content type: {content_type}")
    return json.loads(request_body)


def predict_fn(input_data: Dict[str, Any], model_info: Dict[str, str]) -> Dict[str, Any]:
    """SageMaker prediction callback.

    Routes to the appropriate model based on the 'model' field in input.
    """
    model_name = input_data.get("model")
    if not model_name:
        return {"error": "Missing 'model' field in request"}

    model_dir = model_info["model_dir"]

    try:
        model = _load_model(model_name, model_dir)
    except (FileNotFoundError, ValueError) as e:
        return {"error": f"Failed to load model '{model_name}': {e}"}

    try:
        if model_name == "env-mapper":
            positions = input_data.get("positions", [])
            model.fit(positions)
            return model.predict_heatmap()

        elif model_name == "device-fp":
            observations = input_data.get("observations", [])
            return model.predict(observations)

        elif model_name == "presence":
            rssi_windows = input_data.get("rssi_windows", [])
            return model.predict(rssi_windows)

        else:
            return {"error": f"Unknown model: {model_name}"}

    except Exception as e:
        logger.error("Inference failed for %s: %s", model_name, e)
        return {"error": str(e), "model": model_name, "confidence": 0.0}


def output_fn(prediction: Dict[str, Any], accept: str) -> str:
    """SageMaker output serialization."""
    if accept != "application/json":
        raise ValueError(f"Unsupported accept type: {accept}")
    return json.dumps(prediction, default=str)
