# 5 策略合并 + 架构收敛设计

**日期**: 2026-05-18
**状态**: Draft (待 review)
**前置**: 2026-05-09-buy-sell-strategy-design.md / 2026-05-09-strategy-group-design.md / 2026-04-22-pipeline-time-correlation-design.md / 2026-04-14-chain-backtest-design.md

## 背景

项目当前包含 7 个独立策略,通过 pipeline + join_modes + StrategyGroup 三层组合机制串联。实际使用中:

1. **架构分裂**:`ScreenerStrategy / TraderStrategy / BuyStrategy / SellStrategy` 四个基类并存,Engine 因此有两套(`engine.py` + `buy_sell_engine.py`)、三条执行路径(`mode="screen"` / 选股回测 / 完整回测)、多种入参组合(`source_task_id` / `signal_table` / `join_modes`)。代码量近 700 行,语义割裂。
2. **业务概念过载**:Pipeline、StrategyGroup、链式回测、join_mode 都是"组合多个策略"的不同抽象,功能重叠且难以解释。
3. **复用难度**:跨策略复用某段逻辑(如"获取 ROE")只能通过类继承或重复实现,没有函数级复用。

本设计将 5 个相关策略合并为 1 个完整策略 `MaTangleValueStrategy`,并借此重构基类、引擎、上下文、数据库、前端,使整个回测系统收敛到**单一策略 = 单次回测**的模型。

## 决策

### D1. 单一 `Strategy` 基类

废弃 `ScreenerStrategy / TraderStrategy / BuyStrategy / SellStrategy`,改为单一 `Strategy` 类同时拥有 `screen / on_buy / on_sell` 三个钩子,默认实现:

- `screen()` → 返回全部输入 symbols(等价无筛选)
- `on_buy()` → pass
- `on_sell()` → pass(永久持有)

`frequency` / `settings` 整合到主类。子类按需覆盖,不强制 `NotImplementedError`。

### D2. 取消 Pipeline / StrategyGroup / 链式回测

一次回测 = 一个 Strategy 实例。多策略复用通过**工具函数**(代码层面)实现,不再有 pipeline / StrategyGroup / source_task_id / signal_table / join_mode 等业务概念。

### D3. Engine 单一执行路径

删 `buy_sell_engine.py`,重写 `engine.py` 为唯一入口。删除 `mode="screen"` 分支(纯选股需求由 `routers/screener.py` 直接调 `strategy.screen()`,不进 Engine)、删除 `_union_results / _intersect_results / _filter_to_finest` 等 join_mode 合并逻辑。保留按 `frequency` 周期切换的 screen 缓存(性能必需)。

主循环固定顺序:`fill_orders(T+1) → screen(若周期切换) → on_sell → on_buy → snapshot`。

### D4. utils 库结构

```
strategies/utils/
├── kline.py            # 单源:K线
├── financial.py        # 单源:财务三表+指标(不拆四表)
├── dividend.py         # 单源:分红事件
├── valuation.py        # 单源:估值(PE/PB/市值)
└── composite/
    ├── __init__.py
    └── market_cap_weighted_batch_buyer.py   # 跨源(估值+K线),含状态 → class
```

**组织规则**(两维独立):
- **位置维度**:单源 vs 跨源 → 是否进 `composite/`
- **形式维度**:无状态 vs 有状态 → 函数 vs class

跨源的无状态函数(如 `dividend_yield = 分红/股价`)也放 composite/ 但仍是函数。所以 composite/ 下函数和类都可以有。

### D5. 日志契约(决策可追溯性)

合并后单次回测产生 `N_days × N_stocks × N_conditions` 量级决策。必须做到事后给定 (symbol, date) 能精确定位被哪个 stage 选中/淘汰。

三层日志:
| 层 | 用途 | logger | 默认级别 | 输出 |
|---|---|---|---|---|
| 决策层 | per-symbol per-stage pass/reject | `backtest.decisions` | DEBUG | JSONL 文件 |
| 聚合层 | per-stage per-bar 总数 | `backtest.flow` | INFO | stdout + 文件 |
| 执行层 | 下单/平仓 | `backtest.exec` | INFO | stdout + 文件 |

`Context` 暴露 `log_pass / log_reject / log_flow` 三个 API,utils 函数和 Strategy 都通过它打日志(不直接用 logging),保证格式统一。

任务日志目录:`data/logs/backtest/<task_id>/{decisions.jsonl, flow.log, exec.log}`。`backtest_tasks` 表新增 `log_dir` 列。

提供 `enable_decision_log: bool = True` 开关,大规模批跑可关。

### D6. 数据库迁移

- `backtest_tasks` 表:清理 `source_task_id` 死列;`pipeline_info` 字段重定义为 `{strategy_class: str, params: dict}`;新增 `log_dir` 列。
- DROP `strategy_groups` 表
- DROP `group_runs` 表
- 旧任务记录保留可读(展示历史),不可重跑

### D7. 合并后策略

`MaTangleValueStrategy`(月线均线缠绕价值策略)合并 5 个原策略:
1. DividendYearsScreener(连续分红年数)→ `dividend.filter_by_dividend_years`
2. PePbProductScreener(PE\*PB 区间)→ `valuation.filter_by_pe_pb_product`
3. RoeScreener(ROE 阈值)→ `financial.filter_by_roe`
4. MaTangleBreakoutScreener(月线均线缠绕突破)→ `kline.detect_ma_tangle_breakout`
5. MarketCapWeightedBuyer(市值加权 N 周定投)→ `composite.MarketCapWeightedBatchBuyer`(状态类)

筛选顺序按"数据廉价度递增、淘汰率递减"原则:分红 → PE\*PB → ROE → MA 缠绕。

`MonthlyLowScreener / MonthlyVolumeRedScreener` 的逻辑迁移到 `kline.is_at_history_low / kline.has_consecutive_red_bars`,不参与本次合并策略,但作为 utils 保留供其他策略使用。

## 详细设计

### Strategy 基类 (`backend/services/backtest/base.py` 重写)

```python
class ParamAccessor:
    """保留不动,负责参数覆盖与类型转换。"""

class Strategy:
    name: str = ""
    description: str = ""
    params: dict = {}
    frequency: str = "daily"   # screen() 调用周期 (daily/weekly/monthly)
    settings: dict = {}        # initial_capital / commission_rate / slippage,有默认

    def __init__(self, param_overrides: dict = None):
        self.p = ParamAccessor(self.params, overrides=param_overrides)
        defaults = {
            "initial_capital": 1_000_000,
            "commission_rate": 0.0003,
            "slippage": 0.002,
        }
        self.settings = {**defaults, **self.__class__.settings}

    def screen(self, ctx: "Context", symbols: list[str]) -> list[str]:
        return symbols  # 默认全通过

    def on_buy(self, ctx: "Context") -> None:
        pass  # 默认不买

    def on_sell(self, ctx: "Context") -> None:
        pass  # 默认永久持有
```

### Engine (`backend/services/backtest/engine.py` 重写,目标 ~200 行)

```python
class BacktestEngine:
    def __init__(
        self,
        strategy: Strategy,
        stock_data: dict[str, pd.DataFrame],
        valuation_data: dict | None = None,
        dividend_data: dict | None = None,
        financial_data: dict | None = None,
        on_progress: Callable | None = None,
        log_dir: Path | None = None,
        enable_decision_log: bool = True,
    ):
        self._strategy = strategy
        self._broker = Broker(**strategy.settings)
        self._market_data = MarketData(...)  # 按 strategy.frequency 预聚合
        self._log_sink = DecisionLogSink(log_dir, enable_decision_log)

    def run(self) -> dict:
        ref_df = ...; n_bars = len(ref_df)
        target_symbols: set[str] = set()
        screener_cache: list[str] = []
        prev_period_key: str | None = None
        equity_curve, prev_closes = [], {}

        for idx in range(n_bars):
            current_bars, current_prices = self._build_bar_data(idx)
            if idx > 0:
                self._broker.fill_orders(...)

            current_date = ref_df.iloc[idx]["date"]
            ctx = Context(
                strategy=self._strategy,
                idx=idx,
                broker=self._broker,
                market_data=self._market_data,
                log_sink=self._log_sink,
            )

            # 1) screen 仅在 frequency 周期切换时跑
            pk = self._period_key(current_date, self._strategy.frequency)
            if pk != prev_period_key:
                screener_cache = self._strategy.screen(ctx, list(self._all_symbols))
                prev_period_key = pk

            # 2) 累计目标池
            today_signals = [s for s in screener_cache if s in current_bars]
            new_symbols = [s for s in today_signals if s not in target_symbols]
            target_symbols.update(new_symbols)
            ctx.set_pool(target_symbols, new_symbols)

            # 3) sell 先于 buy
            self._strategy.on_sell(ctx)
            self._strategy.on_buy(ctx)

            equity_curve.append(self._broker.portfolio.snapshot(current_date, current_prices))
            prev_closes = dict(current_prices)

        self._log_sink.flush()
        return {
            "metrics": compute_metrics(...),
            "equity_curve": equity_curve,
            "trades": self._broker.all_trades,
        }
```

### Context (`backend/services/backtest/context.py` 重写)

合并 `ScreenerContext / TraderContext` 为单一 `Context`,同时提供:
- 数据访问:`get_price / get_history / get_valuation / get_dividend / get_financial / indicator`
- 多频率:`_get_data_for_freq` 保留(按 `period` 参数)
- 持仓与下单:`get_position / get_positions / order_shares / order_value / order_target_percent / available_cash`
- 累计池:`target_symbols / new_symbols / remove_target() / set_pool()`
- 日志:`log_pass(symbol, stage, **values) / log_reject(symbol, stage, reason, **values) / log_flow(stage, **counts)`

`current_date / current_idx` 作为属性。

### utils 函数签名

#### `strategies/utils/kline.py`

```python
def detect_ma_tangle_breakout(
    ctx, symbol: str, *,
    fast: int = 5, mid: int = 10, slow: int = 20,
    tangle_threshold: float = 0.05,
    tangle_months: int = 2,
    spread_months: int = 6,
    spread_threshold: float = 0.01,
    vol_red_bars: int = 4,
    freq: str = "monthly",
) -> bool:
    """当前 bar 是否完成了一次「均线缠绕→发散→连续阳线」突破。
    内部对 symbol 写 log_pass / log_reject(stage='kline.ma_tangle')。
    """

def is_at_history_low(
    ctx, symbol: str, *, years: int = 3, range_pct: float = 20.0, freq: str = "monthly"
) -> bool:
    """当月 low 处于过去 N 年最低价的 (1+range_pct%) 范围内。
    stage='kline.history_low'
    """

def has_consecutive_red_bars(
    ctx, symbol: str, *, n: int = 4, freq: str = "monthly"
) -> bool:
    """最近 n 根 K 线全为阳线(close >= open)。
    stage='kline.consecutive_red'
    """

# 通用辅助(纯计算,不打日志)
def get_ma(ctx, symbol: str, window: int, *, freq: str = "daily") -> float | None: ...
def get_macd(ctx, symbol: str, field: str = "dif", *, freq: str = "daily") -> float | None: ...
```

#### `strategies/utils/financial.py`

```python
def filter_by_roe(ctx, symbols: list[str], *, min_roe: float = 10.0) -> list[str]:
    """ROE >= min_roe。stage='financial.roe'。
    使用财报字段 '净资产收益率'(实际数据列名)。
    """

def get_roe(ctx, symbol: str) -> float | None: ...
def get_eps(ctx, symbol: str) -> float | None: ...
def get_net_profit_growth(ctx, symbol: str) -> float | None: ...
```

#### `strategies/utils/dividend.py`

```python
def filter_by_dividend_years(
    ctx, symbols: list[str], *, min_years: int = 5
) -> list[str]:
    """累计现金分红年数 >= min_years。stage='dividend.years'"""

def count_dividend_years(ctx, symbol: str) -> int | None:
    """统计该股票历史上有几个不同的年度发生过 cash_dividend > 0"""
```

#### `strategies/utils/valuation.py`

```python
def filter_by_pe_pb_product(
    ctx, symbols: list[str], *,
    min_value: float = 0.0, max_value: float = 22.0
) -> list[str]:
    """PE(TTM) * PB ∈ [min, max]。stage='valuation.pe_pb_product'"""

def get_pe(ctx, symbol: str) -> float | None: ...
def get_pb(ctx, symbol: str) -> float | None: ...
def get_total_mv(ctx, symbol: str) -> float | None:
    """总市值(单位:元)"""
```

#### `strategies/utils/composite/market_cap_weighted_batch_buyer.py`

```python
class MarketCapWeightedBatchBuyer:
    """市值加权 N 周分批买入器。

    跨源:取 valuation.total_mv 决定权重,按 kline 周线 (open+close)/2 成交。
    状态:_buy_plans / _allocated 跨 step 调用累积,因此封装为 class 而非函数。
    """
    def __init__(self, *, buy_weeks: int = 8, lot_size: int = 100):
        self._buy_plans: dict[str, dict] = {}
        self._allocated: set[str] = set()
        self._buy_weeks = buy_weeks
        self._lot_size = lot_size

    def step(self, ctx) -> None:
        """每个 on_buy 调用一次。"""
        self._create_plans_for_new(ctx)   # log stage='batch_buyer.allocate'
        self._execute_weekly_buys(ctx)    # log stage='batch_buyer.buy'
```

### 数据流(Engine ↔ Context ↔ Strategy ↔ Buyer)

每个 bar 主循环固定数据流如下:

```
[Engine 主循环 idx]
   │
   ├─► current_bars, current_prices = build_bar_data(idx)
   ├─► broker.fill_orders(...)                          # T+1 撮合昨日订单
   │
   ├─► ctx = Context(idx, broker, market_data, log_sink)
   │
   ├─► IF 周期切换 (frequency 决定):
   │     screener_cache = strategy.screen(ctx, all_symbols)
   │
   ├─► today_signals = [s for s in screener_cache if s in current_bars]
   ├─► new_symbols   = [s for s in today_signals if s not in target_symbols]
   ├─► target_symbols.update(new_symbols)
   │
   ├─► ctx.set_pool(target_symbols, new_symbols)        # ← 关键:注入累计池
   │       └─ 设置 ctx.target_symbols / ctx.new_symbols 属性
   │       └─ 绑定 ctx.remove_target() 回调(seller 平仓时调用)
   │
   ├─► strategy.on_sell(ctx)                            # 可调 ctx.remove_target(sym)
   │
   ├─► strategy.on_buy(ctx)
   │       └─ self._buyer.step(ctx)
   │             ├─ READS  ctx.new_symbols   → 为新增股票创建买入计划
   │             ├─ READS  ctx.target_symbols → 检查股票是否仍在池中
   │             ├─ READS  ctx.available_cash → 分配本周买入金额
   │             ├─ READS  ctx.get_price(sym, period="weekly") → 取成交价
   │             ├─ CALLS  ctx.order_shares(sym, n) → 下单
   │             └─ WRITES ctx.log_pass / log_reject  (stage='batch_buyer.*')
   │
   └─► equity_curve.append(broker.portfolio.snapshot(...))
```

**Context 字段总览**(给 Strategy / Buyer / utils 函数使用):

| 字段 / 方法 | 来源 | 用途 |
|---|---|---|
| `current_date / current_idx` | Engine 注入 | 当前 bar 时间锚点 |
| `target_symbols: list[str]` | `ctx.set_pool()` 设置 | 累计目标池(已选股+尚未平仓) |
| `new_symbols: list[str]` | `ctx.set_pool()` 设置 | 本 bar 新增的目标(buyer 据此分配) |
| `remove_target(sym)` | `ctx.set_pool()` 绑定回调 | seller 调用,通知 Engine 移除累计池 |
| `available_cash` | broker.portfolio | 当前可用现金 |
| `get_price / get_history / get_valuation / get_dividend / get_financial / indicator` | market_data | 数据访问 |
| `get_position / get_positions` | broker.portfolio | 持仓查询 |
| `order_shares / order_value / order_target_percent` | broker.submit_order | 下单 |
| `log_pass / log_reject / log_flow` | log_sink | 决策日志 |

**关键不变量**:
- `new_symbols ⊆ target_symbols`(新增股票一定也在累计池中)
- `target_symbols` 是 Engine 与 ctx 共享的可变集合。`on_sell` 通过 `ctx.remove_target(sym)` 修改后,**同一 bar 内** `on_buy` 看到的 `ctx.target_symbols` 已经是更新后的视图(seller 先于 buyer,目的就是避免买入刚被卖出的股票)
- buyer 创建买入计划时基于 `ctx.new_symbols`,但执行每周买入前必须重新检查 `sym in ctx.target_symbols`(参考原 `MarketCapWeightedBuyer._execute_weekly_buys` 中 `if sym not in ctx.target_symbols: finished.append(sym)` 的处理)

### 合并策略 (`strategies/examples/ma_tangle_value_strategy.py`)

```python
class MaTangleValueStrategy(Strategy):
    name = "月线均线缠绕价值策略"
    description = (
        "基本面池(连续分红 + PE*PB 区间 + ROE 达标)与月线均线缠绕突破信号交集,"
        "命中后按市值加权 8 周分批买入,默认永久持有。"
    )
    frequency = "monthly"

    params = {
        # 基本面池
        "min_dividend_years": {"default": 5, "type": "int", "label": "最少分红年数"},
        "pe_pb_min": {"default": 0.0, "type": "float", "label": "PE*PB 下限"},
        "pe_pb_max": {"default": 22.0, "type": "float", "label": "PE*PB 上限"},
        "min_roe": {"default": 10.0, "type": "float", "label": "最低 ROE(%)"},

        # 技术信号
        "ma_fast": {"default": 5, "type": "int"},
        "ma_mid": {"default": 10, "type": "int"},
        "ma_slow": {"default": 20, "type": "int"},
        "tangle_threshold": {"default": 0.05, "type": "float"},
        "tangle_months": {"default": 2, "type": "int"},
        "spread_months": {"default": 6, "type": "int"},
        "spread_threshold": {"default": 0.01, "type": "float"},
        "vol_red_bars": {"default": 4, "type": "int"},

        # 买入器
        "buy_weeks": {"default": 8, "type": "int", "label": "分批周数"},
    }

    settings = {
        "initial_capital": 1_000_000,
        "commission_rate": 0.0003,
        "slippage": 0.002,
    }

    def __init__(self, param_overrides=None):
        super().__init__(param_overrides)
        self._buyer = MarketCapWeightedBatchBuyer(buy_weeks=self.p.buy_weeks)

    def screen(self, ctx, symbols):
        ctx.log_flow("strategy.screen.start", input=len(symbols))

        # 顺序:数据廉价的先做,昂贵的 K 线计算后做
        pool = dividend.filter_by_dividend_years(ctx, symbols, min_years=self.p.min_dividend_years)
        pool = valuation.filter_by_pe_pb_product(
            ctx, pool, min_value=self.p.pe_pb_min, max_value=self.p.pe_pb_max
        )
        pool = financial.filter_by_roe(ctx, pool, min_roe=self.p.min_roe)
        ctx.log_flow("strategy.fundamental_pool", passed=len(pool))

        signals = []
        for sym in pool:
            if kline.detect_ma_tangle_breakout(
                ctx, sym,
                fast=self.p.ma_fast, mid=self.p.ma_mid, slow=self.p.ma_slow,
                tangle_threshold=self.p.tangle_threshold,
                tangle_months=self.p.tangle_months,
                spread_months=self.p.spread_months,
                spread_threshold=self.p.spread_threshold,
                vol_red_bars=self.p.vol_red_bars,
                freq="monthly",
            ):
                signals.append(sym)
                ctx.log_pass(sym, "strategy.screen.final")

        ctx.log_flow("strategy.screen.done", input=len(symbols), passed=len(signals))
        return signals

    def on_buy(self, ctx):
        self._buyer.step(ctx)

    # on_sell 默认 pass = 永久持有
```

### 日志样例

```
[flow]   strategy.screen.start         input=4823
[reject] dividend.years                symbol=600519 reason=below_threshold years=3 threshold=5
[pass]   dividend.years                symbol=000858 years=12 threshold=5
[flow]   dividend.years                input=4823 passed=421
[reject] valuation.pe_pb_product       symbol=000858 reason=above_max product=68.5 max=22.0
[pass]   valuation.pe_pb_product       symbol=600036 product=11.2
[flow]   valuation.pe_pb_product       input=421 passed=87
[reject] financial.roe                 symbol=601398 reason=below_threshold roe=8.4 threshold=10.0
[pass]   financial.roe                 symbol=600036 roe=14.7
[flow]   strategy.fundamental_pool     passed=43
[reject] kline.ma_tangle               symbol=600036 reason=no_tangle_in_window
[pass]   kline.ma_tangle               symbol=601318 tangle_end=2024-02 breakout=2024-04
[pass]   strategy.screen.final         symbol=601318
[flow]   strategy.screen.done          input=4823 passed=12
[flow]   batch_buyer.allocate          symbol=601318 mv=8.2e11 weight=0.34 weekly_amount=42500
[exec]                                 BUY 601318 1300 @ 35.20 (week 1/8)
```

JSONL 格式(决策层文件):
```json
{"ts":"2024-03-29","idx":1234,"freq":"monthly","stage":"financial.roe","symbol":"601398","decision":"reject","reason":"below_threshold","roe":8.4,"threshold":10.0}
```

## 影响范围

### 后端

**重写**:
- `backend/services/backtest/base.py`(只剩 `Strategy` 单基类 + `ParamAccessor`)
- `backend/services/backtest/engine.py`(单一路径,~200 行)
- `backend/services/backtest/context.py`(合并 ScreenerContext/TraderContext + 日志 API)
- `backend/services/backtest/strategy_loader.py`(适配单基类扫描)
- `backend/services/backtest/task_manager.py`(适配新 `pipeline_info` schema + `log_dir`)
- `backend/routers/backtest.py`(移除 `source_task_id` / `mode=screen` 路径,简化入参)
- `backend/services/db_schema.py`(迁移脚本)

**新增**:
- `backend/services/backtest/decision_log.py`(`DecisionLogSink` JSONL 写入器,带缓冲)
- `strategies/utils/__init__.py`
- `strategies/utils/kline.py / financial.py / dividend.py / valuation.py`
- `strategies/utils/composite/__init__.py`
- `strategies/utils/composite/market_cap_weighted_batch_buyer.py`
- `strategies/examples/ma_tangle_value_strategy.py`

**删除**:
- `backend/services/backtest/buy_sell_engine.py`
- `backend/services/backtest/group_manager.py`
- `backend/services/backtest/engine_base.py`(合并入 engine.py)
- `backend/services/backtest/date_utils.py` 中 join_mode 相关函数(`date_belongs_to` 等若仅 join_mode 使用则删,否则保留)
- `backend/routers/strategy_group.py`
- 7 个旧 `strategies/examples/*.py`(逻辑已迁移到 utils 后删)

### 数据库

- `backtest_tasks`:DROP `source_task_id`,`pipeline_info` 改为 `{strategy_class, params}`,新增 `log_dir`,新增 `is_deleted BOOLEAN DEFAULT FALSE`(软删,日志永久保留作审计)
- DROP TABLE `strategy_groups`
- DROP TABLE `group_runs`
- 提供迁移脚本 `backend/services/migrations/2026-05-18-merge-strategies.sql`

### 前端

**删除**(StrategyGroup 三层页面):
- `src/pages/StrategyGroup*` / `src/components/strategyGroup/*`
- 相关路由、API client、store

**简化**:
- `src/components/backtest/BacktestConfig.tsx`:从 pipeline 表单(多 screener + trader)简化为单 strategy 选择 + 参数表单
- `src/components/backtest/BacktestResult.tsx`:展示 strategy_class + params,移除 pipeline_info 嵌套展示
- `src/api/backtest.ts`:入参收敛

**新增**(决策日志查询面板,可选范围):
- `src/components/backtest/DecisionLogPanel.tsx`:在任务详情页,按 (symbol, date 范围, stage) 过滤查询 decisions.jsonl

### 测试

- 后端:`backend/tests/services/backtest/` 全面重写(原 ~80 个回测测试)
  - 删除 join_mode / chain / signal_table / strategy_group 相关
  - 新增 utils 函数级测试(每个 filter_by_* / detect_* 各一组)
  - 新增 `MaTangleValueStrategy` 集成测试(全链路)
  - 新增 `DecisionLogSink` 单测
- 前端:删除 StrategyGroup 相关测试

## 测试策略

1. **utils 单测**:每个 `filter_by_*` 用 mock ctx + 固定数据集,验证通过/淘汰名单 + 日志条目数
2. **`MaTangleValueStrategy` 集成测**:用一组已知通过/淘汰的股票运行完整 screen,断言:
   - 最终 signals 列表正确
   - decisions.jsonl 中每个 symbol 至少有一条 pass 或 reject
   - 给定 (symbol, date) 能唯一定位到淘汰原因
3. **Engine 测**:固定单一 Strategy,验证主循环执行顺序、screen 缓存命中、target_symbols 累计、broker T+1
4. **回归测**:用旧 `MaTangleBreakoutScreener` 在某一历史时段产出的信号集,与 `MaTangleValueStrategy(min_dividend_years=0, pe_pb_max=∞, min_roe=-∞)`(等价禁用基本面)的信号集对比应一致

## 实施阶段(高层)

1. **Phase 1**:新增 utils 库 + `Strategy` 基类(向后兼容,旧基类保留)→ 跑通新单测
2. **Phase 2**:新增 `MaTangleValueStrategy` + 决策日志 → 集成测通过
3. **Phase 3**:重写 Engine + Context,迁移旧策略测试
4. **Phase 4**:数据库迁移 + 后端路由简化
5. **Phase 5**:前端 BacktestConfig 简化 + StrategyGroup 删除
6. **Phase 6**:删除 7 个旧策略 + 旧基类 + 旧引擎 + 旧路由
7. **Phase 7**:决策日志查询面板(可选,后续迭代)

每个 Phase 结束跑 `python -m pytest backend/tests/ -x -q` + `cd frontend && npx tsc --noEmit && npm test` 全绿才进入下一阶段。

## 已决议事项(2026-05-18)

1. **决策日志查询面板**:不纳入本次范围,留待后续迭代。本次只保证后端日志正确写入 `data/logs/backtest/<task_id>/`。
2. **JSONL 文件清理策略**:**永久保留作审计**。`backtest_tasks` 表新增 `is_deleted: bool` 软删字段,任务"删除"操作仅置位该字段,日志文件不动。前端列表默认过滤 `is_deleted=False`。
3. **`enable_decision_log`**:UI 不暴露,默认 True 始终开启。代码层面保留参数以便测试或大规模批跑场景关闭。
4. **`MonthlyLowScreener / MonthlyVolumeRedScreener`**:逻辑迁入 `kline.is_at_history_low / has_consecutive_red_bars`,**原策略文件直接删除**,不保留示例策略。最终 `strategies/examples/` 下仅有 `ma_tangle_value_strategy.py` 一个文件。
