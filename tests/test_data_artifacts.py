"""Contract and lifecycle tests for immutable data artifacts."""

from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import FrozenInstanceError, asdict, replace
from unittest.mock import AsyncMock, patch

from nlalpha.core.data_artifacts import (
    ArtifactMetadata, ArtifactScope, DataArtifact, DataArtifactBackendError,
    DataArtifactError, DataArtifactNotFoundError, RedisDataArtifactStore,
    _artifact_key, _decode_artifact, _encode_artifact,
    _METADATA_MAX_BYTES,
)


SCOPE = ArtifactScope("test", "alice")
REF = "ref_" + "a" * 32


def artifact(data=b"payload") -> DataArtifact:
    """Create one deterministic artifact for contract tests."""
    return DataArtifact(ArtifactMetadata(
        data_ref=REF, scope=SCOPE, media_type="application/json", schema="bars.v1",
        size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
        created_at=100.0, expires_at=200.0,
    ), data)


def altered_envelope(**changes) -> bytes:
    """Encode altered metadata for corruption validation."""
    item = artifact()
    fields = asdict(item.metadata)
    fields.update(changes)
    raw = json.dumps(fields).encode()
    return len(raw).to_bytes(4, "big") + raw + item.data


class ArtifactContractTest(unittest.TestCase):
    def test_scope_is_required_and_immutable(self) -> None:
        for environment, owner in (("", "a"), ("a", " "), (None, "a"), ("a", None)):
            with self.subTest(environment=environment, owner=owner):
                with self.assertRaises(DataArtifactError):
                    ArtifactScope(environment, owner)
        with self.assertRaises(FrozenInstanceError):
            SCOPE.owner = "bob"
        with self.assertRaises(DataArtifactError):
            _artifact_key(REF, None)
        with self.assertRaises(FrozenInstanceError):
            artifact().metadata.schema = "new.v1"

    def test_scoped_keys_use_unambiguous_identity(self) -> None:
        scopes = [ArtifactScope("a:b", "c"), ArtifactScope("a", "b:c"),
                  ArtifactScope("prod", "alice"), ArtifactScope("test", "alice")]
        self.assertEqual(len({_artifact_key(REF, scope) for scope in scopes}), 4)
        self.assertNotIn("alice", _artifact_key(REF, SCOPE))
        self.assertEqual(_artifact_key(REF, SCOPE), _artifact_key(REF, ArtifactScope("test", "alice")))

    def test_references_reject_paths_and_partial_matches(self) -> None:
        for value in (None, "", "../ref_" + "a" * 32, REF + "\n", REF.upper(), "ref_123"):
            with self.subTest(value=value), self.assertRaises(DataArtifactError):
                _artifact_key(value, SCOPE)

    def test_envelope_round_trip_preserves_binary_bytes(self) -> None:
        item = artifact(b"\x00\xff\xfe{}\n")
        self.assertEqual(_decode_artifact(_encode_artifact(item), data_ref=REF, scope=SCOPE), item)
        with self.assertRaises(DataArtifactError):
            DataArtifact(item.metadata, bytearray(item.data))

    def test_parameterized_schema_identifier_round_trips(self) -> None:
        original = artifact()
        metadata = replace(original.metadata, schema="nlalpha.market.bar.v2:volume=instrument_quantity")
        item = DataArtifact(metadata, original.data)
        self.assertEqual(_decode_artifact(_encode_artifact(item), data_ref=REF, scope=SCOPE), item)

    def test_metadata_protocol_budget_applies_to_encoding_and_decoding(self) -> None:
        item = artifact()
        oversized = DataArtifact(replace(item.metadata, schema="x" * _METADATA_MAX_BYTES), item.data)
        with self.assertRaisesRegex(DataArtifactError, "metadata.*64 KiB"):
            _encode_artifact(oversized)
        raw = (_METADATA_MAX_BYTES + 1).to_bytes(4, "big") + b"{}"
        with self.assertRaisesRegex(DataArtifactError, "metadata length"):
            _decode_artifact(raw, data_ref=REF, scope=SCOPE)

    def test_corruption_is_explicit(self) -> None:
        valid = _encode_artifact(artifact())
        utf16_metadata = json.dumps(asdict(artifact().metadata)).encode("utf-16")
        cases = [
            len(utf16_metadata).to_bytes(4, "big") + utf16_metadata + artifact().data,
            b"", b"\x00\x00\x00\x00", b"\xff" * 4, b"\x00\x00\x00\x01\xff",
            valid[:-1], valid[:-1] + b"!", altered_envelope(size_bytes=True),
            altered_envelope(size_bytes=999), altered_envelope(sha256="0" * 64),
            altered_envelope(schema=""), altered_envelope(media_type="json"),
            altered_envelope(created_at=float("nan")), altered_envelope(expires_at=99),
            altered_envelope(data_ref="ref_" + "b" * 32),
            altered_envelope(scope={"environment": "test", "owner": "bob"}),
            altered_envelope(unexpected="field"),
        ]
        for raw in cases:
            with self.subTest(raw=raw[:80]), self.assertRaises(DataArtifactError):
                _decode_artifact(raw, data_ref=REF, scope=SCOPE)

    def test_configuration_rejects_invalid_limits(self) -> None:
        for value in (0, -1, float("nan"), float("inf"), True, "1"):
            with self.subTest(ttl=value), self.assertRaises(DataArtifactError):
                RedisDataArtifactStore(client=AsyncMock(), ttl_seconds=value)
        for value in (0, -1, True, 1.5):
            with self.subTest(max_bytes=value), self.assertRaises(DataArtifactError):
                RedisDataArtifactStore(client=AsyncMock(), max_bytes=value)


class ArtifactLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_borrowed_client_remains_open_after_store_close(self) -> None:
        client = AsyncMock()
        store = RedisDataArtifactStore(client=client)
        with self.assertRaises(DataArtifactBackendError):
            await store.read(REF, scope=SCOPE)
        await store.start()
        await store.aclose()
        client.aclose.assert_not_awaited()
        with self.assertRaises(DataArtifactBackendError):
            await store.start()
        with self.assertRaises(DataArtifactBackendError):
            await store.publish(b"x", scope=SCOPE, media_type="text/plain", schema="v1")

    async def test_health_uses_live_client_and_recovers_without_restart(self) -> None:
        client = AsyncMock()
        client.ping.return_value = True
        store = RedisDataArtifactStore(client=client)
        with self.assertRaises(DataArtifactBackendError):
            await store.check_health()
        client.ping.assert_not_awaited()
        await store.start()
        self.assertIsNone(await store.check_health())
        failure = OSError("redis://user:secret@private")
        client.ping.side_effect = failure
        with self.assertRaises(DataArtifactBackendError) as caught:
            await store.check_health()
        self.assertIs(caught.exception.__cause__, failure)
        self.assertNotIn("secret", str(caught.exception))
        client.aclose.assert_not_awaited()
        client.ping.side_effect = None
        client.ping.return_value = False
        with self.assertRaises(DataArtifactBackendError):
            await store.check_health()
        client.ping.return_value = True
        self.assertIsNone(await store.check_health())
        await store.aclose()
        client.ping.reset_mock()
        with self.assertRaises(DataArtifactBackendError):
            await store.check_health()
        client.ping.assert_not_awaited()

    async def test_owned_client_is_closed_with_store(self) -> None:
        client = AsyncMock()
        with patch("redis.asyncio.Redis.from_url", return_value=client):
            store = RedisDataArtifactStore("redis://localhost:6379/0")
        await store.start()
        await store.aclose()
        client.aclose.assert_awaited()
        await store.aclose()

    async def test_readiness_failure_closes_owned_client_and_preserves_cause(self) -> None:
        client = AsyncMock()
        failure = OSError("backend unavailable")
        client.ping.side_effect = failure
        with patch("redis.asyncio.Redis.from_url", return_value=client):
            store = RedisDataArtifactStore("redis://:secret@localhost:6379/0")
        with self.assertRaises(DataArtifactBackendError) as caught:
            await store.start()
        self.assertIs(caught.exception.__cause__, failure)
        self.assertNotIn("secret", str(caught.exception))
        client.aclose.assert_awaited()

    async def test_false_readiness_is_an_error(self) -> None:
        client = AsyncMock()
        client.ping.return_value = False
        store = RedisDataArtifactStore(client=client)
        with self.assertRaises(DataArtifactBackendError):
            await store.start()
        client.aclose.assert_not_awaited()

    async def test_expired_envelope_is_deleted_before_not_found(self) -> None:
        client = AsyncMock()
        client.get.return_value = _encode_artifact(artifact())
        store = RedisDataArtifactStore(client=client, clock=lambda: 201)
        await store.start()
        with self.assertRaises(DataArtifactNotFoundError):
            await store.read(REF, scope=SCOPE)
        client.delete.assert_awaited_with(_artifact_key(REF, SCOPE))
        client.delete.side_effect = OSError("delete failed")
        with self.assertRaises(DataArtifactBackendError):
            await store.read(REF, scope=SCOPE)

    async def test_limits_and_inputs_fail_before_publication(self) -> None:
        store = RedisDataArtifactStore(client=AsyncMock(), max_bytes=3)
        await store.start()
        for data, scope, ttl in ((b"four", SCOPE, None), ("x", SCOPE, None),
                                 (b"x", None, None), (b"x", SCOPE, 0)):
            with self.subTest(data=data, scope=scope, ttl=ttl):
                with self.assertRaises(DataArtifactError):
                    await store.publish(data, scope=scope, media_type="text/plain", schema="v1", ttl_seconds=ttl)

    async def test_backend_failures_are_not_reported_as_missing(self) -> None:
        client = AsyncMock()
        store = RedisDataArtifactStore(client=client)
        await store.start()
        client.get.side_effect = OSError("read failed")
        client.delete.side_effect = OSError("delete failed")
        with self.assertRaises(DataArtifactBackendError):
            await store.read(REF, scope=SCOPE)
        with self.assertRaises(DataArtifactBackendError):
            await store.delete(REF, scope=SCOPE)


if __name__ == "__main__":
    unittest.main()
