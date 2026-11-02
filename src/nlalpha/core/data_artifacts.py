"""Immutable, scoped data artifacts with an asynchronous storage boundary."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any, Callable

from nlalpha.core.errors import DataError, INFRASTRUCTURE_ERROR

_REF_PATTERN = re.compile(r"ref_[0-9a-f]{32}")
_SCHEMA_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/=-]*")
_MEDIA_PATTERN = re.compile(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+")
_METADATA_MAX_BYTES = 64 << 10


class DataArtifactError(DataError):
    """An artifact or its access arguments violate the data contract."""


class DataArtifactNotFoundError(DataArtifactError):
    """The requested artifact does not exist in the supplied scope."""


class DataArtifactBackendError(DataArtifactError):
    """The configured artifact backend failed an operation."""

    error_type = INFRASTRUCTURE_ERROR


def _positive_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DataArtifactError(f"{name} must be a positive finite number")
    if not math.isfinite(value) or value <= 0:
        raise DataArtifactError(f"{name} must be a positive finite number")
    return float(value)


def _validate_ref(data_ref: str) -> None:
    if not isinstance(data_ref, str) or _REF_PATTERN.fullmatch(data_ref) is None:
        raise DataArtifactError("data_ref must contain ref_ and 32 lowercase hex digits")


@dataclass(frozen=True)
class ArtifactScope:
    """Explicit deployment and owner identity for artifact isolation."""

    environment: str
    owner: str

    def __post_init__(self) -> None:
        for name in ("environment", "owner"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise DataArtifactError(f"scope {name} must be a nonempty string")


@dataclass(frozen=True)
class ArtifactMetadata:
    """Immutable content identity and UTC epoch timestamps for one artifact."""

    data_ref: str
    scope: ArtifactScope
    media_type: str
    schema: str
    size_bytes: int
    sha256: str
    created_at: float
    expires_at: float

    def __post_init__(self) -> None:
        _validate_ref(self.data_ref)
        if not isinstance(self.scope, ArtifactScope):
            raise DataArtifactError("scope must be an ArtifactScope")
        if not isinstance(self.media_type, str) or not _MEDIA_PATTERN.fullmatch(self.media_type):
            raise DataArtifactError("media_type must be a type/subtype identifier")
        if not isinstance(self.schema, str) or not _SCHEMA_PATTERN.fullmatch(self.schema):
            raise DataArtifactError("schema must be a nonempty schema identifier")
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise DataArtifactError("size_bytes must be a nonnegative integer")
        if not isinstance(self.sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise DataArtifactError("sha256 must contain 64 lowercase hex digits")
        for name in ("created_at", "expires_at"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise DataArtifactError(f"{name} must be a finite UTC epoch timestamp")
            if not math.isfinite(value) or value < 0:
                raise DataArtifactError(f"{name} must be a finite UTC epoch timestamp")
        if self.expires_at <= self.created_at:
            raise DataArtifactError("expires_at must be after created_at")


@dataclass(frozen=True)
class DataArtifact:
    """An immutable artifact descriptor and its exact payload bytes."""

    metadata: ArtifactMetadata
    data: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, ArtifactMetadata) or not isinstance(self.data, bytes):
            raise DataArtifactError("artifact requires validated metadata and bytes")
        if len(self.data) != self.metadata.size_bytes:
            raise DataArtifactError("artifact payload size does not match metadata")
        if hashlib.sha256(self.data).hexdigest() != self.metadata.sha256:
            raise DataArtifactError("artifact payload digest does not match metadata")


def _artifact_key(data_ref: str, scope: ArtifactScope) -> str:
    _validate_ref(data_ref)
    if not isinstance(scope, ArtifactScope):
        raise DataArtifactError("scope must be an ArtifactScope")
    identity = json.dumps(
        [scope.environment, scope.owner], ensure_ascii=True, separators=(",", ":")
    ).encode("utf-8")
    return f"nlalpha:artifacts:v1:{hashlib.sha256(identity).hexdigest()}:{data_ref}"


def _encode_artifact(artifact: DataArtifact) -> bytes:
    metadata = json.dumps(
        asdict(artifact.metadata), ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    if len(metadata) > _METADATA_MAX_BYTES:
        raise DataArtifactError("artifact metadata exceeds the 64 KiB protocol budget")
    return len(metadata).to_bytes(4, "big") + metadata + artifact.data


def _metadata_length(header: bytes) -> int:
    """Validate the fixed-width header and its bounded metadata declaration."""
    if not isinstance(header, bytes) or len(header) != 4:
        raise DataArtifactError("artifact envelope is malformed")
    metadata_size = int.from_bytes(header, "big")
    if metadata_size == 0 or metadata_size > _METADATA_MAX_BYTES:
        raise DataArtifactError("artifact metadata length is invalid")
    return metadata_size


def _decode_metadata(raw: bytes, *, data_ref: str, scope: ArtifactScope) -> ArtifactMetadata:
    """Decode bounded metadata and verify its exact scoped content identity."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= _METADATA_MAX_BYTES:
        raise DataArtifactError("artifact metadata length is invalid")
    try:
        fields = json.loads(raw.decode("utf-8"))
        if not isinstance(fields, dict) or not isinstance(fields.get("scope"), dict):
            raise DataArtifactError("artifact metadata is malformed")
        fields["scope"] = ArtifactScope(**fields["scope"])
        metadata = ArtifactMetadata(**fields)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise DataArtifactError("artifact metadata is malformed") from exc
    if metadata.data_ref != data_ref or metadata.scope != scope:
        raise DataArtifactError("artifact metadata does not match its scoped reference")
    return metadata


def _envelope_metadata(raw: bytes, *, data_ref: str, scope: ArtifactScope) -> tuple[ArtifactMetadata, int]:
    """Locate and decode one complete metadata header within a received envelope."""
    if not isinstance(raw, bytes):
        raise DataArtifactError("artifact envelope is malformed")
    metadata_size = _metadata_length(raw[:4])
    offset = 4 + metadata_size
    if len(raw) < offset:
        raise DataArtifactError("artifact metadata length is invalid")
    return _decode_metadata(raw[4:offset], data_ref=data_ref, scope=scope), offset


def _check_payload_budget(metadata: ArtifactMetadata, max_bytes: int | None, actual_size: int | None = None) -> None:
    """Check declared and received payload sizes before hashing or artifact construction."""
    if max_bytes is not None and (metadata.size_bytes > max_bytes
                                  or (actual_size is not None and actual_size > max_bytes)):
        raise DataArtifactError("artifact exceeds the configured max_bytes")


def _decode_artifact(raw: bytes, *, data_ref: str, scope: ArtifactScope) -> DataArtifact:
    metadata, offset = _envelope_metadata(raw, data_ref=data_ref, scope=scope)
    return DataArtifact(metadata=metadata, data=raw[offset:])


class DataArtifactStore(ABC):
    """Asynchronous lifecycle and scoped immutable artifact operations."""

    @abstractmethod
    async def start(self) -> None:
        """Verify that the configured backend is ready."""

    @abstractmethod
    async def check_health(self) -> None:
        """Verify availability using the started store's client.

        Raise DataArtifactBackendError when the backend is unavailable.
        """

    @abstractmethod
    async def aclose(self) -> None:
        """Close resources owned by this store."""

    @abstractmethod
    async def publish(
        self, data: bytes, *, scope: ArtifactScope, media_type: str,
        schema: str, ttl_seconds: float | None = None,
    ) -> ArtifactMetadata:
        """Publish bytes under a new immutable reference."""

    @abstractmethod
    async def read(self, data_ref: str, *, scope: ArtifactScope) -> DataArtifact:
        """Read and verify an unexpired artifact in the supplied scope."""

    @abstractmethod
    async def delete(self, data_ref: str, *, scope: ArtifactScope) -> bool:
        """Delete an artifact and report whether it existed."""


class RedisDataArtifactStore(DataArtifactStore):
    """Store each envelope with one atomic Redis write and independent expiry.

    Injected clients are borrowed; clients constructed from a URL are owned.
    """

    def __init__(
        self, url: str | None = None, *, client: Any = None,
        ttl_seconds: float = 86400, max_bytes: int | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._ttl_seconds = _positive_number(ttl_seconds, "ttl_seconds")
        if max_bytes is not None and (type(max_bytes) is not int or max_bytes <= 0):
            raise DataArtifactError("max_bytes must be a positive integer")
        self._max_bytes = max_bytes
        self._clock = clock
        self._owned = client is None
        self._started = False
        self._closed = False
        if client is None:
            if not isinstance(url, str) or not url.strip():
                raise DataArtifactBackendError("Redis artifact storage requires an explicit URL")
            try:
                from redis.asyncio import Redis
                from redis.asyncio.retry import Retry
                from redis.backoff import NoBackoff

                client = Redis.from_url(
                    url, decode_responses=False, socket_timeout=5,
                    socket_connect_timeout=5, retry=Retry(NoBackoff(), 0),
                )
            except Exception as exc:
                raise DataArtifactBackendError("Cannot create Redis artifact client") from exc
        self._client = client

    def _require_started(self) -> None:
        if not self._started or self._closed:
            raise DataArtifactBackendError("Artifact store must be started before use")

    async def start(self) -> None:
        if self._closed:
            raise DataArtifactBackendError("Artifact store is closed")
        if self._started:
            return
        try:
            if not await self._client.ping():
                raise DataArtifactBackendError("Redis artifact backend did not confirm readiness")
        except BaseException as exc:
            await self.aclose()
            if isinstance(exc, Exception):
                raise DataArtifactBackendError("Redis artifact backend readiness check failed") from exc
            raise
        self._started = True

    async def check_health(self) -> None:
        """Ping the existing Redis client and preserve its lifecycle on failure."""
        self._require_started()
        try:
            if not await self._client.ping():
                raise DataArtifactBackendError("Redis artifact backend did not confirm health")
        except Exception as exc:
            raise DataArtifactBackendError("Redis artifact backend health check failed") from exc

    async def aclose(self) -> None:
        if self._closed:
            return
        if self._owned:
            try:
                await self._client.aclose()
            except Exception as exc:
                raise DataArtifactBackendError("Redis artifact client close failed") from exc
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
        ttl = self._ttl_seconds if ttl_seconds is None else _positive_number(ttl_seconds, "ttl_seconds")
        created_at = self._clock()
        metadata = ArtifactMetadata(
            data_ref=f"ref_{uuid.uuid4().hex}", scope=scope, media_type=media_type,
            schema=schema, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
            created_at=created_at, expires_at=created_at + ttl,
        )
        envelope = _encode_artifact(DataArtifact(metadata, data))
        try:
            stored = await self._client.set(
                _artifact_key(metadata.data_ref, scope), envelope, nx=True, px=math.ceil(ttl * 1000)
            )
        except Exception as exc:
            raise DataArtifactBackendError("Redis artifact publish failed") from exc
        if not stored:
            raise DataArtifactBackendError("Artifact reference collision prevented publication", retryable=False)
        return metadata

    async def read(self, data_ref: str, *, scope: ArtifactScope) -> DataArtifact:
        self._require_started()
        key = _artifact_key(data_ref, scope)
        try:
            if self._max_bytes is None:
                raw = await self._client.get(key)
            else:
                raw = await self._client.getrange(key, 0, self._max_bytes + _METADATA_MAX_BYTES + 4)
        except Exception as exc:
            raise DataArtifactBackendError("Redis artifact read failed") from exc
        if raw is None or (self._max_bytes is not None and raw == b""):
            raise DataArtifactNotFoundError("Artifact not found in the supplied scope")
        metadata, offset = _envelope_metadata(raw, data_ref=data_ref, scope=scope)
        if metadata.expires_at <= self._clock():
            await self.delete(data_ref, scope=scope)
            raise DataArtifactNotFoundError("Artifact not found in the supplied scope")
        _check_payload_budget(metadata, self._max_bytes, len(raw) - offset)
        return DataArtifact(metadata=metadata, data=raw[offset:])

    async def delete(self, data_ref: str, *, scope: ArtifactScope) -> bool:
        self._require_started()
        key = _artifact_key(data_ref, scope)
        try:
            return bool(await self._client.delete(key))
        except Exception as exc:
            raise DataArtifactBackendError("Redis artifact delete failed") from exc
