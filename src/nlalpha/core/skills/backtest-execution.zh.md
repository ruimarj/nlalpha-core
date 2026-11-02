# 回测执行

Skill ID: backtest-execution  
Revision: 1  
Language: zh

## 目的

只执行或评审用户请求的回测工作。先从任一服务 `about` 描述的 `principles` section 读取共同的证据、授权和结果边界。description revision 未变化时复用；revision 变化后重新读取当前 section。随后按需读取当前策略、数据和回测服务说明。说明完整且 revision 未变化时可以复用；若支持按 section 读取，只补取当前所需部分。

## 发现可用路径

区分新历史回测与查询、取消、取得或评审既有任务。新回测前发现当前策略族、引擎、validator、事件或 batch 工具及数据 provider。只使用实时目录显示可用的工具。按需读取所选策略族、引擎、provider 和 validator 的当前契约。事件和 batch 路径是条件能力，不得将二者都视为必需。

## 准备与验证

保留用户的策略、品种、日期、时点、账户行为、仓位、成本和风险选择。确认所选策略族与引擎能够表达这些要求。特别是用户要求动态使用当前可用现金时，保留该语义，不得近似为按初始资金静态计算。

核实请求范围内的数据覆盖、质量、价格来源证据、时间戳、时区、单位和日历。只加载任务所需数据，并保留不可变引用及其来源和 scope。依据当前选择的事件或 batch 对象契约校验必需字段，不依赖示例或记忆中的 schema。正式提交前执行适用的静态检查与对应路径的 mock 验证。

## 执行与检查

只有前置条件满足且用户授权新回测时才提交。持续观察已有任务，直到取得真实终态。状态未知或任务仍在运行时，不重复提交。既有任务只执行用户指定的状态查询、取消、取结果或评审操作。

仅按所需结论读取结果和报告部分。确认结果状态为干净成功、数据与策略符合请求，且报告覆盖结论范围。缺失、未记录、截断或不可用的字段保持未知，不当作零。任务结束或工具响应成功本身不等于回测成功。

## 报告结果

用用户的语言说明请求范围、假设、实际验证、结果状态、审阅的证据、风险和限制。静态检查与 mock 不能证明历史表现。回测结果只描述所测样本和假设，不预测未来表现。未经授权不增加实验来填补报告证据缺口。

## 能力路由

从实时工具目录发现路由；以下只是逻辑服务操作，不保证当前环境已安装。新事件驱动回测常用路由包括 `strategy.list_families`、`strategy.about`、`strategy.confess`、`data.list_data_providers`、`data.confess`、`data.check_data_coverage`、`data.get_data_quality`、`data.load_bars`、`backtest.list_engines`、`backtest.confess`、`backtest.validate_strategy` 和 `backtest.run_backtest`。`backtest.validate_batch_strategy`、`backtest.run_batch_backtest` 等 batch 路由仅在实际发布且可用时使用。`backtest.get_backtest_status`、`backtest.cancel_backtest`、`backtest.get_backtest_result` 和 `backtest.get_backtest_report` 等状态、取消、结果与报告路由仅用于用户请求的对应操作。

通过 `strategy.load_skill(name, language)` 读取已打包的 skill；每次调用只请求一种语言。英文和中文文件的章节对应。
