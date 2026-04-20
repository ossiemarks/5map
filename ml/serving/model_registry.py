"""Model registry for versioned S3 storage of trained models.

Manages model artifact upload, download, and version tracking.
"""

from __future__ import annotations

import logging
import os
import tarfile
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

S3_BUCKET = os.environ.get("FIVEMAP_MODELS_BUCKET", "fivemap-prod-models")
S3_PREFIX = "models"


class ModelRegistry:
    """Manage versioned model artifacts in S3."""

    def __init__(self, bucket: str = S3_BUCKET, prefix: str = S3_PREFIX):
        import boto3
        self._s3 = boto3.client("s3")
        self._bucket = bucket
        self._prefix = prefix

    def upload(self, model_name: str, local_path: str, version: int) -> str:
        """Upload a model artifact to S3.

        Args:
            model_name: Name of the model (e.g., "env_mapper").
            local_path: Path to the local model file.
            version: Version number.

        Returns:
            S3 key of the uploaded artifact.
        """
        s3_key = f"{self._prefix}/v{version}/{model_name}.tar.gz"

        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            with tarfile.open(tmp_path, "w:gz") as tar:
                tar.add(local_path, arcname=os.path.basename(local_path))

            self._s3.upload_file(tmp_path, self._bucket, s3_key)
            logger.info("Uploaded model %s v%d to s3://%s/%s", model_name, version, self._bucket, s3_key)
            return s3_key
        finally:
            os.unlink(tmp_path)

    def download(self, model_name: str, version: int, local_dir: str) -> str:
        """Download a model artifact from S3.

        Args:
            model_name: Name of the model.
            version: Version number.
            local_dir: Directory to extract the model into.

        Returns:
            Path to the extracted model file.
        """
        s3_key = f"{self._prefix}/v{version}/{model_name}.tar.gz"

        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            self._s3.download_file(self._bucket, s3_key, tmp_path)

            with tarfile.open(tmp_path, "r:gz") as tar:
                tar.extractall(path=local_dir)

            logger.info("Downloaded model %s v%d to %s", model_name, version, local_dir)
            return local_dir
        finally:
            os.unlink(tmp_path)

    def list_versions(self, model_name: str) -> list[int]:
        """List all available versions of a model.

        Returns:
            Sorted list of version numbers.
        """
        prefix = f"{self._prefix}/v"
        response = self._s3.list_objects_v2(
            Bucket=self._bucket,
            Prefix=prefix,
        )

        versions = set()
        for obj in response.get("Contents", []):
            key = obj["Key"]
            if model_name in key:
                parts = key.split("/")
                for part in parts:
                    if part.startswith("v") and part[1:].isdigit():
                        versions.add(int(part[1:]))

        return sorted(versions)

    def latest_version(self, model_name: str) -> Optional[int]:
        """Get the latest version number for a model."""
        versions = self.list_versions(model_name)
        return versions[-1] if versions else None
