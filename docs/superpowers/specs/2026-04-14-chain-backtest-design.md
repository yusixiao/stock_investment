# 链式回测设计（Chain Backtest via source_task_id）

## 概述

将某次选股回测的结果（筛选出的股票池）作为下一次回测的输入，实现多步骤、渐进式的选股和回测流程。

## 使用场景

1. **选股→选股**：先用宽松的月线策略筛出候选池，再用精细的日线策略从中二次筛选
2. **选股→交易回测**：拿选股结果的股票池，喂给 Trader 策略做完整回测

## 方案：`source_task_id` 引用

API 请求体新增 `source_task_id` 字段，后端从 SQLite 查出来源任务的选股结果，提取 symbol 列表，只加载这些股票的数据。日期范围从来源任务继承。

## 数据流

```
BacktestResult.vue (选股结果页)
  → 用户点击「以此结果进行下一步回测」
  → 跳转到 BacktestPage.vue，URL 携带 ?source_task_id=xxx
  → BacktestPage 从 URL 读取 source_task_id，显示来源任务信息
  → 用户配置 pipeline + 参数（日期范围自动继承，不可编辑）
  → 点击运行，POST /api/backtest/run 携带 source_task_id
  → 后端从 SQLite 查出来源任务的 screened_symbols → 提取 symbol 列表
  → _load_stock_data() 只加载这些 symbol 的 parquet
  → 继承来源任务的 start_date / end_date
  → 新任务的 pipeline_info 中记录 source_task_id（溯源）
  → 结果页展示时也显示来源任务链接
```

## 后端改动

### 1. `POST /api/backtest/run` 请求体

新增可选字段：

```python
{
    "pipeline": [...],
    "param_overrides": {...},
    "source_task_id": "abc123"    # 新增，可选
    # 当 source_task_id 存在时，start_date / end_date 从来源任务继承
}
```

### 2. `backend/routers/backtest.py`

若 `source_task_id` 存在：

1. 调用 `task_manager.get_result(source_task_id)` 获取来源任务
2. 校验状态为 `success` 且 `result` 中有 `screened_symbols`，否则返回 400
3. 提取 symbol 列表（兼容两种格式：`list[str]` 和 `list[dict]`）
4. 继承 `start_date` / `end_date`
5. 传入 `symbols` 给 `_load_stock_data()`

### 3. `_load_stock_data(start_date, end_date, symbols=None)`

- 若 `symbols` 不为 None，只加载这些 symbol 对应的 parquet 文件（跳过 glob 全量扫描）
- 若 `symbols` 为 None，行为不变（加载全部）

### 4. `task_manager.py`

- `backtest_tasks` 表新增 `source_task_id TEXT` 列（可 NULL）
- `create_task()` 接受 `source_task_id` 参数并写入
- `get_result()` 返回 `source_task_id`
- `list_tasks()` 返回 `source_task_id`

### 5. Symbol 提取逻辑

兼容两种 `screened_symbols` 格式：

- `_run_screener_only()` 返回 `list[str]`：直接使用
- `_run_screener_backtest()` 返回 `list[dict]`：提取 `[item["symbol"] for item in screened_symbols]`

```python
def _extract_symbols(screened_symbols):
    if not screened_symbols:
        return []
    if isinstance(screened_symbols[0], str):
        return screened_symbols
    return [item["symbol"] for item in screened_symbols]
```

## 前端改动

### 1. `BacktestResult.vue`（选股结果页）

- 当 `result.screened_symbols` 存在且非空时，底部添加按钮「以此结果进行下一步回测」
- 点击后 `router.push({ path: '/backtest', query: { source_task_id: taskId } })`
- 若任务有 `source_task_id`，显示「来源任务：xxx」可点击链接

### 2. `BacktestPage.vue`

- `onMounted` 检查 `route.query.source_task_id`
- 若存在，调用 `fetchBacktestResult(source_task_id)` 获取来源任务信息
- 显示来源信息卡片：「基于任务 xxx 的选股结果（N 只股票），日期范围 xxx ~ xxx」
- 提供「清除来源」按钮，允许用户取消链式模式回到全量模式
- 日期输入框自动填充并禁用（锁定到来源任务的日期范围）
- 运行时请求体包含 `source_task_id`，不传 `start_date`/`end_date`（由后端从来源任务继承）

### 3. `api/index.js`

无需改动，`runBacktest(body)` 已支持任意 body 字段。

## 数据库迁移

`backtest_tasks` 表新增一列：

```sql
ALTER TABLE backtest_tasks ADD COLUMN source_task_id TEXT;
```

在 `init_db()` 中用 `ALTER TABLE ... ADD COLUMN` 的兼容写法（捕获 `OperationalError` 跳过已存在的列）。

## 优先级规则

- 当 `source_task_id` 存在时，`start_date`/`end_date` 从来源任务继承，请求体中的日期字段被忽略
- 当 `source_task_id` 不存在时，行为完全不变（全量股票池 + 请求体中的日期）

## 错误处理

- `source_task_id` 对应的任务不存在 → 400 "来源任务不存在"
- 来源任务状态不是 `success` → 400 "来源任务未成功完成"
- 来源任务结果中没有 `screened_symbols` → 400 "来源任务不是选股类型"
- 来源任务选出 0 只股票 → 400 "来源任务未选出任何股票"

## 测试计划

1. 后端单元测试：`source_task_id` 参数传递、symbol 提取、日期继承、错误处理
2. `_load_stock_data` 的 `symbols` 过滤
3. 链式任务的 `source_task_id` 持久化和查询
