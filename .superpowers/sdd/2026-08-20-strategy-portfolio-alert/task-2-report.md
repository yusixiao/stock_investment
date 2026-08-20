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
- Task 3 尚未实现，当前 materializer 默认为空实现；后续应注入目标解析与物化实现，并在同一 service 编排边界内接入。
- Task 1 的 `TaskManager` 当前自行打开 SQLite connection；生产环境若 materializer 在绑定事务中写大量目标数据，后续应评估跨 connection 锁与原子性，并由后续任务决定是否扩展 TaskManager connection seam。
