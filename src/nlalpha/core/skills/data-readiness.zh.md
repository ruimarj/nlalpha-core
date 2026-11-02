# 数据准备

Skill ID: data-readiness  
Revision: 1  
Language: zh

## 目的

检查所需行情数据是否可用、是否适合当前任务；用户需要数据引用时再准备数据。先从任一服务 `about` 描述的 `principles` section 读取共同的证据和范围原则。description revision 未变化时复用；revision 变化后重新读取当前 section。随后读取数据服务说明及相关 provider 说明。说明完整且 revision 未变化时可以复用；若支持按 section 读取，只补取当前所需部分。

## 确定请求范围

确认品种、周期、日期范围和目的：覆盖检查、质量检查、日历或时间核验、缺失交易日分析，或准备数据。数据检查本身不授权回测。仅在请求确实需要时才额外准备数据或启动运行。

## 选择并评估来源

发现当前可用 provider。用户明确指定时使用指定来源；否则遵循已配置的默认项或服务的单一可用来源规则。若多个来源可用但没有默认项，应请用户选择，或说明因此无法继续。不得静默换源。在开展 provider 专属能力前，读取所选 provider 的 manifest capabilities 与相关 `confess` 章节；不要根据工具名或包名推断支持范围。

针对确切品种、周期和范围检查覆盖与质量。价格复权属性相关时核实来源证据。复权基准与锚点由所选 provider 的说明定义；不要假定不同 provider 使用相同锚点。进行时间判断前确认时间戳含义、时区、周期和适用的品种日历。日期范围、记录数、加载成功或日历会话本身都不能证明实际观测覆盖。精确缺失交易日数必须将真实观测日期与适用日历对照；任一证据不可用时，报告数量未知。

## 按需加载数据

只有任务需要数据引用、核验加载契约或支持后续已授权研究时才加载。将返回的不可变 `data_ref`、来源 metadata、时间契约、单位和 scope 作为一组保留。引用只标识其 scope 下的 payload，不能证明数据质量或覆盖完整。复用既有数据前，核实来源、schema、scope 和时间语义符合本次请求。

## 报告核验结果

用用户的语言说明检查范围、实际覆盖与质量、已确认的来源和时间证据，以及重要未知。不要推断缺失日期、复权、时区、日历或单位。provider 或所需证据不可用时，说明限制，不用假设补齐。

## 能力路由

从实时工具目录发现路由；以下只是逻辑服务操作，不保证当前环境已安装。常用数据路由为 `data.list_data_providers`、`data.confess`、`data.check_data_coverage` 和 `data.get_data_quality`。仅在需要数据引用或核验加载契约时使用 `data.load_bars`。只有需要日历证据时，才按需使用 `data.list_trading_calendars`、`data.get_trading_days` 或 `data.is_trading_day`。

通过 `strategy.load_skill(name, language)` 读取已打包的 skill；每次调用只请求一种语言。英文和中文文件的章节对应。
