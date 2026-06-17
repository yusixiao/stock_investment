"""成长方向实验策略组(A 股全周期,纯多头等权,无止损/无防护层)。

⚠️ 实验性质(experiments/,不暴露 UI)。目标:在「成长」方向上(不绑估值)
横向比较 4 类预先承诺的教科书因子定义,看哪一类在 A 股全周期(2010-2026)
能做出较好的**绝对年化**(用户口径:可接受深回撤)。

== 绝不数据拟合 ==
4 类定义 + 阈值全部用教科书经典值,**不网格搜索找历史最优**:
  - 双增门槛 20%(经典 high-growth 筛选)
  - 动量 12-1(250 日回报跳过最近 20 日,Jegadeesh-Titman 经典口径)
  - 质量 ROE ≥ 15%(巴菲特式优质门槛)
  - 持仓 top30 等权(与前面价值实验对齐,便于横向比较)
公共宇宙过滤:剔 ST、剔次新(<250 交易日)、NOTICE_DATE-as-of 防 look-ahead。
仓位:等权 1/N,无止损/止盈/择时(纯基线,先看原生表现)。

== 4 组 ==
  G1 EarningsGrowth   营收 YoY≥20% 且 归母净利 YoY≥20%,按双增复合 z 排序  季度调仓
  G2 PriceMomentum    12-1 月价格动量 top30                              月度调仓
  G3 QualityGrowth    ROE≥15% 且 归母净利 YoY≥0,按 ROE 降序            季度调仓
  G4 EarningsMomentum 双增基本面 ∩ 正价格动量,按动量降序(基本面动量)  月度调仓

== 🚨 结论:全组证伪(2010-2026 A 股全市场,/tmp/growth_eval.py)==
按绝对年化排名,**四组全部失败**,与价值方向(C_full_t30 +11.5%/35%DD)不是一个量级:
  G1 盈利双增   +3.13% / 回撤 60.5% / Sharpe 0.13   (最好的一组,仍弱且深回撤)
  G3 质量成长   -5.69% / 回撤 73.0% / Sharpe -0.32
  G4 基本面动量 -6.13% / 回撤 80.6% / Sharpe -0.25
  G2 价格动量   -8.47% / 回撤 84.2% / Sharpe -0.41  (最差,纯动量在 A 股反转/失效)
根因(均为 A 股公认现象):①价格动量在 A 股反转失效;②高 ROE 无估值约束 = 买最贵优质
溢价股,均值回归;③盈利双增买在景气顶点,只在少数主题牛年(2015/2025)爆发后全吐回,
无持续性。反向印证:**A 股全周期超额主要来自估值锚(便宜),成长脱离估值即接盘。**
结果存档:logs/smoke/growth_eval.{log,json}。**不要再重复探索纯成长方向。**
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from services.backtest.strategy_base import Strategy
from services.backtest.strategies.utils import growth
from services.backtest.strategies.utils.st_filter import _is_st_on

# ---- 预先承诺的教科书常量(不搜索)----
GROWTH_THRESHOLD = 20.0      # 双增门槛 %
ROE_QUALITY_MIN = 15.0       # 质量 ROE 门槛 %
MOM_LOOKBACK = 250           # 动量回看(约 12 个月交易日)
MOM_SKIP = 20                # 跳过最近 1 个月(短期反转)
MIN_HISTORY_DAYS = 250       # 次新过滤:需 ≥ 250 个交易日
QUARTERLY_MONTHS = {3, 6, 9, 12}


def _z(values: np.ndarray) -> np.ndarray:
    if len(values) == 0:
        return values
    std = values.std()
    if std == 0 or np.isnan(std):
        return np.zeros_like(values)
    return (values - values.mean()) / std


def _mom_12_1(ctx, sym: str) -> Optional[float]:
    """12-1 月动量:[t-250, t-20] 区间收益,跳过最近 20 日。"""
    bars = ctx.get_history(sym, n=MOM_LOOKBACK + 1, period="daily")
    if not bars or len(bars) < MIN_HISTORY_DAYS:
        return None
    old = bars[0].get("close")
    recent = bars[-(MOM_SKIP + 1)].get("close")  # 跳过最近 MOM_SKIP 日
    if old is None or recent is None or float(old) <= 0:
        return None
    return float(recent) / float(old) - 1.0


class _GrowthBase(Strategy):
    """成长实验基类:公共宇宙过滤 + 等权调仓机制(无止损)。

    子类只需实现 `_select(ctx, symbols, cur_str) -> list[str]`(已选好的 top 列表)。
    """

    frequency = "monthly"
    frequency_overridable = False
    strategy_type = "strategy"
    rebalance_quarterly = True  # True=季度调仓([3,6,9,12]),False=月度

    params = {
        "top_n": {"default": 30, "type": "int", "label": "持仓数量"},
    }

    def __init__(self, param_overrides: dict = None):
        super().__init__(param_overrides)
        self._target_holdings: list[str] = []
        self._rebalance_pending = False

    # ---- 公共宇宙过滤:剔 ST + 剔次新 ----
    def _universe(self, ctx, symbols: list[str], cur_str: str) -> list[str]:
        out = []
        for sym in symbols:
            if _is_st_on(sym, cur_str):
                continue
            bars = ctx.get_history(sym, n=MIN_HISTORY_DAYS, period="daily")
            if not bars or len(bars) < MIN_HISTORY_DAYS:
                continue  # 次新/停牌数据不足
            out.append(sym)
        return out

    def _select(self, ctx, symbols: list[str], cur_str: str) -> list[str]:
        raise NotImplementedError

    def screen(self, ctx, symbols: list[str]) -> list[str]:
        cur_str = ctx.current_date
        if not cur_str:
            return []
        try:
            cur_d = date.fromisoformat(cur_str[:10])
        except (ValueError, TypeError):
            return []
        # 调仓频率门控
        if self.rebalance_quarterly and cur_d.month not in QUARTERLY_MONTHS:
            ctx.log_flow("growth.screen.skip", reason="not_rebalance_month")
            return []

        ctx.log_flow("growth.screen.start", input=len(symbols))
        universe = self._universe(ctx, symbols, cur_str)
        selected = self._select(ctx, universe, cur_str)[: int(self.p.top_n)]
        for sym in selected:
            ctx.log_pass(sym, "growth.screen.final")
        ctx.log_flow("growth.screen.done", input=len(symbols), passed=len(selected))

        self._target_holdings = selected
        self._rebalance_pending = True
        return selected

    # ---- 等权调仓(无止损/止盈)----
    def on_buy(self, ctx) -> None:
        if not self._rebalance_pending:
            return
        target = self._target_holdings
        if not target:
            self._rebalance_pending = False
            return
        eq = 1.0 / float(len(target))
        for sym in target:
            ctx.order_target_percent(sym, eq)
        self._rebalance_pending = False

    def on_sell(self, ctx) -> None:
        if not self._rebalance_pending:
            return
        target_set = set(self._target_holdings)
        for sym, pos in list(ctx.get_positions().items()):
            shares = pos.shares if hasattr(pos, "shares") else pos.get("shares", 0)
            if shares <= 0 or sym in target_set:
                continue
            ctx.order_shares(sym, -int(shares))
            try:
                ctx.target_symbols.discard(sym)
            except AttributeError:
                pass


class EarningsGrowthStrategy(_GrowthBase):
    """G1 盈利成长:营收 YoY≥20% 且 归母净利 YoY≥20%,按双增复合 z 排序。"""

    name = "成长G1·盈利双增(实验)"
    description = "营收+归母净利双 YoY≥20% 筛选,双增复合 z-score 排序取 top30,季度调仓。纯成长不看估值。"
    rebalance_quarterly = True

    def _select(self, ctx, symbols, cur_str):
        rows = []  # (sym, rev_yoy, np_yoy)
        for sym in symbols:
            m = growth.get_growth_metrics_as_of_notice(ctx, sym)
            if not m:
                continue
            rev = m.get("TOTALOPERATEREVETZ")
            npg = m.get("PARENTNETPROFITTZ")
            if rev is None or npg is None:
                continue
            if rev < GROWTH_THRESHOLD or npg < GROWTH_THRESHOLD:
                continue
            rows.append((sym, float(rev), float(npg)))
            ctx.record_factor(sym, "RevYoY", float(rev))
            ctx.record_factor(sym, "NpYoY", float(npg))
        if not rows:
            return []
        z_rev = _z(np.array([r[1] for r in rows]))
        z_np = _z(np.array([r[2] for r in rows]))
        scores = z_rev + z_np
        ranked = sorted(zip([r[0] for r in rows], scores.tolist()), key=lambda x: -x[1])
        return [s for s, _ in ranked]


class PriceMomentumStrategy(_GrowthBase):
    """G2 价格动量:12-1 月动量 top30,月度调仓。"""

    name = "成长G2·价格动量(实验)"
    description = "经典 12-1 月价格动量(250 日回报跳过最近 20 日),横截面取涨幅 top30,月度调仓。纯价格驱动。"
    rebalance_quarterly = False

    def _select(self, ctx, symbols, cur_str):
        rows = []
        for sym in symbols:
            mom = _mom_12_1(ctx, sym)
            if mom is None:
                continue
            rows.append((sym, mom))
            ctx.record_factor(sym, "Mom12_1", mom)
        ranked = sorted(rows, key=lambda x: -x[1])
        return [s for s, _ in ranked]


class QualityGrowthStrategy(_GrowthBase):
    """G3 质量成长:ROE≥15% 且 归母净利 YoY≥0,按 ROE 降序。"""

    name = "成长G3·质量成长(实验)"
    description = "ROE≥15% 且 归母净利 YoY≥0 筛选,按 ROE 降序取 top30,季度调仓。重质量不设估值上限。"
    rebalance_quarterly = True

    def _select(self, ctx, symbols, cur_str):
        rows = []
        for sym in symbols:
            m = growth.get_growth_metrics_as_of_notice(ctx, sym)
            if not m:
                continue
            roe = m.get("ROEJQ")
            npg = m.get("PARENTNETPROFITTZ")
            if roe is None or npg is None:
                continue
            if roe < ROE_QUALITY_MIN or npg < 0:
                continue
            rows.append((sym, float(roe)))
            ctx.record_factor(sym, "ROE", float(roe))
        ranked = sorted(rows, key=lambda x: -x[1])
        return [s for s, _ in ranked]


class EarningsMomentumStrategy(_GrowthBase):
    """G4 盈利成长×动量:双增基本面 ∩ 正价格动量,按动量降序(基本面动量)。"""

    name = "成长G4·基本面动量(实验)"
    description = "营收+净利双 YoY≥20% ∩ 12-1 月动量>0,按价格动量降序取 top30,月度调仓。基本面与价格双确认。"
    rebalance_quarterly = False

    def _select(self, ctx, symbols, cur_str):
        rows = []
        for sym in symbols:
            m = growth.get_growth_metrics_as_of_notice(ctx, sym)
            if not m:
                continue
            rev = m.get("TOTALOPERATEREVETZ")
            npg = m.get("PARENTNETPROFITTZ")
            if rev is None or npg is None:
                continue
            if rev < GROWTH_THRESHOLD or npg < GROWTH_THRESHOLD:
                continue
            mom = _mom_12_1(ctx, sym)
            if mom is None or mom <= 0:
                continue
            rows.append((sym, mom))
            ctx.record_factor(sym, "Mom12_1", mom)
        ranked = sorted(rows, key=lambda x: -x[1])
        return [s for s, _ in ranked]
