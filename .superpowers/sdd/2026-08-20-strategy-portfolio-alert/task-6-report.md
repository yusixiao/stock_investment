# Task 6 完成报告

## 删除与迁移清单

- 删除 `backend/routers/portfolio.py`，生产不再注册旧 `/api/portfolio` 路由。
- 删除 `backend/services/portfolio/manager.py`，旧 `PortfolioManager` 不再被调度器或生产代码引用。
- 删除旧接口测试 `test_portfolio_api.py`、`test_portfolio_manager.py` 和只覆盖旧表的 `test_portfolio_db.py`。
- 将 `backend/services/portfolio/db.py` 收窄为共享 SQLite connection/bootstrap helper，不再创建旧 `portfolios`、`trades`、`snapshots` 表。
- `init_db()` 现在幂等初始化 v1 portfolio schema，并保留 `backtest_tasks`、`chat_sessions`、`chat_messages` 共享表。
- 更新 `test_portfolio_account_service.py`，验证共享表保留且旧表不再由 bootstrap 创建。
- 新增 `test_portfolio_migration.py`，覆盖路由移除、共享 schema、scheduler 调用契约、v1 快照落库和 15:30 调度。

## Scheduler 接口

- `_snapshot_job()` 仍从 `DuckDBStore` 查询 A 股每只股票最新收盘价。
- 最新交易日期取查询结果最大 `date`，价格字典传入新的 `holdings_service.take_all_snapshots()`。
- 连接由共享 `get_connection()` 提供，并在服务调用后始终关闭。
- 调度时间从原来的 `SCHEDULER_MINUTE + 10` 修正为 `SCHEDULER_MINUTE`，当前保持 `15:30`。
- v1 新增 `portfolio_account_snapshots`，快照按 `account_id + date` 幂等 upsert。
- 快照估值由 v1 holdings service 的实际持仓推导；当前 v1 account 没有现金字段，因此 `cash=0`，`total_value=market_value`。

## TDD 与测试输出

先写失败测试并运行：

```text
Pytest: 0 passed, 5 failed
失败原因分别为：旧路由仍注册、共享 backtest/chat 表未初始化、scheduler 没有 v1 快照方法、快照方法不存在、调度为 15:40。
```

定向后端回归：

```text
rtk pytest backend/tests/test_portfolio_migration.py backend/tests/test_portfolio_account_service.py backend/tests/test_portfolio_holdings_service.py backend/tests/test_buy_opportunity.py -q
Pytest: 43 passed
```

前端 Vitest：

```text
npm test
Test Files  40 passed (40)
Tests       392 passed | 2 skipped (394)
Duration    11.56s
```

前端 TypeScript：

```text
npx tsc --noEmit
TypeScript: No errors found
```

前端 ESLint：

```text
npm run lint
ESLint: No issues found
```

Diff 检查：

```text
rtk git diff --check
无输出，退出码 0
```

完整后端 suite 按长任务规则后台执行：

```text
nohup python -m pytest backend/tests/ -x -q > logs/task6-backend-pytest.log 2>&1 &
首个收集错误：ModuleNotFoundError: No module named 'baostock'
位置：backend/tests/test_adapters.py
```

忽略该 adapter 测试后再次后台执行：

```text
nohup python -m pytest backend/tests/ -x -q --ignore=backend/tests/test_adapters.py > logs/task6-backend-no-adapters.log 2>&1 &
首个收集错误：ModuleNotFoundError: No module named 'yfinance'
位置：backend/tests/test_yfinance_adapter_management.py
```

因此完整 backend suite 受当前环境缺少 `baostock`、`yfinance` 阻断，不能宣称全量通过；本次迁移相关定向测试已通过。

## 风险与 concerns

- 完整后端 suite 仍需在安装数据源测试依赖的环境重新执行。
- v1 account schema 没有现金/初始资金字段，scheduler 快照按当前 v1 契约将现金记为 `0.0`；若后续账户模型加入现金，应同步扩展快照服务。
- 旧数据库中历史旧表不会被自动删除，代码已移除其生产读写路径；如需物理清理，应另行执行明确的数据迁移并先备份。
- 未修改回测逻辑、result、status 或执行状态语义；共享 `backtest_tasks` 初始化和现有 `TaskManager` 行为保持不变。
