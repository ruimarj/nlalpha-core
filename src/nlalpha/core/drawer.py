"""Shared data drawer for inter-MCP data exchange.

抽屉：所有 MCP server 共享的数据交换层。
MCP 工具之间只传递 data_ref（轻量引用），实际数据留在抽屉里。
"""

from __future__ import annotations

import os
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class DrawerBackend(ABC):
    """Abstract drawer backend."""

    @abstractmethod
    def put(self, key: str, data: bytes) -> str:
        """Store data by key. Returns storage path."""
        ...

    @abstractmethod
    def get(self, key: str) -> bytes | None:
        """Retrieve data by key. Returns None if not found."""
        ...

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if key exists."""
        ...

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Remove data by key. Returns True if deleted."""
        ...


class FilesystemBackend(DrawerBackend):
    """Filesystem-backed drawer.

    Stores files under NLALPHA_DRAWER_DIR (default: workspace/drawer).
    """

    def __init__(self, base_dir: str | None = None) -> None:
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            _workspace = os.getenv("NLALPHA_WORKSPACE_DIR", str(Path.cwd() / "workspace"))
            self.base_dir = Path(os.getenv("NLALPHA_DRAWER_DIR", os.path.join(_workspace, "drawer")))
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = self.base_dir / "data"
        self.data_dir.mkdir(exist_ok=True)

    def put(self, key: str, data: bytes) -> str:
        path = self._path(key)
        path.write_bytes(data)
        return str(path)

    def get(self, key: str) -> bytes | None:
        path = self._path(key)
        return path.read_bytes() if path.exists() else None

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if path.exists():
            path.unlink()
            return True
        return False

    def _path(self, key: str) -> Path:
        safe = key.replace("/", "_").replace(":", "_")
        return self.data_dir / safe


# ---------------------------------------------------------------------------
# Ref index: data_ref → key mapping (file-backed for cross-process sharing)
# ---------------------------------------------------------------------------

_ref_index_path: Path | None = None


def _get_index_path() -> Path:
    global _ref_index_path
    if _ref_index_path is None:
        _workspace = os.getenv("NLALPHA_WORKSPACE_DIR", str(Path.cwd() / "workspace"))
        _ref_index_path = Path(os.getenv("NLALPHA_DRAWER_DIR", os.path.join(_workspace, "drawer"))) / "index.json"
        _ref_index_path.parent.mkdir(parents=True, exist_ok=True)
    return _ref_index_path


def _load_index() -> dict[str, str]:
    path = _get_index_path()
    if path.exists():
        import json
        return json.loads(path.read_text())
    return {}


def _save_index(index: dict[str, str]) -> None:
    path = _get_index_path()
    import json
    path.write_text(json.dumps(index, indent=2))


def generate_ref() -> str:
    """Generate a unique data_ref."""
    return f"ref_{uuid.uuid4().hex[:12]}"


def register_ref(data_ref: str, key: str) -> None:
    """Register a data_ref → key mapping (file-backed, cross-process)."""
    index = _load_index()
    index[data_ref] = key
    _save_index(index)


def resolve_ref(data_ref: str) -> str | None:
    """Resolve data_ref to drawer key. Returns None if unknown."""
    return _load_index().get(data_ref)


def get_drawer() -> DrawerBackend:
    """Factory: return configured drawer backend."""
    backend = os.getenv("NLALPHA_DRAWER_BACKEND", "filesystem")
    if backend == "filesystem":
        return FilesystemBackend()
    raise ValueError(f"Unknown drawer backend: {backend}")
