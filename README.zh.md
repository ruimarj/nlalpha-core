# nlalpha-core

nlalpha 自然语言驱动量化生态的领域契约与插件框架。

这是**基础包**，nlalpha 体系内的所有其他包都依赖它。它为策略族插件、策略生成、回测引擎和能力提供者之间定义了共享语言。

平台 workspace 中的包版本为 `0.7.0`。回测契约与具体引擎及宿主无关；时区规则使用固定版本 `tzdata==2026.3`。

## 设计哲学

- **最小契约**：核心只施加最小必要的接口。策略族自行定义语义，核心不理解它们。
- **插件自治**：CTA、组合等，每个策略族插件定义自己的世界。主干通过 entry points 发现它们，只通过协议与之交互。
- **引擎无关**：市场契约（`Bar`、`Order`、`Trade`、`Position`）不含任何引擎专属细节，任何回测引擎都可以消费它们。
- **LLM 友好**：策略接口刻意保持极简。策略族契约可声明 `on_bar(bar)` 或 `on_bars(bars)` 等生命周期入口；引擎按所选契约校验。
- **万物自白**：服务暴露结构化的 `about` 描述和对象级 `confess` 说明。agent 从实时目录发现已安装能力，再阅读所选策略族或 provider 契约及声明的指引后再依赖它。

## 模块总览

| 模块 | 职责 | 核心类型 |
|------|------|---------|
| `nlalpha.core.strategy.plugin` | 策略族插件协议 | `StrategyFamilyPlugin`、`BaseStrategyFamilyPlugin` |
| `nlalpha.core.strategy.runtime` | 策略运行时契约 | `EventDrivenStrategy`、`VectorizedStrategy`、`BaseEventDrivenStrategy` |
| `nlalpha.core.strategy.spec` | 策略规格通用外壳 | `StrategySpecEnvelope` |
| `nlalpha.core.capabilities` | 能力提供者框架 | `CapabilityPlugin`、`CapabilityRegistry`、`CapabilityPluginRegistry`、`CapabilityEntry`、`ProviderManifest` |
| `nlalpha.core.contracts.market` | 市场数据契约 | `MarketData`、`OrderLike`、`Bar`、`Order`、`Trade`、`Position` |
| `nlalpha.core.backtest` | 引擎无关的事件与批量执行契约 | `EngineManifest`、`EngineRunContext`、`BatchBacktestInput`、`BacktestResult`、`BacktestResultStatus` |
| `nlalpha.core.data_artifacts` | MCP 服务间共享的带作用域不可变产物 | `DataArtifactStore`、`RedisDataArtifactStore`、`DataArtifact`、`ArtifactScope`、`ArtifactMetadata` |
| `nlalpha.core.artifact_config` | 应用本地产物后端配置 | `ArtifactStoreConfig`、`create_data_artifact_store` |
| `nlalpha.core.telemetry` | 可观测性工具 | `get_tracer`、`start_span`、`setup_logging` |
| `nlalpha.core.config` | 配置辅助 | — |
| `nlalpha.core.errors` | 共享错误类型与六个规范错误码 | `NlAlphaError`、`DataError`、`ErrorType`、`ErrorStage` |
| `nlalpha.core.result_contract` | 规范失败信封与确定性预算执行器 | `build_error`、`failure_response`、`format_traceback_tail`、`enforce_budget` |

## 核心概念

### 策略族插件

策略族插件代表一个策略**世界**，如 CTA、组合优化、价差交易。它声明：

- `family`：策略族标识符（如 `"cta"`、`"portfolio"`）
- `family_contract()`：策略族专属契约模式
- `confess()`：主观补充说明、注意事项和最佳实践（Markdown 格式）

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

插件通过 `nlalpha.strategy_family` entry points 被发现。参考实现见 `nlalpha-family-cta`。

### 能力提供者插件

能力插件向策略代码注入领域专属 helper，如指标、风险度量、组合优化器等。它们通过 `nlalpha.capabilities` entry points 被发现。

> **注**：nlalpha 的能力插件本质上是成熟开源量化库（quantstats、empyrical、arch、pyportfolioopt 等）的适配层。核心只定义契约，实际计算由这些库完成。

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

### 策略运行时

核心定义两种策略运行时协议：

- **`EventDrivenStrategy`**：逐根 bar 通过 `on_bar(bar)` 接收数据。策略通过 `submit_order()` 或 `buy()`/`sell()`/`short()`/`cover()` helper 提交不可变命令，通过 `cancel_order(order_id)` 请求撤单。运行时使用 `collect_commands()` 按 FIFO 顺序取走命令。
- **`VectorizedStrategy`**：通过 `generate_signals(df)` 接收 DataFrame 并返回信号/权重序列。该协议定义策略接口；它不表示当前批量回测分发器会编译策略源代码或生成信号。

独立的 `nlalpha.core.backtest` 契约描述事件驱动和带 schema 版本的批量引擎输入。它们是纯标准库数据契约；具体引擎的金融仿真、Arrow 处理和撮合行为属于引擎/provider 包。`EngineManifest` 声明 provider 支持的运行方式与输入 schema。

核心的 backtest 契约保存运行上下文、输入、结果与策略公共契约；执行时点、费用、账户校验、订单状态和假设由实际引擎提供，宿主原样保存。

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

### 不可变数据产物

`DataArtifactStore` 是 MCP 服务之间交付不可变数据的异步边界。`data_ref` 标识一个确切载荷及其 metadata：可信作用域、媒体类型、schema、字节大小、SHA-256 摘要、创建时间与逻辑过期时间。发布创建新的引用，不覆盖既有产物。读取会校验载荷与作用域，过期或越界的引用会失败。

`redis` 与 `s3` 后端按各服务部署显式选择，不按大小路由。Redis 直接存储产物信封。S3 每个对象存储一个信封，不使用 Redis 索引。MinIO 是可选的 S3 兼容服务，不是 Redis 部署的必需项。不存在默认 10 MiB 上限：未配置时 `max_bytes` 为空，所选后端仍受其部署预算约束。

每个应用拥有自己的 store 生命周期。使用 `create_data_artifact_store()` 创建，在提供服务前调用 `start()`，应用停止时用 `aclose()` 关闭。`nlalpha-data` 与 `nlalpha-backtest` 都使用该接口；Data 到 backtest 的消费路径已通过父级指导的端到端核验。

**产物配置**：

| 变量 | 默认值 | 含义 |
|----------|---------|---------|
| `NLALPHA_ARTIFACT_BACKEND` | `redis` | 所选后端：`redis` 或 `s3` |
| `NLALPHA_ARTIFACT_REDIS_URL` | `redis://127.0.0.1:6379/0` | Redis 产物服务 URL |
| `NLALPHA_ARTIFACT_TTL_SECONDS` | `86400` | 每个产物的逻辑生命周期（秒） |
| `NLALPHA_ARTIFACT_MAX_BYTES` | 未设置 | 可选的产物载荷最大字节数；无默认 10 MiB 上限 |
| `NLALPHA_ARTIFACT_S3_BUCKET` | S3 必填 | 存放产物对象的 bucket |
| `NLALPHA_ARTIFACT_S3_ENDPOINT` | 未设置 | 可选的 S3 兼容端点，如 MinIO |
| `NLALPHA_ARTIFACT_S3_ACCESS_KEY` / `NLALPHA_ARTIFACT_S3_SECRET_KEY` | 未设置 | 可选的成对凭据 |
| `NLALPHA_ARTIFACT_S3_REGION` | 未设置 | 可选的 S3 region |
| `NLALPHA_ARTIFACT_S3_RETENTION_DAYS` | `1` | 必需的 bucket 生命周期保留天数（整天）；必须覆盖逻辑 TTL |

S3 读取会强制执行每个对象确切的逻辑过期时间。bucket 的物理生命周期清理是异步的、按天进行的，不保证在逻辑过期那一刻完成。启动前，配置的 bucket 必须禁用版本控制，并启用覆盖专用 `nlalpha/artifacts/v1/` 前缀、保留期与配置一致的 lifecycle 规则。不要把 lifecycle 配置测试理解为等待完整保留期后对象已被物理删除的证明。

### 宿主身份与作用域

`HostIdentityConfig` 从宿主提供的请求上下文解析 `ArtifactScope(environment, owner)`。`NLALPHA_ENV` 默认为 `local`，并属于作用域的一部分。`NLALPHA_IDENTITY_MODE` 默认为 `single-user`，此时 owner 固定为 `standalone`，并拒绝传入的身份 header。在 `trusted-host` 模式下，服务要求可信网关提供配置的 `NLALPHA_IDENTITY_USER_HEADER`（默认 `X-NLAlpha-User-ID`）。这是宿主边界上的身份映射，不是 NLAlpha 实现的认证；网关必须认证并保护该 header。

DNS rebinding 防护保持启用。允许的 host 依次来自显式应用参数、`NLALPHA_ALLOWED_HOSTS`，或安全的 localhost/loopback 默认值。公网或容器 hostname 必须显式配置；通配符 host 会被拒绝。

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

## 安装

```bash
pip install nlalpha-core          # 核心加固定 tzdata
pip install "nlalpha-core[all]"   # 包含 telemetry、dotenv、json-log
```

平台 workspace 副本是平台构建使用的活跃源码。核心需要固定 `tzdata==2026.3` 以保持一致的时区规则；telemetry 集成仍为可选。可选 extras：

| Extra | 依赖 | 用途 |
|-------|-------------|---------|
| `dotenv` | `python-dotenv` | `.env` 文件加载 |
| `telemetry` | `opentelemetry-*` | 链路追踪、指标、日志 |
| `json-log` | `python-json-logger` | 结构化 JSON 日志 |
| `all` | 以上全部 | 启用所有可选能力 |

## 共享结果中的 reports

`BacktestResult.reports` 是可选字典，承载引擎拥有的报告表。每表包含 `schema_id`、`source`、`status`、`reason`、`row_count`、`columns`、`rows` 和 `metadata`；核心只校验共享外层契约，不依赖金融库，也不定义统一的列 schema。状态可区分空但可用的表、未记录的表和生成失败。

## 结果与错误契约

`nlalpha.core.result_contract` 是面向 agent 的失败构造入口，供 MCP 响应、runner stderr 载荷和适配器证据复用。`build_error(exc, stage=None)` 返回有序对象 `type → message → stage → retryable → suggestion → traceback_tail → details`：错误码取自异常的 `error_type` 类变量（未知时为 `internal_error`），`suggestion`、`details`、`retryable` 和 `stage` 取自可选的异常属性。`failure_response` 将其包装为 `{"status": "failed", "error": {...}}`。上限固定：message 2 KiB，suggestion 1 KiB，traceback tail 4 KiB，覆盖最后 15 个用户/策略栈帧（排除标准库、site-packages 和 `nlalpha`/`nlalpha_*` 帧；仅有框架帧时省略），details 8 KiB，列表裁剪为 10 项 × 512 B 并附带 `*_count`/`errors_total`。`enforce_budget(payload, priority=..., max_bytes=...)` 按调用方声明的优先级裁剪超大响应：丢弃 section，按前缀裁剪列表并附带 `*_count`/`*_truncated`，最后对末尾 section 做 UTF-8 安全的字节截断并标记 `result_truncated`；`error` 块永不裁剪。预算常量（`RESPONSE_BUDGET_BYTES` 256 KiB、`ERROR_BUDGET_BYTES` 16 KiB 及各字段上限）从同一模块导出。

## 当前版本针对性核验

Core 0.5.0 的历史 report 信封经宿主报告持久化与缓存恢复路径做了针对性核验。这里只记录针对性集成覆盖，不代表 Core 完整测试套件结果。

## 市场时间戳契约

Core 0.7.0 将 `Bar.datetime`（收盘时刻）及可选 `open_time` 规范为带时区的 UTC。每个 Bar 可保留 `session_date`、`source_timezone`、`source_utc_offset_seconds`、`source_timestamp_semantics`（`open`、`close` 或 `trading_date`）与 `calendar_id`；这些字段描述原始来源，UTC 重建时也保留。不会从 UTC 日期推断交易日标签。Python Bar datetime 保留微秒，遇到亚微秒精度会拒绝截断；底层 Arrow/引擎原始时间戳仍可使用纳秒。

`nlalpha.core.contracts.time` 从固定 `tzdata==2026.3` 提供时区规则，包括 `get_timezone`、`timezone_data`、`timezone_metadata`、严格 `normalize_utc`、精确整数 datetime/ns 转换和九位小数的 `format_timestamp_ns`。Python 与 Rust 使用同一份 TZIF 数据，metadata 记录版本和 SHA-256。naive 本地时间必须声明有效 IANA 时区；歧义或不存在的本地时刻会失败。

源时区 metadata 是来源证据：用已规范化 UTC 收盘时刻重建 Bar 时，仍须保留原 IANA zone key 或精确原始 offset、source semantics、交易日标签和 calendar 身份。规范时间点与来源描述分开保存。

## 自描述与打包指引

`nlalpha.core.description` 构建 `nlalpha.description.v1` 文档。描述 revision 是完整规范文档的 SHA-256，因此整篇读取与按节读取共享同一 revision。`markdown_sections()` 按英文二级标题拆分；`common_description()` 读取打包的通用原则；`read_skill(name, language)` 读取指定语言的单个打包 skill；`skill_catalog(language)` 列出每个打包 skill 的标题、描述、revision 和内容 SHA-256。必需的缺失文档和未知 section ID 会显式失败。服务通过 `about` 与 `confess` 暴露这些材料；核心打包资源，但自身不注册 MCP 工具。

策略族插件继承 `BaseStrategyFamilyPlugin`，实现 `family_contract() -> FamilyContract` 和 `confess()`。注册表为每个策略族缓存一条发现记录，包括插件实例、契约、说明和分发身份。注册表 metadata 失败会保留在诊断中；重复的策略族身份会同时禁用两条记录，清空注册表只移除自身发布的能力条目。基类不要求 `about()` 方法。

telemetry instrument 是惰性的；宿主已配置公共 provider 时与其共享。独立 CLI 可显式调用 `configure_telemetry()` 并拥有产生的 provider；它应只在工作完成且采集停止后 flush 和 shutdown。库不得关闭由其他宿主拥有的 provider。

对于 NLAlpha 服务进程，CLI main 拥有 telemetry SDK 生命周期，并将 shutdown 注入既有 ASGI lifespan。应用拥有的资源在 SDK flush/shutdown 回调之前关闭；应用构造失败也会进入进程清理。四个服务 app factory 在不接管进程 telemetry 的情况下仍可使用。Docker shutdown smoke 已在全部 11 个当前运行镜像上验证最终信号处理和资源清理；这是本地镜像证据，不是已发布的部署结果。

英文和中文任务 skill 与通用原则打包在 `src/nlalpha/core/skills/` 和 `src/nlalpha/core/knowledge/`。它们的规范服务注册属于消费方责任。

## 自描述与产物读取预算

包携带唯一的规范通用原则资源和英文/中文任务 skill 对。描述文档使用 schema `nlalpha.description.v1`；选中 section 与完整文档共享一个 SHA-256 `description_revision`。四个服务从已安装分发 metadata 及其实际 manifest、contract、helper 和资源记录构建描述。没有已安装分发 metadata 的源码检出不会合成包版本。

产物 metadata 有 64 KiB 协议上限；这不是载荷上限。Redis 将单次范围读取限制为配置的载荷预算加 metadata 信封。S3 先读取有界 metadata，校验配置的载荷预算，再以不超过 64 KiB 的分块流式读取至声明大小加一字节，并关闭响应体。`max_bytes=None` 表示没有包默认载荷上限。反序列化对象内存与并发读取预算属于部署配置。

## 许可证

`nlalpha-core` 是 AGPL-3.0-or-later 下的 10 个社区分发之一。根许可证只覆盖这些社区分发和通用社区材料；私有包、平台代码、适配器和第三方依赖保留各自许可证。
