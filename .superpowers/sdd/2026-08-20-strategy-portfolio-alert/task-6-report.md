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

## 第 1 轮 Fix

### 修复内容

- 补齐 v1 核心 contract：`/trades`、`/accounts/{id}/holdings`、`/snapshot`，以及交易删除接口。
- v1 非核心能力 `risk`、`fx/refresh`、cash ledger、corporate actions、CSV imports 均注册明确的 HTTP 501，不再返回 404 或伪造成功。
- PortfolioPage 不再初始自动请求 risk 和 broker 列表；风险区显示明确降级信息，CSV 使用内置券商列表并提示接口未实现。
- DuckDBStore 新增 `query_latest_closes()`，支持 A/HK/US 和裸代码候选映射。
- scheduler 按 A/HK/US 分组查询最新收盘价，再传给 holdings service；不再只查询 A 股。
- 持仓快照通过 canonical/raw candidate 匹配报价；缺失报价记录 warning、价格返回 `null`/`price_available=false`，市值不再回退到 `average_cost`。
- v1 边界把前端 `cn/hk/us` 规范化为内部 `A/HK/US`。

### 第 1 轮验证输出

```text
RED:
rtk pytest backend/tests/test_portfolio_migration.py backend/tests/test_portfolio_v1_api.py -q
Pytest: 8 passed, 4 failed
失败：scheduler grouped quotes、快照新签名、核心 v1 路由缺失、非核心路由 404。

RED:
npm test -- src/pages/__tests__/PortfolioPage.test.tsx
1 failed，确认初始加载仍调用 getRisk。

GREEN:
rtk pytest backend/tests/test_portfolio_migration.py backend/tests/test_portfolio_v1_api.py backend/tests/test_portfolio_account_service.py backend/tests/test_portfolio_holdings_service.py backend/tests/test_buy_opportunity.py backend/tests/test_scheduler.py backend/tests/test_scheduler_market_retry.py -q
Pytest: 60 passed

npm test -- src/pages/__tests__/PortfolioPage.test.tsx
Test Files  1 passed
Tests       16 passed

npm test
Test Files  40 passed (40)
Tests       393 passed | 2 skipped (395)

npx tsc --noEmit
TypeScript: No errors found

npm run lint
ESLint: No issues found

rtk git diff --check
无输出，退出码 0
```

第 1 轮新增 concerns：

- risk、FX、资金流水、公司行为和 CSV 仍是明确 501；前端不再自动调用，但用户主动操作这些功能会看到可见错误，后续实现应补充真实 service 后再解除 501。
- 完整 backend suite 的 `baostock`/`yfinance` 环境阻断仍未解决。

## 第 2 轮 Fix

### 修复内容

- `portfolio_v1` 增加统一 `_connection_scope()` 和 `_close_connection()` seam；账户、交易、holdings、snapshot 路由均通过 `with` 管理连接，成功和异常路径统一释放；`_get_service` 强制接收 request-scoped connection。
- `DuckDBStore.query_latest_closes()` 返回 `(close, quote_date)`，snapshot 使用真实行情日期；早于 `as_of` 时设置 `price_stale=true`，缺价仍为 `null`。
- PortfolioPage 禁用汇率刷新、资金流水、公司行为和 CSV 所有控件，并显示“当前版本未实现”；事件筛选的非交易选项禁用，避免自动请求 501。
- 删除不再使用的现金/公司行为提交 handler，保留核心交易录入路径。

### 第 2 轮验证输出

```text
RED:
rtk pytest backend/tests/test_portfolio_v1_api.py::test_v1_request_scope_closes_connection_on_success_and_error -q
Pytest: 0 passed, 1 failed
失败：_close_connection/_connection_scope 不存在。

npm test -- src/pages/__tests__/PortfolioPage.test.tsx -t "disables unsupported"
1 failed
失败：刷新汇率按钮仍可用。

GREEN:
rtk pytest backend/tests/test_portfolio_migration.py backend/tests/test_portfolio_v1_api.py backend/tests/test_portfolio_account_service.py backend/tests/test_portfolio_holdings_service.py backend/tests/test_buy_opportunity.py backend/tests/test_scheduler.py backend/tests/test_scheduler_market_retry.py -q
Pytest: 61 passed

npm test
Test Files  40 passed (40)
Tests       383 passed | 13 skipped (396)

npx tsc --noEmit
TypeScript: No errors found

npm run lint
ESLint: No issues found

python -m compileall -q backend/routers/portfolio_v1.py backend/services/market_data/duckdb_store.py backend/services/portfolio/holdings_service.py backend/scheduler.py
无输出，退出码 0

rtk git diff --check
无输出，退出码 0
```

第 2 轮 concerns：

- 前端仍保留 11 个旧 FX 交互测试为 skipped，因为对应功能已明确禁用并由新的不可用 contract 测试替代；基线原有 2 个 skip 仍在。
- 非核心 v1 endpoint 继续返回 501，只有核心账户/交易/holdings/snapshot 可用。
