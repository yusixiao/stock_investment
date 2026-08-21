# Monitor Center Fix Report

## 修复范围

- 策略监控使用已加载市场快照，仅将 `as_of_date` 单日窗口交给 `BacktestEngine.run_scan()`，不伪造历史区间；数据不可用时明确记录 `unexecuted`/failed 原因。
- 策略监控创建和更新仅接受 `DEPLOYED_STRATEGY_DIR` 内真实存在、可加载且包含目标 class 的 Python 文件，并校验参数构造；校验失败在写库前返回 422，避免半成品。
- 新建监控按交易日历初始化首次可执行日期。
- 调度成功、未执行和异常失败均推进下一次日期；claim 事务保证重复调度不会重复创建同一轮 run。
- 股票监控每次获得 close 都写回 `last_price` 和 `last_price_date`；事件历史改为最新优先；StockMonitorPatch 禁止未知字段。

## 测试结果

- 监控相关后端：`35 passed`
- 全量后端：`1491 passed, 1 skipped`
- 前端 Vitest：`416 passed, 13 skipped`
- 前端 TypeScript：`npx tsc --noEmit`，退出码 0
- 前端 ESLint：`npm run lint`，退出码 0
- `git diff --check`：通过

## 已知 Concern

- 策略监控依赖已加载的 `data_cache` 快照；缓存未加载或单日数据缺失时不会伪造结果，而是保留明确的未执行失败语义。
- 全量后端测试仍有既有 `pytest-asyncio` 配置弃用警告，不属于本次改动。
- `frontend/package-lock.json` 是 worktree 既有改动，本次未修改、未暂存、未提交。
