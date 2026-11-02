"""Normalize market timestamps with one pinned timezone database and exact integer epochs."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone as utc_timezone
from functools import lru_cache
from importlib import import_module, resources
from io import BytesIO
from zoneinfo import ZoneInfo

from nlalpha.core.errors import DataError


TZDATA_VERSION = "2026.3"
_EPOCH = datetime(1970, 1, 1, tzinfo=utc_timezone.utc)
_NS_PER_SECOND = 1_000_000_000
_ZONE_PATH = re.compile(r"[A-Za-z0-9_+-]+(?:/[A-Za-z0-9_+-]+)*")


def _error(field: str, message: str) -> DataError:
    """Create a structured timestamp-contract failure."""
    return DataError(message, details={"time_contract": True, "field": field})


def _timezone_name(name: str) -> str:
    """Validate a trimmed timezone resource path."""
    if not isinstance(name, str) or not _ZONE_PATH.fullmatch(name):
        raise _error("timezone", "timezone must be a non-empty IANA name without whitespace or traversal")
    return name


def timezone_data(name: str) -> bytes:
    """Return the pinned package's TZIF bytes for one IANA timezone."""
    return _timezone_data(_timezone_name(name))


@lru_cache(maxsize=128)
def _timezone_data(name: str) -> bytes:
    """Cache validated pinned timezone resources."""
    try:
        package = import_module("tzdata")
        if package.__version__ != TZDATA_VERSION:
            raise _error("tzdata_version", f"timezone contract requires tzdata=={TZDATA_VERSION}; installed {package.__version__}")
        data = resources.files("tzdata.zoneinfo").joinpath(*name.split("/")).read_bytes()
        if not data.startswith(b"TZif"):
            raise _error("timezone", f"timezone resource is not TZIF data: {name}")
        return data
    except DataError:
        raise
    except (ImportError, OSError, ValueError) as exc:
        raise _error("timezone", f"timezone is unavailable in tzdata=={TZDATA_VERSION}: {name}") from exc


def get_timezone(name: str) -> ZoneInfo:
    """Build a timezone exclusively from its pinned TZIF bytes."""
    return _get_timezone(_timezone_name(name))


@lru_cache(maxsize=128)
def _get_timezone(name: str) -> ZoneInfo:
    """Cache parsed timezone rules by validated resource path."""
    try:
        return ZoneInfo.from_file(BytesIO(timezone_data(name)), key=name)
    except DataError:
        raise
    except (ValueError, OSError) as exc:
        raise _error("timezone", f"invalid pinned timezone data: {name}") from exc


@lru_cache(maxsize=128)
def _timezone_hash(name: str) -> str:
    """Hash the exact timezone rules shared with engine runtimes."""
    return hashlib.sha256(timezone_data(name)).hexdigest()


def timezone_metadata(name: str) -> dict:
    """Describe the timezone and exact rule database used for analysis."""
    get_timezone(name)
    return {"timezone": name, "tzdata_version": TZDATA_VERSION, "tzif_sha256": _timezone_hash(name)}


def _datetime(value: datetime) -> datetime:
    """Validate datetime transport precision and copy its exact microseconds."""
    if not isinstance(value, datetime):
        raise _error("datetime", "timestamp must be a datetime")
    if getattr(value, "nanosecond", 0) != 0:
        raise _error("datetime", "datetime transport cannot represent sub-microsecond precision")
    try:
        return datetime(value.year, value.month, value.day, value.hour, value.minute, value.second,
                        value.microsecond, tzinfo=value.tzinfo, fold=value.fold)
    except (ValueError, TypeError, OverflowError) as exc:
        raise _error("datetime", "timestamp must be a finite representable datetime") from exc


def normalize_utc(value: datetime, *, source_timezone: str | None = None) -> datetime:
    """Normalize explicit offsets or uniquely resolvable local wall time into UTC."""
    value = _datetime(value)
    zone = get_timezone(source_timezone) if source_timezone is not None else None
    try:
        if value.utcoffset() is not None:
            return value.astimezone(utc_timezone.utc)
        if zone is None:
            raise _error("source_timezone", "naive timestamps require an explicit source_timezone")
        candidates = set()
        wall_time = value.replace(tzinfo=None, fold=0)
        for fold in (0, 1):
            candidate = wall_time.replace(tzinfo=zone, fold=fold).astimezone(utc_timezone.utc)
            if candidate.astimezone(zone).replace(tzinfo=None, fold=0) == wall_time:
                candidates.add(candidate)
        if len(candidates) != 1:
            kind = "ambiguous" if candidates else "nonexistent"
            raise _error("datetime", f"{kind} local timestamp in {source_timezone}: {wall_time.isoformat()}")
        return next(iter(candidates))
    except DataError:
        raise
    except (ValueError, TypeError, OverflowError) as exc:
        raise _error("datetime", "timestamp cannot be represented as a UTC datetime") from exc


def datetime_to_ns(value: datetime) -> int:
    """Convert an aware timestamp into exact integer UTC epoch nanoseconds."""
    delta = normalize_utc(value) - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * _NS_PER_SECOND + delta.microseconds * 1_000


def _timestamp_ns(value: int) -> int:
    """Validate an arbitrary-width integer timestamp."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise _error("timestamp_ns", "timestamp_ns must be an integer")
    return value


def ns_to_datetime(value: int) -> datetime:
    """Convert an exact microsecond timestamp without losing nanoseconds."""
    value = _timestamp_ns(value)
    if value % 1_000:
        raise _error("timestamp_ns", "datetime transport cannot represent sub-microsecond precision")
    try:
        return _EPOCH + timedelta(microseconds=value // 1_000)
    except OverflowError as exc:
        raise _error("timestamp_ns", "timestamp is outside the datetime calendar range") from exc


def format_timestamp_ns(value: int, timezone: str) -> str:
    """Render exact nanoseconds with the requested pinned timezone's numeric offset."""
    value = _timestamp_ns(value)
    zone = get_timezone(timezone)
    seconds, nanoseconds = divmod(value, _NS_PER_SECOND)
    try:
        local = (_EPOCH + timedelta(seconds=seconds)).astimezone(zone)
    except (OverflowError, ValueError) as exc:
        raise _error("timestamp_ns", "timestamp is outside the display calendar range") from exc
    offset = local.utcoffset()
    offset_seconds = offset.days * 86_400 + offset.seconds
    sign = "+" if offset_seconds >= 0 else "-"
    hours, remaining = divmod(abs(offset_seconds), 3_600)
    minutes, seconds = divmod(remaining, 60)
    suffix = f"{sign}{hours:02d}:{minutes:02d}" + (f":{seconds:02d}" if seconds else "")
    return (f"{local.year:04d}-{local.month:02d}-{local.day:02d}T{local.hour:02d}:"
            f"{local.minute:02d}:{local.second:02d}.{nanoseconds:09d}{suffix}")


def period_boundary_ns(year: int, month: int, timezone: str) -> int:
    """Resolve a uniquely existing local first-of-month midnight into UTC nanoseconds."""
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (year, month)):
        raise _error("calendar", "calendar year and month must be integers")
    try:
        boundary = datetime(year, month, 1)
    except ValueError as exc:
        raise _error("calendar", "calendar year or month is outside the datetime range") from exc
    return datetime_to_ns(normalize_utc(boundary, source_timezone=timezone))
