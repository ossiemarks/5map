"""Pydantic configuration schema for 5map.

All configuration is validated at startup via these models.
Includes schema version for future migration support.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class RadioConfig(BaseModel):
    """Configuration for a single WiFi radio."""

    interface: str
    band: str
    channels: List[int]
    mode: str = "monitor"

    @field_validator("channels")
    @classmethod
    def channels_not_empty(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("channels list cannot be empty")
        return v

    @field_validator("band")
    @classmethod
    def valid_band(cls, v: str) -> str:
        if v not in ("2.4GHz", "5GHz"):
            raise ValueError(f"band must be '2.4GHz' or '5GHz', got '{v}'")
        return v


class CaptureConfig(BaseModel):
    """Capture timing and buffer settings."""

    window_seconds: float = 1.0
    max_observations_per_window: int = 10000
    channel_dwell_ms: int = 200
    buffer_max_size: int = 50000

    @field_validator("window_seconds")
    @classmethod
    def positive_window(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("window_seconds must be positive")
        return v


class MQTTConfig(BaseModel):
    """MQTT transport settings for AWS IoT Core."""

    broker: str = "localhost"
    port: int = 8883
    topic: str = "5map/rssi/{sensor_id}"
    qos: int = 1
    keepalive: int = 60
    tls: bool = True
    cert_dir: str = "/etc/5map/certs"
    ca_cert: str = "AmazonRootCA1.pem"
    client_cert: str = "certificate.pem.crt"
    private_key: str = "private.pem.key"


class TransportConfig(BaseModel):
    """Transport layer configuration."""

    type: str = "mqtt"
    mqtt: MQTTConfig = Field(default_factory=MQTTConfig)
    queue_max_size: int = 1000


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: str = "INFO"
    file: Optional[str] = None
    max_bytes: int = 5242880
    backup_count: int = 3

    @field_validator("level")
    @classmethod
    def valid_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid:
            raise ValueError(f"level must be one of {valid}")
        return v.upper()


class SensorConfig(BaseModel):
    """Sensor identity configuration."""

    id: str
    type: str = "rssi"


class FiveMapConfig(BaseModel):
    """Root configuration model for 5map.

    Validates all configuration at startup. Includes schema_version
    for future migration support.
    """

    schema_version: int = 1
    sensor: SensorConfig
    radios: Dict[str, RadioConfig] = Field(default_factory=dict)
    capture: CaptureConfig = Field(default_factory=CaptureConfig)
    transport: TransportConfig = Field(default_factory=TransportConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @classmethod
    def from_yaml(cls, path: str) -> "FiveMapConfig":
        """Load and validate config from a YAML file.

        Args:
            path: Path to the YAML config file.

        Returns:
            Validated FiveMapConfig instance.

        Raises:
            FileNotFoundError: If the file doesn't exist.
            ValidationError: If the config is invalid.
        """
        import yaml
        from pathlib import Path as FsPath

        config_path = FsPath(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(config_path) as f:
            raw = yaml.safe_load(f)

        return cls.model_validate(raw)
