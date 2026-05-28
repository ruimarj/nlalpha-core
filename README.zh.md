# nlalpha-core

nlalpha 自然语言驱动量化生态的领域契约与插件框架。

这是**基础包** —— nlalpha 体系内的所有其他包都依赖它。它为策略族插件、策略生成、回测引擎和能力提供者之间定义了共享语言。

## 设计哲学

- **最小契约**：核心只施加最小必要的接口。策略族自行定义语义，核心不理解它们。
- **插件自治**：CTA、组合等 —— 每个策略族插件定义自己的世界。主干通过 entry points 发现它们，只通过协议与之交互。
- **引擎无关**：市场契约（`Bar`、`Order`、`Trade`、`Position`）不含任何引擎专属细节，任何回测引擎都可以消费它们。
- **LLM 友好**：策略接口刻意保持极简。策略只需实现 `on_bar(bar)`，通过 `buy()`/`sell()` 生成订单即可。
- **万物自白**：策略族和引擎都暴露 `confess()` 方法 —— 面向 LLM agent 的主观自白。agent 在选型前阅读自白，了解约定、陷阱和最佳实践。

## 模块总览

| 模块 | 职责 | 核心类型 |
|------|------|---------|
| `nlalpha.core.strategy.plugin` | 策略族插件协议 | `StrategyFamilyPlugin`、`BaseStrategyFamilyPlugin` |
| `nlalpha.core.strategy.runtime` | 策略运行时契约 | `EventDrivenStrategy`、`VectorizedStrategy`、`BaseEventDrivenStrategy` |
| `nlalpha.core.strategy.spec` | 策略规格通用外壳 | `StrategySpecEnvelope` |
| `nlalpha.core.capabilities` | 能力提供者框架 | `CapabilityPlugin`、`CapabilityRegistry`、`CapabilityPluginRegistry`、`CapabilityEntry`、`ProviderManifest` |
| `nlalpha.core.contracts.market` | 市场数据契约 | `MarketData`、`OrderLike`、`Bar`、`Order`、`Trade`、`Position` |
| `nlalpha.core.telemetry` | 可观测性工具 | `get_tracer`、`start_span`、`setup_logging` |
| `nlalpha.core.config` | 配置辅助 | — |
| `nlalpha.core.errors` | 共享错误类型 | — |

## 核心概念

### 策略族插件

策略族插件代表一个策略**世界** —— 如 CTA、组合优化、价差交易。它声明：

- `family`：策略族标识符（如 `"cta"`、`"portfolio"`）
- `family_contract()`：策略族专属契约模式
- `confess()`：主观补充说明、注意事项和最佳实践（Markdown 格式）

```python
from nlalpha.core import StrategyFamilyPlugin, BaseStrategyFamilyPlugin

class CTAPlugin(BaseStrategyFamilyPlugin):
    family = "cta"
    plugin_name = "nlalpha-family-cta"

    def family_contract(self):
        return {"indicators": [...], "timeframes": [...]}

    def confess(self) -> str:
        return "# CTA 策略族自白\n\n- 使用 bar_close 撮合模式..."
```

插件通过 `nlalpha.strategy_family` entry points 被自动发现。参考实现见 `nlalpha-family-cta`。

### 能力提供者插件

能力插件向策略代码注入领域专属 helper —— 指标、风险度量、组合优化器等。通过 `nlalpha.capabilities` entry points 被自动发现。

> **注**：nlalpha 的能力插件本质上是成熟开源量化库（quantstats、empyrical、arch、pyportfolioopt 等）的 nlalpha 适配层。core 只定义契约，底层计算由这些开源库完成。

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
                description="年化夏普比率",
                source_plugin="nlalpha-statistics",
                domain="statistics",
            )
        ]
```

### 策略运行时

两种互斥的策略协议：

- **`EventDrivenStrategy`**：逐根 bar 通过 `on_bar(bar)` 接收数据。通过 `buy()`/`sell()`/`short()`/`cover()` 生成订单，引擎通过 `collect_orders()` 收集。适用于 CTA、日内、事件驱动策略。
- **`VectorizedStrategy`**：通过 `generate_signals(df)` 接收全量 DataFrame，返回信号/权重序列。无需子进程隔离。适用于组合优化和因子选股。

`BaseEventDrivenStrategy` 是事件驱动策略的共享基类，提供：

- 订单生成方法（`buy`、`sell`、`short`、`cover`）
- 账户快照属性（`initial_cash`、`available_cash`、`current_equity`）
- 动态 provider 代理 —— 任何指标或度量方法通过 `__getattr__` 从已注册的能力提供者中解析
- 生命周期钩子（`on_init`、`on_start`、`on_stop`）

### 市场契约

策略与引擎之间交换的纯数据结构：

- **`Bar`**：K 线，含 `symbol`、`datetime`、`open`、`high`、`low`、`close`、`volume`、`open_interest`
- **`Order`**：订单，含 `order_id`、`symbol`、`direction`（`long`/`short`）、`offset`（`open`/`close`）、`price`、`volume`、`order_type`、`status`
- **`Trade`**：成交记录，含 `trade_id`、`order_id`、`symbol`、`direction`、`offset`、`price`、`volume`、`commission`、`slippage_cost`
- **`Position`**：持仓，支持多空分离模型，提供 `net_volume`、`avg_price`、`tradable_long`、`tradable_short`

`MarketData` 和 `OrderLike` 均为协议 —— 任何满足接口的对象都被接受。

### 策略规格外壳

`StrategySpecEnvelope` 是策略合同的通用外壳。主干只理解通用字段；`family_spec` 内部对核心不透明。

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

## 依赖方

| 下游包 | 角色 |
|--------|------|
| `nlalpha-family-cta` | 实现 CTA 策略的 `StrategyFamilyPlugin` |
| `nlalpha-family-portfolio` | 组合优化策略族（实验性） |
| 策略生成模块 | 发现策略族、生成策略代码 |
| `nlalpha-backtest` | 发现引擎与能力、执行回测 |
| `nlalpha-statistics` | 绩效指标（封装 quantstats 等开源库） |
| `nlalpha-nautilus` | Nautilus Trader 引擎适配器 |
| `nlalpha-basic-engine` | 内部引擎（设计上借鉴 vnpy 的 bar_close 撮合模式） |

## 安装

```bash
pip install nlalpha-core          # 仅核心，零依赖
pip install "nlalpha-core[all]"   # 包含遥测、dotenv、结构化日志
```

核心包除 Python 标准库外**零强制外部依赖**。可选 extras：

| Extra | 依赖 | 用途 |
|-------|------|------|
| `dotenv` | `python-dotenv` | `.env` 文件加载 |
| `telemetry` | `opentelemetry-*` | 链路追踪、指标、日志 |
| `json-log` | `python-json-logger` | 结构化 JSON 日志 |
| `all` | 以上全部 | 启用所有可选能力 |
