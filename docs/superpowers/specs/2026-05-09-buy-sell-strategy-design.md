# 买入/卖出策略体系设计

## 概述

将现有的 TraderStrategy 拆分为独立的 BuyStrategy 和 SellStrategy 基类，支持在 pipeline 中作为独立节点串联，共享同一个 Broker/Portfolio 账户。

## 基类体系

```
BaseStrategy
├── ScreenerStrategy          (选股)
├── BuyStrategy               (买入)
│   - strategy_type = "buy"
│   - on_bar(ctx)
└── SellStrategy              (卖出)
    - strategy_type = "sell"
    - on_bar(ctx)
```

删除 TraderStrategy。

## 关键设计决策

### initial_capital 属于运行级别

- 不再由策略定义起始资金
- 在运行时指定（UI 运行对话框中输入，默认 100 万）
- 存储在 group_runs 表中（新增 initial_capital 字段）
- BuyStrategy 和 SellStrategy 共享同一个账户

### Pipeline 结构

完整 pipeline 示例：`选股A → 选股B → 买入策略 → 卖出策略`

- 选股节点：筛选股票，输出 symbol 列表
- 买入节点：根据分配逻辑建仓
- 卖出节点：根据平仓逻辑减仓/清仓

### 回测执行模型

Engine 按日期逐 bar 推进：
1. 评估选股策略，更新 selected_symbols
2. 执行买入策略的 on_bar(ctx)
3. 执行卖出策略的 on_bar(ctx)
4. Broker 撮合订单

买入和卖出共享同一个 Broker，资金约束由 Broker 自然保证（cash 不足时订单不成交）。

### 资金不足处理

当可用资金不足时，由策略自身决定处理方式：
- 部分买入（按比例缩减）
- 完全跳过
- 优先级买入（按指标排序）

这是策略编写者的职责，引擎不做额外干预。

## ctx 接口

BuyStrategy 和 SellStrategy 的 ctx 需要提供：
- `selected_symbols` — 当前选中的股票列表
- `available_cash` — 账户可用现金
- `get_positions()` — 当前持仓
- `get_price(symbol)` — 当前价格
- `order_target_percent(symbol, pct)` — 按目标百分比下单
- `order_shares(symbol, shares)` — 按股数下单
- `financial_data` — 财报数据（ROE 等）
- `valuation_data` — 估值数据

## UI 变化

- 运行对话框新增「起始资金」输入框，默认 100 万
- PipelineBuilder 中 buy/sell 策略显示不同颜色 badge（如绿色=买入，红色=卖出）
- 策略扫描结果返回 strategy_type 用于前端区分

## GroupRunner 适配

`_execute_step` 识别策略类型：
- screener 类型：执行选股逻辑
- buy + sell 类型：在同一回测循环中共同执行

当 pipeline 中相邻的 buy 和 sell 节点被检测到时，engine 将它们合并到同一个回测循环中执行，而非作为独立 step 分别跑。

## 数据库变更

- `group_runs` 表新增 `initial_capital REAL DEFAULT 1000000`
- 删除 TraderStrategy 相关的旧引用

## 信号表优化模式

当已有选股结果（即从上一次 run 链式传入的 screened_symbols + match_dates）时，可跳过选股步骤，直接进入「信号表模式」：

### 触发条件

- Pipeline 中存在 buy/sell 策略
- 运行时传入了 `source_run_id`（链式执行）
- source run 的结果包含 `screened_symbols` 且每个 symbol 带有 `match_dates`

### 执行方式

1. 不再实时执行选股策略
2. 将 source run 的结果转为「信号表」：`{date: [symbol1, symbol2, ...], ...}`
3. 回测起止日期：从信号表中最早的 match_date 开始，到最晚的 match_date 结束（或使用用户指定的 end_date）
4. 逐 bar 推进时，每天执行：
   - 查信号表：当天有信号 → `selected_symbols` 更新为该日期对应的股票列表；当天无信号 → `selected_symbols` 为空
   - 买入策略 on_bar：只在 `selected_symbols` 非空时才有标的可买入
   - 卖出策略 on_bar：**每天都执行**，评估所有当前持仓是否满足卖出条件

### 买入与卖出的触发频率区别

- **买入**：依赖信号表，仅在 match_date 当天才有买入标的（selected_symbols 非空）
- **卖出**：不依赖信号表，每个 bar 都对所有持仓进行评估（如 PE > 40、止损、均线破位等），任意日期均可触发

这意味着整个回测区间内每天都需要加载持仓股票的行情/估值/财报数据用于卖出判断，卖出条件与选股的 match_dates 没有直接关系。

### 好处

- 大幅减少计算量（无需重复选股）
- 支持「先跑选股，看结果，排除部分股票，再跑买卖回测」的工作流
- 排除功能自然生效：`get_effective_symbols(source_run_id)` 过滤掉已排除的股票

### 非信号表模式（完整模式）

如果没有 source_run_id 或 source run 没有 match_dates，则按完整模式执行（选股 + 买卖在同一循环中逐 bar 运行）。

## 文件变更范围

- `backend/services/backtest/base.py` — 新增 BuyStrategy、SellStrategy，删除 TraderStrategy
- `backend/services/backtest/engine.py` — 适配新策略类型
- `backend/services/backtest/context.py` — 确保 ctx 提供所需接口
- `backend/services/backtest/strategy_loader.py` — 识别新类型
- `backend/services/backtest/group_manager.py` — _execute_step 适配
- `backend/routers/strategy_group.py` — 传递 initial_capital
- `frontend/src/views/StrategyGroupList.vue` — 运行对话框加起始资金
- `frontend/src/components/PipelineBuilder.vue` — buy/sell badge
- `strategies/examples/equal_weight_trader.py` — 改写为 BuyStrategy
