# TaskManager 职责拆分设计

## 背景

`backend/services/backtest/task_manager.py` 当前同时承担 SQLite 持久化、任务生命周期、结果格式化、内存进度和 Portfolio 账户绑定。它是一个重要模块，但接口包含大量持久化兼容细节，导致回测、监控、历史页面和 Portfolio 都直接依赖同一个混合实现。

## 目标

在不改变 `backtest_tasks` schema、现有调用方接口和历史返回格式的前提下，将内部职责拆到清晰的 seam，使任务生命周期、结果编码和进度状态可以独立理解与测试。

## 非目标

- 不修改 `backtest_tasks` 表结构。
- 不删除 `source_task_id`、`deleted` 等历史字段。
- 不改变 full、scan、monitor 的结果 payload。
- 不在本阶段迁移 Portfolio 的公共调用方。
- 不引入任务队列或新的持久化数据库。

## 设计

保留 `TaskManager` 作为兼容 facade。它继续提供现有 public interface，但将实现委托给三个内部模块：

```text
TaskManager facade
├── TaskRepository       SQLite 连接、CRUD、查询、软删除
├── TaskResultCodec      pipeline/result JSON、summary、date_range 兼容
└── TaskProgressStore    进程内 current/total/phase 状态
```

`set_execution_account()` 和 `clear_execution_account()` 在本阶段仍由 facade 暴露并保持事务语义；它们暂不迁移到 Portfolio，避免跨模块改动扩大范围。后续若第二个真实 adapter 出现，再把账户绑定移到 Portfolio 的独立 seam。

### TaskRepository

只负责 `backtest_tasks` 的 SQLite 读写、连接生命周期、启动时 running 任务恢复、任务 CRUD 和账户绑定所需的原子更新。它不解析 JSON，不推断结果类型，不维护内存进度。

### TaskResultCodec

集中处理 `pipeline_info`、`result`、`summary` 的 JSON 编解码以及 scan `date_range` 回写日期列。`_build_summary()` 的 full/scan 分支属于此模块，不再由数据库模块推断。

### TaskProgressStore

只负责线程安全的进度字典。任务完成或失败时清理进度；不存在 SQLite I/O，也不负责判断任务生命周期。

### 兼容策略

第一阶段不改变 `TaskManager` 的构造方式、方法名、参数和返回值。现有测试继续通过 facade 验证 public interface；新增模块测试验证各自 seam。实现采用逐步委托，不做一次性大规模迁移。

## 错误与事务

- Repository 保持现有 SQLite commit/rollback 行为。
- 结果编码失败时不能把任务静默标记成功；由 facade 保持现有异常传播语义。
- 进度存储失败不能影响已经完成的 SQLite 结果写入。
- 账户绑定继续使用 `BEGIN IMMEDIATE` 和现有冲突检查。

## 验证

- 先为新模块写失败测试，再实现最小委托。
- 运行 `test_backtest_task_manager.py`、`test_task_manager.py`、回测 execution/API、Portfolio account/strategy targets 测试。
- 最后运行完整后端测试，确认历史结果、监控任务和账户绑定没有行为变化。
