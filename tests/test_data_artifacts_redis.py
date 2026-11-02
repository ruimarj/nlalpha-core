"""Integration tests against an isolated Redis process using a Unix socket."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
import time
import unittest
import uuid
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from redis.asyncio import Redis

from nlalpha.core.data_artifacts import (
    ArtifactScope, DataArtifactBackendError, DataArtifactError,
    DataArtifactNotFoundError, RedisDataArtifactStore, _artifact_key, _METADATA_MAX_BYTES,
)


class RedisArtifactTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """Start a disposable local Redis without network listeners or persistence."""
        super().setUpClass()
        cls.directory = tempfile.TemporaryDirectory(prefix="nlalpha-artifacts-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.socket_path = str(Path(cls.directory.name) / "redis.sock")
        cls.log_path = Path(cls.directory.name) / "redis.log"
        cls.process = subprocess.Popen([
            "/usr/bin/redis-server", "--port", "0", "--unixsocket", cls.socket_path,
            "--unixsocketperm", "700", "--save", "", "--appendonly", "no",
            "--dir", cls.directory.name, "--logfile", str(cls.log_path),
        ], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        cls.addClassCleanup(cls.stop_redis)
        deadline = time.monotonic() + 5
        while not os.path.exists(cls.socket_path):
            if cls.process.poll() is not None:
                raise RuntimeError(f"isolated Redis exited during startup: {cls.log_path.read_text()}")
            if time.monotonic() >= deadline:
                raise TimeoutError("isolated Redis socket did not become ready")
            time.sleep(0.01)

    @classmethod
    def stop_redis(cls) -> None:
        """Reap the isolated server before deleting its temporary directory."""
        cls.process.terminate()
        try:
            cls.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait()
            raise

    async def asyncSetUp(self) -> None:
        self.client = Redis(unix_socket_path=self.socket_path, decode_responses=False)
        self.addAsyncCleanup(self.client.aclose)
        await self.client.flushdb()
        self.store = RedisDataArtifactStore(client=self.client)
        self.addAsyncCleanup(self.store.aclose)
        await self.store.start()
        self.scope = ArtifactScope("test", "alice")

    async def publish(self, data: bytes, **kwargs):
        """Publish a test payload with its explicit schema and scope."""
        return await self.store.publish(
            data, scope=self.scope, media_type="application/octet-stream", schema="test.v1", **kwargs
        )

    async def test_repeated_publication_never_changes_old_references(self) -> None:
        first = await self.publish(b"same")
        second = await self.publish(b"same")
        third = await self.publish(b"different")
        self.assertEqual(len({first.data_ref, second.data_ref, third.data_ref}), 3)
        for metadata, expected in ((first, b"same"), (second, b"same"), (third, b"different")):
            item = await self.store.read(metadata.data_ref, scope=self.scope)
            self.assertEqual(item.metadata, metadata)
            self.assertEqual(item.data, expected)

    async def test_concurrent_payloads_keep_their_own_digest(self) -> None:
        payloads = [f"payload-{index}".encode() for index in range(32)]
        metadata = await asyncio.gather(*(self.publish(data) for data in payloads))
        self.assertEqual(len({item.data_ref for item in metadata}), len(payloads))
        artifacts = await asyncio.gather(*(self.store.read(item.data_ref, scope=self.scope) for item in metadata))
        for item, expected in zip(artifacts, payloads):
            self.assertEqual(item.data, expected)
            self.assertEqual(item.metadata.sha256, hashlib.sha256(expected).hexdigest())

    async def test_real_write_failure_preserves_existing_artifact(self) -> None:
        old = await self.publish(b"retained")
        await self.client.config_set("maxmemory", 1)
        try:
            with self.assertRaises(DataArtifactBackendError):
                await self.publish(b"rejected")
        finally:
            await self.client.config_set("maxmemory", 0)
        self.assertEqual((await self.store.read(old.data_ref, scope=self.scope)).data, b"retained")
        self.assertEqual(await self.client.dbsize(), 1)

    async def test_reference_collision_cannot_overwrite(self) -> None:
        old = await self.publish(b"original")
        with patch("nlalpha.core.data_artifacts.uuid.uuid4", return_value=uuid.UUID(hex=old.data_ref[4:])):
            with self.assertRaises(DataArtifactBackendError):
                await self.publish(b"replacement")
        self.assertEqual((await self.store.read(old.data_ref, scope=self.scope)).data, b"original")

    async def test_independent_physical_expiry_and_reads_do_not_extend_ttl(self) -> None:
        first = await self.publish(b"short", ttl_seconds=0.6)
        first_key = _artifact_key(first.data_ref, self.scope)
        before = await self.client.pttl(first_key)
        await asyncio.sleep(0.25)
        second = await self.publish(b"long", ttl_seconds=2)
        await self.store.read(first.data_ref, scope=self.scope)
        self.assertLess(await self.client.pttl(first_key), before)
        await asyncio.sleep(0.45)
        self.assertIsNone(await self.client.get(first_key))
        with self.assertRaises(DataArtifactNotFoundError):
            await self.store.read(first.data_ref, scope=self.scope)
        self.assertEqual((await self.store.read(second.data_ref, scope=self.scope)).data, b"long")

    async def test_scope_and_environment_are_isolated_for_reads_and_deletes(self) -> None:
        metadata = await self.publish(b"private")
        for scope in (ArtifactScope("test", "bob"), ArtifactScope("prod", "alice")):
            with self.subTest(scope=scope):
                with self.assertRaises(DataArtifactNotFoundError):
                    await self.store.read(metadata.data_ref, scope=scope)
                self.assertFalse(await self.store.delete(metadata.data_ref, scope=scope))
        self.assertEqual((await self.store.read(metadata.data_ref, scope=self.scope)).data, b"private")
        self.assertTrue(await self.store.delete(metadata.data_ref, scope=self.scope))
        self.assertFalse(await self.store.delete(metadata.data_ref, scope=self.scope))

    async def test_corrupt_backend_payload_is_rejected(self) -> None:
        metadata = await self.publish(b"original")
        key = _artifact_key(metadata.data_ref, self.scope)
        raw = await self.client.get(key)
        await self.client.set(key, raw[:-1] + b"!")
        with self.assertRaises(DataArtifactError):
            await self.store.read(metadata.data_ref, scope=self.scope)

    async def test_metadata_expiry_physically_deletes_an_envelope(self) -> None:
        store = RedisDataArtifactStore(client=self.client, clock=lambda: 100)
        await store.start()
        self.addAsyncCleanup(store.aclose)
        metadata = await store.publish(b"old", scope=self.scope, media_type="text/plain", schema="v1", ttl_seconds=10)
        key = _artifact_key(metadata.data_ref, self.scope)
        self.assertIsNotNone(await self.client.get(key))
        with self.assertRaises(DataArtifactNotFoundError):
            await self.store.read(metadata.data_ref, scope=self.scope)
        self.assertIsNone(await self.client.get(key))

    async def test_eleven_mebibytes_use_the_selected_redis_backend(self) -> None:
        data = b"x" * (11 * 1024 * 1024)
        metadata = await self.publish(data)
        item = await self.store.read(metadata.data_ref, scope=self.scope)
        self.assertEqual(item.data, data)
        self.assertEqual(metadata.size_bytes, len(data))
        self.assertEqual(await self.client.dbsize(), 1)
        self.assertGreater(await self.client.strlen(_artifact_key(metadata.data_ref, self.scope)), len(data))
        bounded = RedisDataArtifactStore(client=self.client, max_bytes=len(data))
        await bounded.start()
        self.addAsyncCleanup(bounded.aclose)
        self.assertEqual((await bounded.read(metadata.data_ref, scope=self.scope)).data, data)

    async def test_reader_budget_bounds_fetched_bytes_and_preserves_the_object(self) -> None:
        data = b"x" * (1 << 20)
        metadata = await self.publish(data)
        key = _artifact_key(metadata.data_ref, self.scope)
        original = await self.client.get(key)
        low = RedisDataArtifactStore(client=self.client, max_bytes=16)
        high = RedisDataArtifactStore(client=self.client, max_bytes=len(data))
        for store in (low, high):
            await store.start()
            self.addAsyncCleanup(store.aclose)
        fetched = []
        getrange = self.client.getrange

        async def read_range(*args):
            raw = await getrange(*args)
            fetched.append(raw)
            return raw

        with patch.object(self.client, "getrange", side_effect=read_range), \
             patch.object(self.client, "get", side_effect=AssertionError("unbounded GET")):
            with self.assertRaisesRegex(DataArtifactError, "configured max_bytes"):
                await low.read(metadata.data_ref, scope=self.scope)
        self.assertEqual(len(fetched), 1)
        self.assertEqual(len(fetched[0]), 16 + _METADATA_MAX_BYTES + 4 + 1)
        self.assertLess(len(fetched[0]), len(original))
        self.assertEqual(await self.client.get(key), original)
        self.assertEqual((await high.read(metadata.data_ref, scope=self.scope)).data, data)

    async def test_reader_checks_actual_payload_budget_before_hashing_corrupt_metadata(self) -> None:
        data = b"x" * (1 << 20)
        metadata = await self.publish(data)
        fields = asdict(metadata)
        fields.update(size_bytes=0, sha256=hashlib.sha256(b"").hexdigest())
        encoded = json.dumps(fields).encode()
        raw = len(encoded).to_bytes(4, "big") + encoded + data
        key = _artifact_key(metadata.data_ref, self.scope)
        await self.client.set(key, raw)
        low = RedisDataArtifactStore(client=self.client, max_bytes=1)
        await low.start()
        self.addAsyncCleanup(low.aclose)
        with self.assertRaisesRegex(DataArtifactError, "configured max_bytes"):
            await low.read(metadata.data_ref, scope=self.scope)
        self.assertEqual(await self.client.get(key), raw)

    async def test_bounded_reader_preserves_empty_missing_scope_and_expiry_semantics(self) -> None:
        low = RedisDataArtifactStore(client=self.client, max_bytes=1)
        await low.start()
        self.addAsyncCleanup(low.aclose)
        empty = await self.publish(b"")
        self.assertEqual((await low.read(empty.data_ref, scope=self.scope)).data, b"")
        for reference, scope in (("ref_" + "0" * 32, self.scope),
                                 (empty.data_ref, ArtifactScope("test", "bob"))):
            with self.subTest(reference=reference, scope=scope), self.assertRaises(DataArtifactNotFoundError):
                await low.read(reference, scope=scope)
        writer = RedisDataArtifactStore(client=self.client, clock=lambda: 100)
        await writer.start()
        self.addAsyncCleanup(writer.aclose)
        expired = await writer.publish(b"oversized", scope=self.scope, media_type="text/plain", schema="v1", ttl_seconds=10)
        with self.assertRaises(DataArtifactNotFoundError):
            await low.read(expired.data_ref, scope=self.scope)
        self.assertIsNone(await self.client.get(_artifact_key(expired.data_ref, self.scope)))

    async def test_owned_url_client_is_ready_and_closed(self) -> None:
        store = RedisDataArtifactStore(f"unix://{self.socket_path}")
        self.addAsyncCleanup(store.aclose)
        await store.start()
        metadata = await store.publish(b"owned", scope=self.scope, media_type="text/plain", schema="v1")
        self.assertEqual((await store.read(metadata.data_ref, scope=self.scope)).data, b"owned")
        await store.aclose()
        with self.assertRaises(DataArtifactBackendError):
            await store.read(metadata.data_ref, scope=self.scope)
        self.assertTrue(await self.client.ping())


if __name__ == "__main__":
    unittest.main()
