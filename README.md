# nlalpha-core

Domain contracts and plugin framework for the nlalpha natural-language-driven quantitative ecosystem.

This is the **foundational package** — every other nlalpha package depends on it. It defines the shared language between strategy family plugins, strategy generation, backtest engines, and capability providers.

## Design Philosophy

- **Minimal contracts**: The core only imposes the smallest possible interface. Strategy families define their own semantics; the core does not understand them.
- **Plugin autonomy**: CTA, Portfolio, etc. — each family plugin defines its own world. The backbone discovers them through entry points and interacts only through protocols.
- **Engine-agnostic**: Market contracts (`Bar`, `Order`, `Trade`, `Position`) carry no engine-specific details. Any backtest engine can consume them.
- **LLM-friendly**: Strategy interfaces are intentionally minimal. A strategy only needs to implement `on_bar(bar)` and generate orders via `buy()`/`sell()`.
- **Confess everything**: Strategy families and engines expose a `confess()` method — a subjective self-disclosure in Markdown for LLM agents. Before selecting a strategy family or engine, the agent reads the confession to learn conventions, caveats, and best practices.

## Module Overview

| Module | Purpose | Key Types |
|--------|---------|-----------|
| `nlalpha.core.strategy.plugin` | Strategy family plugin protocol | `StrategyFamilyPlugin`, `BaseStrategyFamilyPlugin` |
| `nlalpha.core.strategy.runtime` | Strategy runtime contracts | `EventDrivenStrategy`, `VectorizedStrategy`, `BaseEventDrivenStrategy` |
| `nlalpha.core.strategy.spec` | Strategy specification envelope | `StrategySpecEnvelope` |
| `nlalpha.core.capabilities` | Capability provider framework | `CapabilityPlugin`, `CapabilityRegistry`, `CapabilityPluginRegistry`, `CapabilityEntry`, `ProviderManifest` |
| `nlalpha.core.contracts.market` | Market data contracts | `MarketData`, `OrderLike`, `Bar`, `Order`, `Trade`, `Position` |
| `nlalpha.core.telemetry` | Observability utilities | `get_tracer`, `start_span`, `setup_logging` |
| `nlalpha.core.config` | Configuration helpers | — |
| `nlalpha.core.errors` | Shared error types | — |

## Core Concepts

### Strategy Family Plugin

A strategy family plugin represents a strategy *world* — e.g. CTA, portfolio optimization, spread trading. It declares:

- `family`: the family identifier (e.g. `"cta"`, `"portfolio"`)
- `family_contract()`: the family-specific contract schema
- `confess()`: subjective notes, caveats, and best practices in Markdown

```python
from nlalpha.core import StrategyFamilyPlugin, BaseStrategyFamilyPlugin

class CTAPlugin(BaseStrategyFamilyPlugin):
    family = "cta"
    plugin_name = "nlalpha-family-cta"

    def family_contract(self):
        return {"indicators": [...], "timeframes": [...]}

    def confess(self) -> str:
        return "# CTA Family Confession\n\n- Use bar_close execution..."
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

Two mutually exclusive strategy protocols:

- **`EventDrivenStrategy`**: Receives one bar at a time via `on_bar(bar)`. Orders are generated via `buy()`/`sell()`/`short()`/`cover()` and collected by the engine via `collect_orders()`. Suitable for CTA, intraday, and event-driven logic.
- **`VectorizedStrategy`**: Receives the full DataFrame via `generate_signals(df)` and returns signal/weight series. No subprocess isolation needed. Suitable for portfolio optimization and factor-based strategies.

`BaseEventDrivenStrategy` is the shared base class for event-driven strategies. It provides:

- Order generation methods (`buy`, `sell`, `short`, `cover`)
- Account snapshot properties (`initial_cash`, `available_cash`, `current_equity`)
- Dynamic provider proxy via `__getattr__` — any indicator or metric method is resolved from registered capability providers
- Lifecycle hooks (`on_init`, `on_start`, `on_stop`)

### Market Contracts

Pure data structures exchanged between strategies and engines:

- **`Bar`**: OHLCV bar with `symbol`, `datetime`, `open`, `high`, `low`, `close`, `volume`, `open_interest`
- **`Order`**: Order with `order_id`, `symbol`, `direction` (`long`/`short`), `offset` (`open`/`close`), `price`, `volume`, `order_type`, `status`
- **`Trade`**: Fill record with `trade_id`, `order_id`, `symbol`, `direction`, `offset`, `price`, `volume`, `commission`, `slippage_cost`
- **`Position`**: Long/short-separated position with `net_volume`, `avg_price`, `tradable_long`, `tradable_short`

Both `MarketData` and `OrderLike` are protocols — any object satisfying the interface is accepted.

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
    execution={"mode": "bar_close", "commission": 0.001},
    capital={"initial": 1_000_000},
    family_spec={"indicators": [...]},
)
```

## Who Depends on This

| Downstream Package | Role |
|-------------------|------|
| `nlalpha-family-cta` | Implements `StrategyFamilyPlugin` for CTA strategies |
| `nlalpha-family-portfolio` | Portfolio optimization family (experimental) |
| Strategy generation module | Discovers strategy families, generates strategy code |
| `nlalpha-backtest` | Discovers engines & capabilities, executes backtests |
| `nlalpha-statistics` | Performance metrics (wrapping quantstats, etc.) |
| `nlalpha-nautilus` | Nautilus Trader engine adapter |
| `nlalpha-basic-engine` | Internal engine (design inspired by vnpy's bar_close matching) |

## Installation

```bash
pip install nlalpha-core          # core only, zero dependencies
pip install "nlalpha-core[all]"   # with telemetry, dotenv, json-log
```

The core package has **zero mandatory external dependencies** beyond the Python standard library. Optional extras:

| Extra | Dependencies | Purpose |
|-------|-------------|---------|
| `dotenv` | `python-dotenv` | `.env` file loading |
| `telemetry` | `opentelemetry-*` | Tracing, metrics, logs |
| `json-log` | `python-json-logger` | Structured JSON logging |
| `all` | all of the above | Enable everything |
