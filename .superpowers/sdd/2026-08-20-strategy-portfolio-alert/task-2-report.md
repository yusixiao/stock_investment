# Task 2 实现报告

## 改动文件

- `backend/services/portfolio/models.py`：新增不可变 `Account` 领域模型。
- `backend/services/portfolio/repository.py`：新增 v1 账户、账户交易、当前持仓和策略状态归档 repository。
- `backend/services/portfolio/account_service.py`：新增账户创建、策略绑定、解绑、查询服务。
- `backend/services/db_schema.py`：新增 `init_portfolio_v1_tables`，包含账户、账户交易、目标/历史、提醒状态表及索引，全部幂等。
- `backend/services/portfolio/db.py`：初始化共享数据库时调用 v1 schema；旧 `portfolios/trades/snapshots` 保持不变。
- `backend/routers/portfolio_v1.py`：注册 `/api/v1/portfolio/accounts` 账户查询、创建、绑定和解绑接口。
- `backend/main.py`：注册 v1 Portfolio router，未删除旧 Portfolio router。
- `backend/tests/test_portfolio_account_service.py`：账户生命周期、持仓拒绑、一对一约束、解绑保留交易、schema 幂等测试。
- `backend/tests/test_portfolio_v1_api.py`：v1 API 生命周期和错误映射测试。

## 接口与 seam

- 服务接口：`create_account`、`bind_strategy`、`unbind_strategy`、`get_account`、`list_accounts`。
- HTTP 接口：`POST/GET /api/v1/portfolio/accounts`、`GET /api/v1/portfolio/accounts/{id}`、`POST/DELETE /api/v1/portfolio/accounts/{id}/strategy`。
- `AccountService` 注入 `AccountRepository`、TaskManager 和 `target_materializer`。
- `materialize_strategy_targets` 是 Task 3 的稳定替换点；本任务不解析、不修改回测 result JSON。
- 绑定拒绝当前真实持仓、非 success 任务、active 任务和已关联任务；解绑归档目标/提醒状态、保留交易并调用 `clear_execution_account`。

## 测试命令及结果

- `python -m pytest backend/tests/test_portfolio_account_service.py backend/tests/test_portfolio_v1_api.py -q`：`10 passed`。
- `python -m pytest backend/tests/test_portfolio_db.py backend/tests/test_portfolio_manager.py backend/tests/test_backtest_task_manager.py -q`：`40 passed`。
- `python -m compileall -q ...`（本任务涉及 Python 文件）：通过。
- `git diff --check`：通过。

## 已知风险/疑问

- 当前工作树中旧 `backend/tests/test_portfolio_api.py::TestHoldings::test_holdings` 单独运行会因 DuckDB 测试环境缺少 `v_a_daily` 失败；失败发生在既有旧 holdings 路由查询，不涉及本任务新增代码。
- Task 3 尚未实现；Fix Round 1 已将默认 materializer 改为 fail-closed，后续必须注入目标解析与物化实现。
- Fix Round 1 已为 TaskManager 增加外部 connection seam，并由 AccountService 统一管理绑定/解绑事务。

## Fix Round 1

### 处理内容

- `TaskManager.set_execution_account` / `clear_execution_account` 增加可选外部 SQLite connection；传入时不自行 commit/close，由 `AccountService` 通过同一 connection 和 `BEGIN IMMEDIATE` 管理绑定/解绑事务，保留原有无参公共调用行为。
- 默认目标物化器改为 fail-closed，Task 3 未接入时抛出明确 `RuntimeError`；生产 router 通过 `_get_materializer()` 明确装配 seam，绑定 API 返回 503，不再返回无目标的成功状态。
- `portfolio_strategy_targets` 与 `portfolio_strategy_alerts` 增加 `(account_id, symbol)` 的未归档 partial unique index，历史归档记录仍可保留。
- v1 请求改用 Pydantic `AccountCreateRequest` / `StrategyBindingRequest`，缺字段或空字符串由 FastAPI 返回 422。
- 新增真实 TaskManager 同 SQLite connection 的绑定/解绑失败回滚测试、fail-closed 测试、materializer connection 断言、current 状态唯一性测试，以及重复 schema 初始化和既有表列结构保持测试。

### Fix 测试命令及完整结果

- `python -m pytest backend/tests/test_portfolio_account_service.py backend/tests/test_portfolio_v1_api.py -q`

  ```text
  Pytest: 18 passed
  ```

- `python -m pytest backend/tests/test_portfolio_db.py backend/tests/test_portfolio_manager.py backend/tests/test_backtest_task_manager.py backend/tests/test_backtest_api.py -q`

  ```text
  Pytest: 59 passed
  ```

### Fix 剩余 concerns

- Task 3 仍需在 `_get_materializer()` seam 接入真实目标物化实现；当前生产绑定会明确返回 503，这是预期的 fail-closed 行为。
- 当前目标/提醒 partial unique index 假设既有未归档数据没有重复值；若部署到已有重复数据的数据库，schema 初始化前需要单独数据清理迁移。
