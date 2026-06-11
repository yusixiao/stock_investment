"""GARP 季度调仓策略(GarpQuarterlyStrategy)v1。

Peter Lynch 风格:合理价格的成长股(Growth At Reasonable Price)。

筛选(每年 5/9/11 月初,与 LowValuationQuarterlyStrategy 调仓节奏对齐):
1. 营收 TTM YOY ≥ revenue_yoy_min(默认 20%)
2. 扣非净利润 TTM YOY ≥ deduct_profit_yoy_min(默认 25%)
3. ROE(年报口径)≥ roe_min(默认 12%)
4. 净现比(经营现金流 / 净利润)≥ ocf_to_np_min(默认 0.7,防应收堆出来的伪成长)
5. 排除 ST、peTTM<=0、PB<=0
6. 估值时效性检查(防退市股 stale 数据,沿用低估值策略思路)

排序:
- PEG = peTTM / 扣非净利润 YOY,升序
- 强制 PEG > 0(剔除负利润),且 ≤ peg_max(默认 1.5)

持仓:
- 前 top_n(默认 15)只,等权 1/N
- 调仓 = 完全替换:不在新目标里的清仓,目标里 order_target_percent

数据源:
- 财务/成长指标:DuckDB v_a_indicator(NOTICE_DATE-aware,防 look-ahead)
- 估值:ctx.get_valuation(peTTM, pbMRQ)
- ST:_is_st_on(复用 LowValuationQuarterlyStrategy 缓存模式)

成交价口径:T+1 + (open+close)/2(项目铁律)。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from strategies.base import Strategy
from strategies.utils import financial, growth
from strategies.examples.low_valuation_quarterly_strategy import _is_st_on


class GarpQuarterlyStrategy(Strategy):
    name = "GARP 季度调仓"
    description = (
        "合理价格的成长股(GARP):营收/扣非净利双增长 + ROE + 净现比四联门槛 → "
        "PEG 升序取前 N 等权。每年 5/9/11 月初调仓。v1 标准档参数:"
        "营收YOY≥20%、扣非净利YOY≥25%、ROE≥12%、净现比≥0.7、PEG≤1.5、Top15。"
    )
    frequency = "monthly"
    frequency_overridable = False
    strategy_type = "strategy"

    params = {
        "revenue_yoy_min": {
            "default": 20.0,
            "type": "float",
            "label": "营收 TTM YOY 下限(%)",
        },
        "deduct_profit_yoy_min": {
            "default": 25.0,
            "type": "float",
            "label": "扣非净利润 TTM YOY 下限(%)",
        },
        "roe_min": {
            "default": 12.0,
            "type": "float",
            "label": "ROE 下限(%,年报口径)",
        },
        "ocf_to_np_min": {
            "default": 0.7,
            "type": "float",
            "label": "净现比下限(经营现金流/净利润)",
        },
        "peg_max": {
            "default": 1.5,
            "type": "float",
            "label": "PEG 上限(peTTM/扣非净利YOY)",
        },
        "top_n": {
            "default": 15,
            "type": "int",
            "label": "持仓数量",
        },
        "max_valuation_staleness_days": {
            "default": 5,
            "type": "int",
            "label": "估值数据时效上限(交易日,防退市股)",
        },
        "rebalance_months": {
            "default": [5, 9, 11],
            "type": "list[int]",
            "label": "调仓月份(每年这些月的第一个交易日)",
        },
        # ---- 可选增强(默认关闭,做 ablation 用)----
        "momentum_lookback_days": {
            "default": 0,
            "type": "int",
            "label": "动量回看交易日数(0=不计算动量)",
        },
        "momentum_drop_pct": {
            "default": 0.0,
            "type": "float",
            "label": "剔除动量最差分位(0=不剔除,如 0.2 = 剔最差 20%)",
        },
        "sort_by": {
            "default": "peg",
            "type": "str",
            "label": "排序键:peg(升序) | momentum(降序)",
        },
    }

    def __init__(self, param_overrides: dict | None = None):
        super().__init__(param_overrides)
        self._target_holdings: list[str] = []
        self._rebalance_pending: bool = False

    def screen(self, ctx, symbols: list[str]) -> list[str]:
        cur_str = ctx.current_date
        if not cur_str:
            return []
        try:
            cur_d = date.fromisoformat(cur_str[:10])
        except (ValueError, TypeError):
            return []

        rebal_months = self.p.rebalance_months
        if isinstance(rebal_months, str):
            rebal_months = [int(x) for x in rebal_months.split(",") if x.strip()]
        if cur_d.month not in set(rebal_months):
            ctx.log_flow("strategy.screen.skip", reason="not_rebalance_month")
            return []

        ctx.log_flow("strategy.screen.start", input=len(symbols))

        rev_min = float(self.p.revenue_yoy_min)
        dp_min = float(self.p.deduct_profit_yoy_min)
        roe_min = float(self.p.roe_min)
        ocf_min = float(self.p.ocf_to_np_min)
        peg_max = float(self.p.peg_max)
        top_n = int(self.p.top_n)
        staleness_days = int(self.p.max_valuation_staleness_days)

        # ---- Stage 1: 估值健康 + ST + 时效性 ----
        # 拿到 peTTM 是后面算 PEG 的必备,所以先做估值层
        stage1: list[tuple[str, float, float]] = []  # (sym, pe, pb)
        for sym in symbols:
            val = ctx.get_valuation(sym) if hasattr(ctx, "get_valuation") else None
            if val is None:
                continue
            val_date = val.get("date")
            if val_date is not None:
                try:
                    vd = date.fromisoformat(str(val_date)[:10])
                    if (cur_d - vd).days > staleness_days * 2:
                        continue
                except (ValueError, TypeError):
                    pass
            pe = val.get("peTTM")
            pb = val.get("pbMRQ")
            if pd.isna(pe) or pe is None or pe <= 0:
                continue
            if pd.isna(pb) or pb is None or pb <= 0:
                continue
            if _is_st_on(sym, cur_str):
                continue
            stage1.append((sym, float(pe), float(pb)))
        ctx.log_flow("strategy.valuation_st", passed=len(stage1))

        # ---- Stage 2: 成长四联门槛 ----
        # 成长指标走 NOTICE_DATE-aware lookup,严防 look-ahead
        # ROE 用年报口径(沿用低估值策略思路:5月调仓时Q1ROEJQ仅2-4%,易系统性踏空)
        stage2: list[tuple[str, float, float]] = []  # (sym, pe, dp_yoy)
        for sym, pe, _pb in stage1:
            metrics = growth.get_growth_metrics_as_of_notice(ctx, sym)
            if metrics is None:
                continue
            rev_yoy = metrics.get("TOTALOPERATEREVETZ")
            dp_yoy = metrics.get("KCFJCXSYJLRTZ")
            ocf_np = metrics.get("NCO_NETPROFIT")
            # ROE 走年报口径,不用 metrics["ROEJQ"](后者可能是 Q1 累计)
            roe = financial.get_roe_annual_as_of_notice(ctx, sym)

            if rev_yoy is None or rev_yoy < rev_min:
                continue
            if dp_yoy is None or dp_yoy < dp_min:
                continue
            if roe is None or roe < roe_min:
                continue
            if ocf_np is None or ocf_np < ocf_min:
                continue

            stage2.append((sym, pe, dp_yoy))
            ctx.record_factor(sym, "RevenueYOY", rev_yoy)
            ctx.record_factor(sym, "DeductProfitYOY", dp_yoy)
            ctx.record_factor(sym, "ROE", roe)
            ctx.record_factor(sym, "OCF/NP", ocf_np)
        ctx.log_flow("strategy.growth_quality", passed=len(stage2))

        # ---- Stage 3: PEG 计算 + 上限 ----
        stage3: list[tuple[str, float]] = []  # (sym, peg)
        for sym, pe, dp_yoy in stage2:
            if dp_yoy <= 0:
                continue
            peg = pe / dp_yoy
            if peg <= 0 or peg > peg_max:
                continue
            stage3.append((sym, peg))
            ctx.record_factor(sym, "PEG", peg)
        ctx.log_flow("strategy.peg", passed=len(stage3))

        # ---- Stage 3.5: 动量计算(可选)----
        # lookback>0 时计算每只股票过去 N 个交易日的累计涨跌幅
        # drop_pct>0 时剔除最差分位(借鉴低估值策略的反趋势保护)
        # sort_by=='momentum' 时改用动量降序选股(CANSLIM 风格)
        lookback = int(self.p.momentum_lookback_days)
        drop_pct = float(self.p.momentum_drop_pct)
        sort_key = str(self.p.sort_by).lower()

        sym_to_mom: dict[str, float] = {}
        if lookback > 0 and stage3:
            for sym, _peg in stage3:
                bars = ctx.get_history(sym, n=lookback + 1, period="daily")
                if not bars or len(bars) < 2:
                    continue
                old_close = bars[0].get("close")
                new_close = bars[-1].get("close")
                if old_close is None or new_close is None or float(old_close) <= 0:
                    continue
                mom = float(new_close) / float(old_close) - 1.0
                sym_to_mom[sym] = mom
                ctx.record_factor(sym, f"Mom{lookback}D", mom)

            # 剔除最差分位
            if drop_pct > 0 and sym_to_mom:
                import numpy as np

                moms = np.array(list(sym_to_mom.values()))
                cutoff = float(np.quantile(moms, drop_pct))
                stage3 = [
                    (s, p)
                    for s, p in stage3
                    if s in sym_to_mom and sym_to_mom[s] >= cutoff
                ]
                ctx.log_flow("strategy.momentum_filter", passed=len(stage3))

        # ---- Stage 4: 排序 + 取 top_n ----
        if sort_key == "momentum" and sym_to_mom:
            # 动量降序;无动量数据的排最后
            stage3.sort(key=lambda x: -sym_to_mom.get(x[0], -float("inf")))
        else:
            # 默认 PEG 升序
            stage3.sort(key=lambda x: x[1])
        selected = [sym for sym, _ in stage3[:top_n]]
        for sym in selected:
            ctx.log_pass(sym, "strategy.screen.final")

        ctx.log_flow(
            "strategy.screen.done",
            input=len(symbols),
            passed=len(selected),
        )

        self._target_holdings = selected
        self._rebalance_pending = True
        return selected

    def on_sell(self, ctx) -> None:
        if not self._rebalance_pending:
            return
        target_set = set(self._target_holdings)
        positions = list(ctx.get_positions().items())
        for sym, pos in positions:
            shares = pos.shares if hasattr(pos, "shares") else pos.get("shares", 0)
            if shares <= 0:
                continue
            if sym in target_set:
                continue
            ctx.order_shares(sym, -int(shares))
            try:
                ctx.target_symbols.discard(sym)
            except AttributeError:
                pass
            if hasattr(ctx, "log_exec"):
                price = ctx.get_price(sym)
                px = float(price["close"]) if price and price.get("close") else 0.0
                ctx.log_exec(
                    "rebalance_sell",
                    sym,
                    shares=int(shares),
                    price=px,
                    note="not_in_new_target",
                )

    def on_buy(self, ctx) -> None:
        if not self._rebalance_pending:
            return
        target = self._target_holdings
        if not target:
            self._rebalance_pending = False
            return
        target_pct = 1.0 / float(len(target))
        for sym in target:
            ctx.order_target_percent(sym, target_pct)
            if hasattr(ctx, "log_pass"):
                ctx.log_pass(sym, "strategy.rebalance_buy", target_pct=target_pct)
        self._rebalance_pending = False
