# Task 3 报告：Strategy Monitor Scheduling Contract

## 改动

- 新增 `backend/services/monitoring/strategy_monitor.py`。
- 新增 `backend/tests/test_strategy_monitor.py`，覆盖 daily、weekly、monthly、quarterly 调度、交易日边界、重复 claim、成功持久化、失败持久化和未执行 seam。
- 未修改股票监控表、Portfolio 表或 `strategy_loader.py`。

## Seam 决策

- 调度日只来自 `store` 的真实市场交易日：优先使用 `get_trading_dates`，DuckDBStore 则通过公开 `query` 查询 `v_{market}_daily`，不读取 parquet 文件路径。
- weekly 使用 ISO 周的第一交易日，monthly 使用自然月第一交易日，quarterly 使用 1、4、7、10 月所在季度的第一交易日；daily 对每个有效交易日执行。
- claim 使用 SQLite `BEGIN IMMEDIATE`，并同时检查 active、`next_run_date` 和现有 `running` run，避免同一策略被重复领取。
- 成功执行会持久化 `task_id`、result，并推进 `next_run_date`；失败只记录 error，不推进日期，也不覆盖此前成功 run 的 result。
- `execute_strategy_current_date` 是最小安全 service seam：通过现有 `load_strategy_from_file` 加载并用 monitor params 构造策略配置，但当前回测引擎需要历史窗口，无法安全代表 current-date execution，因此明确返回 `status=unexecuted`，由 run 记录为 `failed` 并保存 durable error。没有伪造历史日期，也没有从前端执行 Python。
- 未来接入安全的当前日期数据快照时，可替换该 service seam；成功执行器返回的 `task_id` 会写入 strategy run。

## TDD 与测试

先新增测试并确认缺失模块导致 collection failure：

```text
python -m pytest backend/tests/test_strategy_monitor.py -q
ModuleNotFoundError: No module named 'services.monitoring.strategy_monitor'
```

实现后：

```text
python -m pytest backend/tests/test_strategy_monitor.py -q
5 passed

python -m pytest backend/tests/test_monitoring_repository.py backend/tests/test_stock_price_monitor.py -q
16 passed

python -m pytest backend/tests/ -x -q
1466 passed, 0 failed, 1 skipped
```

另已通过新增文件的 `compileall` 和 `git diff --check`。

## Concerns

- 当前默认执行 adapter 只完成策略加载和配置校验，不执行真实策略；这是 ledger ruling 要求的显式安全降级，不是成功执行能力。
- 调度函数本身是同步 service seam。若未来执行器超过一分钟，应由现有后台任务/调度层异步调用，避免在请求线程中运行长任务。
- `next_run_date` 为空或已错过当前日期的 monitor 不会被隐式补跑；避免在没有明确补偿语义时重复执行历史周期。
