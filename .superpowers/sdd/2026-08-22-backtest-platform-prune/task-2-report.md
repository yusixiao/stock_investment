# Task 2 报告

## 改动文件

- `backend/main.py`：lifespan 改为仅初始化 runtime tables、DuckDB、stock index、cache 和 scheduler，不再导入或调用 `services.portfolio.db.init_db`。
- `backend/scheduler.py`：删除 `_snapshot_job`、`_evaluate_buy_opportunities_after_refresh` 及 daily snapshot 注册；保留市场刷新、重试和两个 monitoring 回调。
- `backend/services/db_schema.py`：新增 `init_runtime_tables(conn)`，集中初始化 backtest、market refresh、monitoring 表。
- `backend/tests/test_scheduler.py`：移除 portfolio scheduler 旧断言，新增 monitoring 保留且 portfolio 工作移除的回归测试。
- `backend/tests/test_scheduler_market_retry.py`：移除已删除 buy-opportunity seam 的旧断言。
- `backend/tests/test_runtime_bootstrap.py`：新增 lifespan 不导入 portfolio bootstrap 的测试。
- `backend/tests/test_portfolio_migration.py`：移除已删除 snapshot job 和 daily snapshot 调度的过时测试，保留 portfolio schema/API 迁移覆盖。

## 测试命令及结果

- `python -m pytest backend/tests/test_scheduler.py -k refresh_completion_keeps_monitoring_and_drops_portfolio_work -q`：通过，1 passed。
- `python -m pytest backend/tests/test_scheduler.py backend/tests/test_scheduler_market_retry.py backend/tests/test_runtime_bootstrap.py -q`：通过，18 passed。
- 必要 backend 回归集（scheduler、retry、bootstrap、runtime schema、portfolio migration、monitoring repository/strategy/stock tests）：通过，64 passed。

## Concerns

- 未运行完整 `backend/tests/` 全量套件；本次仅运行 brief 指定和受影响模块的必要回归集。
- `services.portfolio.db.init_db` 仍由 portfolio 路由及 portfolio 测试使用，按要求未删除 portfolio 路由或产品代码。
