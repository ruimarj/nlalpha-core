# nlalpha-core

Domain contracts and plugin framework for the nlalpha natural-language-driven quantitative ecosystem.

This is the **foundational package** — every other nlalpha package depends on it. It defines the shared language between strategy family plugins, strategy generation, backtest engines, and capability providers.

The platform workspace package is version `0.7.0`. Its backtest contracts are engine- and host-independent; timezone support uses the pinned `tzdata==2026.3` package.

## Design Philosophy

- **Minimal contracts**: The core only imposes the smallest possible interface. Strategy families define their own semantics; the core does not understand them.
- **Plugin autonomy**: CTA, Portfolio, etc. — each family plugin defines its own world. The backbone discovers them through entry points and interacts only through protocols.
- **Engine-agnostic**: Market contracts (`Bar`, `Order`, `Trade`, `Position`) carry no engine-specific details. Any backtest engine can consume them.
- **LLM-friendly**: Strategy interfaces are intentionally minimal. A strategy family contract can declare one or more lifecycle methods, including `on_bar(bar)` or `on_bars(bars)`; engines validate the selected family contract.
- **Confess everything**: Services expose structured `about` descriptions and object-level `confess` notes. Agents discover installed capabilities from the live catalog, then read the selected family or provider contract and declared guidance before relying on it.

## Module Overview

| Module | Purpose | Key Types |
|--------|---------|-----------|
| `nlalpha.core.strategy.plugin` | Strategy family plugin protocol | `StrategyFamilyPlugin`, `BaseStrategyFamilyPlugin` |
| `nlalpha.core.strategy.runtime` | Strategy runtime contracts | `EventDrivenStrategy`, `VectorizedStrategy`, `BaseEventDrivenStrategy` |
| `nlalpha.core.strategy.spec` | Strategy specification envelope | `StrategySpecEnvelope` |
| `nlalpha.core.capabilities` | Capability provider framework | `CapabilityPlugin`, `CapabilityRegistry`, `CapabilityPluginRegistry`, `CapabilityEntry`, `ProviderManifest` |
| `nlalpha.core.contracts.market` | Market data contracts | `MarketData`, `OrderLike`, `Bar`, `Order`, `Trade`, `Position` |
| `nlalpha.core.backtest` | Engine-agnostic event and batch execution contracts | `EngineManifest`, `EngineRunContext`, `BatchBacktestInput`, `BacktestResult`, `BacktestResultStatus` |
| `nlalpha.core.data_artifacts` | Scoped immutable artifacts shared between MCP services | `DataArtifactStore`, `RedisDataArtifactStore`, `DataArtifact`, `ArtifactScope`, `ArtifactMetadata` |
| `nlalpha.core.artifact_config` | Application-local artifact backend configuration | `ArtifactStoreConfig`, `create_data_artifact_store` |
| `nlalpha.core.telemetry` | Observability utilities | `get_tracer`, `start_span`, `setup_logging` |
| `nlalpha.core.config` | Configuration helpers | — |
| `nlalpha.core.errors` | Shared error types and the six canonical error codes | `NlAlphaError`, `DataError`, `ErrorType`, `ErrorStage` |
| `nlalpha.core.result_contract` | Canonical failure envelope and deterministic budget enforcer | `build_error`, `failure_response`, `format_traceback_tail`, `enforce_budget` |

## Core Concepts

### Strategy Family Plugin

A strategy family plugin represents a strategy *world* — e.g. CTA, portfolio optimization, spread trading. It declares:

- `family`: the family identifier (e.g. `"cta"`, `"portfolio"`)
- `family_contract()`: the family-specific contract schema
- `confess()`: subjective notes, caveats, and best practices in Markdown

```python
from nlalpha.core import StrategyFamilyPlugin, BaseStrategyFamilyPlugin, FamilyContract

class CTAPlugin(BaseStrategyFamilyPlugin):
    family = "cta"
    plugin_name = "nlalpha-family-cta"

    def family_contract(self) -> FamilyContract:
        return FamilyContract(
            family="cta",
            base_class="CtaStrategyBase",
            base_import="nlalpha_cta.strategy_base.CtaStrategyBase",
            lifecycle_methods=["on_bar(self, bar)"],
        )

    def confess(self) -> str:
        return "## CTA conventions\n\n- Follow the family contract and current engine semantics."
```

Plugins are discovered via `nlalpha.strategy_family` entry points. See `nlalpha-family-cta` for a reference implementation.

### Capability Provider Plugin

Capability plugins inject domain-specific helpers into strategy code — indicators, risk metrics, portfolio optimizers, etc. They are discovered via `nlalpha.capabilities` entry points.

> **Note**: nlalpha capability plugins are essentially adaptation layers over mature open-source quantitative libraries (quantstats, empyrical, arch, pyportfolioopt, etc.). The core only defines contracts; the actual computation is done by these libraries.

```python
from nlalpha.core.capabilities import CapabilityPlugin, BaseCapabilityPlugin, CapabilityEntry

class SharpePlugin(BaseCapabilityPlugin):
    plugin_name = "nlalpha-statistics"
    plugin_version = "0.1.0"

    def is_available(self) -> bool:
        return True

    def get_provider(self):
        return SharpeCalculator()

    def get_manifest(self) -> dict:
        return {
            "provider_id": "sharpe",
            "provider_name": "Sharpe Ratio",
            "methods": ["sharpe_ratio"],
            "domains": ["statistics", "performance"],
        }

    def get_helpers(self) -> list[CapabilityEntry]:
        return [
            CapabilityEntry(
                name="sharpe_ratio",
                category="function",
                signature="sharpe_ratio(returns, risk_free=0.0) -> float",
                description="Annualized Sharpe ratio",
                source_plugin="nlalpha-statistics",
                domain="statistics",
            )
        ]
```

### Strategy Runtime

Two strategy runtime protocols are defined:

- **`EventDrivenStrategy`**: Receives one bar at a time via `on_bar(bar)`. Strategies submit immutable commands with `submit_order()` or the `buy()`/`sell()`/`short()`/`cover()` helpers, and request cancellation with `cancel_order(order_id)`. The runtime drains commands in FIFO order with `collect_commands()`.
- **`VectorizedStrategy`**: Receives a DataFrame via `generate_signals(df)` and returns signal/weight series. This protocol is a strategy contract; it does not imply that the current batch backtest dispatcher compiles strategy source or generates signals.

The separate `nlalpha.core.backtest` contracts describe event-driven and schema-versioned batch engine inputs. They are pure standard-library data contracts: engine-specific financial simulation, Arrow handling, and matching behavior live in engine/provider packages. `EngineManifest` declares the runtime modes and input schemas accepted by a provider.

The core backtest contracts preserve the run context, inputs, results, and public strategy contracts. Execution timing, fees, account validation, order state, and assumptions are provided by the actual engine; the host preserves them as supplied.

`BacktestResult.status` is limited to `succeeded` or `failed`; other values, including `completed`, raise `ValueError`. `is_successful` is true only when the status is `succeeded` and `errors` is empty. This describes an engine result. The host's `JobService` has a separate lifecycle status such as `completed`, and its completion callback text is not an engine result status.

`BaseEventDrivenStrategy` is the shared base class for event-driven strategies. It provides:

- Order generation methods (`buy`, `sell`, `short`, `cover`)
- Account snapshot properties (`initial_cash`, `available_cash`, `current_equity`)
- Dynamic provider proxy via `__getattr__` — any indicator or metric method is resolved from registered capability providers
- Lifecycle hooks (`on_init`, `on_start`, `on_stop`) and optional order/fill callbacks (`on_order`, `on_trade`)

### Market Contracts

Pure data structures exchanged between strategies and engines:

- **`Bar`**: OHLCV bar with `symbol`, `datetime`, `open`, `high`, `low`, `close`, `volume`, `open_interest`
- **`Order`**: Immutable submission command with `order_id`, `symbol`, `direction`, `offset`, `volume`, optional reference `price`, `order_type`, `limit_price`, `stop_price`, and `time_in_force`
- **`OrderSnapshot`**: Immutable view of the submitted fields and live engine state, including `status`, `filled_volume`, `remaining_volume`, `avg_price`, `timestamp_ns`, and `reason`
- **`CancelOrder` / `OrderEvent`**: Immutable cancel intent and native order-event snapshot with kind, order, nanosecond timestamp, and reason
- **`Trade`**: Fill record with `trade_id`, `order_id`, `symbol`, `direction`, `offset`, `price`, `volume`, `commission`, optional `slippage_cost`, and optional nanosecond `timestamp_ns`
- **`Position`**: Long/short-separated position with `net_volume`, `avg_price`, `tradable_long`, `tradable_short`

`Order`, `CancelOrder`, `OrderSnapshot`, `OrderEvent`, and `Trade` are immutable command/event values. `OrderSnapshot` is a read-only engine snapshot, not a mutable request. `OrderEvent.timestamp_ns` and `Trade.timestamp_ns` preserve native nanoseconds when available. `MarketData` and `OrderLike` remain protocols.

### Strategy Specification Envelope

`StrategySpecEnvelope` is the generic envelope for strategy contracts. The backbone only understands the generic fields; `family_spec` internals are opaque to the core.

```python
from nlalpha.core.strategy.spec import StrategySpecEnvelope

spec = StrategySpecEnvelope(
    id="spec-abc123",
    version="0.1",
    family="cta",
    universe={"symbols": ["AAPL", "MSFT"]},
    data={"timeframe": "1d", "source": "akshare"},
    capital={"initial": 1_000_000},
    family_spec={"indicators": [...]},
)
```

### Immutable data artifacts

`DataArtifactStore` is the asynchronous boundary for immutable data handed between MCP services. A `data_ref` identifies one exact payload and its metadata: trusted scope, media type, schema, byte size, SHA-256 digest, creation time, and logical expiry. Publishing creates a new reference; it does not overwrite an earlier artifact. Reads verify the payload and scope, and expired or out-of-scope references fail.

The `redis` and `s3` backends are selected explicitly for each service deployment; there is no size-based routing. Redis stores the artifact envelope directly. S3 stores one envelope per object and does not use a Redis index. MinIO is an optional S3-compatible service, not a requirement for Redis deployments. There is no default 10 MiB limit: `max_bytes` is unset unless configured, and each selected backend remains bounded by its own deployment budget.

Each application owns its store lifecycle. Create it with `create_data_artifact_store()`, call `start()` before serving, and close it with `aclose()` when the application stops. `nlalpha-data` and `nlalpha-backtest` both use this interface; the Data-to-backtest consumer path has passed parent-directed end-to-end verification.

**Artifact configuration**:

| Variable | Default | Meaning |
|----------|---------|---------|
| `NLALPHA_ARTIFACT_BACKEND` | `redis` | Selected backend: `redis` or `s3` |
| `NLALPHA_ARTIFACT_REDIS_URL` | `redis://127.0.0.1:6379/0` | Redis artifact service URL |
| `NLALPHA_ARTIFACT_TTL_SECONDS` | `86400` | Per-artifact logical lifetime in seconds |
| `NLALPHA_ARTIFACT_MAX_BYTES` | unset | Optional maximum artifact payload size; no default 10 MiB cap |
| `NLALPHA_ARTIFACT_S3_BUCKET` | required for S3 | Bucket containing artifact objects |
| `NLALPHA_ARTIFACT_S3_ENDPOINT` | unset | Optional S3-compatible endpoint, such as MinIO |
| `NLALPHA_ARTIFACT_S3_ACCESS_KEY` / `NLALPHA_ARTIFACT_S3_SECRET_KEY` | unset | Optional paired credentials |
| `NLALPHA_ARTIFACT_S3_REGION` | unset | Optional S3 region |
| `NLALPHA_ARTIFACT_S3_RETENTION_DAYS` | `1` | Required bucket lifecycle retention in whole days; must cover the logical TTL |

S3 reads enforce the exact per-object logical expiry. Physical bucket lifecycle cleanup is asynchronous and day-based, not guaranteed at the logical expiry second. Before startup, the configured bucket must have versioning disabled and an enabled lifecycle rule covering the dedicated `nlalpha/artifacts/v1/` prefix at the configured retention. Do not interpret a lifecycle configuration test as proof that an object was physically deleted after waiting a full retention period.

### Host identity and scope

`HostIdentityConfig` resolves `ArtifactScope(environment, owner)` from host-provided request context. `NLALPHA_ENV` defaults to `local` and is part of the scope. `NLALPHA_IDENTITY_MODE` defaults to `single-user`, which assigns owner `standalone` and rejects a supplied identity header. In `trusted-host` mode, the service requires the configured `NLALPHA_IDENTITY_USER_HEADER` (default `X-NLAlpha-User-ID`) to be supplied by a trusted gateway. This is identity mapping at the host boundary, not authentication implemented by NLAlpha; the gateway must authenticate and protect the header.

DNS rebinding protection remains enabled. Allowed hosts come from the explicit application argument, then `NLALPHA_ALLOWED_HOSTS`, or a safe localhost/loopback default. Configure public or container hostnames explicitly; wildcard hosts are rejected.

## Who Depends on This

| Downstream Package | Role |
|-------------------|------|
| `nlalpha-family-cta` | Implements `StrategyFamilyPlugin` for CTA strategies |
| `nlalpha-family-portfolio` | Portfolio optimization family (experimental) |
| Strategy generation module | Discovers strategy families, generates strategy code |
| `nlalpha-backtest` | Discovers engines & capabilities, executes backtests |
| `nlalpha-statistics` | Performance metrics (wrapping quantstats, etc.) |
| `nlalpha-nautilus` | Nautilus Trader engine adapter |
| `nlalpha-engine-vector` | Arrow-native Rust provider for schema-versioned, precomputed-signal batches |

## Installation

```bash
pip install nlalpha-core          # core plus pinned tzdata
pip install "nlalpha-core[all]"   # with telemetry, dotenv, json-log
```

The platform workspace copy is the active source for platform builds. Core requires the pinned `tzdata==2026.3` package for consistent timezone rules; telemetry integrations remain optional. Optional extras:

| Extra | Dependencies | Purpose |
|-------|-------------|---------|
| `dotenv` | `python-dotenv` | `.env` file loading |
| `telemetry` | `opentelemetry-*` | Tracing, metrics, logs |
| `json-log` | `python-json-logger` | Structured JSON logging |
| `all` | all of the above | Enable everything |

## Reports on shared results

`BacktestResult.reports` is an optional dictionary of engine-owned report tables. Each table carries `schema_id`, `source`, `status`, `reason`, `row_count`, `columns`, `rows`, and `metadata`; core validates the shared envelope without depending on a financial library or defining one universal column schema. Status distinguishes an available empty table from a table not recorded and a generation failure.

## Result and error contract

`nlalpha.core.result_contract` is the single constructor for agent-facing failures reused by MCP responses, runner stderr payloads, and adapter evidence. `build_error(exc, stage=None)` returns the ordered object `type → message → stage → retryable → suggestion → traceback_tail → details`: the code is read from the exception's `error_type` class variable (unknown → `internal_error`), and `suggestion`, `details`, `retryable`, and `stage` are read from optional exception attributes. `failure_response` wraps it as `{"status": "failed", "error": {...}}`. Caps are frozen: message 2 KiB, suggestion 1 KiB, traceback tail 4 KiB over the last 15 user/strategy frames (stdlib, site-packages, and `nlalpha`/`nlalpha_*` frames excluded; omitted when only framework frames exist), details 8 KiB with lists trimmed to 10 items × 512 B plus `*_count`/`errors_total`. `enforce_budget(payload, priority=..., max_bytes=...)` sheds an oversized response in caller-declared priority order — dropping sections, prefix-trimming lists with `*_count`/`*_truncated`, then UTF-8-safe byte-cutting the last section with `result_truncated`; the `error` block is never shed. Budget constants (`RESPONSE_BUDGET_BYTES` 256 KiB, `ERROR_BUDGET_BYTES` 16 KiB, and the per-field caps) are exported from the same module.

## Current-version focused verification

Historical Core 0.5.0 report envelopes were exercised through the host report persistence and cache-restoration path. This records focused integration coverage only, not a full core suite result.

## Market timestamp contract

Core 0.7.0 canonicalizes `Bar.datetime` (the close instant) and optional `open_time` to aware UTC. Each Bar can retain `session_date`, `source_timezone`, `source_utc_offset_seconds`, `source_timestamp_semantics` (`open`, `close`, or `trading_date`), and `calendar_id`; these describe the original source and survive UTC reconstruction. Session labels are never inferred from the UTC date. Python Bar datetimes preserve microseconds and reject sub-microsecond truncation. Raw Arrow/engine timestamps may retain nanoseconds.

`nlalpha.core.contracts.time` provides timezone rules from the pinned `tzdata==2026.3` package, including `get_timezone`, `timezone_data`, `timezone_metadata`, strict `normalize_utc`, exact integer datetime/ns conversion, and nine-digit `format_timestamp_ns`. Python and Rust use identical TZIF data; metadata exposes its version and SHA-256. Naive wall times require an explicit supported IANA zone and ambiguous/nonexistent instants fail.

Source timezone metadata is provenance: reconstructing a Bar with its already-UTC close time must preserve the original source IANA key or exact original offset, source semantics, session label, and calendar identity. The canonical instant and its source description are stored separately.

## Self-description and packaged guidance

`nlalpha.core.description` builds `nlalpha.description.v1` documents. A description revision is the SHA-256 of the complete canonical document, so full and selected-section reads share the same revision. `markdown_sections()` splits English level-two sections; `common_description()` reads the packaged common principles; `read_skill(name, language)` reads one packaged skill in one language; `skill_catalog(language)` lists every packaged skill with its title, description, revision, and content SHA-256. Required missing documents and unknown section IDs fail explicitly. Services expose this material through their `about` and `confess` operations; core packages the resources but does not itself register an MCP tool.

Strategy-family plugins inherit `BaseStrategyFamilyPlugin` and implement `family_contract() -> FamilyContract` plus `confess()`. The registry caches one discovery record per family, including plugin instance, contract, notes, and distribution identity. Registry metadata failures remain visible in diagnostics; duplicate family identities disable both records, and clearing the registry removes only its own published capability entries. The base class does not require an `about()` method.

Telemetry instruments are lazy and share one public provider when the host has already configured it. An independent CLI may explicitly call `configure_telemetry()` and owns the resulting providers; it should flush and shut them down only after work is complete and capture has stopped. The library must not shut down providers owned by another host.

For the NLAlpha service processes, CLI mains own the telemetry SDK lifecycle and inject shutdown into the existing ASGI lifespan. Application-owned resources close before the SDK flush/shutdown callback; app construction failure also reaches process cleanup. The four service app factories remain usable without taking ownership of process telemetry. Docker shutdown smoke verified final signal handling and resource cleanup across all 11 current runtime images; this is local image evidence, not a published deployment result.

The English and Chinese task skills and common principles are packaged at `src/nlalpha/core/skills/` and `src/nlalpha/core/knowledge/`. Their canonical service registration is a consumer responsibility.


## Self-description and artifact read budgets

The package carries the single canonical common-principles resource and the English/Chinese task skill pairs. Description documents use schema `nlalpha.description.v1`; a selected section and the complete document share one SHA-256 `description_revision`. The four services build descriptions from installed distribution metadata and their actual manifest, contract, helper, and resource records. A source checkout without installed distribution metadata does not synthesize a package version.

Artifact metadata has a 64 KiB protocol ceiling; this is not a payload ceiling. Redis bounds a single range read to the configured payload budget plus the metadata envelope. S3 reads bounded metadata first, validates the configured payload budget, then streams chunks of at most 64 KiB up to the declared size plus one byte and closes the response body. `max_bytes=None` means no package default payload cap. Deserialized object memory and concurrent read budgets belong to the deployment configuration.

## License

`nlalpha-core` is one of the 10 community distributions under AGPL-3.0-or-later. The root license covers only those community distributions and common community material; private packages, Jingzhe platform code, the adapter, and third-party dependencies retain their own licenses.
