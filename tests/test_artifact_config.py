"""Verify immutable backend configuration and selected-store construction."""

import builtins
from dataclasses import FrozenInstanceError
import os
import unittest
from unittest.mock import patch

from nlalpha.core.artifact_config import ArtifactStoreConfig, create_data_artifact_store


class ArtifactConfigTests(unittest.TestCase):
    def test_defaults_and_legacy_settings_are_independent(self):
        with patch.dict(os.environ, {"NLALPHA_DRAWER_BACKEND": "s3", "NLALPHA_DRAWER_MAX_BYTES": "10"}, clear=True):
            config = ArtifactStoreConfig.from_env()
        self.assertEqual(config.backend, "redis")
        self.assertEqual(config.redis_url, "redis://127.0.0.1:6379/0")
        self.assertEqual(config.ttl_seconds, 86400)
        self.assertIsNone(config.max_bytes)

    def test_configuration_is_frozen_and_application_local(self):
        with patch.dict(os.environ, {"NLALPHA_ARTIFACT_TTL_SECONDS": "12.5"}, clear=True):
            first = ArtifactStoreConfig.from_env()
        with patch.dict(os.environ, {"NLALPHA_ARTIFACT_MAX_BYTES": "25"}, clear=True):
            second = ArtifactStoreConfig.from_env()
        self.assertEqual(first.ttl_seconds, 12.5)
        self.assertIsNone(first.max_bytes)
        self.assertEqual(second.max_bytes, 25)
        self.assertEqual(second.ttl_seconds, 86400)
        with self.assertRaises(FrozenInstanceError):
            first.backend = "s3"

    def test_invalid_values_fail_without_echoing_input(self):
        cases = [
            {"NLALPHA_ARTIFACT_BACKEND": "unknown"},
            *({"NLALPHA_ARTIFACT_TTL_SECONDS": value} for value in ("0", "-1", "nan", "inf", "secret")),
            *({"NLALPHA_ARTIFACT_MAX_BYTES": value} for value in ("", "0", "-1", "1.5", "secret")),
            {"NLALPHA_ARTIFACT_REDIS_URL": ""},
            {"NLALPHA_ARTIFACT_BACKEND": "s3"},
            {"NLALPHA_ARTIFACT_BACKEND": "s3", "NLALPHA_ARTIFACT_S3_BUCKET": "bucket", "NLALPHA_ARTIFACT_S3_ACCESS_KEY": "secret"},
            *({"NLALPHA_ARTIFACT_BACKEND": "s3", "NLALPHA_ARTIFACT_S3_BUCKET": "bucket", "NLALPHA_ARTIFACT_S3_RETENTION_DAYS": value} for value in ("0", "-1", "1.5")),
            {"NLALPHA_ARTIFACT_BACKEND": "s3", "NLALPHA_ARTIFACT_S3_BUCKET": "bucket", "NLALPHA_ARTIFACT_TTL_SECONDS": "86401"},
        ]
        for values in cases:
            with self.subTest(values=values), patch.dict(os.environ, values, clear=True):
                with self.assertRaises(ValueError) as raised:
                    ArtifactStoreConfig.from_env()
                self.assertNotIn("secret", str(raised.exception).replace("secret_key", ""))

    def test_sensitive_values_are_absent_from_repr(self):
        config = ArtifactStoreConfig(
            backend="s3", bucket="bucket", redis_url="redis://private", endpoint_url="https://private",
            access_key="access-sensitive", secret_key="secret-sensitive",
        )
        for value in ("redis://private", "https://private", "access-sensitive", "secret-sensitive"):
            self.assertNotIn(value, repr(config))

    def test_redis_constructs_only_selected_backend_without_starting(self):
        config = ArtifactStoreConfig(ttl_seconds=30, max_bytes=100)
        with patch("nlalpha.core.data_artifacts.RedisDataArtifactStore") as redis:
            with patch("nlalpha.core.data_artifacts_s3.S3DataArtifactStore") as s3:
                result = create_data_artifact_store(config)
        redis.assert_called_once_with(config.redis_url, ttl_seconds=30, max_bytes=100)
        s3.assert_not_called()
        result.start.assert_not_called()

    def test_s3_assembly_avoids_redis_import_and_uses_sdk_defaults(self):
        original_import = builtins.__import__

        def checked_import(name, *args, **kwargs):
            if name == "redis" or name.startswith("redis."):
                raise AssertionError("S3 must not import Redis")
            return original_import(name, *args, **kwargs)

        with patch.dict(os.environ, {"NLALPHA_ARTIFACT_BACKEND": "s3", "NLALPHA_ARTIFACT_S3_BUCKET": "bucket"}, clear=True):
            with patch("nlalpha.core.data_artifacts_s3.S3DataArtifactStore") as s3:
                with patch("builtins.__import__", side_effect=checked_import):
                    result = create_data_artifact_store()
        s3.assert_called_once_with(
            "bucket", endpoint_url=None, access_key=None, secret_key=None, region=None,
            retention_days=1, ttl_seconds=86400, max_bytes=None,
        )
        result.start.assert_not_called()

    def test_s3_explicit_settings_and_selected_backend_validation(self):
        values = {
            "NLALPHA_ARTIFACT_BACKEND": "s3", "NLALPHA_ARTIFACT_S3_BUCKET": "bucket",
            "NLALPHA_ARTIFACT_S3_ENDPOINT": "https://storage", "NLALPHA_ARTIFACT_S3_ACCESS_KEY": "key",
            "NLALPHA_ARTIFACT_S3_SECRET_KEY": "credential", "NLALPHA_ARTIFACT_S3_REGION": "region",
            "NLALPHA_ARTIFACT_S3_RETENTION_DAYS": "2", "NLALPHA_ARTIFACT_TTL_SECONDS": "172800",
            "NLALPHA_ARTIFACT_REDIS_URL": "",
        }
        with patch.dict(os.environ, values, clear=True):
            config = ArtifactStoreConfig.from_env()
        self.assertEqual((config.endpoint_url, config.access_key, config.secret_key, config.region),
                         ("https://storage", "key", "credential", "region"))
        self.assertEqual((config.retention_days, config.ttl_seconds), (2, 172800))
        with patch.dict(os.environ, {"NLALPHA_ARTIFACT_S3_RETENTION_DAYS": "invalid"}, clear=True):
            self.assertEqual(ArtifactStoreConfig.from_env().backend, "redis")

    def test_backend_constructor_failure_propagates(self):
        with patch("nlalpha.core.data_artifacts.RedisDataArtifactStore", side_effect=RuntimeError("failed")):
            with self.assertRaisesRegex(RuntimeError, "failed"):
                create_data_artifact_store(ArtifactStoreConfig())
