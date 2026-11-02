# nlalpha-core

nlalpha 自然语言驱动量化生态的领域契约与插件框架。

这是**基础包** —— nlalpha 体系内的所有其他包都依赖它。它为策略族插件、策略生成、回测引擎和能力提供者之间定义了共享语言。

平台 workspace 中的包版本为 `0.6.0`。回测契约与具体引擎及宿主无关；时区规则使用固定版本 `tzdata==2026.3`。

## 设计哲学

- **最小契约**：核心只施加最小必要的接口。策略族自行定义语义，核心不理解它们。
- **插件自治**：CTA、组合等 —— 每个策略族插件定义自己的世界。主干通过 entry points 发现它们，只通过协议与之交互。
- **引擎无关**：市场契约（`Bar`、`Order`、`Trade`、`Position`）不含任何引擎专属细节，任何回测引擎都可以消费它们。
- **LLM 友好**：策略接口刻意保持极简。策略族契约可声明 `on_bar(bar)` 或 `on_bars(bars)` 等生命周期入口；引擎按所选契约校验。
- **万物自白**：策略族和引擎都暴露 `confess()` 方法 —— 面向 LLM agent 的主观自白。agent 在选型前阅读自白，了解约定、陷阱和最佳实践。

## 模块总览

| 模块 | 职责 | 核心类型 |
|------|------|---------|
| `nlalpha.core.strategy.plugin` | 策略族插件协议 | `StrategyFamilyPlugin`、`BaseStrategyFamilyPlugin` |
| `nlalpha.core.strategy.runtime` | 策略运行时契约 | `EventDrivenStrategy`、`VectorizedStrategy`、`BaseEventDrivenStrategy` |
| `nlalpha.core.strategy.spec` | 策略规格通用外壳 | `StrategySpecEnvelope` |
| `nlalpha.core.capabilities` | 能力提供者框架 | `CapabilityPlugin`、`CapabilityRegistry`、`CapabilityPluginRegistry`、`CapabilityEntry`、`ProviderManifest` |
| `nlalpha.core.contracts.market` | 市场数据契约 | `MarketData`、`OrderLike`、`Bar`、`Order`、`Trade`、`Position` |
| `nlalpha.core.backtest` | 引擎无关的事件与批量执行契约 | `EngineManifest`、`EngineRunContext`、`BatchBacktestInput`、`BacktestResult`、`BacktestResultStatus` |
| `nlalpha.core.drawer` | MCP 间共享数据交换层 | `DrawerBackend`、`RedisBackend`、`S3Backend`、`get_drawer`、`register_ref`、`resolve_ref`、`resolve_ref_info` |
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
        return "# CTA 策略族自白\n\n- 遵循策略族声明的原生事件语义..."
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

core 定义两种策略运行时协议：

- **`EventDrivenStrategy`**：逐根 bar 通过 `on_bar(bar)` 接收数据。策略通过 `submit_order()` 或 `buy()`/`sell()`/`short()`/`cover()` helper 提交不可变命令，通过 `cancel_order(order_id)` 请求撤单。运行时使用 `collect_commands()` 按 FIFO 顺序取走命令。
- **`VectorizedStrategy`**：通过 `generate_signals(df)` 接收 DataFrame 并返回信号/权重序列。该协议定义策略接口；它不表示当前批量回测分发器会编译策略源代码或生成信号。

独立的 `nlalpha.core.backtest` 契约描述事件驱动和带 schema 版本的批量引擎输入。它们是纯标准库数据契约；具体引擎的金融仿真、Arrow 处理和撮合行为属于引擎/provider 包。`EngineManifest` 声明 provider 支持的运行方式与输入 schema。

core 的 backtest 契约保存运行上下文、输入、结果与策略公共契约；执行时点、费用、账户校验、订单状态和 assumptions 由实际 engine 提供，host 原样保存。

`BacktestResult.status` 仅允许 `succeeded` 或 `failed`；其他值（包括 `completed`）会触发 `ValueError`。只有 status 为 `succeeded` 且 `errors` 为空时，`is_successful` 才为真。这是引擎结果状态。宿主的 `JobService` 使用单独的任务生命周期状态，例如 `completed`；完成回调文字也不是引擎结果状态。

`BaseEventDrivenStrategy` 是事件驱动策略的共享基类，提供：

- 订单生成方法（`buy`、`sell`、`short`、`cover`）
- 账户快照属性（`initial_cash`、`available_cash`、`current_equity`）
- 动态 provider 代理 —— 任何指标或度量方法通过 `__getattr__` 从已注册的能力提供者中解析
- 生命周期钩子（`on_init`、`on_start`、`on_stop`）与可选订单/成交回调（`on_order`、`on_trade`）

### 市场契约

策略与引擎之间交换的纯数据结构：

- **`Bar`**：K 线，含 `symbol`、`datetime`、`open`、`high`、`low`、`close`、`volume`、`open_interest`
- **`Order`**：不可变订单提交命令，含 `order_id`、`symbol`、`direction`、`offset`、`volume`、可选参考 `price`、`order_type`、`limit_price`、`stop_price` 和 `time_in_force`
- **`OrderSnapshot`**：不可变订单状态快照，包含提交字段以及引擎提供的 `status`、`filled_volume`、`remaining_volume`、`avg_price`、`timestamp_ns`、`reason`
- **`CancelOrder` / `OrderEvent`**：不可变撤单意图，以及含 kind、订单快照、纳秒时间戳和原因的原生订单事件
- **`Trade`**：成交记录，含 `trade_id`、`order_id`、`symbol`、`direction`、`offset`、`price`、`volume`、`commission`、可空的 `slippage_cost` 和可选纳秒 `timestamp_ns`
- **`Position`**：持仓，支持多空分离模型，提供 `net_volume`、`avg_price`、`tradable_long`、`tradable_short`

`Order`、`CancelOrder`、`OrderSnapshot`、`OrderEvent` 和 `Trade` 都是不可变命令/事件值。`OrderSnapshot` 是只读引擎快照，不是可变请求。`OrderEvent.timestamp_ns` 和 `Trade.timestamp_ns` 在可用时保留原生纳秒时间。`MarketData` 和 `OrderLike` 仍为协议。

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
    capital={"initial": 1_000_000},
    family_spec={"indicators": [...]},
)
```

### Drawer

MCP 服务之间的共享数据交换层。MCP 消息只传递轻量的 `data_ref` 字符串，实际数据留在 Drawer 中。

**设计**：每个 MCP 服务运行在独立进程内。`nlalpha-data` 将数据写入 Drawer 并返回 `data_ref`，`nlalpha-backtest` 通过 `data_ref` 解析并读取数据，避免在 MCP 消息中序列化大型 DataFrame。

**多租户隔离**：`NLALPHA_DRAWER_NAMESPACE` 环境变量控制基础隔离域（默认 `default`，用于环境/部署级隔离）。**请求级用户隔离**由宿主注入：MCP 工具函数经 `nlalpha.core.platform.apply_user_drawer_namespace(ctx)` 从请求 HTTP header（默认 `X-NLAlpha-User-ID`，可用 `NLALPHA_IDENTITY_USER_HEADER` 覆盖）提取宿主用户，通过 `set_drawer_namespace()` 写入请求级 contextvar（命名空间由 `NLALPHA_DRAWER_NAMESPACE_TEMPLATE` 模板拼接，默认 `{env}:{user_id}`）。无宿主身份时回到基础隔离域。身份头和命名空间模板都属于宿主组合配置，核心不绑定特定平台。

**后端类型**：
- `RedisBackend`：Redis bytes 存储，index 用 hash，默认后端，适合中小对象（<10MB）和多 Pod 共享
- `S3Backend`：基于 boto3 的 MinIO/S3 兼容存储，适合大对象（>10MB），支持元数据（size, created-at）

**Index 统一走 Redis**：无论 data 后端是 Redis 还是 S3，`data_ref -> key` 映射始终存储在 Redis hash 中，确保跨 Pod 一致性。

**大对象自动路由**：写入方根据数据大小自动选择后端——大数据走 S3，小数据走 Redis。`register_ref(data_ref, key, backend_type)` 记录实际后端，`resolve_ref_info(data_ref)` 返回 `{"key", "backend"}`，读取方据此选择正确后端，避免解析失败。

**环境变量**：
| 变量 | 说明 | 默认值 |
|------|------|--------|
| `NLALPHA_DRAWER_BACKEND` | Data 后端类型（`redis`/`s3`） | `redis` |
| `NLALPHA_DRAWER_NAMESPACE` | 环境级隔离域；请求级用户隔离由宿主层经 contextvar 注入（模板见 `NLALPHA_DRAWER_NAMESPACE_TEMPLATE`） | `default` |
| `NLALPHA_DRAWER_NAMESPACE_TEMPLATE` | 用户级隔离域模板，占位符 `{env}`（环境域）、`{user_id}`（宿主用户 ID） | `{env}:{user_id}` |
| `NLALPHA_IDENTITY_USER_HEADER` | 宿主身份 HTTP header 名（入站读取 + 出站 LLM 注入共用） | `X-NLAlpha-User-ID` |
| `NLALPHA_DRAWER_REDIS_URL` | Redis 连接 URL（data + index 共用） | `redis://localhost:6379/0` |
| `NLALPHA_DRAWER_INDEX_REDIS_URL` | Index 专用 Redis URL（可选，默认同 `REDIS_URL`） | — |
| `NLALPHA_DRAWER_S3_ENDPOINT` | S3/MinIO 服务端点 | — |
| `NLALPHA_DRAWER_S3_BUCKET` | S3 Bucket 名 | — |
| `NLALPHA_DRAWER_TTL` | Data 和 Index 默认过期时间（秒） | `86400`（24h） |
| `NLALPHA_S3_ACCESS_KEY` | S3 访问密钥 | — |
| `NLALPHA_S3_SECRET_KEY` | S3 密钥 | — |

> 同一个集群内所有使用 Drawer 的服务必须配置相同的 `NLALPHA_DRAWER_BACKEND`。混合使用不同后端会导致 `data_ref` 无法解析。

```python
from nlalpha.core.drawer import get_drawer, generate_ref, register_ref, resolve_ref_info, S3Backend

# 写入方：自动路由大对象
drawer = S3Backend() if len(data_bytes) > 10 * 1024 * 1024 else get_drawer()
drawer.put(key, data_bytes)
backend_type = "s3" if isinstance(drawer, S3Backend) else "redis"
register_ref(data_ref, key, backend_type)

# 读取方：解析实际后端
info = resolve_ref_info(data_ref)
read_drawer = S3Backend() if info.get("backend") == "s3" else get_drawer()
parquet_bytes = read_drawer.get(info["key"])
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
| `nlalpha-engine-vector` | 面向带 schema 版本预计算信号批次的 Arrow/Rust provider |

平台 workspace 副本是平台构建使用的活跃源码。除 Python 标准库外，Core 需要固定 `tzdata==2026.3`；telemetry 集成仍为可选能力。

## 安装

```bash
pip install nlalpha-core          # 仅核心，零依赖
pip install "nlalpha-core[all]"   # 包含遥测、dotenv、结构化日志
```

Core 除标准库外还依赖固定版本 `tzdata==2026.3`，提供跨运行时一致的时区规则。其他可选 extras：

| Extra | 依赖 | 用途 |
|-------|------|------|
| `dotenv` | `python-dotenv` | `.env` 文件加载 |
| `telemetry` | `opentelemetry-*` | 链路追踪、指标、日志 |
| `json-log` | `python-json-logger` | 结构化 JSON 日志 |
| `all` | 以上全部 | 启用所有可选能力 |

## 共享结果中的 reports

`BacktestResult.reports` 是可选字典，承载引擎拥有的报告表。每表包含 `schema_id`、`source`、`status`、`reason`、`row_count`、`columns`、`rows`、`metadata`；Core 只校验共享外层契约，不依赖金融库，也不强行统一各引擎列定义。状态可区分空但可用、未记录和生成失败。

## 当前版本针对性核验

Core 0.5.0 历史版本的 reports 外层结构经宿主报告持久化与 cache 恢复路径做了针对性核验；这仅记录集成核验范围，不代表 Core 完整测试套件通过。

## 市场时间戳契约

Core 0.6.0 将 `Bar.datetime`（收盘时刻）及可选 `open_time` 规范为带时区的 UTC。Bar 可保留 `session_date`、`source_timezone`、`source_utc_offset_seconds`、`source_timestamp_semantics`（`open`、`close`、`trading_date`）与 `calendar_id`；这些字段描述原始来源，UTC 重建时也保留。不会从 UTC 日期推断交易日标签。Python Bar datetime 保留微秒，遇到亚微秒精度会拒绝截断；底层 Arrow/引擎原始时间戳仍可使用纳秒。

`nlalpha.core.contracts.time` 从固定 `tzdata==2026.3` 提供时区规则，包括 `get_timezone`、`timezone_data`、`timezone_metadata`、严格 `normalize_utc`、精确整数 datetime/ns 转换和九位小数的 `format_timestamp_ns`。Python 与 Rust 使用同一份 TZIF 数据，metadata 记录版本和 SHA-256。naive 本地时间必须声明有效 IANA 时区；歧义或不存在的本地时刻会失败。

源时区 metadata 是来源证据：用已规范化 UTC 收盘时刻重建 Bar 时，仍须保留原 IANA zone key 或精确原始 offset、source semantics、交易日标签和 calendar 身份。规范时间点与来源描述分开保存。
