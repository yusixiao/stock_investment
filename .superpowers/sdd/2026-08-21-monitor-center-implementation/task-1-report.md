# Task 1 实施报告

## 范围

已实现监控中心持久化层，未实现价格评估、策略调度、API 或前端。

## 实施内容

- 在 `init_portfolio_v1_tables` 中新增四张幂等 SQLite 表及查询索引：策略监控、策略运行、股票监控、股票触发事件。
- 新增 `StrategyMonitor`、`StrategyRun`、`StockPriceMonitor` 持久化实体。
- 新增 `MonitoringRepository`，覆盖策略监控 CRUD/软删除、运行记录、股票监控 CRUD/暂停恢复/软删除。
- `claim_price_trigger` 使用事务和 `UPDATE ... WHERE is_active = 1 AND state = 'armed'`，确保同一 armed 监控只创建一次事件。
- 策略监控与股票监控之间没有外键或同步关系；软删除不删除运行记录或触发事件。
- JSON 字段以 JSON text 存储并在 repository 层还原。

## TDD 证据

1. 先添加 `backend/tests/test_monitoring_repository.py`。
2. 首次运行失败：`ModuleNotFoundError: No module named 'services.monitoring'`。
3. 添加最小 schema、实体和 repository 实现。
4. 再次运行通过。

## 验证

- `rtk pytest backend/tests/test_monitoring_repository.py backend/tests/test_portfolio_account_service.py backend/tests/test_portfolio_migration.py -q`：35 passed
- `rtk git diff --check`：通过
- SQLite 双次初始化检查：`schema idempotence: OK`

## Concerns

- 工作区原有 `frontend/package-lock.json` 修改未触碰、未纳入本任务提交。
- 本任务未运行后端全量测试；已运行监控及受影响 Portfolio schema/repository 回归测试。
