# 调仓逻辑：target_symbols 累计语义 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 BuySellEngine 改为维护 target_symbols 累计池，Buyer 仅在有新增时调用，Seller 每天评估持仓并可从池中移除。

**Architecture:** Engine 内部维护 `target_symbols: set` 累计池。每个 bar: (1) 信号/选股产生新股票加入池, (2) Seller 先执行可平仓并移除, (3) Buyer 仅在有新增时执行。TraderContext 增加 `target_symbols` 和 `new_symbols` 属性。Seller 通过 ctx 方法移除 target。

**Tech Stack:** Python, pytest

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `backend/services/backtest/context.py` | TraderContext 增加 target_symbols, new_symbols, remove_target() |
| `backend/services/backtest/buy_sell_engine.py` | 维护 target_symbols 池，改变执行顺序和调用条件 |
| `backend/tests/test_buy_sell_engine.py` | 更新现有测试适配新语义 |
| `backend/tests/test_rebalance_logic.py` | 新增：调仓逻辑专项测试 |

---

### Task 1: TraderContext 增加 target_symbols 和 new_symbols

**Files:**
- Modify: `backend/services/backtest/context.py:236-256`
- Test: `backend/tests/test_rebalance_logic.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_rebalance_logic.py
"""调仓逻辑测试：target_symbols 累计语义、执行顺序、Buyer 调用条件。"""
import pandas as pd
import pytest
from services.backtest.context import TraderContext
from services.backtest.portfolio import Portfolio


def _make_stock_data():
    dates = [f"2024-01-{d:02d}" for d in range(2, 12)]
    df = pd.DataFrame({
        "date": dates,
        "open": [10.0] * 10,
        "high": [11.0] * 10,
        "low": [9.0] * 10,
        "close": [10.0] * 10,
        "volume": [1000.0] * 10,
        "amount": [10000.0] * 10,
    })
    return {"SH600001": df, "SH600002": df.copy(), "SH600003": df.copy()}


def test_trader_context_target_symbols():
    """TraderContext 应能接收并暴露 target_symbols 和 new_symbols。"""
    stock_data = _make_stock_data()
    portfolio = Portfolio(cash=1_000_000)

    ctx = TraderContext(
        stock_data=stock_data,
        current_idx=0,
        portfolio=portfolio,
        broker_submit=lambda *a: None,
        selected_symbols=[],
        target_symbols=["SH600001", "SH600002"],
        new_symbols=["SH600002"],
    )
    assert set(ctx.target_symbols) == {"SH600001", "SH600002"}
    assert ctx.new_symbols == ["SH600002"]


def test_trader_context_remove_target():
    """Seller 通过 ctx.remove_target() 从 target_symbols 中移除股票。"""
    stock_data = _make_stock_data()
    portfolio = Portfolio(cash=1_000_000)
    target_set = {"SH600001", "SH600002"}

    ctx = TraderContext(
        stock_data=stock_data,
        current_idx=0,
        portfolio=portfolio,
        broker_submit=lambda *a: None,
        selected_symbols=[],
        target_symbols=list(target_set),
        new_symbols=[],
        on_remove_target=lambda sym: target_set.discard(sym),
    )
    ctx.remove_target("SH600001")
    assert "SH600001" not in target_set
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_rebalance_logic.py -x -v`
Expected: FAIL — TraderContext 不接受 target_symbols/new_symbols/on_remove_target 参数

- [ ] **Step 3: Implement — 修改 TraderContext**

在 `backend/services/backtest/context.py` 的 `TraderContext.__init__` 中增加参数：

```python
class TraderContext(ScreenerContext):
    """交易策略上下文，继承ScreenerContext并增加下单、持仓查询等交易接口。"""
    def __init__(
        self,
        stock_data: dict[str, pd.DataFrame],
        current_idx: int,
        portfolio: Portfolio,
        broker_submit,
        selected_symbols: list[str],
        days_since_rebalance: int = 0,
        weekly_data: dict[str, pd.DataFrame] | None = None,
        monthly_data: dict[str, pd.DataFrame] | None = None,
        valuation_data: dict[str, pd.DataFrame] | None = None,
        dividend_data: dict[str, pd.DataFrame] | None = None,
        financial_data: dict[str, pd.DataFrame] | None = None,
        target_symbols: list[str] | None = None,
        new_symbols: list[str] | None = None,
        on_remove_target: callable = None,
    ):
        super().__init__(stock_data, current_idx, "daily", weekly_data, monthly_data, valuation_data, dividend_data, financial_data)
        self._portfolio = portfolio
        self._broker_submit = broker_submit
        self.selected_symbols = selected_symbols
        self.days_since_rebalance = days_since_rebalance
        self.target_symbols = target_symbols or []
        self.new_symbols = new_symbols or []
        self._on_remove_target = on_remove_target

    def remove_target(self, symbol: str):
        """Seller 调用：平仓后从 target_symbols 中移除，通知引擎更新累计池。"""
        if self._on_remove_target:
            self._on_remove_target(symbol)
        if symbol in self.target_symbols:
            self.target_symbols.remove(symbol)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_rebalance_logic.py -x -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to check no regressions**

Run: `python -m pytest backend/tests/ -x -q`
Expected: All pass (TraderContext 新参数有默认值，不影响现有调用)

- [ ] **Step 6: Commit**

```bash
git add backend/services/backtest/context.py backend/tests/test_rebalance_logic.py
git commit -m "feat: TraderContext 增加 target_symbols/new_symbols/remove_target 支持"
```

---

### Task 2: BuySellEngine 维护 target_symbols 累计池

**Files:**
- Modify: `backend/services/backtest/buy_sell_engine.py:137-263`
- Test: `backend/tests/test_rebalance_logic.py`

- [ ] **Step 1: Write the failing test**

追加到 `backend/tests/test_rebalance_logic.py`:

```python
from services.backtest.buy_sell_engine import BuySellEngine
from services.backtest.base import BuyStrategy, SellStrategy, ScreenerStrategy


class RecordingBuyer(BuyStrategy):
    """记录每次 on_bar 调用时的 target_symbols 和 new_symbols。"""
    name = "recording_buyer"
    params = {}

    def __init__(self):
        super().__init__()
        self.calls = []

    def on_bar(self, ctx):
        self.calls.append({
            "date": ctx._current_date,
            "target_symbols": list(ctx.target_symbols),
            "new_symbols": list(ctx.new_symbols),
            "cash": ctx.available_cash,
        })


class RecordingSeller(SellStrategy):
    """在特定日期对特定股票调用 remove_target + 卖出。"""
    name = "recording_seller"
    params = {}

    def __init__(self, sell_plan: dict[str, list[str]] = None):
        super().__init__()
        self.sell_plan = sell_plan or {}
        self.calls = []

    def on_bar(self, ctx):
        self.calls.append(ctx._current_date)
        symbols_to_sell = self.sell_plan.get(ctx._current_date, [])
        for sym in symbols_to_sell:
            pos = ctx.get_position(sym)
            if pos and pos["shares"] > 0:
                ctx.order_shares(sym, -pos["shares"])
                ctx.remove_target(sym)


def test_target_symbols_accumulates():
    """信号表命中时 target_symbols 累计，buyer 仅在有新增时调用。"""
    stock_data = _make_stock_data()
    # 信号表: day3 加入 SH600001, day5 加入 SH600002
    signal_table = {
        "2024-01-04": ["SH600001"],
        "2024-01-06": ["SH600002"],
    }
    buyer = RecordingBuyer()
    seller = RecordingSeller()

    engine = BuySellEngine(
        stock_data=stock_data,
        buyer=buyer,
        seller=seller,
        initial_capital=1_000_000,
        signal_table=signal_table,
    )
    engine.run()

    # Buyer 应该被调用2次（day4 和 day6，T+1后的日期？不对，信号日当天就调用）
    # 实际上信号日当天 buyer 就被调用
    assert len(buyer.calls) == 2

    # 第一次调用: target_symbols = [SH600001], new_symbols = [SH600001]
    assert "SH600001" in buyer.calls[0]["target_symbols"]
    assert "SH600001" in buyer.calls[0]["new_symbols"]

    # 第二次调用: target_symbols = [SH600001, SH600002], new_symbols = [SH600002]
    assert "SH600001" in buyer.calls[1]["target_symbols"]
    assert "SH600002" in buyer.calls[1]["target_symbols"]
    assert buyer.calls[1]["new_symbols"] == ["SH600002"]


def test_seller_removes_from_target():
    """Seller 平仓后从 target_symbols 移除，不触发 buyer。"""
    stock_data = _make_stock_data()
    signal_table = {
        "2024-01-03": ["SH600001"],
    }
    # Seller 在 day5 卖出 SH600001
    seller = RecordingSeller(sell_plan={"2024-01-06": ["SH600001"]})
    buyer = RecordingBuyer()

    engine = BuySellEngine(
        stock_data=stock_data,
        buyer=buyer,
        seller=seller,
        initial_capital=1_000_000,
        signal_table=signal_table,
    )
    engine.run()

    # Buyer 只在 day3（信号日）被调用1次
    assert len(buyer.calls) == 1
    assert buyer.calls[0]["target_symbols"] == ["SH600001"]

    # Seller 每天都被调用
    assert len(seller.calls) == 10


def test_seller_executes_before_buyer():
    """同一天: seller 先执行释放资金，buyer 后执行时能用到释放的资金。"""
    stock_data = _make_stock_data()
    # 同一天既有信号又有卖出
    signal_table = {
        "2024-01-03": ["SH600001"],
        "2024-01-06": ["SH600002"],
    }
    # day6 同时: 卖出 SH600001 + 买入 SH600002 信号
    seller = RecordingSeller(sell_plan={"2024-01-06": ["SH600001"]})
    buyer = RecordingBuyer()

    engine = BuySellEngine(
        stock_data=stock_data,
        buyer=buyer,
        seller=seller,
        initial_capital=1_000_000,
        signal_table=signal_table,
    )
    engine.run()

    # Buyer 第二次调用时（day6），SH600001 已被 seller 移除
    day6_call = [c for c in buyer.calls if c["date"] == "2024-01-06"]
    assert len(day6_call) == 1
    assert "SH600001" not in day6_call[0]["target_symbols"]
    assert "SH600002" in day6_call[0]["target_symbols"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_rebalance_logic.py::test_target_symbols_accumulates -x -v`
Expected: FAIL — 当前引擎不维护 target_symbols 池

- [ ] **Step 3: Implement — 重写 BuySellEngine.run() 主循环**

修改 `backend/services/backtest/buy_sell_engine.py` 的 `run()` 方法。核心变更：

```python
def run(self) -> dict:
    """执行回测主循环，返回 metrics/equity_curve/trades。"""
    mode_desc = "signal_table" if self._signal_table is not None else "screener+trader"
    logger.info("开始运行回测, 模式: %s", mode_desc)

    broker = Broker(
        initial_capital=self._initial_capital,
        commission_rate=self._commission_rate,
        slippage=self._slippage,
    )

    ref_sym = self._all_symbols[0]
    ref_df = self._stock_data[ref_sym]
    n_bars = len(ref_df)

    equity_curve = []
    prev_closes: dict[str, float] = {}
    screener_cache: dict[int, list[str]] = {}
    prev_period_keys: dict[int, str] = {}

    # 累计目标池：信号/选股加入，seller 平仓时移除
    target_symbols: set[str] = set()

    for idx in range(n_bars):
        if idx % 10 == 0 or idx == n_bars - 1:
            self._report(idx + 1, n_bars, "回测中")

        current_bars = {}
        current_prices = {}
        for sym, df in self._stock_data.items():
            if idx < len(df):
                row = df.iloc[idx]
                current_bars[sym] = {
                    "open": row["open"],
                    "close": row["close"],
                    "high": row["high"],
                    "low": row["low"],
                }
                current_prices[sym] = row["close"]

        # T+1 成交
        if idx > 0:
            broker.fill_orders(ref_df.iloc[idx]["date"], current_bars, prev_closes)

        current_date = ref_df.iloc[idx]["date"]
        available_symbols = [s for s in self._all_symbols if s in current_bars]

        # --- 选股/信号逻辑: 确定本 bar 新增的股票 ---
        if self._signal_table is not None:
            today_signals = self._signal_table.get(current_date, [])
        elif self._screeners:
            # screener 动态筛选（带周期缓存）
            screener_sets: list[set[str]] = []
            for si, screener in enumerate(self._screeners):
                freq = getattr(screener, "frequency", "daily")
                pk = self._period_key(current_date, freq)
                need_run = (si not in prev_period_keys) or (pk != prev_period_keys[si])
                if need_run:
                    ctx = self._make_screener_ctx(screener, idx)
                    raw_result = screener.screen(ctx, list(available_symbols))
                    symbols = self._parse_screen_result(raw_result)
                    screener_cache[si] = list(symbols)
                    prev_period_keys[si] = pk
                screener_sets.append(set(screener_cache.get(si, [])))

            merged_set = screener_sets[0] if screener_sets else set(available_symbols)
            for i, jm in enumerate(self._join_modes):
                next_set = screener_sets[i + 1]
                if jm == "correlated":
                    merged_set = merged_set & next_set
                else:
                    merged_set = merged_set | next_set
            today_signals = [s for s in available_symbols if s in merged_set]
        else:
            today_signals = []

        # 计算新增：仅不在 target_symbols 中的才是新增
        new_symbols = [s for s in today_signals if s not in target_symbols]
        target_symbols.update(new_symbols)
        has_new = len(new_symbols) > 0

        # 回调：seller 平仓时从 target_symbols 移除
        def on_remove_target(sym: str):
            target_symbols.discard(sym)

        # --- Seller 先执行（每天都执行）---
        if self._seller:
            seller_ctx = TraderContext(
                stock_data=self._stock_data,
                current_idx=idx,
                portfolio=broker.portfolio,
                broker_submit=broker.submit_order,
                selected_symbols=list(target_symbols),
                target_symbols=list(target_symbols),
                new_symbols=new_symbols,
                on_remove_target=on_remove_target,
                weekly_data=self._weekly_data,
                monthly_data=self._monthly_data,
                valuation_data=self._valuation_data,
                dividend_data=self._dividend_data,
                financial_data=self._financial_data,
            )
            try:
                self._seller.on_bar(seller_ctx)
            except Exception as e:
                logger.warning("Seller 执行异常: date=%s, error=%s", current_date, e)

        # --- Buyer 后执行（仅在有新增时）---
        if has_new and self._buyer:
            buyer_ctx = TraderContext(
                stock_data=self._stock_data,
                current_idx=idx,
                portfolio=broker.portfolio,
                broker_submit=broker.submit_order,
                selected_symbols=list(target_symbols),
                target_symbols=list(target_symbols),
                new_symbols=new_symbols,
                on_remove_target=on_remove_target,
                weekly_data=self._weekly_data,
                monthly_data=self._monthly_data,
                valuation_data=self._valuation_data,
                dividend_data=self._dividend_data,
                financial_data=self._financial_data,
            )
            try:
                self._buyer.on_bar(buyer_ctx)
            except Exception as e:
                logger.warning("Buyer 执行异常: date=%s, error=%s", current_date, e)

        snap = broker.portfolio.snapshot(current_date, current_prices)
        equity_curve.append(snap)
        prev_closes = dict(current_prices)

    metrics = compute_metrics(equity_curve, broker.all_trades, self._initial_capital)

    logger.info(
        "回测完成: bars=%d, trades=%d, final_equity=%.2f",
        n_bars,
        len(broker.all_trades),
        equity_curve[-1]["total_value"] if equity_curve else 0,
    )

    return {
        "metrics": metrics,
        "equity_curve": equity_curve,
        "trades": broker.all_trades,
    }
```

- [ ] **Step 4: Run rebalance tests**

Run: `python -m pytest backend/tests/test_rebalance_logic.py -x -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest backend/tests/ -x -q`
Expected: All pass. 现有 test_buy_sell_engine.py 可能需要调整（旧语义是 `selected_symbols` 非空时 buyer 就被调用）。

- [ ] **Step 6: Fix any broken existing tests**

现有测试中 buyer 的调用条件已变（从 `selected_symbols 非空` 变为 `target_symbols 有新增`）。对于 signal_table 模式，只要信号表某天有信号且该 symbol 之前不在 target_symbols 中就会触发 buyer，语义基本兼容。检查 `test_buy_sell_engine.py` 和 `test_signal_table_integration.py`，如有 assertion 数量不对则调整。

- [ ] **Step 7: Commit**

```bash
git add backend/services/backtest/buy_sell_engine.py backend/tests/test_rebalance_logic.py
git commit -m "feat: BuySellEngine 实现 target_symbols 累计池和调仓执行顺序"
```

---

### Task 3: 修复现有测试适配新语义

**Files:**
- Modify: `backend/tests/test_buy_sell_engine.py`
- Modify: `backend/tests/test_signal_table_integration.py`
- Modify: `backend/tests/test_group_runner_buy_sell.py`

- [ ] **Step 1: Run existing buy_sell tests to identify failures**

Run: `python -m pytest backend/tests/test_buy_sell_engine.py backend/tests/test_signal_table_integration.py backend/tests/test_group_runner_buy_sell.py -v`

- [ ] **Step 2: Fix assertion mismatches**

主要变更点：
- 旧: buyer 在 `selected_symbols` 非空时每天都被调用
- 新: buyer 仅在 `target_symbols` 有新增时被调用（首次出现的 signal 才算新增）

对于 signal_table 模式，如果同一股票在多天出现信号，只有第一天算新增。调整测试中的 buyer 调用次数断言。

- [ ] **Step 3: Run full suite**

Run: `python -m pytest backend/tests/ -x -q`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add backend/tests/
git commit -m "fix: 更新现有测试适配 target_symbols 累计语义"
```

---

### Task 4: 更新 AGENTS.md

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: 更新 Discoveries 和 Accomplished 部分**

在 Discoveries 中添加调仓逻辑的关键设计决策。在 Accomplished 中标记完成。

- [ ] **Step 2: Commit**

```bash
git add AGENTS.md
git commit -m "docs: 更新 AGENTS.md 记录调仓逻辑实现"
```
