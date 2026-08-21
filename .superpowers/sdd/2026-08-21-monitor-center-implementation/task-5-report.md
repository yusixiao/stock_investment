# Task 5 实现报告：Scheduler Integration

## 修改文件

- `backend/scheduler.py`
  - 在市场刷新完成回调中，仅筛选 `update/view/cache` 成功且 `result` 为 `ready`（或缺省）的市场。
  - 对每个可用市场调用 `run_due_strategy_monitors(as_of_date, markets={market})`。
  - 对每个可用市场调用 `evaluate_stock_price_monitors(as_of_date, markets={market})`。
  - 策略监控和股票价格监控使用独立异常保护；任一市场或任一 seam 失败不会阻断其他调用。
  - 记录市场、日期、处理数量和失败原因。
  - 未增加邮件发送逻辑，未改变现有 Portfolio buy-opportunity 流程。
- `backend/tests/test_scheduler.py`
  - 新增成功市场过滤与两个监控 callback 调用测试。
  - 新增策略 callback 失败仍执行股票价格 evaluator 的测试。
  - 新增跨市场故障隔离测试。
- `.superpowers/sdd/2026-08-21-monitor-center-implementation/task-5-report.md`
  - 本报告。

## TDD 测试记录

先写测试后运行：

```text
python -m pytest backend/tests/test_scheduler.py -k "monitor" -q
Pytest: 0 passed, 3 failed
```

失败原因是 scheduler 尚未接入监控 seam，符合预期红测。

实现后定向测试：

```text
python -m pytest backend/tests/test_scheduler.py -k "monitor" -q
Pytest: 3 passed
```

完整 scheduler 测试：

```text
python -m pytest backend/tests/test_scheduler.py -q
Pytest: 10 passed
```

## 风险 / Concerns

- 策略 runner 当前按市场逐个调用，具体 daily/weekly/monthly/quarterly due 判断继续由 Task 3 seam 负责。
- 本任务只接入 scheduler，不验证真实数据刷新或 DuckDB 的长任务运行链路。
- worktree 中原有 `frontend/package-lock.json` 变更未修改、未回退、未纳入本次提交。
