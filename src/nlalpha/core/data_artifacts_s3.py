"""S3 artifact storage with conditional writes and verified lifecycle retention."""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any, Callable

from nlalpha.core.data_artifacts import (
    ArtifactMetadata,
    ArtifactScope,
    DataArtifact,
    DataArtifactBackendError,
    DataArtifactError,
    DataArtifactNotFoundError,
    DataArtifactStore,
    _artifact_key,
    _check_payload_budget,
    _decode_metadata,
    _encode_artifact,
    _positive_number,
    _metadata_length,
)

_PREFIX = "nlalpha/artifacts/v1/"
_READ_CHUNK_BYTES = 64 << 10


async def _read_bounded(body: Any, amount: int) -> bytes:
    """Read up to a declared byte count using fixed-size streaming chunks."""
    chunks = []
    remaining = amount
    while remaining:
        requested = min(remaining, _READ_CHUNK_BYTES)
        chunk = await body.read(requested)
        if not chunk:
            break
        if len(chunk) > requested:
            raise DataArtifactError("artifact stream exceeded its requested byte count")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _s3_key(data_ref: str, scope: ArtifactScope) -> str:
    scoped_key = _artifact_key(data_ref, scope)
    _, scope_hash, reference = scoped_key.rsplit(":", 2)
    return f"{_PREFIX}{scope_hash}/{reference}"


def _is_missing(exc: Exception) -> bool:
    response = getattr(exc, "response", {})
    code = response.get("Error", {}).get("Code")
    return code in {"NoSuchKey", "NotFound", "404"}


def _validate_lifecycle(configuration: dict[str, Any], retention_days: int) -> None:
    """Require full-prefix expiration coverage without earlier overlapping expiry."""
    covered = False
    for rule in configuration.get("Rules", []):
        if rule.get("Status") != "Enabled":
            continue
        expiration = rule.get("Expiration", {})
        if not expiration:
            continue
        if "Filter" in rule:
            rule_filter = rule["Filter"]
            if not isinstance(rule_filter, dict):
                raise DataArtifactBackendError("S3 lifecycle filter is invalid")
            pure_prefix = set(rule_filter) <= {"Prefix"}
            rule_prefix = rule_filter.get("Prefix", rule_filter.get("And", {}).get("Prefix", ""))
        else:
            pure_prefix = True
            rule_prefix = rule.get("Prefix", "")
        if not isinstance(rule_prefix, str):
            raise DataArtifactBackendError("S3 lifecycle prefix is invalid")
        overlaps = _PREFIX.startswith(rule_prefix) or rule_prefix.startswith(_PREFIX)
        if not overlaps:
            continue
        if "Date" in expiration:
            raise DataArtifactBackendError("S3 artifact retention requires day-based expiration")
        days = expiration.get("Days")
        if days is None:
            continue
        if type(days) is not int or days <= 0:
            raise DataArtifactBackendError("S3 lifecycle expiration days are invalid")
        if days < retention_days:
            raise DataArtifactBackendError("S3 lifecycle can expire artifacts before configured retention")
        if pure_prefix and _PREFIX.startswith(rule_prefix) and days == retention_days:
            covered = True
    if not covered:
        raise DataArtifactBackendError("S3 lifecycle must expire the artifact prefix at configured retention days")


class S3DataArtifactStore(DataArtifactStore):
    """Store one immutable envelope per S3 object with verified bucket retention.

    Logical expiry is per artifact; bucket lifecycle performs asynchronous daily cleanup.
    """

    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str | None = None,
        retention_days: int = 1,
        ttl_seconds: float = 86400,
        max_bytes: int | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not isinstance(bucket, str) or not bucket.strip():
            raise DataArtifactBackendError("S3 artifact storage requires an explicit bucket")
        if type(retention_days) is not int or retention_days <= 0:
            raise DataArtifactError("retention_days must be a positive integer")
        self._retention_days = retention_days
        self._ttl_seconds = self._validate_ttl(ttl_seconds)
        if max_bytes is not None and (type(max_bytes) is not int or max_bytes <= 0):
            raise DataArtifactError("max_bytes must be a positive integer")
        if (access_key is None) != (secret_key is None):
            raise DataArtifactBackendError("S3 access_key and secret_key must be supplied together")
        if endpoint_url is not None and (not isinstance(endpoint_url, str) or not endpoint_url.strip()):
            raise DataArtifactBackendError("S3 endpoint_url must be a nonempty URL when supplied")
        self._bucket = bucket
        self._max_bytes = max_bytes
        self._clock = clock
        self._client_kwargs: dict[str, Any] = {}
        if endpoint_url is not None:
            self._client_kwargs["endpoint_url"] = endpoint_url
        if access_key is not None:
            if not isinstance(access_key, str) or not access_key or not isinstance(secret_key, str) or not secret_key:
                raise DataArtifactBackendError("S3 credentials must be nonempty strings")
            self._client_kwargs.update(aws_access_key_id=access_key, aws_secret_access_key=secret_key)
        if region is not None:
            self._client_kwargs["region_name"] = region
        self._client: Any = None
        self._client_context: Any = None
        self._started = False
        self._closed = False

    def _validate_ttl(self, ttl_seconds: float) -> float:
        ttl = _positive_number(ttl_seconds, "ttl_seconds")
        if ttl > self._retention_days * 86400:
            raise DataArtifactError("ttl_seconds exceeds the configured S3 retention period")
        return ttl

    def _require_started(self) -> None:
        if not self._started or self._closed:
            raise DataArtifactBackendError("Artifact store must be started before use")

    async def start(self) -> None:
        if self._closed:
            raise DataArtifactBackendError("Artifact store is closed")
        if self._started:
            return
        try:
            from aiobotocore.session import get_session
            from botocore.config import Config

            context = get_session().create_client(
                "s3", **self._client_kwargs,
                config=Config(
                    retries={"total_max_attempts": 1},
                    connect_timeout=5, read_timeout=30,
                ),
            )
            self._client = await context.__aenter__()
            self._client_context = context
            await self._client.head_bucket(Bucket=self._bucket)
            versioning = await self._client.get_bucket_versioning(Bucket=self._bucket)
            if versioning.get("Status") is not None:
                raise DataArtifactBackendError("S3 artifact bucket must have versioning unconfigured")
            configuration = await self._client.get_bucket_lifecycle_configuration(Bucket=self._bucket)
            _validate_lifecycle(configuration, self._retention_days)
        except BaseException as exc:
            await self.aclose()
            if isinstance(exc, DataArtifactBackendError):
                raise
            if isinstance(exc, Exception):
                raise DataArtifactBackendError("S3 artifact backend readiness check failed") from exc
            raise
        self._started = True

    async def check_health(self) -> None:
        """Check bucket availability through the existing S3 client."""
        self._require_started()
        try:
            await self._client.head_bucket(Bucket=self._bucket)
        except Exception as exc:
            raise DataArtifactBackendError("S3 artifact backend health check failed") from exc

    async def aclose(self) -> None:
        if self._closed:
            return
        if self._client_context is not None:
            try:
                await self._client_context.__aexit__(None, None, None)
            except Exception as exc:
                raise DataArtifactBackendError("S3 artifact client close failed") from exc
            self._client_context = None
            self._client = None
        self._closed = True
        self._started = False

    async def publish(
        self, data: bytes, *, scope: ArtifactScope, media_type: str,
        schema: str, ttl_seconds: float | None = None,
    ) -> ArtifactMetadata:
        self._require_started()
        if not isinstance(data, bytes):
            raise DataArtifactError("artifact data must be bytes")
        if self._max_bytes is not None and len(data) > self._max_bytes:
            raise DataArtifactError("artifact exceeds the configured max_bytes")
        ttl = self._ttl_seconds if ttl_seconds is None else self._validate_ttl(ttl_seconds)
        created_at = self._clock()
        metadata = ArtifactMetadata(
            data_ref=f"ref_{uuid.uuid4().hex}", scope=scope, media_type=media_type,
            schema=schema, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
            created_at=created_at, expires_at=created_at + ttl,
        )
        envelope = _encode_artifact(DataArtifact(metadata, data))
        try:
            await self._client.put_object(
                Bucket=self._bucket, Key=_s3_key(metadata.data_ref, scope),
                Body=envelope, ContentType="application/octet-stream", IfNoneMatch="*",
            )
        except Exception as exc:
            raise DataArtifactBackendError("S3 artifact publish failed") from exc
        return metadata

    async def read(self, data_ref: str, *, scope: ArtifactScope) -> DataArtifact:
        self._require_started()
        key = _s3_key(data_ref, scope)
        try:
            response = await self._client.get_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            if _is_missing(exc):
                raise DataArtifactNotFoundError("Artifact not found in the supplied scope") from exc
            raise DataArtifactBackendError("S3 artifact read failed") from exc
        body = response["Body"]
        try:
            metadata_size = _metadata_length(await _read_bounded(body, 4))
            raw_metadata = await _read_bounded(body, metadata_size)
            if len(raw_metadata) != metadata_size:
                raise DataArtifactError("artifact metadata length is invalid")
            metadata = _decode_metadata(raw_metadata, data_ref=data_ref, scope=scope)
            expired = metadata.expires_at <= self._clock()
            if not expired:
                _check_payload_budget(metadata, self._max_bytes)
                data = await _read_bounded(body, metadata.size_bytes + 1)
                _check_payload_budget(metadata, self._max_bytes, len(data))
                return DataArtifact(metadata=metadata, data=data)
        except DataArtifactError:
            raise
        except Exception as exc:
            raise DataArtifactBackendError("S3 artifact body read failed") from exc
        finally:
            body.close()
        await self.delete(data_ref, scope=scope)
        raise DataArtifactNotFoundError("Artifact not found in the supplied scope")

    async def delete(self, data_ref: str, *, scope: ArtifactScope) -> bool:
        self._require_started()
        key = _s3_key(data_ref, scope)
        try:
            await self._client.head_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            if _is_missing(exc):
                return False
            raise DataArtifactBackendError("S3 artifact existence check failed") from exc
        try:
            await self._client.delete_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            raise DataArtifactBackendError("S3 artifact delete failed") from exc
        return True
