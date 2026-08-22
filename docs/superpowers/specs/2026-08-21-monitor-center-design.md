# Monitor Center Design

## 1. Goal

将当前仅有前端占位实现的“盘面监控”改造成独立的“监控中心”，提供两类互不关联的后台监控能力：

1. 策略运行监控：按用户设置的交易周期自动运行策略并保存运行记录。
2. 股票价格监控：用户手动添加股票和目标价格，每个交易日检查收盘价并记录触发事件。

本阶段不实现邮件、SMTP、Webhook 或其他通知渠道；只持久化监控状态和触发事件，为后续通知渠道提供稳定事件源。

## 2. Non-Goals

- 策略运行监控不生成或创建股票价格监控。
- 股票价格监控不关联策略、回测任务、策略账户或策略目标。
- 不支持从策略结果中选择股票加入价格监控。
- 不因策略重新运行而创建、修改、暂停或删除股票监控。
- 不在本阶段发送邮件或配置通知渠道。
- 不把监控数据放进 Portfolio 账户、持仓或交易表。

## 3. Domain Model

### 3.1 Strategy Monitor

策略监控保存一个可定期运行的策略配置快照：

- `id`
- `name`
- `strategy_class`
- `filepath`
- `params` JSON
- `market`
- `frequency`: `daily | weekly | monthly | quarterly`
- `symbols` JSON，可为空表示策略默认股票池
- `is_active`
- `next_run_date`
- `last_run_at`
- `last_run_status`: `pending | running | success | failed`
- `last_error`
- `created_at`, `updated_at`

每次运行另存 `strategy_monitor_runs`：

- `id`, `monitor_id`
- `scheduled_date`, `started_at`, `finished_at`
- `status`: `running | success | failed`
- `task_id`，如果复用现有回测任务记录
- `result` JSON 或结果引用
- `error`

策略监控的频率含义：

- `daily`: 每个市场交易日运行。
- `weekly`: 每周第一个交易日运行。
- `monthly`: 每月第一个交易日运行。
- `quarterly`: 每年 1、4、7、10 月第一个交易日运行。

判断调度日必须基于 DuckDB 的市场交易日数据，不使用自然日猜测。A/HK/US 按各自市场交易日独立判断。

### 3.2 Stock Price Monitor

股票监控完全独立保存：

- `id`
- `market`: `A | HK | US`
- `symbol`
- `name`，可选缓存展示名
- `threshold_price`
- `is_active`
- `state`: `armed | triggered | paused`
- `last_price`
- `last_price_date`
- `last_triggered_at`
- `created_at`, `updated_at`

不包含 `strategy_task_id`、`account_id` 或任何策略外键。

每次触发另存 `stock_price_monitor_events`：

- `id`, `monitor_id`
- `market`, `symbol`
- `observed_price`, `threshold_price`
- `observed_date`, `triggered_at`
- `status`: `recorded | notified`

`notified` 仅为未来通知渠道预留，本阶段始终写入 `recorded`。

## 4. Trigger Rules

股票价格监控每天市场数据刷新完成后执行：

1. 读取该市场最新已完成交易日收盘价。
2. 只处理 `is_active=1` 且 `state != paused` 的监控。
3. 当 `close < threshold_price` 且当前状态为 `armed` 时，原子写入一条事件并将状态设为 `triggered`。
4. 当 `close >= threshold_price` 时，将 `triggered` 状态重新设为 `armed`，不创建事件。
5. 同一监控在价格持续低于阈值期间只触发一次。
6. 缺少行情时不改变状态、不创建事件，并记录可诊断日志。
7. A/HK/US 市场评估相互隔离，一个市场失败不阻断其他市场。

## 5. Strategy Run Rules

策略运行监控到期后由 scheduler 执行：

1. 使用现有 Strategy loader 和回测执行能力，不能由前端直接执行 Python 策略。
2. 每个到期 monitor 只创建一个运行记录，重复 scheduler 触发不得重复运行。
3. 运行成功保存 `strategy_monitor_runs`；运行失败保留上一次成功结果并保存错误。
4. 策略运行结果只属于策略监控，不创建股票价格监控。
5. 当前策略执行能力若无法安全支持“当前交易日单次运行”，先抽取可复用的策略运行服务，不通过伪造历史日期绕过执行语义。

## 6. API Boundary

建议新增独立路由前缀 `/api/v1/monitoring`：

### Strategy monitors

- `GET /strategy-monitors`
- `POST /strategy-monitors`
- `PATCH /strategy-monitors/{id}`
- `DELETE /strategy-monitors/{id}`，软停用
- `POST /strategy-monitors/{id}/run`，手动触发一次
- `GET /strategy-monitors/{id}/runs`

### Stock price monitors

- `GET /stock-monitors`
- `POST /stock-monitors`
- `PATCH /stock-monitors/{id}`
- `DELETE /stock-monitors/{id}`，软停用
- `POST /stock-monitors/{id}/pause`
- `POST /stock-monitors/{id}/resume`
- `GET /stock-monitors/{id}/events`

API 不提供策略到股票监控的导入接口，防止两个域重新耦合。

## 7. Scheduler Boundary

新增独立 monitoring service，由现有 scheduler 在市场刷新成功后调用：

- `run_due_strategy_monitors()`：按市场和频率执行到期策略监控。
- `evaluate_stock_price_monitors(markets)`：按成功刷新的市场评估价格监控。

两者独立执行、独立日志和失败隔离。任务状态写入 SQLite，避免重启或重复回调造成重复运行/重复事件。

## 8. Frontend

将 `MarketMonitor.tsx` 从临时内存组件改为监控中心页面，分成两个独立区域：

- 策略运行监控：策略配置、频率、下次运行日、最近运行状态、手动运行。
- 股票价格监控：市场、股票代码、目标价、当前价、状态、暂停/恢复/删除、事件记录。

股票监控表单必须要求用户手动输入市场、股票代码和目标价格；不出现“从策略选择股票”入口。

页面状态只通过 `/api/v1/monitoring` 获取，不读 Portfolio API。

## 9. Error Handling

- 策略不存在或配置无效：创建/更新返回 409 或 422，不创建半成品监控。
- 调度运行失败：运行记录标记 failed，保留错误，下一次到期仍可重试。
- 股票代码无行情：监控继续保留，状态不触发，返回最近可诊断状态。
- 重复股票监控：同一市场同一 symbol 允许多条记录，因为它们可能有不同阈值；API 返回各自 id。
- 删除采用软停用，历史运行记录和价格事件保留。

## 10. Security and Data Rules

- 不通过 HTTP 返回 SMTP 密码；本阶段不处理 SMTP。
- 所有监控业务数据写入 SQLite，通过 repository/service 访问。
- 不读取 parquet 或旧数据路径；行情查询必须通过 DuckDBStore。
- 长时间策略运行必须后台执行，并持久化状态和日志。

## 11. Acceptance Criteria

- 用户可以创建、暂停、恢复和软删除独立股票价格监控。
- 每个交易日价格低于阈值只产生一次事件，价格恢复后可再次触发。
- 用户可以创建带 daily/weekly/monthly/quarterly 周期的策略运行监控。
- scheduler 能按市场交易日运行到期策略监控。
- 策略监控和股票价格监控之间没有外键、导入入口或隐式同步。
- 策略运行失败不影响股票价格监控；单市场价格评估失败不影响其他市场。
- 前后端测试、TypeScript、ESLint 和后端全量测试通过。
