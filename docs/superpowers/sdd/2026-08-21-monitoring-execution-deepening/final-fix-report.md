# Final Fix Report

## Findings Fixed

- 路由现在只解析请求和基础市场参数，full/scan 均通过共享 execution seam 创建任务；策略加载、实例化、快照和执行失败都会回写同一个 task 为 failed。
- 线程启动异常会立即 `fail_task`，并通过 `ExecutionSubmissionError.task_id` 向调用方传递已创建任务。
- Monitoring 提交异常会把异常携带的 task ID 写回 `monitoring_strategy_runs.task_id`，避免监控运行记录与执行任务脱链。
- 保留 full raw result、scan hits/date_range/factors/metadata、任务 metadata、log_dir 和 snapshot provenance。

## Tests

- RED: `test_backtest_execution.py` 初次运行因 `execution.py` 不存在而收集失败，确认测试捕获的是缺失 seam。
- GREEN: `python -m pytest backend/tests/test_backtest_execution.py backend/tests/test_strategy_monitor.py -q`，28 passed。
- GREEN: `python -m pytest backend/tests/test_backtest_api.py backend/tests/test_backtest_task_manager.py -q`，25 passed，1 failed。

## Concerns

- 现有 `test_scan_result_contains_snapshot_context` 在异步隔离 task manager 下仍读到空 result；execution seam 内部曾确认该任务完成并持久化成功。该测试需要进一步处理测试 fixture 的模块级 task manager 绑定，不能将其标为全绿。
