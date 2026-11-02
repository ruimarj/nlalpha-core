"""Canonical failure envelope and deterministic response budget enforcement.

Builds the single agent-facing error object reused by MCP responses, runner
stderr payloads, and adapter evidence, and sheds oversized successful payloads
in the frozen priority order while never shedding the error block.
"""

from __future__ import annotations

import json
import os
import sysconfig
import traceback
from collections.abc import Iterator, Sequence
from typing import Any

from nlalpha.core.errors import (
    ERROR_STAGES,
    ERROR_TYPES,
    INTERNAL_ERROR,
    RETRYABLE_ERROR_TYPES,
)

# 预算常量（契约 §3.1 冻结值）。
RESPONSE_BUDGET_BYTES = 256 * 1024
ERROR_BUDGET_BYTES = 16 * 1024
ERROR_MESSAGE_BUDGET_BYTES = 2 * 1024
ERROR_SUGGESTION_BUDGET_BYTES = 1024
ERROR_TRACEBACK_BUDGET_BYTES = 4 * 1024
ERROR_DETAILS_BUDGET_BYTES = 8 * 1024
TRACEBACK_MAX_FRAMES = 15
DETAILS_LIST_ITEM_LIMIT = 10
DETAILS_LIST_ITEM_BYTES = 512
VALIDATION_ERRORS_LIMIT = 10
VALIDATION_ERROR_ITEM_BYTES = 512
EQUITY_CURVE_LIMIT = 200
TRADE_DETAILS_LIMIT = 20
EVENT_ORDER_DETAILS_LIMIT = 100
ASSUMPTIONS_WARNINGS_LIMIT = 20
ASSUMPTIONS_WARNINGS_ITEM_BYTES = 256
NATIVE_ANALYSIS_BUDGET_BYTES = 8 * 1024
INPUT_METADATA_BUDGET_BYTES = 2 * 1024
REPRODUCIBILITY_BUDGET_BYTES = 2 * 1024
REPORTS_CATALOG_LIMIT = 50
BACKEND_EVIDENCE_BUDGET_BYTES = 8 * 1024
BACKEND_EVIDENCE_TAIL_BYTES = 2 * 1024

ERROR_KEY = "error"
RESULT_TRUNCATED_KEY = "result_truncated"
ERROR_FIELD_ORDER = (
    "type",
    "message",
    "stage",
    "retryable",
    "suggestion",
    "traceback_tail",
    "details",
)

_STDLIB_DIRS = tuple(
    sorted(
        {
            path.replace("\\", "/")
            for path in (
                sysconfig.get_paths().get("stdlib"),
                sysconfig.get_paths().get("platstdlib"),
            )
            if path
        }
    )
)


def clip_utf8(text: str, max_bytes: int) -> str:
    """Clip text to at most max_bytes of UTF-8 without splitting a code point."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _json_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _under(path: str, prefixes: tuple[str, ...]) -> bool:
    normalized = os.path.realpath(path).replace("\\", "/")
    for prefix in prefixes:
        real = os.path.realpath(prefix).replace("\\", "/")
        if normalized == real or normalized.startswith(real + "/"):
            return True
    return False


def _is_framework_frame(frame: Any) -> bool:
    """Return True for stdlib, installed, or nlalpha-package frames."""
    module = frame.f_globals.get("__name__", "")
    if module == "nlalpha" or module.startswith("nlalpha.") or module.startswith("nlalpha_"):
        return True
    filename = frame.f_code.co_filename
    if not filename:
        return True
    if filename.startswith("<frozen"):
        return True
    # 编译扩展的 co_filename 常为相对 .pyx，真实安装路径在 __file__。
    for candidate in (filename, frame.f_globals.get("__file__")):
        if not isinstance(candidate, str) or not candidate:
            continue
        normalized = candidate.replace("\\", "/")
        if "site-packages" in normalized or "dist-packages" in normalized:
            return True
        if _under(candidate, _STDLIB_DIRS):
            return True
    return False


def _related_exceptions(exc: BaseException) -> Iterator[BaseException]:
    """Yield an exception then its cause/context chain, guarded against cycles."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def format_traceback_tail(
    exc: BaseException,
    *,
    max_frames: int = TRACEBACK_MAX_FRAMES,
    max_bytes: int = ERROR_TRACEBACK_BUDGET_BYTES,
) -> str | None:
    """Format the last user or strategy frames, omitting the exception line.

    Frames are collected across the cause/context chain (wrapper first, then
    cause); framework frames are dropped and None is returned when no user frame exists.
    """
    pairs: list[tuple[Any, int]] = []
    for related in _related_exceptions(exc):
        tb = related.__traceback__
        while tb is not None:
            if not _is_framework_frame(tb.tb_frame):
                pairs.append((tb.tb_frame, tb.tb_lineno))
            tb = tb.tb_next
    if not pairs:
        return None
    summary = traceback.StackSummary.extract(pairs[-max_frames:], lookup_lines=True, capture_locals=False)
    return clip_utf8("".join(summary.format()), max_bytes)


def _resolve_traceback_tail(exc: BaseException) -> str | None:
    """Prefer an explicit non-empty traceback_tail, else walk the exception frames."""
    explicit = getattr(exc, "traceback_tail", None)
    if isinstance(explicit, str) and explicit:
        return clip_utf8(explicit, ERROR_TRACEBACK_BUDGET_BYTES)
    return format_traceback_tail(exc)


def _clip_json_value(value: Any, max_bytes: int) -> Any:
    if _json_bytes(value) <= max_bytes:
        return value
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    limit = max_bytes
    while limit > 0:
        clipped = clip_utf8(text, limit)
        if _json_bytes(clipped) <= max_bytes:
            return clipped
        limit = limit * 7 // 8
    return ""


def _trim_item(value: Any) -> Any:
    if isinstance(value, dict):
        value = _trim_lists(value)
    elif isinstance(value, list):
        value = [_trim_item(item) for item in value[:DETAILS_LIST_ITEM_LIMIT]]
    return _clip_json_value(value, DETAILS_LIST_ITEM_BYTES)


def _trim_lists(details: dict[str, Any]) -> dict[str, Any]:
    trimmed: dict[str, Any] = {}
    for key, value in details.items():
        if isinstance(value, list):
            trimmed[key] = [_trim_item(item) for item in value[:DETAILS_LIST_ITEM_LIMIT]]
            if len(value) > DETAILS_LIST_ITEM_LIMIT:
                marker = "errors_total" if key == "errors" else f"{key}_count"
                trimmed[marker] = len(value)
                trimmed[f"{key}_truncated"] = True
        elif isinstance(value, dict):
            trimmed[key] = _trim_lists(value)
        else:
            trimmed[key] = value
    return trimmed


def _fit_details(details: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    trimmed = _trim_lists(details)
    if _json_bytes(trimmed) <= max_bytes:
        return trimmed
    marker = {"details_truncated": True}
    while trimmed and _json_bytes({**trimmed, **marker}) > max_bytes:
        trimmed.popitem()
    trimmed.update(marker)
    return trimmed


def build_error(exc: BaseException, *, stage: str | None = None) -> dict[str, Any]:
    """Build the canonical ordered error object from any exception."""
    error_type = getattr(exc, "error_type", INTERNAL_ERROR)
    if error_type not in ERROR_TYPES:
        error_type = INTERNAL_ERROR

    raw_message = getattr(exc, "message", None) or str(exc)
    error: dict[str, Any] = {
        "type": error_type,
        "message": clip_utf8(str(raw_message), ERROR_MESSAGE_BUDGET_BYTES),
    }

    resolved_stage = stage if stage is not None else getattr(exc, "stage", None)
    if resolved_stage in ERROR_STAGES:
        error["stage"] = resolved_stage

    override = getattr(exc, "retryable", None)
    error["retryable"] = bool(override) if override is not None else error_type in RETRYABLE_ERROR_TYPES

    suggestion = getattr(exc, "suggestion", None)
    if suggestion:
        error["suggestion"] = clip_utf8(str(suggestion), ERROR_SUGGESTION_BUDGET_BYTES)

    tail = _resolve_traceback_tail(exc)
    if tail:
        error["traceback_tail"] = tail

    details = getattr(exc, "details", None)
    if isinstance(details, dict) and details:
        reserved = _json_bytes(error) + 64
        budget = min(ERROR_DETAILS_BUDGET_BYTES, max(0, ERROR_BUDGET_BYTES - reserved))
        fitted = _fit_details(details, budget)
        if fitted:
            error["details"] = fitted

    return error


def failure_response(exc: BaseException, *, stage: str | None = None) -> dict[str, Any]:
    """Wrap a canonical error object in the failed response envelope."""
    return {"status": "failed", "error": build_error(exc, stage=stage)}


def _trim_list(result: dict[str, Any], key: str, max_bytes: int) -> None:
    original_count = len(result[key])
    marker = "errors_total" if key == "errors" else f"{key}_count"
    current = result[key]
    while current:
        current = current[: len(current) // 2]
        result[key] = current
        if marker not in result:
            result[marker] = original_count
        result[f"{key}_truncated"] = True
        if _json_bytes(result) <= max_bytes:
            return


def _cut_last_section(result: dict[str, Any], max_bytes: int) -> None:
    candidates = [
        key
        for key in result
        if key != ERROR_KEY and not key.endswith(("_count", "_truncated")) and key != "errors_total"
    ]
    if not candidates:
        return
    key = candidates[-1]
    result[RESULT_TRUNCATED_KEY] = True
    while result[key] and _json_bytes(result) > max_bytes:
        current = result[key]
        if isinstance(current, str):
            text = current
        else:
            text = json.dumps(current, ensure_ascii=False, separators=(",", ":"))
        shrunk = clip_utf8(text, len(text.encode("utf-8")) * 7 // 8)
        result[key] = shrunk


def enforce_budget(
    payload: dict[str, Any],
    *,
    priority: Sequence[str],
    max_bytes: int = RESPONSE_BUDGET_BYTES,
) -> dict[str, Any]:
    """Shed an oversized payload in deterministic order down to the byte budget.

    ``priority`` lists top-level keys from first-shed to last-shed; each key is
    dropped, or list-trimmed with ``*_count``/``*_truncated``. Any remaining
    overflow is byte-cut from the last content section with ``result_truncated``.
    The ``error`` block is never dropped, trimmed, or cut.
    """
    result = dict(payload)
    if _json_bytes(result) <= max_bytes:
        return result

    for key in priority:
        if key == ERROR_KEY or key not in result:
            continue
        if _json_bytes(result) <= max_bytes:
            return result
        if isinstance(result[key], list):
            _trim_list(result, key, max_bytes)
        else:
            del result[key]

    if _json_bytes(result) > max_bytes:
        _cut_last_section(result, max_bytes)
    return result
