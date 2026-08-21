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

## 过期调度复审追加

- scheduler 现在先处理已过期的 `next_run_date`：只对其对应日期的 stale running run 做 failed recovery，不重新执行过期日期。
- 过期日期被跳过后，指针推进到当前日期之后的第一个 due 日期；若当前日期是 due，则同一次 scheduler 调用进入当前日期 claim。
- 同日幂等、不同日期 running 不互相阻塞以及无未来日期返回 `None` 的规则保持不变。

本轮定向验证：监控、scheduler、repository、API 测试 `55 passed`。

本轮最终全量验证：

- 全量后端：`1503 passed, 1 skipped`
- 前端 Vitest：`416 passed, 13 skipped`
- 前端 TypeScript：`npx tsc --noEmit`，退出码 0
- 前端 ESLint：`npm run lint`，退出码 0

## 最终复审裁决追加

- `initial_run_date()` 无未来交易日时严格返回 `None`，不回退历史 due 日期；scheduler 在 `None` 状态按当前交易日重新评估。
- 策略运行通过有界后台执行器（最多 4 个 worker）dispatch；scheduler/API 不同步执行扫描。dispatch 或 worker 失败均持久化为 `failed`，并推进本轮调度状态。
- 幂等键为 `monitor_id + scheduled_date`，数据库增加唯一索引；不同 scheduled date 的 running run 不互相阻塞。
- 同日 stale running run 原地 reclaim，保持同一 run ID；新日期不受旧日期 stale/run 状态阻塞。

本轮定向验证：监控、scheduler、repository、API 测试 `53 passed`。

并行完成顺序回归后最终验证：

- 监控、scheduler、repository、API：`54 passed`
- 全量后端：`1502 passed, 1 skipped`
- 前端 Vitest：`416 passed, 13 skipped`
- 前端 TypeScript：`npx tsc --noEmit`，退出码 0
- 前端 ESLint：`npm run lint`，退出码 0
- `git diff --check`：通过

## 已知 Concern

- 策略监控依赖已加载的 `data_cache` 快照；缓存未加载或单日数据缺失时不会伪造结果，而是保留明确的未执行失败语义。
- 全量后端测试仍有既有 `pytest-asyncio` 配置弃用警告，不属于本次改动。
- `frontend/package-lock.json` 是 worktree 既有改动，本次未修改、未暂存、未提交。

## 追加复审修复

- `next_run_date` 为 `None` 时，scheduler 仍按当前交易日和 frequency 的 due 规则评估。
- claim 在 `next_run_date IS NULL` 时按 `monitor_id + scheduled_date` 去重，避免最新交易日重复创建 run。
- 新交易日进入 store 后，daily/weekly/monthly/quarterly 均可在下一个 due 日重新调度，不会因暂无未来日期永久停摆。
- 手动 API 继续使用仅当前日期的有界执行 seam；代码明确禁止接入历史/完整回测，成功、失败和未执行状态均同步持久化，未伪造后台任务。

追加验证：监控与 scheduler 测试 `40 passed`。

本轮最终验证：

- 全量后端：`1495 passed, 1 skipped`
- 前端 Vitest：`416 passed, 13 skipped`
- 前端 TypeScript：`npx tsc --noEmit`，退出码 0
- 前端 ESLint：`npm run lint`，退出码 0
