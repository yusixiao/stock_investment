# 回测数据快照设计

## 目标

为一次完整回测或雷达扫描固定一个一致的数据上下文，记录用户可理解的数据截至日期和 stale 状态，同时不复制常驻的全市场 `MarketBundle`。

## 设计决策

### 数据所有权

- `data_cache` 继续按 A/HK/US 常驻完整 `MarketBundle`。
- `BacktestDataSnapshot` 只持有 `MarketBundle` 和 `SlicedBundle` 的轻量引用/视图，不深拷贝 DataFrame。
- `MarketData` 仍可为当前回测建立自己的 numpy 索引，这是热路径实现缓存，不属于全市场 bundle 的第二份业务数据所有权。

### Snapshot 内容

Snapshot 固定以下语义：

- 物理市场 `A` / `HK` / `US`；`HK_CONNECT` 仍映射到 `HK` 并携带过滤后的 symbols。
- symbols、回测 `start_date` / `end_date`、指标预热范围和策略 frequency。
- raw/qfq 口径。
- `data_as_of`：来自 bundle 的数据截止日期，作为用户可见信息。
- `stale`：刷新失败但仍使用旧 bundle 时为 true。
- `generation` / `market_version` / `refresh_id`：内部诊断信息，其中 refresh_id 不进入普通 UI。

### 一致性策略

- Snapshot 创建时绑定当前 bundle 和 cache generation。
- cache 后续 invalidate/rebuild 不改变已创建 Snapshot 所引用的数据。
- stale bundle 允许用于回测和雷达，但结果必须传播 stale 状态。
- 没有可用 bundle 时，创建 Snapshot 失败，不触发回测内部 IO 或隐式全市场加载。

### 用户结果

回测结果增加简单元信息：

```json
{
  "data_context": {
    "market": "A",
    "data_as_of": "2026-08-20",
    "stale": false
  }
}
```

内部 refresh_id、generation 和 market_version 同样保存在结果 JSON，供日志和诊断使用，但前端第一阶段只展示 data_as_of 和 stale 文案。

## 非目标

- 不恢复 StrategyGroup 或旧三角策略模型。
- 不改变按市场完整预加载的生产策略。
- 不实现 dataset fingerprint 或用户选择历史 refresh_id。
- 不解决 HK_CONNECT 缺少 point-in-time 历史成分股的问题；只记录当前使用的过滤语义。
- 不在本次改造中重写 `MarketData` 的 numpy 热路径。

## 验收标准

1. Snapshot 创建不复制完整 market bundle 的 DataFrame。
2. Snapshot 固定后，cache generation 更新不会改变既有回测的数据引用或元信息。
3. 完整回测和雷达扫描均可获得同一套 data_context。
4. stale bundle 可运行且结果标记 stale。
5. 无 bundle 时明确失败。
6. 使用 mini DuckDB fixture 测试，不读取项目 `data/market/`。
