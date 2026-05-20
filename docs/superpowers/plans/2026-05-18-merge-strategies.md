# 5 策略合并 + 架构收敛 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 5 个独立策略合并为单一 `MaTangleValueStrategy`,同步重构基类、Engine、Context、数据访问层、数据库与前端,使整个回测系统收敛到「单一策略 = 单次回测」的模型。

**Architecture:** 单一 `Strategy` 基类(`screen / on_buy / on_sell`)+ 函数式 utils 库(按数据源分文件)+ DuckDB 唯一业务数据源(`adjust_factor` 视图实时算 qfq)+ 软删任务表 + 决策三层日志。

**Tech Stack:** Python 3 + FastAPI + DuckDB + pandas + pytest;前端 React 19 + TypeScript + Vite。

**Spec:** `docs/superpowers/specs/2026-05-18-merge-strategies-design.md` (D1-D8)

---

## Phase 概览

| Phase | 主题 | 大致 task 数 | 状态 |
|---|---|---|---|
| 1 | 新增 utils 库 + 新 `Strategy` 基类(additive,不动现有代码) | 9 | 待执行 |
| 2 | `MaTangleValueStrategy` + 决策日志(`DecisionLogSink`) | 5 | 待写 |
| 3 | 重写 Engine + Context | 6 | 待写 |
| 4 | DB 迁移 + 路由简化 + D8 数据访问统一(qfq_cache 删除) | 8 | 待写 |
| 5 | 前端 BacktestConfig API 收敛 + 历史列表软删 | 4 | 待写 |
| 6 | 删除 7 个旧策略 + 旧基类 + 旧引擎 + 旧路由 | 3 | 待写 |
| 7 | 决策日志查询面板(可选,后续迭代) | 1 | 留待 |

每个 Phase 结束跑 `python -m pytest backend/tests/ -x -q` + `cd frontend && npx tsc --noEmit && npm test`,全绿才进入下一阶段。

---

# Phase 1:utils 库 + 新 `Strategy` 基类(additive)

**Phase 1 目标**:
- 在 `backend/services/backtest/base.py` 中**新增** `Strategy` 类,与旧的 `ScreenerStrategy / TraderStrategy / BuyStrategy / SellStrategy` 并存
- 创建 `strategies/utils/` 包,包含 `kline / financial / dividend / valuation` 四个单源模块 + `composite/market_cap_weighted_batch_buyer.py` 状态类
- 所有 utils 用 **mock Context** 单测,真实 Context 在 Phase 3 才完成
- **不动**现有 engine、context、router、策略文件 — Phase 1 完全 additive,既有 550 测试集应保持全绿

**Phase 1 完成判据**:
- `python -m pytest backend/tests/ -x -q` 仍 550 个 case 全绿,新增 utils 单测全绿
- `from services.backtest.base import Strategy` 可成功导入
- `from strategies.utils import kline, financial, dividend, valuation` 可成功导入
- `from strategies.utils.composite.market_cap_weighted_batch_buyer import MarketCapWeightedBatchBuyer` 可成功导入

---

## Task 1.1:在 `base.py` 新增 `Strategy` 基类(与旧基类并存)

**Files:**
- Modify: `backend/services/backtest/base.py`(末尾追加,不动现有 4 个基类)
- Test: `backend/tests/test_strategy_new_base.py`(新建)

**设计要点**:
- 新 `Strategy` 类同时拥有 `screen / on_buy / on_sell` 三个钩子,默认实现:`screen → 返回输入 symbols`,`on_buy / on_sell → pass`
- `frequency: str = "daily"`(默认日线)
- `frequency_overridable: bool = False`(默认锁死,作者必须主动放开)
- `settings` 合并 default + 子类(逻辑同旧 `TraderStrategy`)
- 复用现有 `ParamAccessor`(已能处理 dict/原始值两种 override 格式)

- [ ] **Step 1:写测试 `test_strategy_new_base.py`**

```python
"""Strategy 新基类单测(Phase 1)。
旧的 ScreenerStrategy/TraderStrategy/BuyStrategy/SellStrategy 在本 Phase 仍并存,
本测试仅覆盖新增 Strategy 类。"""
import pytest
from services.backtest.base import Strategy


def test_default_screen_returns_input_symbols():
    s = Strategy()
    assert s.screen(ctx=None, symbols=["A", "B"]) == ["A", "B"]


def test_default_on_buy_and_on_sell_are_noop():
    s = Strategy()
    # 不抛异常即可
    s.on_buy(ctx=None)
    s.on_sell(ctx=None)


def test_default_frequency_is_daily_and_locked():
    assert Strategy.frequency == "daily"
    assert Strategy.frequency_overridable is False


def test_settings_merges_class_settings_with_defaults():
    class MyStrat(Strategy):
        settings = {"commission_rate": 0.001}

    s = MyStrat()
    assert s.settings["initial_capital"] == 1_000_000  # default
    assert s.settings["commission_rate"] == 0.001       # override
    assert s.settings["slippage"] == 0.002              # default


def test_param_overrides_via_p_accessor():
    class MyStrat(Strategy):
        params = {"min_x": {"default": 5, "type": "int"}}

    s = MyStrat(param_overrides={"min_x": 10})
    assert s.p.min_x == 10


def test_subclass_can_override_screen():
    class MyStrat(Strategy):
        def screen(self, ctx, symbols):
            return [s for s in symbols if s.startswith("0")]

    s = MyStrat()
    assert s.screen(None, ["000001", "600519"]) == ["000001"]


def test_legacy_classes_still_importable():
    """Phase 1 是 additive,旧基类必须仍可导入。"""
    from services.backtest.base import (
        ScreenerStrategy, TraderStrategy, BuyStrategy, SellStrategy
    )
    assert ScreenerStrategy is not None
    assert TraderStrategy is not None
    assert BuyStrategy is not None
    assert SellStrategy is not None
```

- [ ] **Step 2:跑测试确认失败**

```bash
python -m pytest backend/tests/test_strategy_new_base.py -v
```

预期:`ImportError: cannot import name 'Strategy' from 'services.backtest.base'`

- [ ] **Step 3:在 `base.py` 末尾追加 `Strategy` 类**

```python
# 在 base.py 现有 SellStrategy 之后追加(不动现有代码):


class Strategy(BaseStrategy):
    """统一策略基类(2026-05-18 重构)。

    替代 ScreenerStrategy / TraderStrategy / BuyStrategy / SellStrategy 四类拆分,
    一个 Strategy 同时拥有 screen / on_buy / on_sell 三个钩子。

    子类按需覆盖钩子;默认实现:
      - screen() → 返回全部输入 symbols(等价无筛选)
      - on_buy()  → pass(默认不买)
      - on_sell() → pass(默认永久持有)

    频率(frequency)语义见 spec D1.1:
      - frequency: "daily" | "weekly" | "monthly",指 screen() 调用节奏
      - frequency_overridable: 是否允许用户在 UI 改频率,默认 False(锁死)
    """
    strategy_type = "strategy"
    frequency: str = "daily"
    frequency_overridable: bool = False
    settings: dict = {}

    def __init__(self, param_overrides: dict = None):
        super().__init__(param_overrides)
        defaults = {
            "initial_capital": 1_000_000,
            "commission_rate": 0.0003,
            "slippage": 0.002,
        }
        self.settings = {**defaults, **self.__class__.settings}

    def screen(self, ctx, symbols: list[str]) -> list[str]:
        return list(symbols)

    def on_buy(self, ctx) -> None:
        pass

    def on_sell(self, ctx) -> None:
        pass
```

- [ ] **Step 4:跑测试确认通过 + 全量回归**

```bash
python -m pytest backend/tests/test_strategy_new_base.py -v
python -m pytest backend/tests/ -x -q
```

预期:新测试 7 个全过;旧测试 550 个全过(新基类不影响旧代码)。

- [ ] **Step 5:Commit**

```bash
git add backend/services/backtest/base.py backend/tests/test_strategy_new_base.py
git commit -m "feat(backtest): add unified Strategy base class alongside legacy classes (Phase 1.1)"
```

---

## Task 1.2:创建 utils 包 + `MockContext` 测试基础设施

**Files:**
- Create: `strategies/utils/__init__.py`(空文件,使其成为 package)
- Create: `strategies/utils/composite/__init__.py`(空文件)
- Create: `backend/tests/utils_test_helpers.py`(MockContext 类)
- Test: `backend/tests/test_utils_mock_context.py`(MockContext 自测)

**设计要点**:
- utils 函数和类全部接收 `ctx` 第一参数,通过 `ctx.get_dividend / get_financial / get_valuation / get_history / get_price / log_pass / log_reject / log_flow` 等接口取数和写日志
- Phase 3 的真实 Context 会实现这些接口;Phase 1 / 2 用 MockContext 单测
- MockContext 提供:可注入数据 dict、记录所有日志调用以便断言、计数器辅助 flow 验证
- `current_date / current_idx` 也作为属性可设置

- [ ] **Step 1:写 MockContext 自测 `test_utils_mock_context.py`**

```python
"""验证 MockContext 自身的语义,作为后续 utils 测试的基础设施。"""
import pandas as pd
from tests.utils_test_helpers import MockContext


def test_get_dividend_returns_injected_df():
    df = pd.DataFrame({"现金分红-现金分红比例": [3.62], "报告期": ["2023-12-31"]})
    ctx = MockContext(dividend={"000001.SZ": df})
    assert ctx.get_dividend("000001.SZ") is df
    assert ctx.get_dividend("999999.SZ") is None  # 未注入返回 None


def test_get_financial_returns_injected_dict():
    ctx = MockContext(financial={"000001.SZ": {"净资产收益率": 14.7}})
    assert ctx.get_financial("000001.SZ") == {"净资产收益率": 14.7}


def test_get_valuation_returns_injected_dict():
    ctx = MockContext(valuation={"000001.SZ": {"pe_ttm": 5.2, "pb": 0.7, "total_mv": 4.5e11}})
    val = ctx.get_valuation("000001.SZ")
    assert val["pe_ttm"] == 5.2


def test_get_history_returns_injected_list_capped_by_n():
    bars = [{"date": f"2024-{m:02d}-01", "close": 10.0 + m, "open": 10.0,
             "high": 11.0, "low": 9.0, "volume": 1000} for m in range(1, 13)]
    ctx = MockContext(history={"000001.SZ": bars})
    h = ctx.get_history("000001.SZ", 5)
    assert len(h) == 5
    assert h[-1]["date"] == "2024-12-01"  # 最后 5 根


def test_log_pass_records_calls():
    ctx = MockContext()
    ctx.log_pass("000001.SZ", "dividend.years", years=12)
    ctx.log_pass("000002.SZ", "dividend.years", years=8)
    assert len(ctx.pass_logs) == 2
    assert ctx.pass_logs[0] == ("000001.SZ", "dividend.years", {"years": 12})


def test_log_reject_records_calls():
    ctx = MockContext()
    ctx.log_reject("600519.SH", "dividend.years", reason="below_threshold", years=3)
    assert ctx.reject_logs[0] == (
        "600519.SH", "dividend.years", "below_threshold", {"years": 3}
    )


def test_log_flow_records_calls():
    ctx = MockContext()
    ctx.log_flow("dividend.years", input=4823, passed=421)
    assert ctx.flow_logs[0] == ("dividend.years", {"input": 4823, "passed": 421})


def test_current_date_and_idx_default():
    ctx = MockContext()
    assert ctx.current_date is None
    assert ctx.current_idx == 0


def test_current_date_can_be_set():
    ctx = MockContext(current_date="2024-03-29", current_idx=42)
    assert ctx.current_date == "2024-03-29"
    assert ctx.current_idx == 42
```

- [ ] **Step 2:跑测试确认失败**

```bash
python -m pytest backend/tests/test_utils_mock_context.py -v
```

预期:`ModuleNotFoundError: No module named 'tests.utils_test_helpers'`

- [ ] **Step 3:创建 `strategies/utils/__init__.py` 与 `strategies/utils/composite/__init__.py`**

两个都是空文件:

```bash
mkdir -p strategies/utils/composite
touch strategies/utils/__init__.py strategies/utils/composite/__init__.py
```

- [ ] **Step 4:创建 `backend/tests/utils_test_helpers.py`**

```python
"""utils 函数单测共用的 MockContext。

Phase 1 / 2 阶段真实 Context 尚未重写完(在 Phase 3),utils 函数测试通过此 mock 隔离。
真实 Context 接口见 spec § Context (D1 完成后逐步实现)。
"""
from typing import Any


class MockContext:
    """模拟 Context,提供 utils 函数所需的所有接口。"""

    def __init__(
        self,
        dividend: dict | None = None,
        financial: dict | None = None,
        valuation: dict | None = None,
        history: dict | None = None,
        price: dict | None = None,
        target_symbols: list | None = None,
        new_symbols: list | None = None,
        available_cash: float = 1_000_000.0,
        current_date: str | None = None,
        current_idx: int = 0,
    ):
        self._dividend = dividend or {}
        self._financial = financial or {}
        self._valuation = valuation or {}
        self._history = history or {}
        self._price = price or {}
        self.target_symbols = list(target_symbols or [])
        self.new_symbols = list(new_symbols or [])
        self.available_cash = available_cash
        self.current_date = current_date
        self.current_idx = current_idx

        # 日志记录(测试可断言)
        self.pass_logs: list[tuple[str, str, dict]] = []
        self.reject_logs: list[tuple[str, str, str, dict]] = []
        self.flow_logs: list[tuple[str, dict]] = []

        # 下单记录(测试可断言)
        self.orders: list[tuple[str, int]] = []

    # ===== 数据访问 =====
    def get_dividend(self, symbol: str):
        return self._dividend.get(symbol)

    def get_financial(self, symbol: str):
        return self._financial.get(symbol)

    def get_valuation(self, symbol: str):
        return self._valuation.get(symbol)

    def get_history(self, symbol: str, n: int):
        bars = self._history.get(symbol)
        if bars is None:
            return []
        return bars[-n:] if n > 0 else bars

    def get_price(self, symbol: str, period: str = "daily"):
        # price 注入格式:{symbol: {period: {"open": .., "close": ..}}}
        sym_data = self._price.get(symbol)
        if sym_data is None:
            return None
        return sym_data.get(period)

    # ===== 日志 =====
    def log_pass(self, symbol: str, stage: str, **values: Any) -> None:
        self.pass_logs.append((symbol, stage, dict(values)))

    def log_reject(self, symbol: str, stage: str, reason: str, **values: Any) -> None:
        self.reject_logs.append((symbol, stage, reason, dict(values)))

    def log_flow(self, stage: str, **counts: Any) -> None:
        self.flow_logs.append((stage, dict(counts)))

    # ===== 下单 =====
    def order_shares(self, symbol: str, shares: int) -> None:
        self.orders.append((symbol, shares))
```

- [ ] **Step 5:跑测试确认通过**

```bash
python -m pytest backend/tests/test_utils_mock_context.py -v
```

预期:9 个测试全过。

- [ ] **Step 6:Commit**

```bash
git add strategies/utils/__init__.py \
        strategies/utils/composite/__init__.py \
        backend/tests/utils_test_helpers.py \
        backend/tests/test_utils_mock_context.py
git commit -m "test(backtest): add MockContext infrastructure for utils unit tests (Phase 1.2)"
```

---

## Task 1.3:`strategies/utils/dividend.py`

**Files:**
- Create: `strategies/utils/dividend.py`
- Test: `backend/tests/test_utils_dividend.py`

**设计要点**:
- 迁移 `strategies/examples/dividend_years_screener.py` 的逻辑(40 行)到函数 `filter_by_dividend_years(ctx, symbols, *, min_years)`
- 抽出辅助函数 `count_dividend_years(ctx, symbol) -> int | None`,无数据返回 `None`
- 通过 `ctx.log_pass / log_reject / log_flow` 写日志(stage = `"dividend.years"`)
- 字段:`"现金分红-现金分红比例" > 0` 且按 `"报告期"` 前 4 字符聚合年份

- [ ] **Step 1:写测试 `test_utils_dividend.py`**

```python
import pandas as pd
import math
from tests.utils_test_helpers import MockContext
from strategies.utils import dividend


def _div_df(rows):
    """rows: list of (报告期, 现金分红-现金分红比例)"""
    return pd.DataFrame({
        "报告期": [r[0] for r in rows],
        "现金分红-现金分红比例": [r[1] for r in rows],
    })


def test_count_dividend_years_basic():
    df = _div_df([("2020-12-31", 3.0), ("2021-12-31", 2.5), ("2022-12-31", 1.8)])
    ctx = MockContext(dividend={"A": df})
    assert dividend.count_dividend_years(ctx, "A") == 3


def test_count_dividend_years_dedupes_same_year():
    df = _div_df([("2020-06-30", 1.0), ("2020-12-31", 2.0), ("2021-12-31", 1.5)])
    ctx = MockContext(dividend={"A": df})
    assert dividend.count_dividend_years(ctx, "A") == 2


def test_count_dividend_years_skips_zero_or_negative():
    df = _div_df([("2020-12-31", 0.0), ("2021-12-31", 2.5)])
    ctx = MockContext(dividend={"A": df})
    assert dividend.count_dividend_years(ctx, "A") == 1


def test_count_dividend_years_skips_nan():
    df = _div_df([("2020-12-31", float("nan")), ("2021-12-31", 2.5)])
    ctx = MockContext(dividend={"A": df})
    assert dividend.count_dividend_years(ctx, "A") == 1


def test_count_dividend_years_no_data_returns_none():
    ctx = MockContext()
    assert dividend.count_dividend_years(ctx, "A") is None


def test_count_dividend_years_missing_column_returns_none():
    df = pd.DataFrame({"报告期": ["2020-12-31"]})
    ctx = MockContext(dividend={"A": df})
    assert dividend.count_dividend_years(ctx, "A") is None


def test_filter_by_dividend_years_pass_and_reject():
    pass_df = _div_df([(f"{y}-12-31", 1.0) for y in range(2018, 2024)])  # 6 年
    fail_df = _div_df([(f"{y}-12-31", 1.0) for y in range(2022, 2024)])  # 2 年
    ctx = MockContext(dividend={"P": pass_df, "F": fail_df})

    result = dividend.filter_by_dividend_years(ctx, ["P", "F"], min_years=5)

    assert result == ["P"]
    assert ctx.pass_logs == [("P", "dividend.years", {"years": 6, "threshold": 5})]
    assert ctx.reject_logs == [
        ("F", "dividend.years", "below_threshold", {"years": 2, "threshold": 5})
    ]


def test_filter_by_dividend_years_no_data_rejects_with_reason_no_data():
    ctx = MockContext()  # 无注入
    result = dividend.filter_by_dividend_years(ctx, ["X"], min_years=5)
    assert result == []
    assert ctx.reject_logs == [
        ("X", "dividend.years", "no_data", {"threshold": 5})
    ]


def test_filter_by_dividend_years_logs_flow_summary():
    pass_df = _div_df([(f"{y}-12-31", 1.0) for y in range(2018, 2024)])
    ctx = MockContext(dividend={"P": pass_df})
    dividend.filter_by_dividend_years(ctx, ["P", "X"], min_years=5)
    assert ctx.flow_logs == [
        ("dividend.years", {"input": 2, "passed": 1})
    ]
```

- [ ] **Step 2:跑测试确认失败**

```bash
python -m pytest backend/tests/test_utils_dividend.py -v
```

预期:`ModuleNotFoundError` 或 `AttributeError: module 'strategies.utils.dividend' has no attribute ...`

- [ ] **Step 3:创建 `strategies/utils/dividend.py`**

```python
"""分红事件相关 utils 函数(单数据源:dividend)。

迁移自 strategies/examples/dividend_years_screener.py(2026-05-18 重构)。
"""
import math


def count_dividend_years(ctx, symbol: str) -> int | None:
    """统计该股票历史上有几个不同的年度发生过现金分红 (cash > 0)。

    无分红数据 / 缺少分红比例列 / 列全为 NaN/0 → 返回 None
    返回:有效分红年数(int)或 None
    """
    df = ctx.get_dividend(symbol)
    if df is None:
        return None
    col = "现金分红-现金分红比例"
    if col not in df.columns:
        return None

    years: set[str] = set()
    for idx, val in df[col].items():
        if not isinstance(val, (int, float)):
            continue
        if math.isnan(val) or val <= 0:
            continue
        report_date = str(df.loc[idx, "报告期"])
        if len(report_date) >= 4:
            years.add(report_date[:4])

    return len(years)


def filter_by_dividend_years(
    ctx, symbols: list[str], *, min_years: int = 5
) -> list[str]:
    """筛选累计现金分红年数 >= min_years 的股票。

    stage = "dividend.years"
    日志:
      log_pass(symbol, stage, years=N, threshold=min_years)
      log_reject(symbol, stage, "below_threshold", years=N, threshold=min_years)
      log_reject(symbol, stage, "no_data", threshold=min_years)
      log_flow(stage, input=len(symbols), passed=len(result))
    """
    stage = "dividend.years"
    result: list[str] = []
    for sym in symbols:
        years = count_dividend_years(ctx, sym)
        if years is None:
            ctx.log_reject(sym, stage, "no_data", threshold=min_years)
            continue
        if years >= min_years:
            ctx.log_pass(sym, stage, years=years, threshold=min_years)
            result.append(sym)
        else:
            ctx.log_reject(sym, stage, "below_threshold", years=years, threshold=min_years)
    ctx.log_flow(stage, input=len(symbols), passed=len(result))
    return result
```

- [ ] **Step 4:跑测试确认通过**

```bash
python -m pytest backend/tests/test_utils_dividend.py -v
```

预期:9 个全过。

- [ ] **Step 5:Commit**

```bash
git add strategies/utils/dividend.py backend/tests/test_utils_dividend.py
git commit -m "feat(utils): dividend.filter_by_dividend_years + count_dividend_years (Phase 1.3)"
```

---

## Task 1.4:`strategies/utils/financial.py`

**Files:**
- Create: `strategies/utils/financial.py`
- Test: `backend/tests/test_utils_financial.py`

**设计要点**:
- 迁移 `strategies/examples/roe_screener.py` 逻辑(35 行)
- 主函数 `filter_by_roe(ctx, symbols, *, min_roe)`,辅助 getter `get_roe / get_eps / get_net_profit_growth`
- `ctx.get_financial(sym)` 返回 dict 或 None;字段名沿用现有数据中文列(`"净资产收益率"`,`"基本每股收益"`,`"净利润同比增长率"`)
- stage = `"financial.roe"`

- [ ] **Step 1:写测试 `test_utils_financial.py`**

```python
from tests.utils_test_helpers import MockContext
from strategies.utils import financial


def test_get_roe_returns_value():
    ctx = MockContext(financial={"A": {"净资产收益率": 14.7}})
    assert financial.get_roe(ctx, "A") == 14.7


def test_get_roe_returns_none_when_missing_data():
    ctx = MockContext()
    assert financial.get_roe(ctx, "A") is None


def test_get_roe_returns_none_when_field_missing():
    ctx = MockContext(financial={"A": {"基本每股收益": 1.2}})
    assert financial.get_roe(ctx, "A") is None


def test_get_eps_basic():
    ctx = MockContext(financial={"A": {"基本每股收益": 1.2}})
    assert financial.get_eps(ctx, "A") == 1.2


def test_get_net_profit_growth_basic():
    ctx = MockContext(financial={"A": {"净利润同比增长率": 25.4}})
    assert financial.get_net_profit_growth(ctx, "A") == 25.4


def test_filter_by_roe_pass_and_reject():
    ctx = MockContext(financial={
        "P": {"净资产收益率": 14.7},
        "F": {"净资产收益率": 8.4},
    })
    result = financial.filter_by_roe(ctx, ["P", "F"], min_roe=10.0)
    assert result == ["P"]
    assert ctx.pass_logs == [("P", "financial.roe", {"roe": 14.7, "threshold": 10.0})]
    assert ctx.reject_logs == [
        ("F", "financial.roe", "below_threshold", {"roe": 8.4, "threshold": 10.0})
    ]


def test_filter_by_roe_no_data():
    ctx = MockContext()
    result = financial.filter_by_roe(ctx, ["X"], min_roe=10.0)
    assert result == []
    assert ctx.reject_logs == [("X", "financial.roe", "no_data", {"threshold": 10.0})]


def test_filter_by_roe_field_missing():
    ctx = MockContext(financial={"X": {"基本每股收益": 1.2}})
    result = financial.filter_by_roe(ctx, ["X"], min_roe=10.0)
    assert result == []
    assert ctx.reject_logs == [
        ("X", "financial.roe", "no_data", {"threshold": 10.0})
    ]


def test_filter_by_roe_logs_flow_summary():
    ctx = MockContext(financial={"P": {"净资产收益率": 14.7}})
    financial.filter_by_roe(ctx, ["P", "X"], min_roe=10.0)
    assert ctx.flow_logs == [("financial.roe", {"input": 2, "passed": 1})]
```

- [ ] **Step 2:跑测试确认失败**

```bash
python -m pytest backend/tests/test_utils_financial.py -v
```

- [ ] **Step 3:创建 `strategies/utils/financial.py`**

```python
"""财务三表 + 指标相关 utils 函数(单数据源:financial)。

迁移自 strategies/examples/roe_screener.py(2026-05-18 重构)。
"""


def _get_field(ctx, symbol: str, field: str):
    fin = ctx.get_financial(symbol)
    if fin is None:
        return None
    return fin.get(field)


def get_roe(ctx, symbol: str) -> float | None:
    """净资产收益率(%)。"""
    return _get_field(ctx, symbol, "净资产收益率")


def get_eps(ctx, symbol: str) -> float | None:
    """基本每股收益。"""
    return _get_field(ctx, symbol, "基本每股收益")


def get_net_profit_growth(ctx, symbol: str) -> float | None:
    """净利润同比增长率(%)。"""
    return _get_field(ctx, symbol, "净利润同比增长率")


def filter_by_roe(
    ctx, symbols: list[str], *, min_roe: float = 10.0
) -> list[str]:
    """筛选 ROE >= min_roe 的股票。

    stage = "financial.roe"
    """
    stage = "financial.roe"
    result: list[str] = []
    for sym in symbols:
        roe = get_roe(ctx, sym)
        if roe is None:
            ctx.log_reject(sym, stage, "no_data", threshold=min_roe)
            continue
        if roe >= min_roe:
            ctx.log_pass(sym, stage, roe=roe, threshold=min_roe)
            result.append(sym)
        else:
            ctx.log_reject(sym, stage, "below_threshold", roe=roe, threshold=min_roe)
    ctx.log_flow(stage, input=len(symbols), passed=len(result))
    return result
```

- [ ] **Step 4:跑测试确认通过**

```bash
python -m pytest backend/tests/test_utils_financial.py -v
```

- [ ] **Step 5:Commit**

```bash
git add strategies/utils/financial.py backend/tests/test_utils_financial.py
git commit -m "feat(utils): financial.filter_by_roe + getters (Phase 1.4)"
```

---

## Task 1.5:`strategies/utils/valuation.py`

**Files:**
- Create: `strategies/utils/valuation.py`
- Test: `backend/tests/test_utils_valuation.py`

**设计要点**:
- 迁移 `strategies/examples/pe_pb_product_screener.py`(38 行)
- 主函数 `filter_by_pe_pb_product(ctx, symbols, *, min_value, max_value)`
- 辅助:`get_pe / get_pb / get_total_mv`
- `ctx.get_valuation(sym)` 返回 dict 或 None;字段:`"pe_ttm"`, `"pb"`, `"total_mv"`
- stage = `"valuation.pe_pb_product"`

- [ ] **Step 1:写测试 `test_utils_valuation.py`**

```python
from tests.utils_test_helpers import MockContext
from strategies.utils import valuation


def test_get_pe_returns_value():
    ctx = MockContext(valuation={"A": {"pe_ttm": 5.2, "pb": 0.7, "total_mv": 4.5e11}})
    assert valuation.get_pe(ctx, "A") == 5.2


def test_get_pb_returns_value():
    ctx = MockContext(valuation={"A": {"pe_ttm": 5.2, "pb": 0.7}})
    assert valuation.get_pb(ctx, "A") == 0.7


def test_get_total_mv_returns_value():
    ctx = MockContext(valuation={"A": {"total_mv": 4.5e11}})
    assert valuation.get_total_mv(ctx, "A") == 4.5e11


def test_get_pe_no_data_returns_none():
    ctx = MockContext()
    assert valuation.get_pe(ctx, "A") is None


def test_filter_by_pe_pb_product_in_range():
    ctx = MockContext(valuation={
        "P": {"pe_ttm": 4.0, "pb": 1.5},   # product=6.0  in [0, 22]
        "F": {"pe_ttm": 30.0, "pb": 5.0},  # product=150  out
    })
    result = valuation.filter_by_pe_pb_product(
        ctx, ["P", "F"], min_value=0.0, max_value=22.0
    )
    assert result == ["P"]
    assert ctx.pass_logs == [
        ("P", "valuation.pe_pb_product",
         {"pe": 4.0, "pb": 1.5, "product": 6.0, "min": 0.0, "max": 22.0})
    ]
    assert ctx.reject_logs == [
        ("F", "valuation.pe_pb_product", "above_max",
         {"pe": 30.0, "pb": 5.0, "product": 150.0, "min": 0.0, "max": 22.0})
    ]


def test_filter_by_pe_pb_product_below_min():
    ctx = MockContext(valuation={"X": {"pe_ttm": 1.0, "pb": 0.5}})  # product=0.5
    result = valuation.filter_by_pe_pb_product(
        ctx, ["X"], min_value=1.0, max_value=22.0
    )
    assert result == []
    assert ctx.reject_logs[0][2] == "below_min"


def test_filter_by_pe_pb_product_no_data():
    ctx = MockContext()
    result = valuation.filter_by_pe_pb_product(ctx, ["X"], min_value=0.0, max_value=22.0)
    assert result == []
    assert ctx.reject_logs == [
        ("X", "valuation.pe_pb_product", "no_data", {"min": 0.0, "max": 22.0})
    ]


def test_filter_by_pe_pb_product_missing_pe_or_pb():
    ctx = MockContext(valuation={"X": {"pe_ttm": 5.0}})  # 缺 pb
    result = valuation.filter_by_pe_pb_product(ctx, ["X"], min_value=0.0, max_value=22.0)
    assert result == []
    assert ctx.reject_logs[0][2] == "no_data"


def test_filter_by_pe_pb_product_logs_flow():
    ctx = MockContext(valuation={"P": {"pe_ttm": 4.0, "pb": 1.5}})
    valuation.filter_by_pe_pb_product(ctx, ["P", "X"], min_value=0.0, max_value=22.0)
    assert ctx.flow_logs == [
        ("valuation.pe_pb_product", {"input": 2, "passed": 1})
    ]
```

- [ ] **Step 2:跑测试确认失败**

```bash
python -m pytest backend/tests/test_utils_valuation.py -v
```

- [ ] **Step 3:创建 `strategies/utils/valuation.py`**

```python
"""估值数据相关 utils 函数(单数据源:valuation)。

迁移自 strategies/examples/pe_pb_product_screener.py(2026-05-18 重构)。
"""


def _get_field(ctx, symbol: str, field: str):
    val = ctx.get_valuation(symbol)
    if val is None:
        return None
    return val.get(field)


def get_pe(ctx, symbol: str) -> float | None:
    """PE(TTM)。"""
    return _get_field(ctx, symbol, "pe_ttm")


def get_pb(ctx, symbol: str) -> float | None:
    """PB。"""
    return _get_field(ctx, symbol, "pb")


def get_total_mv(ctx, symbol: str) -> float | None:
    """总市值(单位:元)。"""
    return _get_field(ctx, symbol, "total_mv")


def filter_by_pe_pb_product(
    ctx, symbols: list[str], *,
    min_value: float = 0.0, max_value: float = 22.0,
) -> list[str]:
    """筛选 PE(TTM) * PB ∈ [min_value, max_value] 的股票。

    stage = "valuation.pe_pb_product"
    reject reason: "no_data" | "below_min" | "above_max"
    """
    stage = "valuation.pe_pb_product"
    result: list[str] = []
    for sym in symbols:
        pe = get_pe(ctx, sym)
        pb = get_pb(ctx, sym)
        if pe is None or pb is None:
            ctx.log_reject(sym, stage, "no_data", min=min_value, max=max_value)
            continue
        product = pe * pb
        if product < min_value:
            ctx.log_reject(sym, stage, "below_min",
                           pe=pe, pb=pb, product=product,
                           min=min_value, max=max_value)
        elif product > max_value:
            ctx.log_reject(sym, stage, "above_max",
                           pe=pe, pb=pb, product=product,
                           min=min_value, max=max_value)
        else:
            ctx.log_pass(sym, stage,
                         pe=pe, pb=pb, product=product,
                         min=min_value, max=max_value)
            result.append(sym)
    ctx.log_flow(stage, input=len(symbols), passed=len(result))
    return result
```

- [ ] **Step 4:跑测试确认通过**

```bash
python -m pytest backend/tests/test_utils_valuation.py -v
```

- [ ] **Step 5:Commit**

```bash
git add strategies/utils/valuation.py backend/tests/test_utils_valuation.py
git commit -m "feat(utils): valuation.filter_by_pe_pb_product + getters (Phase 1.5)"
```

---

## Task 1.6:`strategies/utils/kline.py` — getters (`get_ma` / `get_macd`)

**Files:**
- Create: `strategies/utils/kline.py`(本任务先建文件 + getter,后续 task 追加形态函数)
- Test: `backend/tests/test_utils_kline_getters.py`

**设计要点**:
- 纯计算 getter,**不打日志**(spec L440 注:"通用辅助(纯计算,不打日志)")
- `get_ma(ctx, symbol, window, *, freq="daily") -> float | None`:取最近 `window` 根 close 平均
- `get_macd(ctx, symbol, field="dif", *, freq="daily") -> float | None`:返回 `dif / dea / hist`
  - 计算公式:`EMA(close, 12) - EMA(close, 26)` = DIF;`EMA(DIF, 9)` = DEA;`hist = 2 * (DIF - DEA)`(spec 强调 MACD bar = 2×(DIF-DEA))
- 数据不足 → None
- `freq` 参数本 task 仅传给 `ctx.get_history(symbol, n, period=freq)`,**Phase 1 mock 不区分 period**(MockContext 接收但不切换);真实 Context 在 Phase 3 实现

**先扩展 MockContext 支持 period 参数**(向后兼容):

- [ ] **Step 1:扩展 `MockContext.get_history` 接受 period 参数**

修改 `backend/tests/utils_test_helpers.py`(在现有 `get_history` 基础上加 `period` 参数,行为不变):

```python
    def get_history(self, symbol: str, n: int, period: str = "daily"):
        # period 在 mock 中不切换数据源,留接口给真实 ctx 实现。
        # 测试如需区分 period,可注入 history={"A__weekly": [...], "A__daily": [...]}
        # 并按 f"{symbol}__{period}" 查找(本 mock 简化处理:优先 symbol__period,fallback symbol)
        keyed = self._history.get(f"{symbol}__{period}")
        if keyed is not None:
            bars = keyed
        else:
            bars = self._history.get(symbol)
        if bars is None:
            return []
        return bars[-n:] if n > 0 else bars
```

- [ ] **Step 2:写测试 `test_utils_kline_getters.py`**

```python
import math
from tests.utils_test_helpers import MockContext
from strategies.utils import kline


def _bars(closes, opens=None, highs=None, lows=None, vols=None):
    n = len(closes)
    return [
        {
            "date": f"2024-{i+1:02d}-01",
            "open": (opens[i] if opens else closes[i]),
            "close": closes[i],
            "high": (highs[i] if highs else max(closes[i], (opens[i] if opens else closes[i]))),
            "low": (lows[i] if lows else min(closes[i], (opens[i] if opens else closes[i]))),
            "volume": (vols[i] if vols else 1000),
        }
        for i in range(n)
    ]


def test_get_ma_basic():
    ctx = MockContext(history={"A": _bars([10, 11, 12, 13, 14])})
    # MA5 = (10+11+12+13+14)/5 = 12
    assert kline.get_ma(ctx, "A", window=5) == 12.0


def test_get_ma_insufficient_data_returns_none():
    ctx = MockContext(history={"A": _bars([10, 11])})
    assert kline.get_ma(ctx, "A", window=5) is None


def test_get_ma_no_history_returns_none():
    ctx = MockContext()
    assert kline.get_ma(ctx, "A", window=5) is None


def test_get_ma_uses_last_n_only():
    """如果有 10 根 bar,MA5 应只用最后 5 根。"""
    ctx = MockContext(history={"A": _bars([1, 2, 3, 4, 5, 10, 11, 12, 13, 14])})
    assert kline.get_ma(ctx, "A", window=5) == 12.0


def test_get_macd_dif_basic():
    """足够数据时 dif 应为有限数(具体值用宽松断言)。"""
    closes = [10 + 0.1 * i for i in range(40)]
    ctx = MockContext(history={"A": _bars(closes)})
    dif = kline.get_macd(ctx, "A", field="dif")
    assert dif is not None and not math.isnan(dif)


def test_get_macd_hist_equals_2x_dif_minus_dea():
    closes = [10 + 0.1 * i for i in range(40)]
    ctx = MockContext(history={"A": _bars(closes)})
    dif = kline.get_macd(ctx, "A", field="dif")
    dea = kline.get_macd(ctx, "A", field="dea")
    hist = kline.get_macd(ctx, "A", field="hist")
    assert abs(hist - 2 * (dif - dea)) < 1e-9


def test_get_macd_insufficient_data_returns_none():
    """少于 26 根 bar(慢线周期)→ None。"""
    closes = [10, 11, 12]
    ctx = MockContext(history={"A": _bars(closes)})
    assert kline.get_macd(ctx, "A", field="dif") is None


def test_get_macd_invalid_field_raises():
    closes = [10 + 0.1 * i for i in range(40)]
    ctx = MockContext(history={"A": _bars(closes)})
    import pytest
    with pytest.raises(ValueError, match="field"):
        kline.get_macd(ctx, "A", field="bogus")


def test_get_ma_freq_param_routes_to_period_history():
    """freq=monthly 应通过 ctx.get_history 拿到 monthly 数据。"""
    daily_bars = _bars([1, 2, 3, 4, 5])
    monthly_bars = _bars([100, 110, 120, 130, 140])
    ctx = MockContext(history={"A": daily_bars, "A__monthly": monthly_bars})
    assert kline.get_ma(ctx, "A", window=5, freq="monthly") == 120.0
    assert kline.get_ma(ctx, "A", window=5, freq="daily") == 3.0
```

- [ ] **Step 3:跑测试确认失败**

```bash
python -m pytest backend/tests/test_utils_kline_getters.py -v
```

- [ ] **Step 4:创建 `strategies/utils/kline.py` 含 getters**

```python
"""K 线相关 utils 函数(单数据源:kline)。

包含:
  - 纯计算 getter: get_ma / get_macd  (不打日志)
  - 形态检测函数: detect_ma_tangle_breakout / is_at_history_low /
                has_consecutive_red_bars  (打日志,见后续 task)

迁移自 strategies/examples/{ma_tangle_breakout,monthly_low,monthly_volume_red}_screener.py
(2026-05-18 重构)。
"""
import math


def get_ma(ctx, symbol: str, window: int, *, freq: str = "daily") -> float | None:
    """最近 window 根 K 线 close 的简单移动平均。

    数据不足 → None。freq 决定从何种周期取数据。
    """
    bars = ctx.get_history(symbol, window, period=freq)
    if not bars or len(bars) < window:
        return None
    return sum(b["close"] for b in bars[-window:]) / window


def _ema(values: list[float], window: int) -> list[float]:
    """指数移动平均(标准公式 alpha = 2/(N+1))。

    返回与输入等长的列表;前 window-1 个位置用 SMA 初始化为同值,
    第 window 个起按 EMA 递推。
    """
    if len(values) < window:
        return []
    alpha = 2.0 / (window + 1)
    out: list[float] = []
    sma = sum(values[:window]) / window
    out.extend([sma] * window)
    for v in values[window:]:
        out.append(out[-1] + alpha * (v - out[-1]))
    return out


def get_macd(
    ctx, symbol: str, field: str = "dif", *,
    fast: int = 12, slow: int = 26, signal: int = 9,
    freq: str = "daily",
) -> float | None:
    """MACD 三个分量之一。

    field: "dif" | "dea" | "hist"
    hist = 2 * (DIF - DEA)  (项目约定,与通达信一致)
    数据不足(< slow + signal)→ None。
    """
    if field not in {"dif", "dea", "hist"}:
        raise ValueError(f"field must be 'dif'/'dea'/'hist', got {field!r}")

    need = slow + signal
    bars = ctx.get_history(symbol, need + 1, period=freq)
    if not bars or len(bars) < slow:
        return None

    closes = [b["close"] for b in bars]
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    if not ema_fast or not ema_slow:
        return None

    # 对齐到较短的列表(取 slow 之后才有有效 DIF)
    aligned_len = min(len(ema_fast), len(ema_slow))
    dif_series = [ema_fast[-aligned_len + i] - ema_slow[-aligned_len + i]
                  for i in range(aligned_len)]
    if field == "dif":
        return dif_series[-1]

    dea_series = _ema(dif_series, signal)
    if not dea_series:
        return None
    if field == "dea":
        return dea_series[-1]

    # hist
    return 2.0 * (dif_series[-1] - dea_series[-1])
```

- [ ] **Step 5:跑测试确认通过**

```bash
python -m pytest backend/tests/test_utils_kline_getters.py -v
```

- [ ] **Step 6:Commit**

```bash
git add strategies/utils/kline.py \
        backend/tests/test_utils_kline_getters.py \
        backend/tests/utils_test_helpers.py
git commit -m "feat(utils): kline.get_ma + get_macd (Phase 1.6)"
```

---

## Task 1.7:`kline.is_at_history_low` + `kline.has_consecutive_red_bars`

**Files:**
- Modify: `strategies/utils/kline.py`(追加两个函数)
- Test: `backend/tests/test_utils_kline_history.py`

**设计要点**:
- `is_at_history_low(ctx, symbol, *, years=3, range_pct=20.0, freq="monthly") -> bool`
  迁移自 `monthly_low_screener.py`:`current_low <= min(past_lookback_lows) * (1 + range_pct/100)`
  lookback = `years * 12`(monthly)、`years * 52`(weekly)、`years * 250`(daily)
- `has_consecutive_red_bars(ctx, symbol, *, n=4, freq="monthly") -> bool`
  迁移自 `monthly_volume_red_screener.py`:最近 n 根 K 线 `close >= open`
- 都打日志,stage 分别为 `"kline.history_low"` 和 `"kline.consecutive_red"`

- [ ] **Step 1:写测试 `test_utils_kline_history.py`**

```python
from tests.utils_test_helpers import MockContext
from strategies.utils import kline


def _bar(date, open_, close, low=None, high=None, volume=1000):
    return {
        "date": date, "open": open_, "close": close,
        "low": low if low is not None else min(open_, close),
        "high": high if high is not None else max(open_, close),
        "volume": volume,
    }


# ===== is_at_history_low =====

def test_is_at_history_low_within_range_passes():
    """current_low=10.5,过去 36 月最低=10.0,range_pct=20% → 阈值=12.0,通过。"""
    bars = [_bar(f"2021-{m:02d}", 20, 21, low=20) for m in range(1, 13)]  # 12 月
    bars += [_bar(f"2022-{m:02d}", 15, 16, low=10) for m in range(1, 13)]  # 12 月,low=10
    bars += [_bar(f"2023-{m:02d}", 12, 13, low=12) for m in range(1, 13)]  # 12 月
    bars += [_bar("2024-01", 11, 12, low=10.5)]  # current

    ctx = MockContext(history={"A__monthly": bars})
    assert kline.is_at_history_low(ctx, "A", years=3, range_pct=20.0, freq="monthly") is True
    # 日志:pass
    assert ctx.pass_logs and ctx.pass_logs[0][1] == "kline.history_low"


def test_is_at_history_low_above_range_fails():
    """current_low=15,过去 36 月最低=10,阈值=12 → 15 > 12,不通过。"""
    bars = [_bar(f"2021-{m:02d}", 20, 21, low=20) for m in range(1, 13)]
    bars += [_bar(f"2022-{m:02d}", 15, 16, low=10) for m in range(1, 13)]
    bars += [_bar(f"2023-{m:02d}", 12, 13, low=12) for m in range(1, 13)]
    bars += [_bar("2024-01", 16, 17, low=15)]

    ctx = MockContext(history={"A__monthly": bars})
    assert kline.is_at_history_low(ctx, "A", years=3, range_pct=20.0, freq="monthly") is False
    assert ctx.reject_logs and ctx.reject_logs[0][2] == "above_threshold"


def test_is_at_history_low_insufficient_history():
    bars = [_bar(f"2024-{m:02d}", 10, 11, low=10) for m in range(1, 6)]  # 仅 5 月
    ctx = MockContext(history={"A__monthly": bars})
    assert kline.is_at_history_low(ctx, "A", years=3, range_pct=20.0, freq="monthly") is False
    assert ctx.reject_logs and ctx.reject_logs[0][2] == "no_data"


# ===== has_consecutive_red_bars =====

def test_has_consecutive_red_bars_all_red():
    bars = [_bar(f"2024-{m:02d}", 10, 11) for m in range(1, 5)]  # 4 个阳线
    ctx = MockContext(history={"A__monthly": bars})
    assert kline.has_consecutive_red_bars(ctx, "A", n=4, freq="monthly") is True
    assert ctx.pass_logs and ctx.pass_logs[0][1] == "kline.consecutive_red"


def test_has_consecutive_red_bars_one_green_breaks():
    bars = [
        _bar("2024-01", 10, 11),  # 阳
        _bar("2024-02", 11, 10),  # 阴 ← 中断
        _bar("2024-03", 10, 12),  # 阳
        _bar("2024-04", 12, 13),  # 阳
    ]
    ctx = MockContext(history={"A__monthly": bars})
    assert kline.has_consecutive_red_bars(ctx, "A", n=4, freq="monthly") is False
    assert ctx.reject_logs and ctx.reject_logs[0][2] == "not_all_red"


def test_has_consecutive_red_bars_close_equal_open_counts_as_red():
    """spec: close >= open 算阳(MACD/月线红柱定义一致)。"""
    bars = [_bar("2024-01", 10, 10) for _ in range(4)]  # 平盘 = 阳
    ctx = MockContext(history={"A__monthly": bars})
    assert kline.has_consecutive_red_bars(ctx, "A", n=4, freq="monthly") is True


def test_has_consecutive_red_bars_insufficient_data():
    bars = [_bar("2024-01", 10, 11), _bar("2024-02", 11, 12)]
    ctx = MockContext(history={"A__monthly": bars})
    assert kline.has_consecutive_red_bars(ctx, "A", n=4, freq="monthly") is False
    assert ctx.reject_logs and ctx.reject_logs[0][2] == "no_data"
```

- [ ] **Step 2:跑测试确认失败**

```bash
python -m pytest backend/tests/test_utils_kline_history.py -v
```

- [ ] **Step 3:在 `strategies/utils/kline.py` 末尾追加两个函数**

```python
def is_at_history_low(
    ctx, symbol: str, *,
    years: int = 3, range_pct: float = 20.0,
    freq: str = "monthly",
) -> bool:
    """当月 low 是否处于过去 N 年同周期最低 low 的 (1 + range_pct%) 范围内。

    迁移自 MonthlyLowScreener。
    stage = "kline.history_low"
    lookback bar 数:monthly→12*years, weekly→52*years, daily→250*years
    """
    stage = "kline.history_low"
    bars_per_year = {"monthly": 12, "weekly": 52, "daily": 250}.get(freq, 12)
    lookback = years * bars_per_year

    bars = ctx.get_history(symbol, lookback + 1, period=freq)
    if not bars or len(bars) < lookback + 1:
        ctx.log_reject(symbol, stage, "no_data",
                       have=len(bars) if bars else 0, need=lookback + 1)
        return False

    range_ratio = 1.0 + range_pct / 100.0
    current_low = bars[-1]["low"]
    past_lows = [b["low"] for b in bars[-(lookback + 1):-1]]
    hist_min = min(past_lows)
    threshold = hist_min * range_ratio

    if current_low <= threshold:
        ctx.log_pass(symbol, stage,
                     current_low=current_low, hist_min=hist_min,
                     threshold=threshold, range_pct=range_pct)
        return True
    ctx.log_reject(symbol, stage, "above_threshold",
                   current_low=current_low, hist_min=hist_min,
                   threshold=threshold, range_pct=range_pct)
    return False


def has_consecutive_red_bars(
    ctx, symbol: str, *,
    n: int = 4, freq: str = "monthly",
) -> bool:
    """最近 n 根 K 线全部满足 close >= open(阳线/平收)。

    迁移自 MonthlyVolumeRedScreener。
    stage = "kline.consecutive_red"
    """
    stage = "kline.consecutive_red"
    bars = ctx.get_history(symbol, n, period=freq)
    if not bars or len(bars) < n:
        ctx.log_reject(symbol, stage, "no_data",
                       have=len(bars) if bars else 0, need=n)
        return False

    recent = bars[-n:]
    if all(b["close"] >= b["open"] for b in recent):
        ctx.log_pass(symbol, stage, n=n)
        return True
    ctx.log_reject(symbol, stage, "not_all_red", n=n)
    return False
```

- [ ] **Step 4:跑测试确认通过**

```bash
python -m pytest backend/tests/test_utils_kline_history.py -v
```

- [ ] **Step 5:Commit**

```bash
git add strategies/utils/kline.py backend/tests/test_utils_kline_history.py
git commit -m "feat(utils): kline.is_at_history_low + has_consecutive_red_bars (Phase 1.7)"
```

---

## Task 1.8:`kline.detect_ma_tangle_breakout`(最复杂)

**Files:**
- Modify: `strategies/utils/kline.py`(追加 `detect_ma_tangle_breakout` + 私有辅助)
- Test: `backend/tests/test_utils_kline_ma_tangle.py`

**设计要点**:
- 完整迁移 `MaTangleBreakoutScreener.screen` 内层逻辑(spec L411-L424)
- 函数签名:
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
  ```
- 旧策略返回 `[{"symbol":..., "match_date":...}]` 列表;新版只返回 `bool`(当前 bar 是否完成突破)。`match_date` 不再需要,因为 spec D2 取消 chain backtest 概念,Engine 只关心当前 bar 是否信号
- 三段判定:① N 月 MA 缠绕 → ② M 月 MA 发散(MA5>MA10>MA20)→ ③ 期间内 vol_red_bars 连续阳线
- 使用 `pandas` 计算 MA(沿用旧实现,clean)
- 旧实现里有 `match_date / skip_until` 逻辑用于"找到最近一次匹配",新版**只在最后一根 bar 看是否有刚完成的突破**;Engine 在每个月切换调用一次,所以只关心当前 bar 是否在某次突破的"阳线段"内
- stage = `"kline.ma_tangle"`

**与旧实现的语义对齐**:
- 旧版输出 `match_date` 用于链式回测(已废)
- 新版语义:对当前 bar 调用,若**最近一次缠绕→发散→连续阳线**事件的"阳线段"覆盖到当前 bar(或紧邻当前 bar 之前刚完成),则返回 True
- 简化实现:逐月扫,找到最后一个满足全部条件的 `tangle_end`,若其对应的 `spread_window_end - 1 == n - 1`(最后一根 bar 在窗口末)则返回 True

**注**:此函数较复杂,测试覆盖以"明显应通过/明显应不通过/缠绕但未发散/发散但无连续阳线"四类边界为主;数值精度对齐由后续 Phase 6 的回归测保证(用 `MaTangleBreakoutScreener` ground truth)。

- [ ] **Step 1:写测试 `test_utils_kline_ma_tangle.py`**

```python
"""detect_ma_tangle_breakout 单测。

数值精度对齐 vs 旧 MaTangleBreakoutScreener 在 Phase 6 回归测覆盖,本 task 仅验证结构性正确。
"""
import pandas as pd
from tests.utils_test_helpers import MockContext
from strategies.utils import kline


def _bars_from_closes(closes, opens=None, vols=None):
    n = len(closes)
    return [
        {
            "date": f"2024-{i+1:02d}-01" if i < 12 else f"2025-{(i-11):02d}-01",
            "open": (opens[i] if opens else closes[i]),
            "close": closes[i],
            "high": max(closes[i], (opens[i] if opens else closes[i])),
            "low": min(closes[i], (opens[i] if opens else closes[i])),
            "volume": (vols[i] if vols else 1000),
        }
        for i in range(n)
    ]


def test_detect_ma_tangle_breakout_no_data_returns_false():
    ctx = MockContext()
    assert kline.detect_ma_tangle_breakout(ctx, "X", freq="monthly") is False
    assert ctx.reject_logs and ctx.reject_logs[0][2] == "no_data"


def test_detect_ma_tangle_breakout_insufficient_history():
    bars = _bars_from_closes([10] * 10)  # < slow + tangle_months + 1 = 23
    ctx = MockContext(history={"A__monthly": bars})
    assert kline.detect_ma_tangle_breakout(
        ctx, "A", slow=20, tangle_months=2, freq="monthly"
    ) is False
    assert ctx.reject_logs and ctx.reject_logs[0][2] == "insufficient_history"


def test_detect_ma_tangle_breakout_flat_then_uptrend_signal():
    """构造:前 25 月横盘价格 ≈ 10(MA 缠绕)→ 后 6 月持续上涨(MA 发散+连续阳线)。
    应该返回 True。"""
    flat = [10.0] * 25
    up = [11.0, 12.5, 14.0, 15.5, 17.0, 18.5]  # 月 26-31:连续阳线、close > open
    closes = flat + up
    opens = flat + [10.5, 11.5, 13.0, 14.5, 16.0, 17.5]  # 阳线 close > open
    bars = _bars_from_closes(closes, opens=opens)
    ctx = MockContext(history={"A__monthly": bars})

    assert kline.detect_ma_tangle_breakout(
        ctx, "A",
        fast=5, mid=10, slow=20,
        tangle_threshold=0.05,
        tangle_months=2,
        spread_months=4,
        spread_threshold=0.01,
        vol_red_bars=4,
        freq="monthly",
    ) is True
    # pass 日志中 stage 正确
    assert any(p[1] == "kline.ma_tangle" for p in ctx.pass_logs)


def test_detect_ma_tangle_breakout_no_tangle_returns_false():
    """单调上涨,从未缠绕,应返回 False。"""
    closes = [10 + i * 0.5 for i in range(40)]
    bars = _bars_from_closes(closes)
    ctx = MockContext(history={"A__monthly": bars})
    assert kline.detect_ma_tangle_breakout(
        ctx, "A", slow=20, tangle_months=2, freq="monthly"
    ) is False


def test_detect_ma_tangle_breakout_tangle_no_spread():
    """全程横盘,从未发散,应返回 False。"""
    closes = [10.0 + 0.01 * (i % 3) for i in range(40)]  # 极小波动
    bars = _bars_from_closes(closes)
    ctx = MockContext(history={"A__monthly": bars})
    assert kline.detect_ma_tangle_breakout(
        ctx, "A", slow=20, tangle_months=2, spread_months=4, freq="monthly"
    ) is False
```

- [ ] **Step 2:跑测试确认失败**

```bash
python -m pytest backend/tests/test_utils_kline_ma_tangle.py -v
```

- [ ] **Step 3:在 `strategies/utils/kline.py` 末尾追加 `detect_ma_tangle_breakout` 与私有辅助**

```python
import pandas as pd as _pd  # 局部别名,避免污染 module namespace 风格


def _is_tangle(df, end: int, col_f: str, col_m: str, col_s: str,
               tangle_months: int, threshold: float) -> bool:
    """end 索引处往前 tangle_months 根都满足 |MA - avg|/avg <= threshold。
    最后一根额外要求 MA_slow < MA_fast(为后续向上发散预留)。"""
    if end < tangle_months - 1:
        return False
    for i in range(end - tangle_months + 1, end + 1):
        row = df.iloc[i]
        avg = (row[col_f] + row[col_m] + row[col_s]) / 3.0
        if avg == 0:
            return False
        if (
            abs(row[col_f] - avg) / avg > threshold
            or abs(row[col_m] - avg) / avg > threshold
            or abs(row[col_s] - avg) / avg > threshold
        ):
            return False
    last = df.iloc[end]
    return last[col_s] < last[col_f]


def _check_spread_bar(row, col_f: str, col_m: str, col_s: str,
                      spread_threshold: float) -> bool:
    avg = (row[col_f] + row[col_m] + row[col_s]) / 3.0
    if avg == 0:
        return False
    if (
        abs(row[col_f] - avg) / avg <= spread_threshold
        or abs(row[col_s] - avg) / avg <= spread_threshold
    ):
        return False
    return row[col_f] > row[col_m] > row[col_s]


def _has_red_run(rows, min_run: int) -> bool:
    """rows 中存在 min_run 长度的连续 close >= open 段。"""
    cur = 0
    for i in range(len(rows)):
        r = rows.iloc[i]
        if r["close"] >= r["open"]:
            cur += 1
            if cur >= min_run:
                return True
        else:
            cur = 0
    return False


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
    """月线均线缠绕→发散→连续阳线 突破检测(迁移自 MaTangleBreakoutScreener)。

    返回 True 当且仅当 history 末尾存在某次「缠绕(N根)→发散(M根)→其中含
    vol_red_bars 连续阳线」事件,且该事件的发散窗口覆盖到最后一根 bar。

    数据需求:历史 bar 数 >= slow + tangle_months + spread_months
    stage = "kline.ma_tangle"
    """
    stage = "kline.ma_tangle"
    need = slow + tangle_months + spread_months
    bars = ctx.get_history(symbol, max(need, 500), period=freq)
    if not bars:
        ctx.log_reject(symbol, stage, "no_data", have=0, need=need)
        return False
    if len(bars) < need:
        ctx.log_reject(symbol, stage, "insufficient_history",
                       have=len(bars), need=need)
        return False

    df = _pd.DataFrame(bars)
    col_f, col_m, col_s = f"ma{fast}", f"ma{mid}", f"ma{slow}"
    for w, col in [(fast, col_f), (mid, col_m), (slow, col_s)]:
        df[col] = df["close"].rolling(window=w, min_periods=w).mean()
    df = df.dropna(subset=[col_f, col_m, col_s]).reset_index(drop=True)

    n = len(df)
    if n < tangle_months + 1:
        ctx.log_reject(symbol, stage, "insufficient_history_after_ma",
                       have=n, need=tangle_months + 1)
        return False

    last_idx = n - 1
    matched = False
    skip_until = -1

    for tangle_end in range(tangle_months - 1, n - 1):
        if tangle_end <= skip_until:
            continue
        if not _is_tangle(df, tangle_end, col_f, col_m, col_s,
                          tangle_months, tangle_threshold):
            continue

        spread_start = tangle_end + 1
        if last_idx < spread_start:
            continue

        if spread_months > 0:
            spread_window_end = min(spread_start + spread_months, n)
            spread_rows = df.iloc[spread_start:spread_window_end]
            all_spread = all(
                _check_spread_bar(spread_rows.iloc[j], col_f, col_m, col_s,
                                  spread_threshold)
                for j in range(len(spread_rows))
            )
            if not all_spread:
                continue
        else:
            spread_window_end = spread_start + 1
            spread_rows = df.iloc[spread_start:spread_window_end]

        red_ok = (vol_red_bars <= 0) or _has_red_run(spread_rows, vol_red_bars)
        if not red_ok:
            continue

        # 命中:仅当发散窗口覆盖到最后一根 bar 时返回 True
        if spread_window_end - 1 >= last_idx:
            matched = True
        skip_until = spread_window_end - 1

    if matched:
        ctx.log_pass(symbol, stage,
                     fast=fast, mid=mid, slow=slow,
                     tangle_months=tangle_months, spread_months=spread_months)
        return True
    ctx.log_reject(symbol, stage, "no_breakout_at_current_bar")
    return False
```

**注**:`import pandas as _pd` 在文件顶部应已存在(Task 1.6 创建文件时未导入,需要追加)。修改 `strategies/utils/kline.py` 顶部:

```python
import math
import pandas as _pd  # 局部命名,避免与 utils 公共 namespace 冲突
```

- [ ] **Step 4:跑测试确认通过**

```bash
python -m pytest backend/tests/test_utils_kline_ma_tangle.py -v
```

预期:5 个测试全过。若 `test_detect_ma_tangle_breakout_flat_then_uptrend_signal` 失败,说明构造的数据未能精确触发条件 — 调整 `up` 数组使 MA5/10/20 在最后 6 根满足 spread 条件。

- [ ] **Step 5:Commit**

```bash
git add strategies/utils/kline.py backend/tests/test_utils_kline_ma_tangle.py
git commit -m "feat(utils): kline.detect_ma_tangle_breakout (Phase 1.8)"
```

---

## Task 1.9:`composite/market_cap_weighted_batch_buyer.py`(状态类)

**Files:**
- Create: `strategies/utils/composite/market_cap_weighted_batch_buyer.py`
- Test: `backend/tests/test_utils_market_cap_buyer.py`

**设计要点**:
- 完整迁移 `strategies/examples/market_cap_weighted_buyer.py`(158 行)
- 命名变更:`MarketCapWeightedBuyer` → `MarketCapWeightedBatchBuyer`(spec D7)
- 类有状态(`_buy_plans / _allocated_symbols`),所以是 class 不是函数(spec D4 「跨源 + 有状态 → composite/ + class」)
- 取消 `BuyStrategy` 继承,改为独立 class;只暴露 `step(ctx)` 方法,Strategy 在 `on_buy(ctx)` 里调用 `self._buyer.step(ctx)`
- 内部方法签名沿用,但 `_create_buy_plans` 与 `_execute_weekly_buys` 改为接收 `ctx` 单参(`current_date` 从 `ctx.current_date` 取)
- 日志:
  - `log_pass / log_reject` stage = `"batch_buyer.allocate"` 与 `"batch_buyer.buy"`(spec L502-503)
- `params` 通过构造函数参数传入,而非旧 `self.p.buy_weeks`(脱离 BuyStrategy 框架)

- [ ] **Step 1:写测试 `test_utils_market_cap_buyer.py`**

```python
from tests.utils_test_helpers import MockContext
from strategies.utils.composite.market_cap_weighted_batch_buyer import (
    MarketCapWeightedBatchBuyer,
)


def _ctx_with_two_new_symbols(cash=1_000_000):
    return MockContext(
        valuation={
            "A": {"total_mv": 6e11},
            "B": {"total_mv": 4e11},
        },
        price={
            "A": {"weekly": {"open": 10.0, "close": 12.0}},  # mid=11
            "B": {"weekly": {"open": 20.0, "close": 22.0}},  # mid=21
        },
        target_symbols=["A", "B"],
        new_symbols=["A", "B"],
        available_cash=cash,
        current_date="2024-01-01",  # 周一(2024-W01)
    )


def test_step_creates_buy_plans_for_new_symbols():
    ctx = _ctx_with_two_new_symbols()
    buyer = MarketCapWeightedBatchBuyer(buy_weeks=8)
    buyer.step(ctx)

    # 两只股票都应有 plan
    assert set(buyer._buy_plans.keys()) == {"A", "B"}
    # A 占 60%,B 占 40%
    plan_a = buyer._buy_plans["A"]
    plan_b = buyer._buy_plans["B"]
    assert abs(plan_a["weekly_amount"] - 1_000_000 * 0.6 / 8) < 1.0
    assert abs(plan_b["weekly_amount"] - 1_000_000 * 0.4 / 8) < 1.0
    assert plan_a["market_cap"] == 6e11


def test_step_executes_first_week_buy():
    ctx = _ctx_with_two_new_symbols()
    buyer = MarketCapWeightedBatchBuyer(buy_weeks=8)
    buyer.step(ctx)

    # ctx.orders 应有两笔下单
    syms_ordered = {o[0] for o in ctx.orders}
    assert syms_ordered == {"A", "B"}
    # A: weekly_amount = 75000,price=11,shares = 75000/11=6818 → 取整 100 = 6800
    a_order = [o for o in ctx.orders if o[0] == "A"][0]
    assert a_order[1] == 6800


def test_step_does_not_buy_twice_in_same_week():
    ctx = _ctx_with_two_new_symbols()
    buyer = MarketCapWeightedBatchBuyer(buy_weeks=8)
    buyer.step(ctx)
    initial_orders = len(ctx.orders)

    # 同一日期再次调用 step,不应产生新订单
    ctx.new_symbols = []  # 已分配过
    buyer.step(ctx)
    assert len(ctx.orders) == initial_orders


def test_step_buys_again_in_next_week():
    ctx = _ctx_with_two_new_symbols()
    buyer = MarketCapWeightedBatchBuyer(buy_weeks=8)
    buyer.step(ctx)

    # 推进一周
    ctx.new_symbols = []
    ctx.current_date = "2024-01-08"  # 下一周(2024-W02)
    buyer.step(ctx)

    # 应再次下单 A 与 B(共 4 笔)
    assert len(ctx.orders) == 4


def test_step_skips_symbol_removed_from_target():
    ctx = _ctx_with_two_new_symbols()
    buyer = MarketCapWeightedBatchBuyer(buy_weeks=8)
    buyer.step(ctx)

    # A 被 seller 移除
    ctx.target_symbols = ["B"]
    ctx.new_symbols = []
    ctx.current_date = "2024-01-08"
    a_orders_before = len([o for o in ctx.orders if o[0] == "A"])
    buyer.step(ctx)
    a_orders_after = len([o for o in ctx.orders if o[0] == "A"])
    assert a_orders_after == a_orders_before  # A 不再被买入


def test_step_finishes_after_buy_weeks():
    ctx = _ctx_with_two_new_symbols(cash=10_000_000)
    buyer = MarketCapWeightedBatchBuyer(buy_weeks=2)
    # week 1
    buyer.step(ctx)
    # week 2
    ctx.new_symbols = []
    ctx.current_date = "2024-01-08"
    buyer.step(ctx)
    # week 3 — 应自动从 _buy_plans 中清除
    ctx.current_date = "2024-01-15"
    buyer.step(ctx)
    assert "A" not in buyer._buy_plans
    assert "B" not in buyer._buy_plans


def test_step_no_valuation_data_uses_equal_weight():
    ctx = MockContext(
        price={
            "A": {"weekly": {"open": 10.0, "close": 12.0}},
            "B": {"weekly": {"open": 20.0, "close": 22.0}},
        },
        target_symbols=["A", "B"],
        new_symbols=["A", "B"],
        available_cash=1_000_000,
        current_date="2024-01-01",
    )
    buyer = MarketCapWeightedBatchBuyer(buy_weeks=8)
    buyer.step(ctx)

    # 无 mv 数据时等权(每只股票 mv=1.0)
    plan_a = buyer._buy_plans["A"]
    plan_b = buyer._buy_plans["B"]
    assert abs(plan_a["weekly_amount"] - plan_b["weekly_amount"]) < 1.0


def test_step_skips_when_no_price():
    ctx = MockContext(
        valuation={"A": {"total_mv": 6e11}},
        price={},  # 无价格
        target_symbols=["A"],
        new_symbols=["A"],
        available_cash=1_000_000,
        current_date="2024-01-01",
    )
    buyer = MarketCapWeightedBatchBuyer(buy_weeks=8)
    buyer.step(ctx)
    # plan 已建,但本周不下单
    assert "A" in buyer._buy_plans
    assert ctx.orders == []
```

- [ ] **Step 2:跑测试确认失败**

```bash
python -m pytest backend/tests/test_utils_market_cap_buyer.py -v
```

- [ ] **Step 3:创建 `strategies/utils/composite/market_cap_weighted_batch_buyer.py`**

```python
"""市值加权 N 周分批买入器(跨数据源 + 有状态)。

跨源:取 valuation.total_mv 决定权重,按 kline 周线 (open+close)/2 成交。
有状态:_buy_plans / _allocated_symbols 跨 step 调用累积,因此封装为 class。

迁移自 strategies/examples/market_cap_weighted_buyer.py(2026-05-18 重构):
- 不再继承 BuyStrategy,改为独立 class
- 公开方法 step(ctx),由 Strategy.on_buy 调用
- 命名 MarketCapWeightedBuyer → MarketCapWeightedBatchBuyer
"""
from datetime import date as _date


class MarketCapWeightedBatchBuyer:
    def __init__(self, *, buy_weeks: int = 8, lot_size: int = 100):
        self._buy_weeks = buy_weeks
        self._lot_size = lot_size
        # {symbol: {"weekly_amount": float, "weeks_bought": int,
        #            "start_week_key": str, "last_buy_week_key": str|None,
        #            "market_cap": float}}
        self._buy_plans: dict[str, dict] = {}
        self._allocated_symbols: set[str] = set()

    def step(self, ctx) -> None:
        """每个 on_buy 调用一次。"""
        new_symbols = ctx.new_symbols
        current_date = ctx.current_date

        if new_symbols:
            self._create_buy_plans(ctx, new_symbols, current_date)

        self._execute_weekly_buys(ctx, current_date)

    # ===== 私有:分配计划 =====
    def _create_buy_plans(
        self, ctx, new_symbols: list[str], current_date: str
    ) -> None:
        stage = "batch_buyer.allocate"
        mv_map: dict[str, float] = {}
        for sym in new_symbols:
            if sym in self._allocated_symbols:
                continue
            val = ctx.get_valuation(sym)
            if val and val.get("total_mv"):
                mv_map[sym] = val["total_mv"]
            else:
                mv_map[sym] = 1.0  # 无市值数据时等权

        if not mv_map:
            return

        total_mv = sum(mv_map.values())
        available = ctx.available_cash
        week_key = self._week_key(current_date)

        for sym, mv in mv_map.items():
            ratio = mv / total_mv
            allocated_amount = available * ratio
            weekly_amount = allocated_amount / self._buy_weeks
            self._buy_plans[sym] = {
                "weekly_amount": weekly_amount,
                "weeks_bought": 0,
                "start_week_key": week_key,
                "last_buy_week_key": None,
                "market_cap": mv,
            }
            self._allocated_symbols.add(sym)
            ctx.log_pass(sym, stage,
                         mv=mv, weight=ratio, weekly_amount=weekly_amount,
                         buy_weeks=self._buy_weeks)

    # ===== 私有:执行买入 =====
    def _execute_weekly_buys(self, ctx, current_date: str) -> None:
        stage = "batch_buyer.buy"
        current_week = self._week_key(current_date)

        # 按市值降序,资金不足时优先大市值
        sorted_plans = sorted(
            self._buy_plans.items(),
            key=lambda x: x[1].get("market_cap", 0),
            reverse=True,
        )

        finished: list[str] = []
        pending_cost = 0.0

        for sym, plan in sorted_plans:
            if plan["weeks_bought"] >= self._buy_weeks:
                finished.append(sym)
                continue
            if plan["last_buy_week_key"] == current_week:
                continue
            if self._weeks_between(plan["start_week_key"], current_week) < 0:
                continue
            if sym not in ctx.target_symbols:
                # seller 已平仓,移出计划
                finished.append(sym)
                continue

            price = self._get_weekly_mid_price(ctx, sym)
            if price is None or price <= 0:
                continue

            target_amount = plan["weekly_amount"]
            available = ctx.available_cash - pending_cost
            actual_amount = min(target_amount, available)
            shares = (int(actual_amount / price) // self._lot_size) * self._lot_size

            if shares >= self._lot_size:
                ctx.order_shares(sym, shares)
                pending_cost += shares * price
                plan["weeks_bought"] += 1
                plan["last_buy_week_key"] = current_week
                ctx.log_pass(sym, stage,
                             week=current_week,
                             week_index=plan["weeks_bought"],
                             total_weeks=self._buy_weeks,
                             shares=shares, price=price)

        for sym in finished:
            del self._buy_plans[sym]

    # ===== 私有:辅助 =====
    @staticmethod
    def _get_weekly_mid_price(ctx, symbol: str) -> float | None:
        price_data = ctx.get_price(symbol, period="weekly")
        if price_data is None:
            price_data = ctx.get_price(symbol)  # fallback to daily
        if price_data is None:
            return None
        return (price_data["open"] + price_data["close"]) / 2

    @staticmethod
    def _week_key(date_str: str) -> str:
        dt = _date.fromisoformat(date_str)
        yr, wk, _ = dt.isocalendar()
        return f"{yr}-W{wk:02d}"

    @staticmethod
    def _weeks_between(start_week: str, current_week: str) -> int:
        s_year, s_week = int(start_week[:4]), int(start_week.split("W")[1])
        c_year, c_week = int(current_week[:4]), int(current_week.split("W")[1])
        s_d = _date.fromisocalendar(s_year, s_week, 1)
        c_d = _date.fromisocalendar(c_year, c_week, 1)
        return (c_d - s_d).days // 7
```

- [ ] **Step 4:跑测试确认通过**

```bash
python -m pytest backend/tests/test_utils_market_cap_buyer.py -v
```

预期:8 个测试全过。

- [ ] **Step 5:全量回归 + Commit**

```bash
python -m pytest backend/tests/ -x -q
```

预期:原 550 + Phase 1 新增 ~50 个 test 全绿。

```bash
git add strategies/utils/composite/market_cap_weighted_batch_buyer.py \
        backend/tests/test_utils_market_cap_buyer.py
git commit -m "feat(utils): MarketCapWeightedBatchBuyer composite class (Phase 1.9)"
```

---

## Phase 1 完成校验

- [ ] **跑全量回归确认 Phase 1 完成**

```bash
python -m pytest backend/tests/ -x -q
```

预期:原 550 case 全绿(因 Phase 1 是 additive,旧路径未动);新增 utils 测试约 50 case 全绿。

- [ ] **确认 import 链路通畅**

```bash
python -c "from services.backtest.base import Strategy; print('ok:', Strategy.frequency)"
python -c "from strategies.utils import kline, financial, dividend, valuation; print('ok')"
python -c "from strategies.utils.composite.market_cap_weighted_batch_buyer import MarketCapWeightedBatchBuyer; print('ok')"
```

- [ ] **Phase 1 总结 commit(可选)**

```bash
git tag phase-1-complete
```

---

# Phase 2:`MaTangleValueStrategy` + `DecisionLogSink`

**Phase 2 目标**:
- 新增 `backend/services/backtest/decision_log.py`,提供 `DecisionLogSink`(JSONL 写入器 + 内存缓冲 + flush)
- 新增 `strategies/examples/ma_tangle_value_strategy.py`,基于 Phase 1 utils 组装单一合并策略
- 全部测试用 mock Context(真实 Context Phase 3 才到位)— 沿用 `backend/tests/utils_test_helpers.py::MockContext`,扩 `log_pass/log_reject/log_flow` 抓取
- **不动**现有 engine/router,既有 550 测试全绿

**Phase 2 完成判据**:
- `from services.backtest.decision_log import DecisionLogSink` 可导入
- `from strategies.examples.ma_tangle_value_strategy import MaTangleValueStrategy` 可导入,`MaTangleValueStrategy.frequency == "monthly"`,`frequency_overridable is False`
- `pytest backend/tests/test_decision_log.py backend/tests/test_ma_tangle_value_strategy.py -v` 全绿
- `pytest backend/tests/ -x -q` 仍 550 + Phase 1 + Phase 2 全绿

---

## Task 2.1:`DecisionLogSink` JSONL 写入器

**Files:**
- Create: `backend/services/backtest/decision_log.py`
- Test: `backend/tests/test_decision_log.py`

**设计要点**:
- 三种事件类型:`pass / reject / flow / exec`(`exec` 在 broker 撮合时由 Engine 调用,Phase 2 仅暴露 API,实际接入在 Phase 3)
- 构造 `DecisionLogSink(log_dir: Path | None, enabled: bool = True)`;`log_dir is None or enabled is False` 时退化为 no-op(测试时高频用)
- 真实模式下三个文件:
  - `decisions.jsonl` — 全部 pass/reject 行,每行 `{"ts","idx","freq","stage","symbol","decision","reason","values"}`
  - `flow.jsonl` — `flow` 事件,`{"ts","idx","stage","counts"}`
  - `exec.jsonl` — `exec` 事件,`{"ts","idx","action","symbol","shares","price","note"}`
- 内存缓冲 `_buffer: dict[Path, list[str]]`,`flush()` 一次性写盘;`log_*` 调用只追加内存
- 进程退出时自动 flush(`atexit.register`)

- [ ] **Step 1:写测试 `test_decision_log.py`**

```python
"""DecisionLogSink 单测(Phase 2)。"""
import json
from pathlib import Path
import pytest
from services.backtest.decision_log import DecisionLogSink


@pytest.fixture
def sink(tmp_path):
    return DecisionLogSink(tmp_path, enabled=True)


def test_disabled_sink_is_noop(tmp_path):
    s = DecisionLogSink(tmp_path, enabled=False)
    s.log_pass("000001", "test.stage", idx=0, ts="2024-01-01", freq="daily", value=1)
    s.flush()
    assert not (tmp_path / "decisions.jsonl").exists()


def test_none_log_dir_is_noop():
    s = DecisionLogSink(None, enabled=True)
    s.log_pass("000001", "test.stage", idx=0, ts="2024-01-01", freq="daily")
    # 不抛异常即可


def test_log_pass_writes_jsonl_after_flush(sink, tmp_path):
    sink.log_pass("000001", "dividend.years",
                  idx=12, ts="2024-03-29", freq="monthly", years=8)
    sink.flush()
    lines = (tmp_path / "decisions.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["decision"] == "pass"
    assert rec["symbol"] == "000001"
    assert rec["stage"] == "dividend.years"
    assert rec["idx"] == 12
    assert rec["ts"] == "2024-03-29"
    assert rec["freq"] == "monthly"
    assert rec["years"] == 8


def test_log_reject_includes_reason(sink, tmp_path):
    sink.log_reject("600519", "valuation.pe_pb_product",
                    reason="above_max", idx=5, ts="2024-01-05", freq="monthly",
                    product=68.5, max=22.0)
    sink.flush()
    rec = json.loads((tmp_path / "decisions.jsonl").read_text().strip())
    assert rec["decision"] == "reject"
    assert rec["reason"] == "above_max"
    assert rec["product"] == 68.5


def test_log_flow_writes_to_flow_jsonl(sink, tmp_path):
    sink.log_flow("strategy.screen.start",
                  idx=0, ts="2024-01-01", input=4823, passed=421)
    sink.flush()
    rec = json.loads((tmp_path / "flow.jsonl").read_text().strip())
    assert rec["stage"] == "strategy.screen.start"
    assert rec["counts"] == {"input": 4823, "passed": 421}


def test_log_exec_writes_to_exec_jsonl(sink, tmp_path):
    sink.log_exec("BUY", "601318", idx=200, ts="2024-04-01",
                  shares=1300, price=35.20, note="week 1/8")
    sink.flush()
    rec = json.loads((tmp_path / "exec.jsonl").read_text().strip())
    assert rec["action"] == "BUY"
    assert rec["symbol"] == "601318"
    assert rec["shares"] == 1300
    assert rec["price"] == 35.20
    assert rec["note"] == "week 1/8"


def test_buffer_does_not_write_until_flush(sink, tmp_path):
    sink.log_pass("000001", "x", idx=0, ts="2024-01-01", freq="daily")
    assert not (tmp_path / "decisions.jsonl").exists()
    sink.flush()
    assert (tmp_path / "decisions.jsonl").exists()


def test_multiple_records_appended_in_order(sink, tmp_path):
    for i in range(5):
        sink.log_pass(f"00000{i}", "test", idx=i, ts="2024-01-01", freq="daily")
    sink.flush()
    lines = (tmp_path / "decisions.jsonl").read_text().strip().splitlines()
    assert len(lines) == 5
    for i, line in enumerate(lines):
        assert json.loads(line)["idx"] == i
```

- [ ] **Step 2:跑测试,确认 ImportError 失败**

```bash
python -m pytest backend/tests/test_decision_log.py -v
```

预期:`ModuleNotFoundError: No module named 'services.backtest.decision_log'`

- [ ] **Step 3:实现 `decision_log.py`**

```python
"""决策日志写入器:JSONL 格式,带内存缓冲 + flush。

三类事件:
- pass/reject:决策层(每条 = 一个 symbol 在某个 stage 的过滤结果)→ decisions.jsonl
- flow:流量层(每条 = 一个 stage 的 input/passed 计数)→ flow.jsonl
- exec:执行层(每条 = 一次买卖)→ exec.jsonl
"""
from __future__ import annotations
import atexit
import json
from pathlib import Path
from typing import Any


class DecisionLogSink:
    DECISIONS = "decisions.jsonl"
    FLOW = "flow.jsonl"
    EXEC = "exec.jsonl"

    def __init__(self, log_dir: Path | None, enabled: bool = True):
        self._enabled = enabled and log_dir is not None
        self._dir = Path(log_dir) if log_dir else None
        self._buffer: dict[str, list[str]] = {
            self.DECISIONS: [],
            self.FLOW: [],
            self.EXEC: [],
        }
        if self._enabled:
            self._dir.mkdir(parents=True, exist_ok=True)
            atexit.register(self.flush)

    def log_pass(self, symbol: str, stage: str, *, idx: int, ts: str,
                 freq: str = "daily", **values: Any) -> None:
        if not self._enabled:
            return
        rec = {"ts": ts, "idx": idx, "freq": freq, "stage": stage,
               "symbol": symbol, "decision": "pass", **values}
        self._buffer[self.DECISIONS].append(json.dumps(rec, ensure_ascii=False))

    def log_reject(self, symbol: str, stage: str, *, reason: str,
                   idx: int, ts: str, freq: str = "daily", **values: Any) -> None:
        if not self._enabled:
            return
        rec = {"ts": ts, "idx": idx, "freq": freq, "stage": stage,
               "symbol": symbol, "decision": "reject", "reason": reason, **values}
        self._buffer[self.DECISIONS].append(json.dumps(rec, ensure_ascii=False))

    def log_flow(self, stage: str, *, idx: int, ts: str, **counts: Any) -> None:
        if not self._enabled:
            return
        rec = {"ts": ts, "idx": idx, "stage": stage, "counts": counts}
        self._buffer[self.FLOW].append(json.dumps(rec, ensure_ascii=False))

    def log_exec(self, action: str, symbol: str, *, idx: int, ts: str,
                 shares: int, price: float, note: str = "") -> None:
        if not self._enabled:
            return
        rec = {"ts": ts, "idx": idx, "action": action, "symbol": symbol,
               "shares": shares, "price": price, "note": note}
        self._buffer[self.EXEC].append(json.dumps(rec, ensure_ascii=False))

    def flush(self) -> None:
        if not self._enabled:
            return
        for fname, lines in self._buffer.items():
            if not lines:
                continue
            path = self._dir / fname
            with path.open("a", encoding="utf-8") as f:
                f.write("\n".join(lines))
                f.write("\n")
            lines.clear()
```

- [ ] **Step 4:跑测试通过**

```bash
python -m pytest backend/tests/test_decision_log.py -v
```

预期:8 个测试全过。

- [ ] **Step 5:Commit**

```bash
git add backend/services/backtest/decision_log.py backend/tests/test_decision_log.py
git commit -m "feat(backtest): DecisionLogSink JSONL writer with buffered flush (Phase 2.1)"
```

---

## Task 2.2:扩 `MockContext` 支持日志抓取

**Files:**
- Modify: `backend/tests/utils_test_helpers.py`(Phase 1.2 创建,补 `log_*` 方法)

**设计要点**:Phase 1 utils 函数已经在调用 `ctx.log_pass/log_reject/log_flow`。Phase 1 MockContext 已 stub 这些方法为 no-op。Phase 2 把它们改为可断言的内存记录,供策略集成测使用。

- [ ] **Step 1:写测试 `test_mock_context_log_capture.py`**

```python
"""验证 MockContext 现在能抓取 log_*。"""
from backend.tests.utils_test_helpers import MockContext


def test_log_pass_recorded():
    ctx = MockContext()
    ctx.log_pass("000001", "stage.x", value=42)
    assert ctx.log_records["pass"] == [
        {"symbol": "000001", "stage": "stage.x", "value": 42}
    ]


def test_log_reject_recorded():
    ctx = MockContext()
    ctx.log_reject("000001", "stage.y", reason="too_low", actual=3, threshold=5)
    assert ctx.log_records["reject"][0]["reason"] == "too_low"


def test_log_flow_recorded():
    ctx = MockContext()
    ctx.log_flow("pipeline.start", input=100, passed=42)
    assert ctx.log_records["flow"] == [
        {"stage": "pipeline.start", "input": 100, "passed": 42}
    ]


def test_passed_symbols_helper():
    ctx = MockContext()
    ctx.log_pass("A", "s")
    ctx.log_pass("B", "s")
    ctx.log_reject("C", "s", reason="x")
    assert ctx.passed_symbols("s") == ["A", "B"]
    assert ctx.rejected_symbols("s") == ["C"]
```

- [ ] **Step 2:跑测试,失败(MockContext 还是 no-op)**

```bash
python -m pytest backend/tests/test_mock_context_log_capture.py -v
```

- [ ] **Step 3:扩 `MockContext`**

修改 `backend/tests/utils_test_helpers.py`,把 `log_pass/log_reject/log_flow` no-op 改为追加到 `self.log_records`:

```python
class MockContext:
    def __init__(self, ...):  # 保留 Phase 1.2 的所有原参数
        ...
        self.log_records: dict[str, list[dict]] = {
            "pass": [], "reject": [], "flow": []
        }

    def log_pass(self, symbol: str, stage: str, **values):
        self.log_records["pass"].append(
            {"symbol": symbol, "stage": stage, **values}
        )

    def log_reject(self, symbol: str, stage: str, *, reason: str, **values):
        self.log_records["reject"].append(
            {"symbol": symbol, "stage": stage, "reason": reason, **values}
        )

    def log_flow(self, stage: str, **counts):
        self.log_records["flow"].append({"stage": stage, **counts})

    # 辅助查询
    def passed_symbols(self, stage: str) -> list[str]:
        return [r["symbol"] for r in self.log_records["pass"] if r["stage"] == stage]

    def rejected_symbols(self, stage: str) -> list[str]:
        return [r["symbol"] for r in self.log_records["reject"] if r["stage"] == stage]
```

- [ ] **Step 4:跑测试通过 + 跑一遍 Phase 1 utils 测试确认未回归**

```bash
python -m pytest backend/tests/test_mock_context_log_capture.py \
                 backend/tests/test_utils_*.py -v
```

预期:Phase 1 ~50 个 utils 测试 + 4 个新增 mock 测试全过。

- [ ] **Step 5:Commit**

```bash
git add backend/tests/utils_test_helpers.py backend/tests/test_mock_context_log_capture.py
git commit -m "test(backtest): MockContext records log_pass/reject/flow for assertions (Phase 2.2)"
```

---

## Task 2.3:`MaTangleValueStrategy` 类骨架

**Files:**
- Create: `strategies/examples/ma_tangle_value_strategy.py`
- Test: `backend/tests/test_ma_tangle_value_strategy.py`(Phase 2.3 测属性 + 默认参数,Phase 2.4 测 screen 集成)

- [ ] **Step 1:写测试 `test_ma_tangle_value_strategy.py`(仅元信息部分)**

```python
"""MaTangleValueStrategy 元信息测试(Phase 2.3)。"""
import pytest
from strategies.examples.ma_tangle_value_strategy import MaTangleValueStrategy


def test_class_metadata():
    assert MaTangleValueStrategy.name == "月线均线缠绕价值策略"
    assert MaTangleValueStrategy.frequency == "monthly"
    assert MaTangleValueStrategy.frequency_overridable is False


def test_default_params_via_p_accessor():
    s = MaTangleValueStrategy()
    assert s.p.min_dividend_years == 5
    assert s.p.pe_pb_min == 0.0
    assert s.p.pe_pb_max == 22.0
    assert s.p.min_roe == 10.0
    assert s.p.ma_fast == 5
    assert s.p.ma_mid == 10
    assert s.p.ma_slow == 20
    assert s.p.tangle_threshold == 0.05
    assert s.p.tangle_months == 2
    assert s.p.spread_months == 6
    assert s.p.spread_threshold == 0.01
    assert s.p.vol_red_bars == 4
    assert s.p.buy_weeks == 8


def test_param_overrides():
    s = MaTangleValueStrategy(param_overrides={
        "min_dividend_years": 10,
        "pe_pb_max": 15.0,
        "buy_weeks": 4,
    })
    assert s.p.min_dividend_years == 10
    assert s.p.pe_pb_max == 15.0
    assert s.p.buy_weeks == 4


def test_buyer_initialized_with_buy_weeks():
    s = MaTangleValueStrategy(param_overrides={"buy_weeks": 12})
    # 私有属性,但本测试要确认 buyer 被正确初始化
    assert s._buyer._buy_weeks == 12


def test_default_settings_inherits_strategy_defaults():
    s = MaTangleValueStrategy()
    assert s.settings["initial_capital"] == 1_000_000
    assert s.settings["commission_rate"] == 0.0003
    assert s.settings["slippage"] == 0.002


def test_inherits_from_new_strategy_base():
    from services.backtest.base import Strategy
    assert issubclass(MaTangleValueStrategy, Strategy)
```

- [ ] **Step 2:跑测试,失败**

```bash
python -m pytest backend/tests/test_ma_tangle_value_strategy.py -v
```

- [ ] **Step 3:实现 `ma_tangle_value_strategy.py`**

参照 spec lines 584-660,完整实现:

```python
"""月线均线缠绕价值策略(MaTangleValueStrategy)。

合并 5 个原策略:
- DividendYearsScreener     → utils.dividend.filter_by_dividend_years
- PePbProductScreener       → utils.valuation.filter_by_pe_pb_product
- RoeScreener               → utils.financial.filter_by_roe
- MaTangleBreakoutScreener  → utils.kline.detect_ma_tangle_breakout
- MarketCapWeightedBuyer    → utils.composite.MarketCapWeightedBatchBuyer
"""
from services.backtest.base import Strategy
from strategies.utils import dividend, valuation, financial, kline
from strategies.utils.composite.market_cap_weighted_batch_buyer import (
    MarketCapWeightedBatchBuyer,
)


class MaTangleValueStrategy(Strategy):
    name = "月线均线缠绕价值策略"
    description = (
        "基本面池(连续分红 + PE*PB 区间 + ROE 达标)与月线均线缠绕突破信号交集,"
        "命中后按市值加权 8 周分批买入,默认永久持有。"
    )
    frequency = "monthly"
    frequency_overridable = False

    params = {
        "min_dividend_years": {"default": 5, "type": "int", "label": "最少分红年数"},
        "pe_pb_min": {"default": 0.0, "type": "float", "label": "PE*PB 下限"},
        "pe_pb_max": {"default": 22.0, "type": "float", "label": "PE*PB 上限"},
        "min_roe": {"default": 10.0, "type": "float", "label": "最低 ROE(%)"},
        "ma_fast": {"default": 5, "type": "int", "label": "快速均线"},
        "ma_mid": {"default": 10, "type": "int", "label": "中速均线"},
        "ma_slow": {"default": 20, "type": "int", "label": "慢速均线"},
        "tangle_threshold": {"default": 0.05, "type": "float", "label": "缠绕阈值"},
        "tangle_months": {"default": 2, "type": "int", "label": "缠绕月数"},
        "spread_months": {"default": 6, "type": "int", "label": "发散月数"},
        "spread_threshold": {"default": 0.01, "type": "float", "label": "发散阈值"},
        "vol_red_bars": {"default": 4, "type": "int", "label": "连阳根数"},
        "buy_weeks": {"default": 8, "type": "int", "label": "分批周数"},
    }

    def __init__(self, param_overrides=None):
        super().__init__(param_overrides)
        self._buyer = MarketCapWeightedBatchBuyer(buy_weeks=self.p.buy_weeks)

    def screen(self, ctx, symbols):
        ctx.log_flow("strategy.screen.start", input=len(symbols))

        # 顺序:廉价数据先,昂贵 K 线后
        pool = dividend.filter_by_dividend_years(
            ctx, symbols, min_years=self.p.min_dividend_years
        )
        pool = valuation.filter_by_pe_pb_product(
            ctx, pool,
            min_value=self.p.pe_pb_min, max_value=self.p.pe_pb_max,
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

        ctx.log_flow("strategy.screen.done",
                     input=len(symbols), passed=len(signals))
        return signals

    def on_buy(self, ctx):
        self._buyer.step(ctx)

    # on_sell 默认 pass = 永久持有
```

- [ ] **Step 4:跑测试通过**

```bash
python -m pytest backend/tests/test_ma_tangle_value_strategy.py -v
```

预期:6 个元信息测试全过。

- [ ] **Step 5:Commit**

```bash
git add strategies/examples/ma_tangle_value_strategy.py \
        backend/tests/test_ma_tangle_value_strategy.py
git commit -m "feat(strategy): MaTangleValueStrategy class metadata + buyer wiring (Phase 2.3)"
```

---

## Task 2.4:`MaTangleValueStrategy.screen()` 集成测(mock context)

**Files:**
- Modify: `backend/tests/test_ma_tangle_value_strategy.py`(追加 screen 流程测试)

**设计要点**:用 `MockContext` 注入一组已知 stocks(分红年数 / PE / PB / ROE / 月 K 线均线状态都预置),覆盖三个过滤层的通过/淘汰路径,以及 `kline.detect_ma_tangle_breakout` 的命中。重点断言 `log_records` 而非内部分支。

- [ ] **Step 1:追加测试**

```python
def _build_full_mock_context():
    """构造一个有 8 只股票的 MockContext,各自命中不同分支:
    A: 分红 8 年 / PE*PB=15 / ROE=12 / 月线缠绕命中  → 通过到 final
    B: 分红 3 年                                    → dividend 淘汰
    C: 分红 8 / PE*PB=68(>22)                       → valuation 淘汰
    D: 分红 8 / PE*PB=15 / ROE=8                     → financial 淘汰
    E: 分红 8 / PE*PB=15 / ROE=12 / 月线无缠绕      → kline 淘汰
    F-H: 同 A,通过到 final(凑数检验 signals 列表)
    """
    from backend.tests.utils_test_helpers import MockContext
    ctx = MockContext()
    # 详细数据填充(参考 Phase 1.3-1.8 测试夹具风格)
    ctx.set_dividend_years({"A": 8, "B": 3, "C": 8, "D": 8, "E": 8, "F": 8, "G": 8, "H": 8})
    ctx.set_pe_pb({"A": (10, 1.5), "C": (40, 1.7), "D": (10, 1.5),
                   "E": (10, 1.5), "F": (10, 1.5), "G": (10, 1.5), "H": (10, 1.5)})
    ctx.set_roe({"A": 12, "D": 8, "E": 12, "F": 12, "G": 12, "H": 12})
    ctx.set_ma_tangle_breakout_hits({"A", "F", "G", "H"})  # E 不命中
    return ctx


def test_screen_returns_only_full_pass_symbols():
    ctx = _build_full_mock_context()
    s = MaTangleValueStrategy()
    signals = s.screen(ctx, ["A", "B", "C", "D", "E", "F", "G", "H"])
    assert set(signals) == {"A", "F", "G", "H"}


def test_screen_logs_each_filter_stage_flow():
    ctx = _build_full_mock_context()
    s = MaTangleValueStrategy()
    s.screen(ctx, ["A", "B", "C", "D", "E", "F", "G", "H"])
    flow_stages = [r["stage"] for r in ctx.log_records["flow"]]
    assert "strategy.screen.start" in flow_stages
    assert "strategy.fundamental_pool" in flow_stages
    assert "strategy.screen.done" in flow_stages


def test_screen_logs_pass_for_each_final_signal():
    ctx = _build_full_mock_context()
    s = MaTangleValueStrategy()
    s.screen(ctx, ["A", "B", "C", "D", "E", "F", "G", "H"])
    final_passed = ctx.passed_symbols("strategy.screen.final")
    assert set(final_passed) == {"A", "F", "G", "H"}


def test_screen_short_circuits_on_dividend_filter():
    """分红淘汰的股票不应再到 valuation/financial/kline 阶段"""
    ctx = _build_full_mock_context()
    s = MaTangleValueStrategy()
    s.screen(ctx, ["A", "B", "C", "D", "E", "F", "G", "H"])
    # B 在 dividend 阶段被拒,后续 stage 中不应出现
    rejected_in_valuation = ctx.rejected_symbols("valuation.pe_pb_product")
    rejected_in_financial = ctx.rejected_symbols("financial.roe")
    assert "B" not in rejected_in_valuation
    assert "B" not in rejected_in_financial


def test_screen_param_override_changes_output():
    ctx = _build_full_mock_context()
    # 收紧 PE*PB 上限到 12,A 的 PE*PB=15 应被淘汰
    s = MaTangleValueStrategy(param_overrides={"pe_pb_max": 12.0})
    signals = s.screen(ctx, ["A", "F", "G", "H"])
    assert "A" not in signals
```

**注**:`MockContext.set_dividend_years / set_pe_pb / set_roe / set_ma_tangle_breakout_hits` 这些 setter 在 Phase 1.2 应已存在(Phase 1 utils 测试已用)— 若缺失,本 task 顺手补齐。

- [ ] **Step 2:跑测试,失败(若 setter 缺失)或直接通过**

```bash
python -m pytest backend/tests/test_ma_tangle_value_strategy.py -v
```

- [ ] **Step 3:补齐 MockContext setter(若需)**

参考 Phase 1 测试夹具,确保以下 setter 存在:
```python
def set_dividend_years(self, mapping: dict[str, int]): self._div_years = mapping
def set_pe_pb(self, mapping: dict[str, tuple[float, float]]): self._pe_pb = mapping
def set_roe(self, mapping: dict[str, float]): self._roe = mapping
def set_ma_tangle_breakout_hits(self, hits: set[str]): self._tangle_hits = hits
```
配合相应的 `get_*` / `detect_ma_tangle_breakout` 短路逻辑(命中查表返回 True/False)。

- [ ] **Step 4:跑测试通过**

```bash
python -m pytest backend/tests/test_ma_tangle_value_strategy.py -v
```

预期:6(metadata)+ 5(screen 集成)= 11 个测试全过。

- [ ] **Step 5:Commit**

```bash
git add backend/tests/test_ma_tangle_value_strategy.py backend/tests/utils_test_helpers.py
git commit -m "test(strategy): MaTangleValueStrategy.screen() integration with MockContext (Phase 2.4)"
```

---

## Task 2.5:Phase 2 完成校验

- [ ] **Step 1:全量回归**

```bash
python -m pytest backend/tests/ -x -q
```

预期:550(原)+ Phase 1(~50)+ Phase 2(~25)≈ 625 个 test 全绿。

- [ ] **Step 2:确认 import 链路**

```bash
python -c "from services.backtest.decision_log import DecisionLogSink; print('ok')"
python -c "from strategies.examples.ma_tangle_value_strategy import MaTangleValueStrategy as M; \
  print('freq=', M.frequency, 'override=', M.frequency_overridable)"
```

- [ ] **Step 3:Tag**

```bash
git tag phase-2-complete
```

---

# Phase 3:重写 Engine + Context

**Phase 3 目标**:
- 新增 `Context` 类替代 `ScreenerContext / TraderContext`(旧类暂不删除,Phase 6 才清理)
- 新增 `BacktestEngine` 类(spec line 347-416 形态)与旧 `engine.py` / `buy_sell_engine.py` 并存
- `strategy_loader` 兼容新单基类扫描
- Context 接 `DecisionLogSink`,真实 sink 替代 MockContext
- 全部走真实 broker / portfolio,但仍可禁用日志(测试场景)

**Phase 3 完成判据**:
- 用 `MaTangleValueStrategy` + 一组真实 parquet 数据跑端到端回测,得到 metrics + equity_curve + trades + decisions.jsonl
- `python -m pytest backend/tests/test_engine_v2*.py backend/tests/test_context_v2*.py -v` 全绿
- 既有 550 测试仍全绿(旧 Engine/Context 路径未动)

---

## Task 3.1:新 `Context` 类

**Files:**
- Create: `backend/services/backtest/context_v2.py`(临时命名,Phase 6 改名)
- Test: `backend/tests/test_context_v2.py`

**设计要点**:
- 构造:`Context(strategy, idx, broker, market_data, log_sink)`
- 属性:`current_idx / current_date / strategy`
- 数据 API(全部代理 `market_data`):`get_price(symbol, period="daily") / get_history(symbol, n, period) / get_valuation / get_dividend / get_financial / indicator(...)`
- 持仓与下单(代理 `broker`):`get_position / get_positions / available_cash / order_shares / order_value / order_target_percent`
- 累计池:`set_pool(target_set: set[str], new_list: list[str], remove_callback)` → 注入 `target_symbols / new_symbols / remove_target`
- 日志:`log_pass / log_reject / log_flow / log_exec`(代理 sink,自动塞 `idx / ts / freq`)

- [ ] **Step 1:写测试**

```python
"""新 Context 单测(Phase 3)。"""
import pytest
from unittest.mock import MagicMock
from services.backtest.context_v2 import Context
from services.backtest.decision_log import DecisionLogSink


@pytest.fixture
def ctx(tmp_path):
    strategy = MagicMock(frequency="monthly")
    broker = MagicMock()
    broker.portfolio.available_cash = 100_000
    market_data = MagicMock()
    market_data.dates = ["2024-01-31", "2024-02-29", "2024-03-29"]
    sink = DecisionLogSink(tmp_path, enabled=True)
    return Context(strategy=strategy, idx=2, broker=broker,
                   market_data=market_data, log_sink=sink)


def test_current_date_and_idx(ctx):
    assert ctx.current_idx == 2
    assert ctx.current_date == "2024-03-29"


def test_set_pool_injects_target_and_new(ctx):
    pool = {"A", "B", "C"}
    new = ["B", "C"]
    removed = []
    ctx.set_pool(pool, new, remove_callback=removed.append)
    assert ctx.target_symbols == {"A", "B", "C"}
    assert ctx.new_symbols == ["B", "C"]
    ctx.remove_target("B")
    assert removed == ["B"]


def test_log_pass_injects_idx_ts_freq(ctx, tmp_path):
    ctx.log_pass("000001", "test.stage", value=42)
    ctx.log_sink.flush()
    import json
    rec = json.loads((tmp_path / "decisions.jsonl").read_text().strip())
    assert rec["idx"] == 2
    assert rec["ts"] == "2024-03-29"
    assert rec["freq"] == "monthly"
    assert rec["value"] == 42


def test_data_access_delegates_to_market_data(ctx):
    ctx._market_data.get_price.return_value = {"close": 35.2}
    assert ctx.get_price("000001")["close"] == 35.2
    ctx._market_data.get_price.assert_called_once_with("000001", period="daily", idx=2)


def test_order_shares_delegates_to_broker(ctx):
    ctx.order_shares("000001", 100)
    ctx._broker.submit_order.assert_called_once()
    args = ctx._broker.submit_order.call_args
    assert args.kwargs["symbol"] == "000001" and args.kwargs["shares"] == 100


def test_available_cash_property(ctx):
    assert ctx.available_cash == 100_000
```

- [ ] **Step 2:跑测试失败**
- [ ] **Step 3:实现 `context_v2.py`**

```python
"""单一 Context(Phase 3 新增,Phase 6 重命名为 context.py 替换旧实现)。"""
from __future__ import annotations
from typing import Callable, Any


class Context:
    def __init__(self, *, strategy, idx: int, broker, market_data, log_sink):
        self.strategy = strategy
        self.current_idx = idx
        self.current_date = market_data.dates[idx]
        self._broker = broker
        self._market_data = market_data
        self.log_sink = log_sink

        # 累计池,默认空(必须由 Engine 调 set_pool 注入)
        self.target_symbols: set[str] = set()
        self.new_symbols: list[str] = []
        self._remove_callback: Callable[[str], None] | None = None

    # ===== 累计池 =====
    def set_pool(self, target: set[str], new: list[str],
                 *, remove_callback: Callable[[str], None]) -> None:
        self.target_symbols = target
        self.new_symbols = new
        self._remove_callback = remove_callback

    def remove_target(self, symbol: str) -> None:
        if self._remove_callback:
            self._remove_callback(symbol)

    # ===== 数据访问(代理 market_data) =====
    def get_price(self, symbol: str, period: str = "daily"):
        return self._market_data.get_price(symbol, period=period, idx=self.current_idx)

    def get_history(self, symbol: str, n: int, period: str = "daily"):
        return self._market_data.get_history(symbol, n=n, period=period,
                                             idx=self.current_idx)

    def get_valuation(self, symbol: str):
        return self._market_data.get_valuation(symbol, date=self.current_date)

    def get_dividend(self, symbol: str):
        return self._market_data.get_dividend(symbol, date=self.current_date)

    def get_financial(self, symbol: str):
        return self._market_data.get_financial(symbol, date=self.current_date)

    def indicator(self, name: str, symbol: str, **kwargs):
        return self._market_data.indicator(name, symbol, idx=self.current_idx, **kwargs)

    # ===== 持仓与下单(代理 broker) =====
    @property
    def available_cash(self) -> float:
        return self._broker.portfolio.available_cash

    def get_position(self, symbol: str):
        return self._broker.portfolio.get_position(symbol)

    def get_positions(self):
        return self._broker.portfolio.positions

    def order_shares(self, symbol: str, shares: int):
        return self._broker.submit_order(symbol=symbol, shares=shares,
                                         date=self.current_date)

    def order_value(self, symbol: str, value: float):
        price = self.get_price(symbol)
        if price is None:
            return None
        shares = int(value / price["close"]) // 100 * 100
        return self.order_shares(symbol, shares) if shares >= 100 else None

    def order_target_percent(self, symbol: str, target_pct: float):
        equity = self._broker.portfolio.equity(self.current_date)
        return self.order_value(symbol, equity * target_pct)

    # ===== 日志(代理 sink) =====
    def _common_log_kwargs(self):
        return {"idx": self.current_idx, "ts": self.current_date,
                "freq": self.strategy.frequency}

    def log_pass(self, symbol: str, stage: str, **values: Any):
        self.log_sink.log_pass(symbol, stage, **self._common_log_kwargs(), **values)

    def log_reject(self, symbol: str, stage: str, *, reason: str, **values: Any):
        self.log_sink.log_reject(symbol, stage, reason=reason,
                                 **self._common_log_kwargs(), **values)

    def log_flow(self, stage: str, **counts: Any):
        self.log_sink.log_flow(stage, idx=self.current_idx,
                               ts=self.current_date, **counts)

    def log_exec(self, action: str, symbol: str, *, shares: int, price: float,
                 note: str = ""):
        self.log_sink.log_exec(action, symbol,
                               idx=self.current_idx, ts=self.current_date,
                               shares=shares, price=price, note=note)
```

- [ ] **Step 4:跑测试通过**
- [ ] **Step 5:Commit**

```bash
git add backend/services/backtest/context_v2.py backend/tests/test_context_v2.py
git commit -m "feat(backtest): new Context with set_pool + log_* + data delegation (Phase 3.1)"
```

---

## Task 3.2:`MarketData` 适配器(Engine 内部)

**Files:**
- Create: `backend/services/backtest/market_data.py`(Engine 用,封装 stock_data dict + 周/月聚合缓存)
- Test: `backend/tests/test_market_data.py`

**设计要点**:
- 输入:`{symbol: pd.DataFrame(daily)}`,`frequency: str`
- 启动时按 `frequency` 预聚合(`weekly`→W-FRI,`monthly`→M),用 `services.stock_data.aggregate_kline`
- 暴露 `dates: list[str]`(参考股票 / 日历对齐)、`get_price(symbol, period, idx)`、`get_history(symbol, n, period, idx)`
- valuation/dividend/financial:对应 dict 入参,默认 None 时返回 None(Phase 4 Layer B 之后接 DuckDB)

- [ ] **Step 1-5:TDD 五步**(测试覆盖:聚合正确性、idx 越界返回 None、周/月切换、history 边界)

```bash
git commit -m "feat(backtest): MarketData adapter with multi-frequency aggregation (Phase 3.2)"
```

---

## Task 3.3:新 `BacktestEngine` 类

**Files:**
- Create: `backend/services/backtest/engine_v2.py`(临时命名,Phase 6 替换旧 engine.py)
- Test: `backend/tests/test_engine_v2.py`

**设计要点**:严格按 spec line 347-416 实现。`_period_key(date, freq)` 复用 `services.backtest.date_utils.format_match_date`。

- [ ] **Step 1:写测试**

最小集合(每个测试用最小 strategy + 最小 stock_data):

```python
def test_engine_runs_one_bar_with_default_strategy():
    """默认 Strategy:screen 全通过、on_buy/on_sell no-op,资产 = 初始资本"""
    
def test_engine_calls_screen_only_on_period_switch_monthly():
    """monthly 频率下,跨月才触发 screen,同月不重复"""
    
def test_engine_calls_screen_every_bar_daily():
    """daily 频率每根 bar 都 screen"""

def test_engine_calls_on_sell_before_on_buy_each_bar():
    """on_sell 调 ctx.remove_target,on_buy 不再看到该 symbol"""

def test_engine_target_symbols_accumulates_across_bars():
    """连续两个月 screen 命中不同股票,target_symbols 累加而非覆盖"""

def test_engine_returns_metrics_equity_curve_trades():
    """返回结构包含三键,equity_curve 长度 == n_bars"""

def test_engine_writes_decision_log_when_log_dir_given(tmp_path):
    """log_dir 传入则 decisions.jsonl 存在"""

def test_engine_disabled_log_does_not_write(tmp_path):
    """enable_decision_log=False 不写盘"""

def test_on_progress_called_per_bar():
    """on_progress 回调每 bar 触发一次"""
```

- [ ] **Step 2-3:实现 engine_v2.py**

```python
"""单一回测引擎(Phase 3 新增,Phase 6 替换旧 engine.py)。"""
from __future__ import annotations
from pathlib import Path
from typing import Callable
import pandas as pd

from services.backtest.base import Strategy
from services.backtest.broker import Broker
from services.backtest.context_v2 import Context
from services.backtest.market_data import MarketData
from services.backtest.decision_log import DecisionLogSink
from services.backtest.analyzer import compute_metrics
from services.backtest.date_utils import format_match_date


class BacktestEngine:
    def __init__(
        self,
        strategy: Strategy,
        stock_data: dict[str, pd.DataFrame],
        valuation_data: dict | None = None,
        dividend_data: dict | None = None,
        financial_data: dict | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        log_dir: Path | None = None,
        enable_decision_log: bool = True,
    ):
        self._strategy = strategy
        self._broker = Broker(**strategy.settings)
        self._market_data = MarketData(
            stock_data=stock_data,
            frequency=strategy.frequency,
            valuation=valuation_data,
            dividend=dividend_data,
            financial=financial_data,
        )
        self._log_sink = DecisionLogSink(log_dir, enabled=enable_decision_log)
        self._on_progress = on_progress
        self._all_symbols = list(stock_data.keys())

    def run(self) -> dict:
        dates = self._market_data.dates
        n_bars = len(dates)
        target_symbols: set[str] = set()
        screener_cache: list[str] = []
        prev_period_key: str | None = None
        equity_curve = []

        for idx in range(n_bars):
            current_date = dates[idx]

            # 1) T+1 撮合(idx>0 才有挂单)
            if idx > 0:
                self._broker.fill_orders(self._market_data, idx)

            ctx = Context(
                strategy=self._strategy, idx=idx, broker=self._broker,
                market_data=self._market_data, log_sink=self._log_sink,
            )

            # 2) screen 仅在 frequency 周期切换时跑
            pk = format_match_date(current_date, self._strategy.frequency)
            if pk != prev_period_key:
                screener_cache = self._strategy.screen(ctx, list(self._all_symbols))
                prev_period_key = pk

            # 3) 累计目标池
            current_bars = self._market_data.symbols_with_data_at(idx)
            today_signals = [s for s in screener_cache if s in current_bars]
            new_symbols = [s for s in today_signals if s not in target_symbols]
            target_symbols.update(new_symbols)
            ctx.set_pool(target_symbols, new_symbols,
                         remove_callback=target_symbols.discard)

            # 4) sell 先于 buy
            self._strategy.on_sell(ctx)
            self._strategy.on_buy(ctx)

            # 5) 快照
            current_prices = self._market_data.close_prices_at(idx)
            equity_curve.append(
                self._broker.portfolio.snapshot(current_date, current_prices)
            )

            if self._on_progress:
                self._on_progress(idx + 1, n_bars)

        self._log_sink.flush()
        return {
            "metrics": compute_metrics(equity_curve, self._broker.all_trades),
            "equity_curve": equity_curve,
            "trades": self._broker.all_trades,
            "log_dir": str(self._log_sink._dir) if self._log_sink._enabled else None,
        }
```

- [ ] **Step 4-5:跑测试 + commit**

```bash
git commit -m "feat(backtest): single-path BacktestEngine with period-aware screen + decision log (Phase 3.3)"
```

---

## Task 3.4:Engine 端到端集成测(用 MaTangleValueStrategy + 真实 parquet)

**Files:**
- Test: `backend/tests/test_engine_v2_e2e.py`

**设计要点**:用 `data/market/A/daily/` 中 5 只真实股票(选有完整 5 年历史的)+ mock valuation/dividend/financial dict,跑 24 个月回测,断言:
- 返回结构完整(metrics / equity_curve / trades)
- decisions.jsonl 存在且含 `strategy.screen.start` flow 行
- equity_curve 长度 == 输入 bar 数
- 至少一笔 buy 成交(若数据命中)

跳过条件:`pytest.skip if not (BACKEND_DATA_DIR / "market/A/daily").exists()`(CI 缺数据时)

```bash
git commit -m "test(backtest): Engine v2 e2e with MaTangleValueStrategy on real parquet (Phase 3.4)"
```

---

## Task 3.5:`strategy_loader` 兼容新基类

**Files:**
- Modify: `backend/services/backtest/strategy_loader.py`

**设计要点**:扫描 `strategies/examples/*.py`,识别同时继承自旧基类(`ScreenerStrategy / BuyStrategy / SellStrategy / TraderStrategy`)与新基类 `Strategy` 的类。返回字段补充 `frequency_overridable: bool`(用于前端 Phase 5)。

实施细节:`StrategyMeta` dataclass 加字段;`load_all_strategies()` 内 isinstance 判断分支增加 `Strategy` 检查;旧字段 `strategy_type` 在过渡期保留(前端 Phase 5 切换后,Phase 6 可删)。

- [ ] **Step 1-5**:测试覆盖「仅新基类」「仅旧基类」「同时兼容」三场景。

```bash
git commit -m "feat(backtest): strategy_loader recognizes new Strategy base + frequency_overridable (Phase 3.5)"
```

---

## Task 3.6:Phase 3 完成校验

```bash
python -m pytest backend/tests/ -x -q
git tag phase-3-complete
```

---

# Phase 4:DB 迁移 + 路由简化 + D8 数据访问统一

**Phase 4 目标**(D8 Layer A + B 在此期同步落地,顺序参考 spec line 265-275):
1. 扩 `DuckDBStore.query_qfq_kline`(D8 Layer B 步骤 1)
2. 写 `scripts/diff_market_vs_kline.py` 对照脚本(D8 风险缓解)
3. 写 `qfq_cache vs query_qfq_kline` 全历史 diff 测(D8 Layer B 步骤 2)
4. 替换全局 `qfq_cache` 调用点(D8 Layer B 步骤 3)
5. 改 `routers/backtest.py::_load_stock_data`(D8 Layer A)
6. `main.py` lifespan 加 DuckDB 健康检查
7. DB 迁移 SQL(`backtest_tasks` schema 改造,DROP `strategy_groups / group_runs`)
8. **删除** `qfq_cache.py` + `data/kline/A/qfq/` + Phase 4 完成校验

**Phase 4 完成判据**:
- 全量 pytest 全绿(diff 测除 floating-point 误差外为 0)
- `grep -rn "from services.qfq_cache\|qfq_cache\." backend/ strategies/` → 无业务代码命中
- `grep -rn "RAW_KLINE_DIR\|QFQ_KLINE_DIR" backend/` 仅剩 `config.py`
- `routers/backtest.py` 不再 `glob` parquet
- `backtest_tasks` 表新 schema 落地,旧字段在 SQLite 中已迁移

---

## Task 4.1:`DuckDBStore.query_qfq_kline`

**Files:**
- Modify: `backend/services/duckdb_store.py`(新增方法)
- Test: `backend/tests/test_duckdb_store_qfq.py`

**设计要点**:
- 签名:`query_qfq_kline(market: str, symbol: str, start: str | None, end: str | None) -> pd.DataFrame`
- 实现:执行 spec line 215-233 的 ASOF JOIN SQL
- 返回 7 列(date / open / high / low / close / volume / amount),date 升序
- 边界:
  - 无除权数据(adjust_factor 表空) → `factor_d=NULL,latest=NULL`,SQL 用 `COALESCE(factor, 1) / COALESCE(latest, 1)` = raw
  - 早于首次除权 → `factor_d=NULL` 退化 raw
  - 时段切片:`start/end` 任一为 None 表不限

- [ ] **Step 1:测试**(7 个用例:无除权 / 单次除权 / 多次除权 / 时段切片 / 空 symbol 报错 / market=HK 视图正常)

- [ ] **Step 2-3:实现**

```python
def query_qfq_kline(self, market: str, symbol: str,
                    start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """前复权 K 线(用 BaoStock foreAdjustFactor 实时算)。"""
    market_l = market.lower()
    daily_view = f"v_{market_l}_daily"
    factor_view = f"v_{market_l}_adjust_factor"

    where_clauses = ["d.code = ?"]
    params: list = [symbol]
    if start:
        where_clauses.append("d.date >= ?")
        params.append(start)
    if end:
        where_clauses.append("d.date <= ?")
        params.append(end)
    where_sql = " AND ".join(where_clauses)

    sql = f"""
    WITH latest AS (
        SELECT MAX(foreAdjustFactor) AS f_latest
        FROM {factor_view} WHERE code = ?
    )
    SELECT
        d.date,
        d.open  * COALESCE(af.foreAdjustFactor, 1) / COALESCE(latest.f_latest, 1) AS open,
        d.high  * COALESCE(af.foreAdjustFactor, 1) / COALESCE(latest.f_latest, 1) AS high,
        d.low   * COALESCE(af.foreAdjustFactor, 1) / COALESCE(latest.f_latest, 1) AS low,
        d.close * COALESCE(af.foreAdjustFactor, 1) / COALESCE(latest.f_latest, 1) AS close,
        d.volume,
        d.amount
    FROM {daily_view} d
    LEFT ASOF JOIN {factor_view} af
      ON af.code = d.code AND af.dividOperateDate <= d.date
    CROSS JOIN latest
    WHERE {where_sql}
    ORDER BY d.date
    """
    return self._con.execute(sql, [symbol] + params).fetchdf()
```

- [ ] **Step 4-5**

```bash
git commit -m "feat(duckdb): query_qfq_kline via ASOF JOIN with adjust_factor view (Phase 4.1, D8-B)"
```

---

## Task 4.2:`scripts/diff_market_vs_kline.py` 对照脚本

**Files:**
- Create: `scripts/diff_market_vs_kline.py`

**设计要点**:抽样 10 只股票,对比:
- `data/market/A/daily/{sym}.parquet` vs `data/kline/A/raw/{sym}.parquet`(schema + 行数 + 数值)
- `store.query_qfq_kline("A", sym)` vs `qfq_cache.get_qfq_kline(sym)`(数值 diff)

阈值:浮点误差 ≤ 1e-4(因子归一化的相对精度)。命令行模式:`python scripts/diff_market_vs_kline.py --samples 10`,输出:`OK / WARN / FAIL` 表格。

```bash
git commit -m "chore: diff_market_vs_kline script for D8 migration verification (Phase 4.2)"
```

---

## Task 4.3:**SKIPPED** —— 经 T4.2 实测,新旧 qfq 算法不可比

**决策(2026-05-19)**:T4.2 sanity 跑发现新 `query_qfq_kline`(BaoStock foreAdjustFactor 因子法)与旧 `qfq_cache.get_qfq_kline`(分红事件派生法)在历史价格上差异显著(样本 close_max_abs 0.36–54.5 元),不是浮点误差,而是**方法学差异**。

用户决策:**信任 BaoStock 因子法**,废弃旧 qfq_cache,跳过严格 diff 测。

T4.1 的 7 个用例已覆盖新算法的边界(无除权 / 单次除权 / 多次除权 / NULL factor / 切片 / HK / 列结构),足以保证算法正确性。直接进入 T4.4。

**No commit for this task.**

---

## Task 4.4:全局替换 `qfq_cache` 调用点

**Files:**
- Modify(grep 列出后逐个改):
  - `backend/services/backtest/engine.py` / `engine_v2.py`(若用到 qfq)
  - `backend/routers/market_kline.py`
  - `backend/routers/backtest.py`
  - 任何 `from services.qfq_cache` 的文件

**设计要点**:
- 搜:`grep -rn "from services.qfq_cache\|services\.qfq_cache" backend/ strategies/`
- 替换:`get_qfq_kline(symbol, start=..., end=...)` → `get_store().query_qfq_kline("A", symbol, start, end)`

- [ ] **Step 1:列出调用点**

```bash
grep -rn "qfq_cache" backend/ strategies/ > /tmp/qfq_callsites.txt
cat /tmp/qfq_callsites.txt
```

- [ ] **Step 2:逐处替换 + 跑全量回归**

```bash
python -m pytest backend/tests/ -x -q
```

注意:Phase 4.3 的 diff 测试此时仍依赖旧 `qfq_cache`,可单独留到最后。
- [ ] **Step 3:Commit**

```bash
git commit -m "refactor: replace all qfq_cache callsites with DuckDBStore.query_qfq_kline (Phase 4.4, D8-B step 3)"
```

---

## Task 4.5:`routers/backtest.py::_load_stock_data` 去 glob

**Files:**
- Modify: `backend/routers/backtest.py`
- Test: `backend/tests/test_router_backtest_load.py`

**设计要点**:按 spec line 159-173 改造:

```python
def _load_stock_data(market: str, symbols: list[str] | None,
                     start: str, end: str) -> dict[str, pd.DataFrame]:
    store = get_store()
    if symbols is None or len(symbols) == 0:
        symbols = store.list_symbols(market=market)
    out = {}
    for sym in symbols:
        df = store.query_qfq_kline(market, sym, start=start, end=end)
        if df is not None and len(df) > 0:
            out[sym] = df
    return out
```

`_load_stock_data` 调用方:把日期范围必填化(spec D6.1)。

- [ ] **Step 1-3**:测试覆盖个股模式 / 全市场模式 / HK 市场,实现替换。
- [ ] **Step 4:回归测**

```bash
python -m pytest backend/tests/ -x -q
```

- [ ] **Step 5:验证旧路径不再被读**

```bash
grep -rn "RAW_KLINE_DIR\|QFQ_KLINE_DIR" backend/ | grep -v "config.py"
# 期望:无输出(除 config.py 常量定义外)
```

```bash
git commit -m "refactor(router): backtest._load_stock_data uses DuckDBStore (Phase 4.5, D8-A)"
```

---

## Task 4.6:DuckDB 健康检查放入 lifespan

**Files:**
- Modify: `backend/main.py`

**设计要点**:`init_duckdb()` 后立即执行 spec line 277-284 的健康检查,失败抛 `RuntimeError`。

```python
def init_duckdb_with_health_check():
    init_duckdb()
    store = get_store()
    a_symbols = store.list_symbols("A")
    if len(a_symbols) == 0:
        raise RuntimeError(
            "DuckDB health check failed: v_a_daily empty, "
            "data/market/A/daily/ has no parquet"
        )
    af_count = store._con.execute(
        "SELECT count(*) AS c FROM v_a_adjust_factor"
    ).fetchone()[0]
    if af_count == 0:
        raise RuntimeError(
            "DuckDB health check failed: v_a_adjust_factor empty, "
            "data/market/A/adjust_factor/ has no parquet"
        )
```

- [ ] **Step 1-3**:加测试覆盖空目录场景(用 fixture 重写 `_con` 跑空查询)。

```bash
git commit -m "feat(main): DuckDB health check on lifespan startup (Phase 4.6, D8 risk mitigation)"
```

---

## Task 4.7:DB Schema 迁移

**Files:**
- Create: `backend/services/migrations/2026-05-18-merge-strategies.sql`
- Modify: `backend/services/db_schema.py`(新建表用新 schema,旧表保留兼容旧任务)
- Modify: `backend/services/backtest/task_manager.py`(写入 `strategy_class / params / log_dir`,读取新增 `is_deleted` 软删过滤)
- Test: `backend/tests/test_db_migration_2026_05_18.py`

**设计要点**(spec D6 + 软删):

```sql
-- 2026-05-18-merge-strategies.sql
-- 1. backtest_tasks 软删 + log_dir
ALTER TABLE backtest_tasks ADD COLUMN is_deleted BOOLEAN DEFAULT FALSE;
ALTER TABLE backtest_tasks ADD COLUMN log_dir TEXT;
-- (DROP source_task_id 在 SQLite 不直接支持,新代码忽略读写即可,实际删列后续单独 migration)

-- 2. 移除策略组(后端从未对前端开放)
DROP TABLE IF EXISTS group_runs;
DROP TABLE IF EXISTS strategy_groups;

-- 3. pipeline_info 字段含义改写(向新格式 {strategy_class, params})— 数据迁移
-- 旧值形如 {"pipeline":[{"filepath":"...","class_name":"X","params":{...}}], ...}
-- 写法:对所有 status='success' 的旧任务,把第一个元素提升为 {strategy_class, params}
UPDATE backtest_tasks
SET pipeline_info = json_object(
    'strategy_class', json_extract(pipeline_info, '$.pipeline[0].class_name'),
    'params', json_extract(pipeline_info, '$.pipeline[0].params')
)
WHERE json_extract(pipeline_info, '$.pipeline') IS NOT NULL;
```

`task_manager.py`:
- `list_tasks()` 默认 `WHERE is_deleted = FALSE`,新增 `include_deleted: bool = False` 参数
- `delete_task(task_id)` 改为 `UPDATE ... SET is_deleted=TRUE`(软删)
- `create_task()` 写入新 schema:`pipeline_info = {"strategy_class": ..., "params": ...}`,`log_dir = "data/logs/backtest/{task_id}/"`

- [ ] **Step 1-5**:测试覆盖 (a) 空旧库迁移成功 (b) 含 1 个旧任务迁移后 pipeline_info 形态正确 (c) 软删后 list_tasks 默认不返回 (d) `include_deleted=True` 返回。

```bash
git commit -m "feat(db): migrate backtest_tasks schema + drop strategy_groups + soft delete (Phase 4.7, D6)"
```

---

## Task 4.8:删除 `qfq_cache.py` + `data/kline/A/qfq/` + Phase 4 校验

**Files:**
- Delete: `backend/services/qfq_cache.py`
- Delete: `data/kline/A/qfq/`(整个目录,包括 `_meta.json`)
- Delete: `backend/tests/test_qfq_migration_diff.py`(Phase 4.3 的 diff 测试此时其依赖的旧实现已不存在)

- [ ] **Step 1:确认 grep 无业务读 qfq_cache**

```bash
grep -rn "qfq_cache" backend/ strategies/ | grep -v ".bak"
# 期望:无输出
```

- [ ] **Step 2:删除文件 + 目录**

```bash
git rm backend/services/qfq_cache.py
git rm -r data/kline/A/qfq/
git rm backend/tests/test_qfq_migration_diff.py
```

- [ ] **Step 3:全量回归**

```bash
python -m pytest backend/tests/ -x -q
```

- [ ] **Step 4:Commit + Tag**

```bash
git commit -m "refactor: delete qfq_cache.py + data/kline/A/qfq/ — replaced by DuckDB ASOF JOIN (Phase 4.8, D8-B step 4)"
git tag phase-4-complete
```

---

# Phase 5:前端 BacktestConfig API 收敛 + 软删

**Phase 5 目标**:
- `frontend/src/api/backtestEngine.ts`:`runBacktest` 入参从 pipeline 数组简化为 `{strategy_class, params, frequency_override?}`
- `frontend/src/components/backtest/BacktestConfig.tsx`:策略下拉副标签从 `screener/trader` 切到 `frequency`;K 线周期字段按 `frequency_overridable` 切换可编辑
- `frontend/src/components/backtest/BacktestResult.tsx + BacktestHistory.tsx`:`pipeline_info` 嵌套结构改为直读 `strategy_class + params`;历史列表加软删过滤 + 「显示已删除」开关
- 既有前端测试(vitest + Playwright smoke)全绿
- TypeScript 类型检查通过

**Phase 5 完成判据**:
- `cd frontend && npx tsc --noEmit && npm test && npm run lint` 全绿
- `npm run test:smoke` Playwright 通过(单策略选择 → 跑回测 → 结果展示)

---

## Task 5.1:`backtestEngine.ts` API 收敛

**Files:**
- Modify: `frontend/src/api/backtestEngine.ts`(签名变更)
- Modify: `frontend/src/types/backtest.ts`(`BacktestRunRequest` 类型)
- Test: `frontend/src/api/__tests__/backtestEngine.test.ts`

**设计要点**:

```ts
// 旧
type BacktestRunRequest = {
  pipeline: Array<{ filepath: string; class_name: string; params: Record<string, any> }>;
  param_overrides: Record<string, Record<string, any>>;
  start_date: string;
  end_date: string;
  symbols?: string[];
  market?: 'A' | 'HK' | 'US';
};

// 新
type BacktestRunRequest = {
  strategy_class: string;            // e.g. "MaTangleValueStrategy"
  params: Record<string, any>;
  start_date: string;                // 必填(D6.1)
  end_date: string;                  // 必填
  symbols?: string[];
  market?: 'A' | 'HK' | 'US';
  frequency_override?: 'daily' | 'weekly' | 'monthly';  // 仅当 strategy.frequency_overridable=true 才允许
};
```

- [ ] **Step 1-5**:测试覆盖 (a) 缺 start_date 类型错误 (b) frequency_override 可选 (c) 入参直接序列化为 JSON body。

```bash
git commit -m "refactor(frontend): backtest API simplified to {strategy_class, params} (Phase 5.1)"
```

---

## Task 5.2:`BacktestConfig.tsx` 表单适配

**Files:**
- Modify: `frontend/src/components/backtest/BacktestConfig.tsx`
- Test: `frontend/src/components/backtest/__tests__/BacktestConfig.test.tsx`

**设计要点**(参考 spec line 730-738):
1. 策略下拉副标签:`s.strategyType === 'screener' ? '选股' : '交易'` → `frequencyLabel(s.frequency)`(`daily` → 「日」/`weekly` → 「周」/`monthly` → 「月」)
2. K 线周期字段(行 227-238)行为:
   - `strategy.frequency_overridable === false` → 只读 chip,显示策略声明频率
   - `=== true` → 下拉,默认值 = `strategy.frequency`,值同步到 `frequency_override`
3. 提交时:`runBacktest({ strategy_class: selected.class_name, params: formValues, ... frequency_override })`

- [ ] **Step 1-5**:测试覆盖 (a) 选月线策略时 K 线周期 chip 不可编辑 (b) 选日线策略且 `frequency_overridable=true` 时下拉可选周/月 (c) 提交 payload 形态正确。

```bash
git commit -m "refactor(frontend): BacktestConfig single-strategy form + frequency_overridable (Phase 5.2)"
```

---

## Task 5.3:`BacktestResult.tsx + BacktestHistory.tsx` 软删与新 schema

**Files:**
- Modify: `frontend/src/components/backtest/BacktestResult.tsx`
- Modify: `frontend/src/components/backtest/BacktestHistory.tsx`
- Modify: `frontend/src/api/history.ts`(列表 API 加 `?include_deleted=true|false` 查询参数)

**设计要点**:
- BacktestResult:从 `pipeline_info.pipeline[0].class_name + params` 改为 `pipeline_info.strategy_class + pipeline_info.params`
- BacktestHistory:
  - 默认请求 `?include_deleted=false`,展示活跃任务
  - 新增 toggle「显示已删除」→ `?include_deleted=true`,已删除行加灰底+「已删除」徽章
  - 删除按钮调 `DELETE /api/backtest/tasks/{id}`(后端软删)+ 列表本地刷新

- [ ] **Step 1-5**:测试覆盖 (a) 旧任务(pipeline_info 旧 schema)展示 fallback 字符串「旧版任务」 (b) toggle 切换 (c) 删除后列表行变灰且不消失。

```bash
git commit -m "refactor(frontend): BacktestResult/History adapt to new pipeline_info + soft delete (Phase 5.3)"
```

---

## Task 5.4:Phase 5 完成校验

```bash
cd frontend
npx tsc --noEmit
npm run lint
npm test
npm run test:smoke
```

```bash
git tag phase-5-complete
```

---

# Phase 6:删除旧策略 / 旧基类 / 旧引擎 / 旧路由

**Phase 6 目标**:
- 删除 7 个旧策略 + 旧测试(`dividend_years_screener / pe_pb_product_screener / roe_screener / ma_tangle_breakout_screener / monthly_low_screener / monthly_volume_red_screener / market_cap_weighted_buyer`)
- 删除旧基类 `ScreenerStrategy / TraderStrategy / BuyStrategy / SellStrategy`(只剩 `Strategy` + `ParamAccessor`)
- 删除旧 Engine `engine.py` / `buy_sell_engine.py` / `engine_base.py`,把 `engine_v2.py` 改名为 `engine.py`
- 删除旧 Context,把 `context_v2.py` 改名为 `context.py`
- 删除 `group_manager.py` + `routers/strategy_group.py`(后端从未对前端开放,前端 Phase 5 已不引用)
- 删除 `services/backtest/date_utils.py` 中 `date_belongs_to / detect_frequency` 等仅 join_mode 用的函数(若还有 `format_match_date` 则保留)
- 删除回测路由的 `mode=screen` / `source_task_id` 分支(spec D2)

**Phase 6 完成判据**:
- 全量 pytest 全绿(测试集大幅缩减但都来自 Phase 1-3 新建)
- `python -m pytest backend/tests/ --collect-only | wc -l` 期望 ~400-500 个 case(原 550 中 join_mode/group/chain/旧策略测试约 100-150 删除,Phase 1-3 新增约 100)
- `grep -rn "ScreenerStrategy\|TraderStrategy\|BuyStrategy\|SellStrategy\|BuySellEngine\|StrategyGroup" backend/ strategies/ frontend/src/` 无业务命中

---

## Task 6.1:删除 7 个旧策略 + 测试

**Files:**
- Delete: `strategies/examples/dividend_years_screener.py`
- Delete: `strategies/examples/pe_pb_product_screener.py`
- Delete: `strategies/examples/roe_screener.py`
- Delete: `strategies/examples/ma_tangle_breakout_screener.py`
- Delete: `strategies/examples/monthly_low_screener.py`
- Delete: `strategies/examples/monthly_volume_red_screener.py`
- Delete: `strategies/examples/market_cap_weighted_buyer.py`
- Delete: `backend/tests/test_dividend_years_screener.py`(及其余 6 个对应测试文件)

- [ ] **Step 1:确认 import 不再有外部依赖**

```bash
grep -rn "dividend_years_screener\|pe_pb_product_screener\|roe_screener\|ma_tangle_breakout_screener\|monthly_low_screener\|monthly_volume_red_screener\|market_cap_weighted_buyer" backend/ strategies/ frontend/src/
# 期望:仅本批被删文件本身命中
```

- [ ] **Step 2:`git rm` 7 文件 + 7 测试 + 全量回归**

```bash
python -m pytest backend/tests/ -x -q
```

- [ ] **Step 3:Commit**

```bash
git commit -m "refactor: delete 7 legacy strategies + tests — logic migrated to utils (Phase 6.1)"
```

---

## Task 6.2:删除旧基类 + 旧 Engine + 旧 Context,改名 v2 → 正式

**Files:**
- Modify: `backend/services/backtest/base.py`(删除 4 个旧基类 + `Strategy`,只保留 `ParamAccessor`)
- **Create: `strategies/base.py`**(把新 `Strategy` 从 backtest/base.py 移过来)
- Delete: `backend/services/backtest/engine.py`(旧)→ Rename `engine_v2.py` → `engine.py`
- Delete: `backend/services/backtest/buy_sell_engine.py`
- Delete: `backend/services/backtest/engine_base.py`(若存在)
- Delete: `backend/services/backtest/context.py`(旧)→ Rename `context_v2.py` → `context.py`
- Modify: 全局 import:`from services.backtest.engine_v2 import BacktestEngine` → `from services.backtest.engine import BacktestEngine`(同 context_v2)
- Modify: 全局 import:`from services.backtest.base import Strategy` → `from strategies.base import Strategy`(engine / 测试 / `MaTangleValueStrategy` 等所有引用方)

**架构理由**:`Strategy` 是策略作者的公共契约,放 `strategies/` 下符合「就近原则」+ 反转依赖方向(engine 依赖 strategies,而非 strategies 反向依赖 backend 内部)。

- [ ] **Step 1:删除 + 改名**

```bash
git rm backend/services/backtest/engine.py
git rm backend/services/backtest/buy_sell_engine.py
git rm -f backend/services/backtest/engine_base.py
git rm backend/services/backtest/context.py
git mv backend/services/backtest/engine_v2.py backend/services/backtest/engine.py
git mv backend/services/backtest/context_v2.py backend/services/backtest/context.py
```

- [ ] **Step 2:全局替换 import**

```bash
grep -rln "engine_v2\|context_v2" backend/ | xargs sed -i.bak \
  -e 's/from services\.backtest\.engine_v2 import/from services.backtest.engine import/g' \
  -e 's/from services\.backtest\.context_v2 import/from services.backtest.context import/g'
find backend -name "*.bak" -delete
```

- [ ] **Step 3:把 `Strategy` 移到 `strategies/base.py`**

```bash
# 创建新文件,把 backend/services/backtest/base.py 中的 Strategy 类整段搬过去
# strategies/base.py 应仅 import 必要依赖(typing 等),不依赖 backend.services.backtest
```

新 `strategies/base.py` 内容大致:
```python
"""策略基类 — 策略作者的公共契约。

所有 strategies/examples/*.py 应继承本文件的 Strategy。
backend/services/backtest/engine.py 反向 import 这里。
"""
from __future__ import annotations
from typing import Any

class Strategy:
    frequency: str = "daily"
    frequency_overridable: bool = False
    strategy_type: str = "strategy"
    settings: dict = {}
    # ... 其余原样从 backend/services/backtest/base.py 搬来
```

- [ ] **Step 4:全局替换 Strategy import**

```bash
grep -rln "from services\.backtest\.base import.*Strategy\|from backend\.services\.backtest\.base import.*Strategy" backend/ strategies/ | \
  xargs sed -i.bak \
    -e 's|from services\.backtest\.base import Strategy|from strategies.base import Strategy|g' \
    -e 's|from backend\.services\.backtest\.base import Strategy|from strategies.base import Strategy|g'
find backend strategies -name "*.bak" -delete
```

注意:`backend/services/backtest/base.py` 中其他 import(`ParamAccessor` 等)保持不动。

- [ ] **Step 5:`backend/services/backtest/base.py` 清理**

手工编辑,删除:
- `ScreenerStrategy / TraderStrategy / BuyStrategy / SellStrategy` 4 个旧基类
- 新 `Strategy` 类(已搬到 strategies/base.py)
- 旧 `_load_settings` 逻辑

仅保留 `ParamAccessor` 等仍被 engine 使用的工具类。若 `base.py` 清理后为空,可整文件删除。

- [ ] **Step 6:全量回归**

```bash
python -m pytest backend/tests/ -x -q
```

- [ ] **Step 7:Commit**

```bash
git commit -m "refactor(backtest): delete legacy base/engine/context, move Strategy to strategies/base.py (Phase 6.2)"
```

---

## Task 6.3:删除策略组路由 + `mode=screen / source_task_id` + Phase 6 完成校验

**Files:**
- Delete: `backend/routers/strategy_group.py`
- Delete: `backend/services/backtest/group_manager.py`
- Modify: `backend/main.py`(删除 `app.include_router(strategy_group.router)`)
- Modify: `backend/routers/backtest.py`(删除 `mode=screen` 分支、`source_task_id` 入参解析、链式回测逻辑)
- Modify: `backend/services/backtest/date_utils.py`(删除 `date_belongs_to / detect_frequency` 等若仅 join_mode 用)
- Delete: `backend/tests/test_strategy_group*.py`、`test_engine_*chain*.py`、`test_engine_*join_mode*.py`、`test_engine_signal_table.py`(全部 group/chain 相关)

- [ ] **Step 1:删除文件 + 路由注册**
- [ ] **Step 2:简化 `routers/backtest.py`**(只剩单一 POST `/run` + GET `/tasks` + DELETE `/tasks/{id}`)
- [ ] **Step 3:全量回归**

```bash
python -m pytest backend/tests/ -x -q
```

- [ ] **Step 4:验证清理**

```bash
grep -rn "ScreenerStrategy\|TraderStrategy\|BuyStrategy\|SellStrategy\|BuySellEngine\|StrategyGroup\|source_task_id\|mode=.screen.\|date_belongs_to" backend/ strategies/ frontend/src/
# 期望:无业务命中(测试 / 历史文档可有)
```

- [ ] **Step 5:Commit + Tag**

```bash
git commit -m "refactor: delete strategy_group router + chain backtest + join_mode (Phase 6.3, D2)"
git tag phase-6-complete
```

---

# Phase 7(可选):决策日志查询面板

**Phase 7 目标**(留待后续迭代,本期仅占位):
- `frontend/src/components/backtest/DecisionLogPanel.tsx`:按 symbol + 日期范围 + stage 过滤查询 `decisions.jsonl`
- `backend/routers/backtest.py`:新增 `GET /api/backtest/tasks/{task_id}/decisions?symbol=&stage=&start=&end=`,流式返回 JSON 行
- `BacktestResult.tsx`:在结果页加「查看决策日志」按钮跳转到面板

**判定推迟条件**:Phase 1-6 完成且至少 1 周正式使用、用户提出明确日志检索需求后,再启动 Phase 7。否则视为本次重构 out-of-scope。

---

# 全 Plan 完成校验

- [ ] **后端全量**

```bash
python -m pytest backend/tests/ -x -q
```

- [ ] **前端全量**

```bash
cd frontend && npx tsc --noEmit && npm run lint && npm test && npm run test:smoke
```

- [ ] **架构静态扫描**(spec D1-D8 都已落地)

```bash
# D1 单一基类:base.py 只剩 Strategy
grep -E "^class (ScreenerStrategy|TraderStrategy|BuyStrategy|SellStrategy)" backend/services/backtest/base.py
# 期望:无输出

# D2 路由清理
grep -rn "strategy_group\|source_task_id\|join_mode" backend/routers/
# 期望:无输出

# D8-A 路由不再 glob parquet
grep -rn "RAW_KLINE_DIR.glob\|QFQ_KLINE_DIR.glob" backend/
# 期望:无输出

# D8-B qfq_cache 已删
test ! -f backend/services/qfq_cache.py && echo "OK: qfq_cache.py deleted"

# D8 数据访问唯一入口
grep -rn "from services.duckdb_store" backend/services/backtest/
# 期望:engine.py + market_data.py 命中
```

- [ ] **手动 smoke**:跑一次 `MaTangleValueStrategy` 全市场 24 月回测,确认:
  - 任务成功,metrics + equity_curve 返回
  - `data/logs/backtest/{task_id}/decisions.jsonl` 含每个 stage 的 pass/reject 记录
  - 历史列表显示新 schema(`strategy_class + params`)
  - 删除任务后列表灰显

- [ ] **Tag 总完成**

```bash
git tag merge-strategies-complete
```

---

# 执行说明

**REQUIRED SUB-SKILL**:用 `superpowers:subagent-driven-development`(推荐,各 task 独立 subagent)或 `superpowers:executing-plans`(顺序、有 checkpoint)执行。

**节奏建议**:
- Phase 1-2 单 session 可一气连做(纯 additive,无破坏性)
- Phase 3-4 之间建议设 checkpoint:Phase 3 结束跑端到端 smoke 后再启 Phase 4(数据层风险点)
- Phase 4.3 → 4.4 → 4.8 是 D8 的关键序列,严格按顺序执行,中间任意失败都立刻 stop 排查
- Phase 5 前端改动小但跨多个组件,建议单 session 完成 5.1-5.4
- Phase 6 是「拆掉脚手架」环节,跑完再次 smoke 验收
- Phase 7 默认延期
