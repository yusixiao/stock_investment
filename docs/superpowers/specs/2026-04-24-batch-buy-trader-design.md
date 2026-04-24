# 分批建仓交易策略（BatchBuyTrader）设计

## 概述

Chain backtest 场景下的买入策略：对选股器筛出的每只股票，从其 match_date 起算的窗口期内分批等额买入。本期只实现买入逻辑，持有到回测结束，卖出逻辑后续迭代。

## 策略参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `buy_window_months` | int | 4 | 买入窗口期（月） |
| `buy_batches` | int | 4 | 分几批买入 |

TraderStrategy.settings 继承：
| 参数 | 默认值 | 说明 |
|------|--------|------|
| `initial_capital` | 1,000,000 | 初始资金 |
| `commission_rate` | 0.0003 | 佣金率（万三） |
| `slippage` | 0.002 | 滑点（0.2%） |

## 仓位分配

- 默认等权分配：每只股票目标金额 = 总资金 / 股票数
- 每只股票的资金均分到 N 批：每批金额 = 目标金额 / buy_batches

## 买入时点

每只股票从自己的 match_date 起算，在窗口期内均匀分布买入时点。例如 4 个月 4 批：第 0、1、2、3 个月各买一次。具体日期为 match_date + k × (window_months / batches) 个月，k = 0, 1, ..., batches-1。

## 成交价

月线 (high + low) / 2，通过 Broker 的 price_func 机制实现。滑点仍叠加在该价格上。

## 架构改动

### 1. TraderContext 新增 match_dates 支持

- TraderContext.__init__ 新增 `source_matches: dict[str, list[str]] | None = None` 参数
- 新增方法 `get_match_dates(symbol) -> list[str] | None`
- Engine._run_backtest 把 self._source_matches 传给 TraderContext

### 2. Broker 自定义成交价

- Broker.__init__ 新增 `price_func: Callable | None = None`
- price_func 签名：`(daily_bar: dict, monthly_bar: dict | None) -> float`
- 默认 price_func：`(daily_bar["open"] + daily_bar["close"]) / 2`（保持现有行为）
- Broker.fill_orders 新增 `monthly_bars: dict[str, dict] | None = None` 参数
- _try_fill 内部使用 price_func 计算成交价，替换硬编码的 mid_price
- 滑点仍叠加在 price_func 返回的价格上
- 涨跌停判断逻辑不变

### 3. Engine 传月线数据给 Broker

- TraderStrategy.settings 新增可选 `price_func` 字段
- Engine._run_backtest 从 settings 读取 price_func，传给 Broker 构造函数
- Engine 在调用 broker.fill_orders 时，额外构造 monthly_bars：对每只股票从 self._monthly_data 中查找当前日期对应的月线 bar

### 4. BatchBuyTrader 策略

文件：`strategies/examples/batch_buy_trader.py`

on_bar(ctx) 逻辑：
1. 首次调用时初始化买入计划：
   - 遍历 ctx.selected_symbols
   - 对每只股票调 ctx.get_match_dates(sym)，取最后一个日期作为窗口起点
   - 计算每批的 target_date 和 amount
   - 存入 _buy_plan
2. 每日检查 _buy_plan，对到期且未执行的批次调 ctx.order_value(symbol, amount)
3. 无卖出逻辑

settings 中设置 price_func 为月线 (high+low)/2 的函数。

## 不改动的部分

- ScreenerStrategy 和选股流程不变
- Broker 的 T+1、涨跌停、佣金印花税逻辑不变
- 现有 equal_weight_trader 等策略不受影响（price_func 为 None 时走默认逻辑）

## 测试计划

- Broker price_func 单元测试：自定义价格函数正确应用、默认行为不变
- TraderContext.get_match_dates 单元测试
- Engine 传 monthly_bars 给 Broker 的集成测试
- BatchBuyTrader 策略测试：买入计划生成、分批执行、窗口期外不买、等权分配
