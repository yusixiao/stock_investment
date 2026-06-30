"""MaTangleValueStrategy PE 多轮分批卖出策略测试(2026-05-24 第二次重构)。

新规格(替代旧的两阶段卖出):
- **模式判定**(首次触发时锁定):
  - 30 < PE ≤ 40 → two_stage(总最多 2 轮,共 35%:15% + 20%)
  - PE > 40        → chain(15% + 20% × N,基于初始持仓,直到清仓)
- **第 1 轮触发**:PE > 30,锚点 P_1 = 当日 daily (high+low)/2,
                   总卖出量 = initial × pct(stage1=15%);分 4 周 4 批,
                   前 3 批 floor(total/4),最后批吃尾差。
- **第 N+1 轮触发**:任意已有锚点满足 daily (h+l)/2 > P_n × 1.05 且模式允许新轮。
                       触发后该锚点锁定,避免重复触发。
- **批次执行时机**:
  - 第 1 批:触发当日,price = daily (h+l)/2
  - 第 2-4 批:之后每个新 ISO 周的周一,price = ctx.get_price(sym, "weekly") 的 (h+l)/2
- **多轮并行**:每轮独立 schedule,可同周共存。
- **链式清仓**:当批量超过剩余持仓 → 卖光为止,不再启动新轮。

PE 缺失保守不卖。
"""

from __future__ import annotations

from typing import Any

from backend.tests.utils_test_helpers import MockContext
from services.backtest.strategies.experiments.ma_tangle_value.ma_tangle_value_strategy import MaTangleValueStrategy


# ===== 共用工具 =====


class _Pos:
    def __init__(self, shares: int):
        self.shares = shares


class _SellCtx(MockContext):
    """扩展 MockContext:支持 positions / remove_target。"""

    def __init__(self, *, positions: dict[str, int], current_date: str, **kw):
        super().__init__(current_date=current_date, **kw)
        self._positions = {sym: _Pos(n) for sym, n in positions.items()}
        self.removed_targets: list[str] = []

    def get_positions(self) -> dict[str, Any]:
        return self._positions

    def remove_target(self, sym: str) -> None:
        self.removed_targets.append(sym)

    def set_daily(self, sym: str, *, close: float, high: float, low: float) -> None:
        self._price.setdefault(sym, {})["daily"] = {
            "close": close,
            "high": high,
            "low": low,
        }

    def set_weekly(self, sym: str, *, close: float, high: float, low: float) -> None:
        self._price.setdefault(sym, {})["weekly"] = {
            "close": close,
            "high": high,
            "low": low,
        }


def _daily(close: float, high: float | None = None, low: float | None = None) -> dict:
    """快速构造 X 的 daily price dict;默认 high=close+0.5 / low=close-0.5。"""
    h = close + 0.5 if high is None else high
    lo = close - 0.5 if low is None else low
    return {"X": {"daily": {"close": close, "high": h, "low": lo}}}


# ===== 1. 策略元信息 =====


def test_pe_sell_params_schema():
    """新参数表:enabled / threshold / chain_threshold / pct1 / pct_n / breakout_pct / batches。"""
    s = MaTangleValueStrategy()
    assert s.p.pe_sell_enabled is True
    assert s.p.pe_sell_threshold == 30.0
    assert s.p.pe_sell_chain_threshold == 40.0
    assert s.p.pe_sell_pct1 == 0.15
    assert s.p.pe_sell_pct_n == 0.20
    assert s.p.pe_sell_breakout_pct == 0.05
    assert s.p.pe_sell_batches == 4


# ===== 2. 第 1 轮首次触发 =====


def test_two_stage_mode_first_trigger_sells_batch1_at_daily_mid():
    """PE=31 ∈ (30, 40] → two_stage 模式;total=150;batch1=floor(150/4)=37,price=daily (h+l)/2=159。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-02",  # 周一
        valuation={"X": {"peTTM": 31.0}},
        price=_daily(close=159.0, high=160.0, low=158.0),
    )
    s = MaTangleValueStrategy()
    s.on_sell(ctx)
    assert ctx.orders == [("X", -37)]
    state = s._sell_state["X"]
    assert state["mode"] == "two_stage"
    assert state["initial_shares"] == 1000
    assert len(state["schedules"]) == 1
    sch = state["schedules"][0]
    assert sch["round"] == 1
    assert sch["anchor_p"] == 159.0
    assert sch["total_shares"] == 150
    assert sch["batches_done"] == 1
    # 余下 3 批待发
    assert sch["batches_remaining"] == 3


def test_chain_mode_first_trigger_sells_batch1():
    """PE=41 > 40 → chain 模式;第 1 轮 total=150,batch1=37。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-02",
        valuation={"X": {"peTTM": 41.0}},
        price=_daily(close=200.0, high=201.0, low=199.0),
    )
    s = MaTangleValueStrategy()
    s.on_sell(ctx)
    assert ctx.orders == [("X", -37)]
    state = s._sell_state["X"]
    assert state["mode"] == "chain"
    assert state["schedules"][0]["anchor_p"] == 200.0


def test_pe_below_threshold_does_not_trigger():
    """PE=20 ≤ 30 → 不触发。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-02",
        valuation={"X": {"peTTM": 20.0}},
        price=_daily(close=100.0),
    )
    s = MaTangleValueStrategy()
    s.on_sell(ctx)
    assert ctx.orders == []
    assert "X" not in s._sell_state


def test_pe_missing_skipped():
    """PE 缺失 → 保守不卖。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-02",
        price=_daily(close=100.0),
    )
    s = MaTangleValueStrategy()
    s.on_sell(ctx)
    assert ctx.orders == []
    assert "X" not in s._sell_state


# ===== 3. 4 周分批正常卖完(无突破) =====


def test_4_weeks_batches_with_remainder_to_last():
    """initial=2700,total=405,batch1/2/3=101,batch4=102 (吃尾差)。"""
    s = MaTangleValueStrategy()
    ctx = _SellCtx(
        positions={"X": 2700},
        current_date="2024-12-02",  # ISO 周 W49 周一
        valuation={"X": {"peTTM": 31.0}},
        price=_daily(close=100.0, high=101.0, low=99.0),
    )

    # 第 1 批:周一,daily mid = 100
    s.on_sell(ctx)
    assert ctx.orders == [("X", -101)]

    # 同周二三四 → 不再发批
    for d in ("2024-12-03", "2024-12-04", "2024-12-05", "2024-12-06"):
        ctx.current_date = d
        s.on_sell(ctx)
    assert ctx.orders == [("X", -101)]

    # 下周一(W50),weekly bar (h+l)/2 = 105
    ctx.current_date = "2024-12-09"
    ctx.set_weekly("X", close=105.0, high=106.0, low=104.0)
    # 同时 daily 必须不构成 5% 突破(避免触发新轮):daily mid 必须 ≤ 100*1.05=105
    ctx.set_daily("X", close=104.0, high=104.5, low=103.5)
    s.on_sell(ctx)
    assert ctx.orders[-1] == ("X", -101)

    # 再下周一(W51)
    ctx.current_date = "2024-12-16"
    ctx.set_weekly("X", close=103.0, high=104.0, low=102.0)
    ctx.set_daily("X", close=103.0, high=103.5, low=102.5)
    s.on_sell(ctx)
    assert ctx.orders[-1] == ("X", -101)

    # 最后一周(W52)→ 吃尾差 102
    ctx.current_date = "2024-12-23"
    ctx.set_weekly("X", close=102.0, high=103.0, low=101.0)
    ctx.set_daily("X", close=102.0, high=102.5, low=101.5)
    s.on_sell(ctx)
    assert ctx.orders[-1] == ("X", -102)

    # schedule 完成
    assert sum(-o[1] for o in ctx.orders) == 405
    sch = s._sell_state["X"]["schedules"][0]
    assert sch["batches_done"] == 4
    assert sch["batches_remaining"] == 0


# ===== 4. 第 2 轮并行启动(突破 5%) =====


def test_round2_starts_in_parallel_when_breakout():
    """第 1 轮还在跑,daily mid 突破 P_1*1.05 → 第 2 轮启动,同周双批共存。

    P_1=20;第 2 轮触发日 daily mid=22 > 21;第 2 轮 anchor P_2=22。
    same week 两个 schedules 各发自己的批。
    """
    s = MaTangleValueStrategy()
    # 准备:initial=1000, two_stage 不够测多轮,改用 chain
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-02",  # W49 周一
        valuation={"X": {"peTTM": 41.0}},
        price=_daily(close=20.0, high=21.0, low=19.0),  # mid=20
    )
    s.on_sell(ctx)
    # 第 1 轮 batch1: floor(150/4)=37
    assert ctx.orders == [("X", -37)]
    ctx._positions["X"].shares = 1000 - 37

    # 下周一 W50:daily mid=22 > 20*1.05=21 → 启动第 2 轮
    # weekly bar 喂给第 1 轮的 batch2(price 不影响订单股数,只影响日志价格)
    ctx.current_date = "2024-12-09"
    ctx.set_weekly("X", close=22.0, high=23.0, low=21.0)
    ctx.set_daily("X", close=22.0, high=23.0, low=21.0)  # mid=22
    s.on_sell(ctx)

    # 期望:第 1 轮 batch2 (-37) + 第 2 轮 batch1 (基于 chain pct_n=20%, total=200, batch1=50)
    # 顺序:轮号小的先发
    assert ctx.orders[-2:] == [("X", -37), ("X", -50)]

    state = s._sell_state["X"]
    assert len(state["schedules"]) == 2
    assert state["schedules"][1]["round"] == 2
    assert state["schedules"][1]["anchor_p"] == 22.0
    assert state["schedules"][1]["total_shares"] == 200
    # 第 1 轮锚点已锁定(避免重复触发)
    assert state["schedules"][0].get("triggered_next") is True


# ===== 5. two_stage 模式只允许 2 轮 =====


def test_two_stage_mode_caps_at_2_rounds():
    """two_stage 模式触发第 2 轮后,即便后续突破也不再启动第 3 轮。"""
    s = MaTangleValueStrategy()
    ctx = _SellCtx(
        positions={"X": 10000},
        current_date="2024-12-02",
        valuation={"X": {"peTTM": 31.0}},  # two_stage
        price=_daily(close=100.0, high=101.0, low=99.0),  # P_1=100
    )
    s.on_sell(ctx)  # 第 1 轮 batch1

    # 突破 P_1 → 启动第 2 轮
    ctx.current_date = "2024-12-09"
    ctx.set_weekly("X", close=110.0, high=111.0, low=109.0)
    ctx.set_daily("X", close=110.0, high=111.0, low=109.0)  # mid=110 > 105
    s.on_sell(ctx)
    assert len(s._sell_state["X"]["schedules"]) == 2

    # 再突破 P_2=110*1.05=115.5 → two_stage 不允许第 3 轮
    ctx.current_date = "2024-12-16"
    ctx.set_weekly("X", close=130.0, high=131.0, low=129.0)
    ctx.set_daily("X", close=130.0, high=131.0, low=129.0)  # mid=130 > 115.5
    s.on_sell(ctx)
    assert len(s._sell_state["X"]["schedules"]) == 2  # 仍然 2 轮


# ===== 6. chain 模式可启动多轮 =====


def test_chain_mode_allows_multiple_rounds():
    """chain 模式在突破不断时可启动 R3, R4, ..."""
    s = MaTangleValueStrategy()
    ctx = _SellCtx(
        positions={"X": 100000},
        current_date="2024-12-02",
        valuation={"X": {"peTTM": 41.0}},
        price=_daily(close=100.0, high=101.0, low=99.0),
    )
    s.on_sell(ctx)  # R1 batch1

    # R2 启动
    ctx.current_date = "2024-12-09"
    ctx.set_weekly("X", close=110.0, high=111.0, low=109.0)
    ctx.set_daily("X", close=110.0, high=111.0, low=109.0)
    s.on_sell(ctx)
    assert len(s._sell_state["X"]["schedules"]) == 2

    # R3 启动(突破 P_2=110*1.05=115.5)
    ctx.current_date = "2024-12-16"
    ctx.set_weekly("X", close=120.0, high=121.0, low=119.0)
    ctx.set_daily("X", close=120.0, high=121.0, low=119.0)
    s.on_sell(ctx)
    assert len(s._sell_state["X"]["schedules"]) == 3


# ===== 7. chain 模式最后一批吃尾差(清仓) =====


def test_chain_mode_clears_remaining_when_batch_exceeds():
    """chain 模式末批 > 剩余持仓 → 卖光为止。"""
    s = MaTangleValueStrategy()
    # 初始 100 股,触发 chain 模式 → R1 total=15 (15%), batch1=floor(15/4)=3, 余 12 待发
    ctx = _SellCtx(
        positions={"X": 100},
        current_date="2024-12-02",
        valuation={"X": {"peTTM": 50.0}},
        price=_daily(close=100.0, high=101.0, low=99.0),
    )
    s.on_sell(ctx)
    assert ctx.orders[-1] == ("X", -3)
    ctx._positions["X"].shares = 97

    # 模拟未来某周,假设剩余 < batch_n —— 直接构造极端 batch
    # 用更小持仓 + 更大的 pct 简化测试:position=10, total=20 (按 chain pct_n) → batch=5
    # 但 100 股不好构造;改:让 position 跌到 2,然后下周触发批次
    ctx._positions["X"].shares = 2
    ctx.current_date = "2024-12-09"
    ctx.set_weekly("X", close=100.0, high=101.0, low=99.0)
    ctx.set_daily("X", close=100.0, high=101.0, low=99.0)  # 无突破
    s.on_sell(ctx)
    # batch 应为 3 但只剩 2 → 卖 2(清仓)
    assert ctx.orders[-1] == ("X", -2)


# ===== 8. PE 跌回阈值以下不影响已启动模式 =====


def test_pe_dropping_back_does_not_affect_running_schedule():
    """模式锁定后,即使 PE 跌回 25,后续批次仍按 schedule 发。"""
    s = MaTangleValueStrategy()
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-02",
        valuation={"X": {"peTTM": 31.0}},
        price=_daily(close=100.0, high=101.0, low=99.0),
    )
    s.on_sell(ctx)
    assert ctx.orders == [("X", -37)]

    # 下周一 PE 跌到 25
    ctx.current_date = "2024-12-09"
    ctx._valuation["X"] = {"peTTM": 25.0}
    ctx.set_weekly("X", close=98.0, high=99.0, low=97.0)
    ctx.set_daily("X", close=98.0, high=99.0, low=97.0)
    s.on_sell(ctx)
    # 仍按 schedule 发 batch2
    assert ctx.orders[-1] == ("X", -37)


# ===== 9. 禁用开关 =====


def test_disabled_by_param():
    """pe_sell_enabled=False → 不卖。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-02",
        valuation={"X": {"peTTM": 50.0}},
        price=_daily(close=100.0),
    )
    s = MaTangleValueStrategy(param_overrides={"pe_sell_enabled": False})
    s.on_sell(ctx)
    assert ctx.orders == []
