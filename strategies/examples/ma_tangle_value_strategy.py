"""月线均线缠绕价值策略(MaTangleValueStrategy)。

合并 5 个原策略 + PE 多轮分批卖出退出(2026-05-24 第二次重构):
- DividendYearsScreener     → utils.dividend.filter_by_dividend_years
- PE 区间筛选               → utils.valuation.filter_by_pe(只看 PE)
- RoeScreener               → utils.financial.filter_by_roe
- MaTangleBreakoutScreener  → utils.kline.detect_ma_tangle_breakout
- MarketCapWeightedBuyer    → utils.composite.MarketCapWeightedBatchBuyer

卖出策略(2026-05-24 PE 多轮分批):
- 模式判定(首次触发时锁定):
    - 30 < PE ≤ 40 → two_stage(总最多 2 轮:15% + 20%)
    - PE > 40        → chain(15% + 20% × N,直到清仓)
- 第 1 轮触发:PE > 30,锚点 P_1 = 当日 daily (h+l)/2,total = initial × 15%。
- 第 N+1 轮触发:任意已有锚点满足 daily (h+l)/2 > P_n × 1.05 且模式允许新轮。
                  锚点锁定避免重复触发;新轮 anchor = 触发日 daily (h+l)/2,
                  total = initial × 20%。
- 4 周分批:前 3 批 floor(total/4),最后批吃尾差。
    - 第 1 批:触发当日,price = daily (h+l)/2
    - 第 2-4 批:之后每个新 ISO 周的周一,price = ctx.get_price(sym, "weekly") 的 (h+l)/2
- 多轮并行:每轮独立 schedule,可同周共存(轮号小的先发)。
- 链式清仓:当批量超过剩余持仓 → 卖光为止。

PE 缺失保守不卖。持仓上限 max_holdings:已持仓达上限时跳过新分批买入。
"""

from __future__ import annotations

from datetime import date, datetime

from strategies.base import Strategy
from strategies.utils import dividend, valuation, financial, kline
from strategies.utils.composite.market_cap_weighted_batch_buyer import (
    MarketCapWeightedBatchBuyer,
)


def _iso_week_key(d: str | date | datetime) -> tuple[int, int]:
    """ISO 周键 (year, week)。"""
    if isinstance(d, str):
        dd = date.fromisoformat(d[:10])
    elif isinstance(d, datetime):
        dd = d.date()
    else:
        dd = d
    iso = dd.isocalendar()
    # date.isocalendar() 在 3.10 返回 IsoCalendarDate(可索引)
    return (int(iso[0]), int(iso[1]))


class MaTangleValueStrategy(Strategy):
    name = "月线均线缠绕价值策略"
    description = (
        "基本面池(连续分红 + PE 区间 + ROE 达标)与月线均线缠绕突破信号交集,"
        "命中后按市值加权 8 周分批买入;PE 高估时多轮 4 周分批退出"
        "(30<PE≤40 两轮共 35%,PE>40 链式 15%+20%×N 直到清仓)。"
    )
    frequency = "monthly"
    frequency_overridable = False

    params = {
        # ===== 选股参数 =====
        "min_dividend_years": {"default": 5, "type": "int", "label": "最少分红年数"},
        "pe_min": {"default": 0.0, "type": "float", "label": "PE最小值"},
        "pe_max": {"default": 22.0, "type": "float", "label": "PE最大值"},
        "min_roe": {"default": 10.0, "type": "float", "label": "最低 ROE(%)"},
        "ma_fast": {"default": 5, "type": "int", "label": "快速均线"},
        "ma_mid": {"default": 10, "type": "int", "label": "中速均线"},
        "ma_slow": {"default": 20, "type": "int", "label": "慢速均线"},
        "tangle_threshold": {"default": 0.05, "type": "float", "label": "缠绕阈值"},
        "tangle_months": {"default": 2, "type": "int", "label": "缠绕月数"},
        "spread_months": {"default": 6, "type": "int", "label": "发散月数"},
        "spread_threshold": {"default": 0.01, "type": "float", "label": "发散阈值"},
        "vol_red_bars": {"default": 4, "type": "int", "label": "连阳根数"},
        # ===== 仓位 / 买入参数 =====
        "buy_weeks": {"default": 8, "type": "int", "label": "分批周数"},
        "max_holdings": {"default": 20, "type": "int", "label": "最大持股只数"},
        # ===== PE 多轮分批卖出参数(2026-05-24)=====
        "pe_sell_enabled": {
            "default": True,
            "type": "bool",
            "label": "启用 PE 多轮分批卖出",
        },
        "pe_sell_threshold": {
            "default": 30.0,
            "type": "float",
            "label": "PE 触发阈值(PE 高于此值才卖)",
        },
        "pe_sell_chain_threshold": {
            "default": 40.0,
            "type": "float",
            "label": "链式模式 PE 阈值(PE > 此值进入链式清仓)",
        },
        "pe_sell_pct1": {
            "default": 0.15,
            "type": "float",
            "label": "第 1 轮卖出比例(初始持仓)",
        },
        "pe_sell_pct_n": {
            "default": 0.20,
            "type": "float",
            "label": "第 2 轮起卖出比例(初始持仓)",
        },
        "pe_sell_breakout_pct": {
            "default": 0.05,
            "type": "float",
            "label": "新轮触发突破阈值(P_n 之上)",
        },
        "pe_sell_batches": {
            "default": 4,
            "type": "int",
            "label": "每轮分批数(默认 4 周 4 批)",
        },
    }

    def __init__(self, param_overrides=None):
        super().__init__(param_overrides)
        # 在 __init__ 内根据参数初始化分批买入器,buy_weeks 可被外部覆盖
        self._buyer = MarketCapWeightedBatchBuyer(buy_weeks=self.p.buy_weeks)
        # 卖出状态(per-symbol):
        # {
        #   "mode": "two_stage" | "chain",
        #   "initial_shares": int,
        #   "schedules": [
        #       {
        #           "round": 1, "anchor_p": float, "total_shares": int,
        #           "batches_done": int, "batches_remaining": int,
        #           "last_batch_week": (year, week) | None,
        #           "triggered_next": bool,  # 是否已用此锚点启动过下一轮
        #       }, ...
        #   ]
        # }
        self._sell_state: dict[str, dict] = {}

    def screen(self, ctx, symbols):
        ctx.log_flow("strategy.screen.start", input=len(symbols))

        # 顺序:廉价数据先,昂贵 K 线后
        pool = dividend.filter_by_dividend_years(
            ctx, symbols, min_years=self.p.min_dividend_years
        )
        pool = valuation.filter_by_pe(
            ctx,
            pool,
            min_value=self.p.pe_min,
            max_value=self.p.pe_max,
        )
        pool = financial.filter_by_roe(ctx, pool, min_roe=self.p.min_roe)
        ctx.log_flow("strategy.fundamental_pool", passed=len(pool))

        signals = []
        for sym in pool:
            if kline.detect_ma_tangle_breakout(
                ctx,
                sym,
                fast=self.p.ma_fast,
                mid=self.p.ma_mid,
                slow=self.p.ma_slow,
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

    # ===== 买入:max_holdings 限制由 buyer.step 内自检 =====
    def on_buy(self, ctx):
        self._buyer.step(ctx, max_holdings=self.p.max_holdings)

    # ===== 卖出:PE 多轮分批 =====
    def on_sell(self, ctx):
        if not self.p.pe_sell_enabled:
            return
        cur_date = getattr(ctx, "current_date", None)
        if not cur_date:
            return

        positions = list(ctx.get_positions().items())
        for sym, pos in positions:
            shares = pos.shares if hasattr(pos, "shares") else pos.get("shares", 0)
            if shares <= 0:
                continue
            self._process_symbol(ctx, sym, shares, cur_date)

    # ----- 单 symbol 处理 -----
    def _process_symbol(self, ctx, sym: str, shares: int, cur_date: str) -> None:
        state = self._sell_state.get(sym)
        daily = ctx.get_price(sym, period="daily")
        daily_mid = self._mid(daily) if daily else None

        # 1) 尚未触发 → 检查首次触发(PE > threshold)
        if state is None:
            if daily_mid is None:
                return
            pe = valuation.get_pe(ctx, sym)
            if pe is None or pe <= float(self.p.pe_sell_threshold):
                return
            mode = (
                "chain" if pe > float(self.p.pe_sell_chain_threshold) else "two_stage"
            )
            state = {
                "mode": mode,
                "initial_shares": int(shares),
                "schedules": [],
            }
            self._sell_state[sym] = state
            self._start_new_round(state, anchor_p=daily_mid, round_no=1)
            # 第 1 批立即发(用 daily mid)
            self._fire_batch(
                ctx, sym, state["schedules"][-1], price=daily_mid, cur_date=cur_date
            )
            return

        # 2) 已有 state:先推进现有 schedules 的批次(轮号小的先发),
        #    再检查是否启动新轮(确保同周老轮 batch 早于新轮 batch1)
        for sch in state["schedules"]:
            self._advance_schedule(ctx, sym, sch, cur_date)

        if daily_mid is not None:
            self._maybe_start_new_round(ctx, sym, state, daily_mid, cur_date)

    # ----- 启动新一轮 -----
    def _maybe_start_new_round(
        self, ctx, sym: str, state: dict, daily_mid: float, cur_date: str
    ) -> None:
        # 模式上限
        if state["mode"] == "two_stage" and len(state["schedules"]) >= 2:
            return
        # 找尚未触发过 next 的锚点中,daily_mid > anchor*1.05 的最早一个
        threshold_factor = 1.0 + float(self.p.pe_sell_breakout_pct)
        for sch in state["schedules"]:
            if sch.get("triggered_next"):
                continue
            if daily_mid > sch["anchor_p"] * threshold_factor:
                sch["triggered_next"] = True
                round_no = len(state["schedules"]) + 1
                self._start_new_round(state, anchor_p=daily_mid, round_no=round_no)
                # 新轮第 1 批立刻发(本日 daily mid)
                self._fire_batch(
                    ctx,
                    sym,
                    state["schedules"][-1],
                    price=daily_mid,
                    cur_date=cur_date,
                )
                return  # 一次 on_sell 最多启动一个新轮

    def _start_new_round(self, state: dict, anchor_p: float, round_no: int) -> None:
        pct = (
            float(self.p.pe_sell_pct1) if round_no == 1 else float(self.p.pe_sell_pct_n)
        )
        total = int(state["initial_shares"] * pct)
        batches = int(self.p.pe_sell_batches)
        state["schedules"].append(
            {
                "round": round_no,
                "anchor_p": float(anchor_p),
                "total_shares": total,
                "batches_done": 0,
                "batches_remaining": batches,
                "last_batch_week": None,
                "triggered_next": False,
            }
        )

    # ----- 推进 schedule:第 2-4 批在新 ISO 周的周一发 -----
    def _advance_schedule(self, ctx, sym: str, sch: dict, cur_date: str) -> None:
        if sch["batches_remaining"] <= 0:
            return
        if sch["last_batch_week"] is None:
            return  # 还没发过任何批(_fire_batch 应已处理),保险
        cur_week = _iso_week_key(cur_date)
        if cur_week == sch["last_batch_week"]:
            return  # 同周不再发
        if cur_week <= sch["last_batch_week"]:
            return  # 倒退保护
        # 进入新周 → 用 weekly bar 的 (h+l)/2
        weekly = ctx.get_price(sym, period="weekly")
        if not weekly:
            return
        price = self._mid(weekly)
        if price is None:
            return
        self._fire_batch(ctx, sym, sch, price=price, cur_date=cur_date)

    # ----- 发批 -----
    def _fire_batch(
        self, ctx, sym: str, sch: dict, price: float, cur_date: str
    ) -> None:
        batches_total = int(self.p.pe_sell_batches)
        # 计算本批股数
        if sch["batches_remaining"] == 1:
            # 最后批吃尾差
            per = sch["total_shares"] // batches_total
            shares = sch["total_shares"] - per * (batches_total - 1)
        else:
            shares = sch["total_shares"] // batches_total
        if shares <= 0:
            sch["batches_remaining"] = 0
            return

        # 链式清仓:本批超过剩余持仓 → 卖光为止
        positions = ctx.get_positions()
        pos = positions.get(sym)
        cur_shares = (
            pos.shares
            if pos is not None and hasattr(pos, "shares")
            else (pos.get("shares", 0) if pos else 0)
        )
        if shares > cur_shares:
            shares = int(cur_shares)
        if shares <= 0:
            sch["batches_remaining"] = 0
            return

        ctx.order_shares(sym, -shares)
        sch["batches_done"] += 1
        sch["batches_remaining"] -= 1
        sch["last_batch_week"] = _iso_week_key(cur_date)

        if hasattr(ctx, "log_exec"):
            ctx.log_exec(
                "sell_signal",
                sym,
                shares=shares,
                price=float(price),
                note=(
                    f"R{sch['round']} batch{sch['batches_done']}/"
                    f"{batches_total} anchor={sch['anchor_p']:.2f} "
                    f"price={price:.2f}"
                ),
            )

    # ----- 工具:bar (h+l)/2 -----
    @staticmethod
    def _mid(bar: dict | None) -> float | None:
        if not bar:
            return None
        try:
            return (float(bar["high"]) + float(bar["low"])) / 2.0
        except (KeyError, TypeError, ValueError):
            return None
