# 最终修复波次报告

## 状态

已完成最终 reviewer 的 Critical/Important 修复，并在当前 worktree 提交。未派生子 agent，未修改 BacktestEngine、回测 `status` 或 result JSON，未恢复旧 `/api/portfolio`，未实现邮件/SMTP/Webhook，也未使用 akshare。

## 修复内容

- `AccountService` 在同一个 `BEGIN IMMEDIATE` 事务内完成账户/持仓/任务状态读取、目标物化、execution metadata 更新和账户绑定；`TaskManager.get_result` 支持复用该连接，失败整体回滚，并补双连接并发绑定测试。
- `db_schema.py` 在创建 active execution 唯一索引前，按 `task_id` 确定性保留一个 active，其他重复行降为 inactive/null；不删除历史，迁移可重复执行，并补 populated-table 测试。
- 明确 `raw_trades` 物化契约：按日期和原始顺序；buy 建立/替换目标，sell（含 partial sell）归零并继承参考价，revision 继承其他 symbol；保留显式 target history 兼容路径，非法/无目标结果 fail-closed。补 2baab97c 五目标 fixture、同日重复 buy 和 partial sell 测试。
- `DuckDBStore.query_previous_close()` 支持 A/HK/US 裸代码到 canonical symbol 映射，提醒 evaluator 同时解析 canonical/raw key。
- snapshot/holdings 从持久化 `portfolio_strategy_alerts.state` 返回 `alert_status`。
- 前端保留策略账户 target-only rows；仅 target=0 且 actual=0 隐藏，并展示目标、参考价、remaining、提醒状态。
- scheduler 对 A/HK/US 逐市场查询，单市场 view 缺失/失败只记录 warning，成功市场继续 snapshot/evaluate。
- `delete_trade` 强制 `account_id` 归属校验；删除后事务内重放交易，阻止负持仓并重算剩余卖出 realized P&L。
- 补 active 组内排序、scheduler success/error resource path 和三市场查询相关测试。

## 测试摘要

- 后端 focused：`100 passed`
- 前端 PortfolioPage：`7 passed, 11 skipped`
- 前端全套：`40 files passed; 384 passed, 13 skipped`
- `frontend`: `npx tsc --noEmit` 通过
- `frontend`: `npm run lint` 通过
- Python focused files `compileall` 通过
- `git diff --check` 通过
- 完整后端首次后台执行：因环境缺少 `baostock`，在 `test_adapters.py` 收集阶段停止
- 忽略 `test_adapters.py` 后再次后台执行：因环境缺少 `yfinance`，在 `test_yfinance_adapter_management.py` 收集阶段停止

## 剩余 concerns

- 完整后端 suite 需在安装 `baostock` 和 `yfinance` 的环境重新执行；这不是本次代码变更引入的测试失败。
- 测试输出仍有既有 pytest-asyncio 配置弃用 warning，以及 jsdom 的 canvas/scrollTo 提示；不影响通过结果。
