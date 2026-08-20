# Task 3 实现报告

## 改动文件

- `backend/services/portfolio/strategy_targets.py`
  - 新增 `StrategyTarget`、`StrategyTargetRevision` 不可变 DTO。
  - 新增只读回测结果 adapter、目标历史 materializer、当前目标查询和买入许可校验。
- `backend/services/portfolio/repository.py`
  - 新增策略目标历史读取、历史归档、历史写入和当前目标替换方法；所有目标表访问经共享 SQLite repository。
- `backend/routers/portfolio_v1.py`
  - `_get_materializer()` 从 Task 2 的 fail-closed 占位切换到真实 `materialize_targets`。
- `backend/tests/test_strategy_targets.py`
  - 覆盖 `2baab97c` 的五个 `2026-06-02` 目标、数量/参考价格、未来日期过滤、零目标、无目标结果错误，以及真实生产 materializer seam 绑定。

## 解析契约

Portfolio adapter 只读取 `backtest_tasks.result` 中显式的 `strategy_targets`、`target_history`、`strategy_target_history`，或 `execution.strategy_targets`；每个 revision 必须提供 `effective_date`（或 `date`）和 `targets`，每个目标必须提供 `symbol`、数量（`target_quantity`/`quantity`/`shares`）和参考价（`reference_price`/`price`）。

缺少显式目标推荐、JSON 无效或字段无效时抛出 `TargetRecommendationUnavailable`，不会从普通成交记录、账户持仓或其它指标推导不安全目标。回测任务的 `status`、`result` 和业务逻辑均未修改。

绑定时按结果 revision 顺序把目标快照写入账户自己的 `portfolio_strategy_target_history`，同时更新账户当前目标表；后续读取只访问 Portfolio 已物化表。删除标的以 `target_quantity=0` 留在 revision 中，`is_buy_allowed()` 仅对评估日最新且数量大于零的目标返回 true。当前目标选择严格使用 `effective_date <= as_of_date`，并按标的采用最新 revision。

## Task 2 seam 接入

`portfolio_v1._get_materializer()` 返回 `services.portfolio.strategy_targets.materialize_targets`。`AccountService.bind_strategy()` 将 Task 2 注入的同一 SQLite connection 传入 materializer，因此目标物化、执行关联和账户绑定仍在同一事务内；materializer 异常会触发 Task 2 的整体回滚。

## 测试命令及完整输出

```text
$ rtk pytest backend/tests/test_strategy_targets.py -q
Pytest: 4 passed

$ rtk pytest backend/tests/test_portfolio_account_service.py backend/tests/test_portfolio_v1_api.py -q
Pytest: 20 passed

$ rtk pytest backend/tests/test_portfolio_db.py backend/tests/test_portfolio_manager.py backend/tests/test_backtest_task_manager.py -q
Pytest: 40 passed

$ rtk git diff --check && python -m compileall -q backend/services/portfolio/strategy_targets.py backend/services/portfolio/repository.py backend/routers/portfolio_v1.py backend/tests/test_strategy_targets.py
(no output; exit code 0)
```

TDD 红灯验证：首次运行 focused 测试在实现前因 `ModuleNotFoundError: No module named 'services.portfolio.strategy_targets'` 失败；实现后上述 focused 测试通过。

## 风险与 concerns

- 当前 adapter 依赖回测结果显式提供目标推荐段；不兼容的结果会 fail-closed，需要由产生该结果的回测版本提供对应 contract。
- 目标历史 payload 使用 JSON 快照保存 source task metadata；当前已有 schema 不增加回测目标字段，也不回写 `backtest_tasks`。
- Task 4 尚未实现真实交易、持仓 overlay 和提醒评估；本任务只提供目标历史与买入范围查询接口。

## Task 3 Fix Round 1

### Reviewer findings 修复

- 生产解析路径改为 `TaskManager.get_result(task_id)`，不再在 Portfolio adapter 内直接查询 `backtest_tasks`。
- `raw_trades` 成为必须支持的生产 contract。按 `(date, 原始顺序)` 折叠：buy 为该标的建立/更新正数量和买入价，sell 将数量置零；每个 revision 继承此前全部标的状态。
- 同一交易日的多笔 trade revision 全部保留；重复 materialize 时只归档该日期的旧批次，不归档本次批次内的 revision。
- current 表只写 `date.today()` 不晚于当前评估日的最后 revision，未来 trade 只保留在历史表。
- 日期严格要求 `YYYY-MM-DD` 且 round-trip 校验；raw trade quantity 必须是正整数，price 必须是 finite positive；显式兼容 target history 允许 quantity=0 表示删除。
- 测试 fixture 改为 raw trade contract，覆盖 2026-06-02 五笔目标：`12200@89.2281`、`28200@39.38361`、`202500@5.39406`、`29700@37.53015`、`41300@26.04528`，并覆盖后续 sell 归零、未来 sell、TaskManager seam 和生产 materializer binding。

### Fix 测试命令及完整结果

```text
$ rtk pytest backend/tests/test_strategy_targets.py -q
Pytest: 7 passed

$ rtk pytest backend/tests/test_portfolio_account_service.py backend/tests/test_portfolio_v1_api.py -q
Pytest: 20 passed

$ rtk pytest backend/tests/test_portfolio_db.py backend/tests/test_portfolio_manager.py backend/tests/test_backtest_task_manager.py -q
Pytest: 40 passed

$ rtk git diff --check && python -m compileall -q backend/services/portfolio/strategy_targets.py backend/services/portfolio/repository.py backend/routers/portfolio_v1.py backend/tests/test_strategy_targets.py
(no output; exit code 0)
```

### Fix concerns

- raw trade 语义按 Controller ruling 实现；如果未来回测结果同时提供显式 target history，仍优先兼容显式字段，但生产不依赖该字段。
- `current` 的 materialize 评估日取运行环境 `date.today()`；历史查询仍可通过 `as_of_date` 回放任意合法交易日。
