"""Canonical bar artifact identities and per-asset data-source evidence."""

from __future__ import annotations

import json

from nlalpha.core.errors import DataError

BAR_CONTRACT_VERSION = 2
BAR_CONTRACT_KEY = b"nlalpha.bar_contract"
BAR_CONTRACT = f"nlalpha.market.bar.v{BAR_CONTRACT_VERSION}:volume=instrument_quantity".encode("ascii")
SOURCE_KEY = b"nlalpha.source.v1"
SOURCE_SCHEMA = "nlalpha.market.source.v1"
PRICE_ADJUSTMENTS = frozenset({"unadjusted", "forward", "backward"})


def validate_request_description(value: object) -> dict:
    """Validate and copy a provider's request-specific source declaration."""
    if not isinstance(value, dict) or set(value) != {"price_adjustment", "evidence"}:
        raise DataError("Source declaration requires price_adjustment and evidence.")
    adjustment = value["price_adjustment"]
    if not isinstance(adjustment, str) or adjustment not in PRICE_ADJUSTMENTS | {"unknown"}:
        raise DataError("Invalid source price_adjustment declaration.")
    evidence = value["evidence"]
    if not isinstance(evidence, dict) or set(evidence) != {"type", "reference"}:
        raise DataError("Source evidence requires type and reference.")
    if any(not isinstance(item, str) or not item or item != item.strip() for item in evidence.values()):
        raise DataError("Source evidence values must be nonempty trimmed strings.")
    if evidence["type"] not in {"unknown", "host_declaration", "provider_documentation"}:
        raise DataError("Unknown source evidence type.")
    if (adjustment == "unknown") != (evidence["type"] == "unknown"):
        raise DataError("Source adjustment and evidence type contradict each other.")
    return {"price_adjustment": adjustment, "evidence": dict(evidence)}


def _source_contract(value: object, symbols: set[str]) -> dict:
    """Validate an exact asset map while retaining explicit unknown source entries."""
    if (not isinstance(value, dict) or set(value) != {"schema", "assets"}
            or value["schema"] != SOURCE_SCHEMA or not isinstance(value["assets"], dict)):
        raise ValueError("Invalid source contract envelope")
    if set(value["assets"]) != symbols:
        raise ValueError("Source assets contradict the table symbols")
    for symbol, source in value["assets"].items():
        if not isinstance(symbol, str) or not symbol or symbol != symbol.strip():
            raise ValueError("Invalid source asset symbol")
        if source is None:
            continue
        if not isinstance(source, dict) or set(source) != {"provider_id", "package", "version", "price_adjustment", "evidence", "cache_hit"}:
            raise ValueError("Invalid asset source fields")
        if not isinstance(source["provider_id"], str) or not source["provider_id"] or source["provider_id"] != source["provider_id"].strip():
            raise ValueError("Invalid source provider_id")
        for name in ("package", "version"):
            item = source[name]
            if item is not None and (not isinstance(item, str) or not item or item != item.strip()):
                raise ValueError(f"Invalid source {name}")
        if type(source["cache_hit"]) is not bool:
            raise ValueError("Invalid source cache_hit")
        validate_request_description({name: source[name] for name in ("price_adjustment", "evidence")})
    return value


def _symbols(table, symbols: tuple[str, ...] | None) -> set[str]:
    """Resolve actual table identities or explicit identities for a schema-only read."""
    if hasattr(table, "column_names"):
        if "symbol" not in table.column_names:
            raise ValueError("Source metadata requires a symbol column")
        observed = set(table.column("symbol").unique().to_pylist())
        if symbols is not None and observed != set(symbols):
            raise ValueError("Source table symbols contradict the expected universe")
        return observed
    if symbols is None:
        raise ValueError("Schema-only source reads require explicit symbols")
    return set(symbols)


def read_source_contract(table, *, symbols: tuple[str, ...] | None = None) -> dict | None:
    """Read optional source evidence and reject malformed or mismatched asset declarations."""
    schema = table.schema if hasattr(table, "schema") else table
    raw = (schema.metadata or {}).get(SOURCE_KEY)
    if raw is None:
        return None
    try:
        return _source_contract(json.loads(raw), _symbols(table, symbols))
    except (UnicodeError, ValueError, TypeError, KeyError, DataError) as exc:
        raise DataError(f"Invalid source contract: {exc}", details={"source_contract": True}) from exc


def merge_source_contracts(tables: list) -> dict | None:
    """Merge disjoint asset evidence and mark undeclared sources explicitly unknown."""
    assets = {}
    declared = False
    for table in tables:
        symbols = _symbols(table, None)
        if assets.keys() & symbols:
            raise DataError("Source contracts require disjoint asset identities.", details={"source_contract": True})
        contract = read_source_contract(table)
        if contract is None:
            assets.update({symbol: None for symbol in sorted(symbols)})
        else:
            declared = True
            assets.update(contract["assets"])
    return {"schema": SOURCE_SCHEMA, "assets": assets} if declared else None


def with_source_contract(table, contract: dict | None):
    """Attach validated source evidence while preserving unrelated Arrow metadata."""
    metadata = dict(table.schema.metadata or {})
    metadata.pop(SOURCE_KEY, None)
    if contract is not None:
        _source_contract(contract, _symbols(table, None))
        metadata[SOURCE_KEY] = json.dumps(contract, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return table.replace_schema_metadata(metadata)


def validate_price_adjustment(contract: dict | None, symbols: tuple[str, ...], requested: str | None) -> None:
    """Require each asset's recorded evidence to prove an explicit adjustment request."""
    if requested is None:
        return
    if not isinstance(requested, str) or requested not in PRICE_ADJUSTMENTS:
        raise DataError("data.price_adjustment must be unadjusted, forward, or backward.", details={"source_contract": True})
    for symbol in symbols:
        source = None if contract is None else contract["assets"].get(symbol)
        actual = "unknown" if source is None else source["price_adjustment"]
        if actual != requested:
            raise DataError(f"Source evidence for {symbol!r} does not prove requested price_adjustment={requested!r}.",
                            details={"source_contract": True, "symbol": symbol, "requested": requested, "actual": actual})
