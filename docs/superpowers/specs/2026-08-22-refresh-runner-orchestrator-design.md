# RefreshRunner 单一刷新编排器设计

## 背景

项目当前已经有 `RefreshRunner`，负责市场更新、DuckDB view 刷新、`data_cache` 重建、refresh 状态和 market version 管理。但 `backend/scheduler.py` 仍保留 `_post_market_update_refresh()`，并在主刷新、retry 和完成回调中重复编排刷新相关逻辑。

这造成了两套潜在刷新流程：一套由 `RefreshRunner` 执行，另一套由 scheduler 直接操作 `data_cache` 和流通股数据。当前旧 helper 似乎不在主运行链路中，但它仍然是可调用的错误 seam，未来修改时容易造成重复 cache 重建、重复后处理和版本时序错误。

## 目标

让 `RefreshRunner` 成为市场刷新生命周期的唯一编排器：

```text
调用方
  → RefreshRunner
       更新市场数据
       → 刷新 DuckDB views
       → 刷新刷新前依赖
       → invalidate/rebuild data_cache
       → 更新 refresh_id / market_version
       → 记录 completed/partial/stale
       → 发出完成回调
```

`scheduler.py` 只负责 APScheduler job、retry 的时间安排和完成后的业务订阅，不再直接实现市场刷新步骤。

## 非目标

- 不改变市场数据 updater 的数据采集逻辑。
- 不改变 `RefreshStateStore` 的数据库字段和状态语义。
- 不引入通用事件总线或消息队列。
- 不改变每日 06:00 市场刷新、retry 次数和 retry 间隔。
- 不改变策略监控、价格监控和买入机会的业务规则。
- 不把财务、指数、港股通和备份任务强行并入同一个 RefreshRunner；它们仍是独立定时任务。

## 当前职责泄漏

当前 `RefreshRunner` 已经拥有主要生命周期：

```text
update market
  → refresh view
  → invalidate cache
  → rebuild cache
  → advance market version
  → finish refresh
```

但 `scheduler.py::_post_market_update_refresh()` 仍然：

- 更新流通股快照；
- 遍历所有市场直接 invalidate cache；
- 异步触发 cache 重建；
- 不携带当前 `refresh_id`；
- 不区分本次 refresh 成功的市场和失败的市场。

主刷新和 retry 又各自构造 callback，容易让后处理和失败重试产生不同语义。

## 设计

### 1. RefreshRunner 负责刷新前置步骤

保留并明确现有 `refresh_before_cache` seam：

```python
RefreshRunner(
    refresh_before_cache=_refresh_circulating_shares,
    on_complete=_on_market_refresh_complete,
)
```

它只接收本次成功更新的市场列表，并且在这些市场进入 cache 重建前执行。前置步骤失败时，RefreshRunner 将相关市场标记为失败/stale，不继续将其当作 ready 市场处理。

这样流通股更新不会再由 scheduler 另一套 helper 独立触发。

### 2. RefreshRunner 负责所有数据刷新状态

以下操作只能出现在 RefreshRunner 的实现中：

- `update_market` / `update_markets`；
- `refresh_view`；
- `data_cache.invalidate`；
- `data_cache.load_market_async`；
- cache ready 等待和 timeout；
- `market_version` 推进；
- refresh state 的 market stage 和最终状态写入。

调用方不得在 refresh callback 中重复执行这些操作。

### 3. scheduler 变成 composition root

`scheduler.py` 保留以下职责：

- 注册 APScheduler jobs；
- 创建并调用 RefreshRunner；
- 根据 refresh 结果安排下一次 retry；
- 注册完成后的业务订阅者。

主刷新和 retry 使用同一套 runner 参数和调用方式：

```text
scheduled job / retry job
  → create RefreshRunner
  → runner.start(..., auto_start=False)
  → runner.run(refresh_id, markets)
  → on_complete(record)
```

retry policy 仍由 scheduler 使用 APScheduler 的 date job 管理，因为它是“何时重试”的调度策略，而不是“如何刷新市场”的生命周期实现。Retry 的判断只读取 RefreshRunner 已写入的 `record.market_states`，不自行检查 updater/cache 状态。

### 4. 完成回调只做业务后处理

`_on_market_refresh_complete(record)` 只处理已完成且 cache ready 的市场：

- 买入机会评估；
- 策略监控调度；
- 股票价格监控评估。

这些调用不再触碰刷新状态、cache invalidate、cache load 或 market version。每个订阅者继续按市场隔离失败，单个订阅者失败不影响其他订阅者。

### 5. 删除旧刷新 helper

`_post_market_update_refresh()` 在迁移完成后删除，不保留兼容 wrapper，因为它的存在本身会继续制造第二个刷新 seam。`grep` 应确认 scheduler 不再直接调用 `data_cache.invalidate()` 或 `data_cache.load_market_async()`。

`backend/routers/market_update.py` 可以继续直接调用 RefreshRunner，因为它是手动刷新入口 adapter；它不实现自己的刷新步骤。

## 失败与时序

每个市场的有效状态顺序保持：

```text
update running
  → update success
  → view running/success
  → cache running/ready
  → market version advanced
  → market ready
```

失败市场不能进入后处理订阅者集合。`partial` refresh 仍然允许成功市场继续完成 view/cache 并触发后处理；失败市场标记 stale，并由 scheduler 根据 updater detail 决定是否 retry。

刷新完成回调只在 `RefreshRunner.finish_refresh()` 后执行，调用方看到的 record 必须已经包含最终状态和 market stage。

## 测试设计

需要通过 RefreshRunner 的 interface 覆盖：

- 主刷新和 retry 使用相同的刷新步骤顺序；
- `refresh_before_cache` 只收到成功市场；
- 前置步骤失败会阻止对应市场进入 cache ready；
- cache rebuild 失败不会推进 market version；
- partial refresh 只通知 ready 市场；
- completion callback 看到最终 refresh record；
- scheduler 不再直接调用旧 post-refresh helper 或 data_cache 刷新函数；
- `router/market_update.py` 手动刷新仍然通过 RefreshRunner 工作。

现有 `test_market_refresh_runner.py`、`test_scheduler.py` 和 `test_scheduler_market_retry.py` 将作为主要回归面。测试应优先使用注入的 updater/view/cache adapter，不访问真实市场数据。

## 兼容性

- 保留 `RefreshRunner.start()`、`run()` 和现有 `on_complete` 调用方式。
- 保留 refresh state 表、market stage 字段、`completed` / `partial` / `stale` 状态。
- 保留 scheduler job id、执行时间、retry 次数和 retry 间隔。
- 保留现有监控和买入机会后处理接口。

## 验收标准

完成后，市场刷新链路应满足：

1. 运行时代码中只有 `RefreshRunner` 负责市场更新后的 view、cache 和 version 编排。
2. scheduler 不再存在第二套 post-refresh cache 流程。
3. 主刷新和 retry 的数据生命周期一致。
4. partial refresh 不会用失败市场触发监控。
5. 现有 RefreshRunner、scheduler、retry 和手动刷新测试全部通过。
