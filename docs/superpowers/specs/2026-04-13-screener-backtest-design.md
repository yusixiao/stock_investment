# 选股 + 量化回测系统设计文档

## 概述

在已有的数据管理和K线可视化基础上，构建选股和量化回测一体化系统。系统采用策略管道（Pipeline）架构，用户用 Python 代码编写筛选策略和交易策略，通过管道串联实现"选股→排序→回测"的完整量化工作流。

## 核心设计决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 策略定义方式 | Python 代码（本地 .py 文件） | 灵活度最高 |
| 策略管理方式 | 本地文件 + importlib 加载 | 个人工具，信任本地用户 |
| 回测架构 | 事件驱动引擎 | 支持多股组合、T+1、涨跌停等高级特性 |
| 选股方式 | 也是 Python 策略代码 | 与回测共享规则引擎 |
| 数据源 | qfq/ 前复权数据（回测），raw/ 不复权数据（K线展示可切换） |
| 成交价格 | 当日 (open + close) / 2 中间价 | 折中方案，更接近实际平均成交价 |
| 执行安全性 | 信任本地用户，直接执行 | 个人工具，无需沙箱 |

## 策略管道（Pipeline）模型

### 管道规则

- 管道由 0~N 个筛选策略 + 0~1 个交易策略组成
- 筛选策略串联执行，每个策略的输出（股票列表）是下一个策略的输入
- 交易策略（如果有）必须在管道末尾，最多1个
- **纯筛选管道**（无交易策略）→ 输出选股结果列表
- **含交易策略的管道** → 输出完整回测绩效报告

### 数据流

```
全市场5000+股
  → [筛选策略A: 月线MA5穿MA20] → 200只
  → [筛选策略B: MA10>MA60] → 50只
  → [交易策略C: 等权买入持有] → 回测绩效报告
```

## 策略接口规范

### 两种策略基类

#### 1. 筛选策略 (ScreenerStrategy)

```python
from backend.services.backtest.base import ScreenerStrategy

class MaCrossScreener(ScreenerStrategy):
    name = "月线MA金叉选股"
    description = "选出MA5上穿MA20的股票"

    params = {
        "fast": {"default": 5},
        "slow": {"default": 20},
        "period": {"default": "monthly"},
    }

    def screen(self, ctx, symbols):
        """
        输入: symbols — 上游传入的股票列表（第一个筛选器收到全市场）
        输出: 过滤后的股票列表
        """
        result = []
        for sym in symbols:
            ma_f = ctx.indicator(sym, "ma", self.p.fast, period=self.p.period)
            ma_s = ctx.indicator(sym, "ma", self.p.slow, period=self.p.period)
            if ma_f is not None and ma_s is not None and ma_f > ma_s:
                result.append(sym)
        return result
```

一个 ScreenerStrategy 内部可以写任意多个条件组合，没有限制。拆分成多个策略串联只是为了复用和灵活组合。

#### 2. 交易策略 (TraderStrategy)

```python
from backend.services.backtest.base import TraderStrategy

class EqualWeightTrader(TraderStrategy):
    name = "等权买入持有"
    description = "对筛选出的股票等权分配资金买入"

    params = {
        "rebalance_days": {"default": 20},
    }

    settings = {
        "initial_capital": 1_000_000,
        "commission_rate": 0.0003,
        "slippage": 0.002,
    }

    def on_bar(self, ctx):
        if ctx.days_since_rebalance >= self.p.rebalance_days:
            targets = ctx.selected_symbols
            target_pct = 1.0 / max(len(targets), 1)
            for sym in ctx.get_positions():
                if sym not in targets:
                    ctx.order_target_percent(sym, 0.0)
            for sym in targets:
                ctx.order_target_percent(sym, target_pct)
            ctx.reset_rebalance_counter()
```

### BaseStrategy 公共属性

- `self.p` — 参数访问器，`self.p.fast` 返回当前参数值
- `name` — 策略名称
- `description` — 策略描述
- `params` — 参数定义（含 default，前端可覆盖）

### Context API

#### 筛选 Context（ScreenerContext）

| 方法 | 说明 |
|------|------|
| `ctx.indicator(sym, type, *args, period=)` | 获取当前时间点的指标值 |
| `ctx.get_price(sym)` | 获取当前bar的OHLCV |
| `ctx.get_history(sym, n)` | 获取最近n根K线 |
| `ctx.current_date` | 当前日期 |

#### 交易 Context（TraderContext，继承筛选Context）

| 方法 | 说明 |
|------|------|
| `ctx.selected_symbols` | 上游筛选器选出的股票列表 |
| `ctx.get_position(sym)` | 获取当前持仓（股数、成本、浮盈） |
| `ctx.get_positions()` | 获取所有持仓的股票列表 |
| `ctx.get_portfolio()` | 获取组合状态（总资产、现金、持仓市值） |
| `ctx.order_target_percent(sym, pct)` | 调仓到目标比例 |
| `ctx.order_shares(sym, shares)` | 买卖指定股数 |
| `ctx.order_value(sym, value)` | 买卖指定金额 |
| `ctx.days_since_rebalance` | 距上次调仓的天数 |
| `ctx.reset_rebalance_counter()` | 重置调仓计数器 |

## 回测引擎

### 事件驱动主循环

```
引擎初始化
  → 加载管道中所有策略
  → 预加载所有相关股票的 qfq 数据到内存
  → 按日期遍历（升序）：
      1. 更新当日行情
      2. Broker 撮合前一日的挂单（pending orders）
      3. 运行筛选管道：策略A.screen() → 策略B.screen() → ...
      4. 将筛选结果传给交易策略：ctx.selected_symbols = 筛选结果
      5. 调用交易策略的 on_bar(ctx)
      6. 记录当日 Portfolio 快照
  → 引擎结束
  → Analyzer 计算绩效
```

### Broker 虚拟券商

模拟 A 股真实交易规则：

| 规则 | 实现 |
|------|------|
| **T+1** | 今天买入的股票，明天才能卖出。持仓记录 `buy_date`，卖出时检查 `current_date > buy_date` |
| **涨跌停** | 一字涨停（low == high == 前收盘×1.1）无法买入；一字跌停（low == high == 前收盘×0.9）无法卖出 |
| **手续费** | 买入：佣金（默认万三，最低5元）。卖出：佣金 + 印花税（千一） |
| **滑点** | 买入价 = 成交价 × (1 + slippage)，卖出价 = 成交价 × (1 - slippage) |
| **最小交易单位** | 买入必须为100股（手）的整数倍，卖出可以零股（不足100股一次性卖出） |
| **成交价格** | 默认使用当日 (open + close) / 2 中间价 |

### 订单流程

```
策略调用 ctx.order_*()
  → 生成 Order 对象（pending 状态）
  → 下一个 bar 开盘时，Broker 撮合：
      1. 检查涨跌停限制
      2. 计算中间价 = (open + close) / 2
      3. 叠加滑点
      4. 检查资金充足（买入）/ T+1（卖出）
      5. 买入取整到100股
      6. 扣除/增加资金，更新持仓
      7. 记录 Trade（成交记录）
  → 订单状态变为 filled / rejected
```

### Portfolio 组合跟踪

每日收盘后记录快照：

```python
{
    "date": "2024-01-15",
    "total_value": 1_050_000,
    "cash": 200_000,
    "market_value": 850_000,
    "positions": {
        "600519.SH": {"shares": 300, "cost": 1800.0, "market_price": 1850.0},
        "000858.SZ": {"shares": 500, "cost": 150.0, "market_price": 155.0},
    },
    "daily_return": 0.005,
}
```

## 数据层

### 数据目录

- `data/kline/A/qfq/` — 前复权数据，回测引擎使用
- `data/kline/A/raw/` — 不复权数据，K线展示使用

### K线展示增强

前端 StockDetail 页面增加不复权/前复权切换按钮，后端 kline API 增加 `adjust` 参数（`raw`/`qfq`），默认 `raw`。

### 性能优化

- **预加载**：引擎启动时一次性读取所有相关股票的 parquet 到内存
- **指标缓存**：同一股票同一指标只计算一次，结果缓存在 dict 中
- **筛选逐级缩小**：上游筛选后，下游只需处理更少的股票
- **超时保护**：单次回测最大运行时间 5 分钟

## 绩效分析 (Analyzer)

### 绩效指标

| 指标 | 计算方式 |
|------|----------|
| 总收益率 | (末日净值 - 初始资金) / 初始资金 |
| 年化收益率 | (1 + 总收益率) ^ (1 / 年数) - 1，年数 = 自然日天数 / 365.25 |
| 最大回撤 | 净值曲线峰值到谷值的最大跌幅 |
| 夏普比率 | (年化收益 - 无风险利率) / 年化波动率，无风险利率默认3% |
| 胜率 | 盈利交易次数 / 总交易次数 |
| 盈亏比 | 平均盈利金额 / 平均亏损金额 |
| 交易次数 | 总买卖成交笔数 |
| 日均换手率 | 日均交易金额 / 日均总资产 |

## 多策略对比

用户选择多个已有的回测结果进行对比：

- 收益曲线叠加（多条净值曲线在同一张图）
- 指标对比表（各策略的年化收益、夏普、回撤等并列展示）
- 按指定指标排名

## REST API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/backtest/strategies` | 列出所有策略文件（名称、类型、参数、描述） |
| POST | `/api/backtest/run` | 运行回测管道（筛选+交易） |
| GET | `/api/backtest/status/{task_id}` | 查询回测任务状态 |
| GET | `/api/backtest/result/{task_id}` | 获取回测结果 |

| POST | `/api/screener/run` | 运行纯选股管道 |
| GET | `/api/screener/result` | 获取最近一次选股结果 |

回测为异步任务（后台线程），通过 `task_id` 轮询状态，结果缓存在内存中。

## 前端页面

| 路由 | 页面 | 功能 |
|------|------|------|
| `/strategies` | StrategyList.vue | 策略管理：列出所有策略文件、类型、参数、描述 |
| `/screener` | ScreenerPage.vue | 选股：选择筛选管道、运行、查看选股结果 |
| `/backtest` | BacktestPage.vue | 回测：组装管道、设置参数/日期、运行、查看结果 |
| `/backtest/result/:id` | BacktestResult.vue | 回测结果详情：完整绩效报告和图表 |
| `/compare` | ComparePage.vue | 多策略对比：选多个回测结果、曲线叠加、指标对比表 |

### 导航

顶部导航栏：`行情 | 策略 | 选股 | 回测 | 对比`

### 关键组件

- **PipelineBuilder.vue** — 管道组装器，选择策略、排列顺序
- **ParamEditor.vue** — 参数编辑器，根据策略 params 自动渲染
- **EquityCurve.vue** — 收益曲线图（ECharts）
- **DrawdownChart.vue** — 回撤曲线
- **TradeTable.vue** — 交易明细表
- **BacktestKline.vue** — K线+买卖点标记
- **MetricCards.vue** — 绩效指标摘要卡片


### K线展示增强

StockDetail 页面增加 `不复权 | 前复权` 切换按钮。

## 文件结构（新增部分）

```
strategies/
  examples/
    ma_cross_screener.py
    macd_screener.py
    equal_weight_trader.py

backend/
  services/
    backtest/
      __init__.py
      base.py                  # BaseStrategy, ScreenerStrategy, TraderStrategy
      engine.py                # BacktestEngine 主循环
      context.py               # ScreenerContext, TraderContext
      broker.py                # Broker（撮合、T+1、涨跌停、费用）
      portfolio.py             # Portfolio（每日净值、持仓快照）
      analyzer.py              # 绩效分析
      strategy_loader.py       # importlib 加载策略文件
      task_manager.py          # 异步任务管理
  routers/
    backtest.py                # 回测 + 优化 API
    screener.py                # 选股 API
  tests/
    test_broker.py
    test_engine.py
    test_analyzer.py
    test_strategy_loader.py
    test_backtest_api.py
    test_screener_api.py

frontend/src/
  views/
    StrategyList.vue
    ScreenerPage.vue
    BacktestPage.vue
    BacktestResult.vue
    ComparePage.vue
  components/
    PipelineBuilder.vue
    ParamEditor.vue
    EquityCurve.vue
    DrawdownChart.vue
    TradeTable.vue
    BacktestKline.vue
    MetricCards.vue
```

## 错误处理

- 策略文件语法错误 → 加载时捕获，返回错误信息
- 策略运行时异常 → on_bar/screen 中异常被捕获，记录到日志，回测终止并返回已有结果
- 数据缺失 → 某只股票在某天没有数据时，ctx.indicator() 返回 None
