"""Verify host identity boundaries, scope isolation, and DNS allowlists."""

from dataclasses import FrozenInstanceError
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from nlalpha.core.data_artifacts import ArtifactScope
from nlalpha.core.errors import INVALID_REQUEST
from nlalpha.core.platform import HostIdentityConfig, HostIdentityError, resolve_allowed_hosts


def context(headers):
    return SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(headers=headers)))


class HostIdentityTests(unittest.TestCase):
    def test_single_user_anonymous_scope_and_header_rejection(self):
        config = HostIdentityConfig()
        for ctx in (None, SimpleNamespace(), context({})):
            self.assertEqual(config.resolve(ctx), ArtifactScope("local", "standalone"))
        for value in ("alice", "", None):
            with self.assertRaisesRegex(HostIdentityError, "trusted-host") as raised:
                config.resolve(context({"x-nlalpha-user-id": value}))
            self.assertEqual(raised.exception.error_type, INVALID_REQUEST)

    def test_trusted_host_requires_valid_http_identity(self):
        config = HostIdentityConfig(mode="trusted-host")
        for ctx in (None, SimpleNamespace(user_id="alice"), context({}),
                    *(context({config.user_header: value}) for value in ("", " ", None, 12, "alice\r\nother", "alice\x00", "\nalice"))):
            with self.subTest(ctx=ctx), self.assertRaises(HostIdentityError):
                config.resolve(ctx)
        self.assertEqual(config.resolve(context({"x-nlalpha-user-id": " alice "})), ArtifactScope("local", "alice"))

    def test_scopes_and_configuration_remain_application_local(self):
        with patch.dict(os.environ, {"NLALPHA_IDENTITY_MODE": "trusted-host", "NLALPHA_ENV": "dev", "NLALPHA_IDENTITY_USER_HEADER": "X-User"}, clear=True):
            first = HostIdentityConfig.from_env()
        with patch.dict(os.environ, {"NLALPHA_ENV": "test"}, clear=True):
            second = HostIdentityConfig.from_env()
        alice = first.resolve(context({"X-User": "alice"}))
        bob = first.resolve(context({"X-User": "bob"}))
        self.assertEqual(alice, ArtifactScope("dev", "alice"))
        self.assertEqual(bob, ArtifactScope("dev", "bob"))
        self.assertEqual(second.resolve(None), ArtifactScope("test", "standalone"))
        self.assertEqual(HostIdentityConfig(mode="trusted-host", environment="other").resolve(context({"X-NLAlpha-User-ID": "alice"})), ArtifactScope("other", "alice"))
        with self.assertRaises(HostIdentityError):
            first.resolve(None)
        with self.assertRaises(FrozenInstanceError):
            first.environment = "other"

    def test_invalid_identity_configuration_fails(self):
        for values in ({"mode": "auto"}, {"environment": ""}, {"environment": "bad\n"},
                       {"user_header": ""}, {"user_header": "X User"}, {"user_header": "X\x00User"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                HostIdentityConfig(**values)

    def test_allowed_hosts_safe_defaults_and_configuration_precedence(self):
        with patch.dict(os.environ, {}, clear=True):
            defaults = resolve_allowed_hosts()
        self.assertEqual(defaults, ["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*", "[::1]", "[::1]:*"])
        with patch.dict(os.environ, {"NLALPHA_ALLOWED_HOSTS": "a.example:*, b.example"}, clear=True):
            self.assertEqual(resolve_allowed_hosts(), ["a.example:*", "b.example"])
            self.assertEqual(resolve_allowed_hosts(("explicit.example:*",)), ["explicit.example:*"])
        defaults.append("changed")
        with patch.dict(os.environ, {}, clear=True):
            self.assertNotIn("changed", resolve_allowed_hosts())

    def test_empty_or_unrestricted_allowed_hosts_fail(self):
        for value in ([], [""], ["*"], ["*:*"], ["*:8000"], ["localhost", "*"], ["x\x00"], ["x y"], "localhost"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                resolve_allowed_hosts(value)
        for value in ("", " ", "*", "localhost,"):
            with patch.dict(os.environ, {"NLALPHA_ALLOWED_HOSTS": value}, clear=True):
                with self.assertRaises(ValueError):
                    resolve_allowed_hosts()
