"""Application-local configuration and construction of artifact stores."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

from nlalpha.core.data_artifacts import DataArtifactStore


@dataclass(frozen=True)
class ArtifactStoreConfig:
    """Immutable settings for one selected artifact storage backend."""

    backend: str = "redis"
    redis_url: str = field(default="redis://127.0.0.1:6379/0", repr=False)
    ttl_seconds: float = 86400
    max_bytes: int | None = None
    bucket: str | None = None
    endpoint_url: str | None = field(default=None, repr=False)
    access_key: str | None = field(default=None, repr=False)
    secret_key: str | None = field(default=None, repr=False)
    region: str | None = None
    retention_days: int = 1

    def __post_init__(self) -> None:
        if self.backend not in ("redis", "s3"):
            raise ValueError("artifact backend must be redis or s3")
        if (isinstance(self.ttl_seconds, bool)
                or not isinstance(self.ttl_seconds, (int, float))
                or not math.isfinite(self.ttl_seconds) or self.ttl_seconds <= 0):
            raise ValueError("artifact ttl_seconds must be a positive finite number")
        if self.max_bytes is not None and (type(self.max_bytes) is not int or self.max_bytes <= 0):
            raise ValueError("artifact max_bytes must be a positive integer")
        if self.backend == "redis":
            if not isinstance(self.redis_url, str) or not self.redis_url.strip():
                raise ValueError("artifact Redis URL must be nonempty")
        else:
            if not isinstance(self.bucket, str) or not self.bucket.strip():
                raise ValueError("artifact S3 bucket must be configured")
            if type(self.retention_days) is not int or self.retention_days <= 0:
                raise ValueError("artifact S3 retention_days must be a positive integer")
            if self.ttl_seconds > self.retention_days * 86400:
                raise ValueError("artifact TTL must not exceed S3 retention")
            if (self.access_key is None) != (self.secret_key is None):
                raise ValueError("artifact S3 access_key and secret_key must be supplied together")
            for value in (self.access_key, self.secret_key):
                if value is not None and (not isinstance(value, str) or not value.strip()):
                    raise ValueError("artifact S3 credentials must be nonempty when supplied")

    @classmethod
    def from_env(cls) -> ArtifactStoreConfig:
        """Snapshot artifact settings from the current process environment."""
        backend = os.getenv("NLALPHA_ARTIFACT_BACKEND", "redis")
        try:
            ttl = float(os.getenv("NLALPHA_ARTIFACT_TTL_SECONDS", "86400"))
            maximum = os.getenv("NLALPHA_ARTIFACT_MAX_BYTES")
            max_bytes = None if maximum is None else int(maximum)
        except ValueError:
            raise ValueError("artifact TTL and max_bytes must be valid numbers") from None
        values = dict(backend=backend, ttl_seconds=ttl, max_bytes=max_bytes)
        if backend == "redis":
            values["redis_url"] = os.getenv("NLALPHA_ARTIFACT_REDIS_URL", "redis://127.0.0.1:6379/0")
        elif backend == "s3":
            try:
                values["retention_days"] = int(os.getenv("NLALPHA_ARTIFACT_S3_RETENTION_DAYS", "1"))
            except ValueError:
                raise ValueError("artifact S3 retention_days must be a positive integer") from None
            for key, variable in (
                ("bucket", "BUCKET"), ("endpoint_url", "ENDPOINT"),
                ("access_key", "ACCESS_KEY"), ("secret_key", "SECRET_KEY"), ("region", "REGION"),
            ):
                values[key] = os.getenv(f"NLALPHA_ARTIFACT_S3_{variable}") or None
        return cls(**values)


def create_data_artifact_store(config: ArtifactStoreConfig | None = None) -> DataArtifactStore:
    """Construct the selected store for its owner to start and close."""
    selected = ArtifactStoreConfig.from_env() if config is None else config
    if selected.backend == "redis":
        from nlalpha.core.data_artifacts import RedisDataArtifactStore

        return RedisDataArtifactStore(
            selected.redis_url, ttl_seconds=selected.ttl_seconds, max_bytes=selected.max_bytes,
        )
    from nlalpha.core.data_artifacts_s3 import S3DataArtifactStore

    return S3DataArtifactStore(
        selected.bucket, endpoint_url=selected.endpoint_url, access_key=selected.access_key,
        secret_key=selected.secret_key, region=selected.region, retention_days=selected.retention_days,
        ttl_seconds=selected.ttl_seconds, max_bytes=selected.max_bytes,
    )
