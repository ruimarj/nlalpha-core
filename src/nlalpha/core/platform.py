"""Host-agnostic identity helpers for nlalpha MCP servers.

Identity protocol details are configurable by the host application.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from nlalpha.core.data_artifacts import ArtifactScope
from nlalpha.core.errors import INVALID_REQUEST, NlAlphaError

DEFAULT_IDENTITY_USER_HEADER = "X-NLAlpha-User-ID"


class HostIdentityError(NlAlphaError):
    """The request cannot establish an identity under the configured host mode."""

    error_type = INVALID_REQUEST


@dataclass(frozen=True)
class HostIdentityConfig:
    """Resolve explicit scopes using a host-owned trusted HTTP boundary."""

    mode: str = "single-user"
    environment: str = "local"
    user_header: str = DEFAULT_IDENTITY_USER_HEADER

    def __post_init__(self) -> None:
        if self.mode not in ("single-user", "trusted-host"):
            raise ValueError("identity mode must be single-user or trusted-host")
        for name in ("environment", "user_header"):
            value = getattr(self, name)
            if (not isinstance(value, str) or not value.strip()
                    or any(char in value for char in "\r\n\x00")):
                raise ValueError(f"identity {name} must be a nonempty safe string")
        if any(char.isspace() for char in self.user_header):
            raise ValueError("identity user_header must not contain whitespace")

    @classmethod
    def from_env(cls) -> HostIdentityConfig:
        """Snapshot identity settings for one application instance."""
        return cls(
            mode=os.getenv("NLALPHA_IDENTITY_MODE", "single-user"),
            environment=os.getenv("NLALPHA_ENV", "local"),
            user_header=os.getenv("NLALPHA_IDENTITY_USER_HEADER", DEFAULT_IDENTITY_USER_HEADER),
        )

    def resolve(self, ctx: Any | None) -> ArtifactScope:
        """Resolve the request header supplied by the host's trusted gateway."""
        request_context = getattr(ctx, "request_context", None)
        request = getattr(request_context, "request", None)
        headers = getattr(request, "headers", None)
        present = False
        value = None
        if headers is not None:
            for key in headers:
                if str(key).lower() == self.user_header.lower():
                    present = True
                    value = headers[key]
                    break
        if self.mode == "single-user":
            if present:
                raise HostIdentityError("Identity headers require trusted-host identity mode")
            return ArtifactScope(self.environment, "standalone")
        if (not present or not isinstance(value, str) or not value.strip()
                or any(char in value for char in "\r\n\x00")):
            raise HostIdentityError("trusted-host requires a nonempty valid HTTP identity header")
        return ArtifactScope(self.environment, value.strip())


def resolve_allowed_hosts(explicit: list[str] | tuple[str, ...] | None = None) -> list[str]:
    """Resolve an explicit DNS rebinding allowlist for one MCP application."""
    if explicit is not None:
        if not isinstance(explicit, (list, tuple)):
            raise ValueError("allowed hosts must be a list or tuple")
        values = list(explicit)
    elif "NLALPHA_ALLOWED_HOSTS" in os.environ:
        values = os.environ["NLALPHA_ALLOWED_HOSTS"].split(",")
    else:
        values = ["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*", "[::1]", "[::1]:*"]
    if not values:
        raise ValueError("allowed hosts must not be empty")
    hosts = []
    for value in values:
        if not isinstance(value, str) or not value.strip() or value.strip() == "*":
            raise ValueError("allowed hosts require nonempty restricted host names")
        host = value.strip()
        if host.startswith("*:"):
            raise ValueError("allowed hosts must restrict the host name")
        if any(char.isspace() or char == "\x00" for char in host):
            raise ValueError("allowed hosts must not contain whitespace or NUL")
        hosts.append(host)
    return hosts
