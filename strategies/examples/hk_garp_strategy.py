"""港股 GARP(合理价格成长股)策略 —— HkGarpStrategy。

目标:在全 H股(2734 只)2010-2026 上探索能否达到平均年化 ≥15%。

逻辑(GARP = Growth At Reasonable Price):
- **成长**:3 年归母净利 CAGR + 营收 CAGR(年报口径,发布滞后防 look-ahead)
- **质量**:年报 ROE 门槛(可选连续 N 年)
- **估值**:peTTM / pbMRQ(来自日线 bar,天然 point-in-time);PEG 上限
- **排序**:PEG 升序 / 成长降序 / 复合,取 Top N 等权,定期调仓完全替换

数据源:
- 成长/ROE:`strategies.utils.growth_hk`(v_hk_income + v_hk_indicator,发布滞后
  年报 +120 天 / 中报 +90 天,严防未来函数)
- 估值:`ctx.get_valuation`(日线 peTTM / pbMRQ,PIT)

⚠️ 已知偏差:数据仅含当前在市港股,**退市股缺失 → survivorship bias**,
   结果偏乐观。HK 无 ST 机制,不做 ST 过滤。
成交价口径:T+1 + (open+close)/2(项目铁律)。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from strategies.base import Strategy
from strategies.utils import growth_hk, hk_industry


class HkGarpStrategy(Strategy):
    name = "港股 GARP(成长+合理估值)"
    description = (
        "全 H股 GARP:3 年净利/营收 CAGR + ROE 质量门槛 + peTTM/PB 估值健康 → "
        "PEG 升序 Top N 等权,定期调仓。发布滞后防 look-ahead。目标 CAGR≥15%。"
    )
    frequency = "monthly"
    frequency_overridable = False
    strategy_type = "strategy"

    params = {
        "np_cagr_min": {
            "default": 0.15,
            "type": "float",
            "label": "3 年归母净利 CAGR 下限(小数)",
        },
        "rev_cagr_min": {
            "default": 0.10,
            "type": "float",
            "label": "3 年营收 CAGR 下限(小数)",
        },
        "cagr_years": {
            "default": 3,
            "type": "int",
            "label": "CAGR 回看年数",
        },
        "roe_min": {
            "default": 10.0,
            "type": "float",
            "label": "最新年报 ROE 下限(%)",
        },
        "roe_consistency_years": {
            "default": 0,
            "type": "int",
            "label": "连续 N 年 ROE≥下限(0=只看最新一年)",
        },
        "pe_max": {
            "default": 35.0,
            "type": "float",
            "label": "peTTM 上限(防泡沫)",
        },
        "peg_max": {
            "default": 1.5,
            "type": "float",
            "label": "PEG 上限(peTTM / 净利CAGR%)",
        },
        "peg_min": {
            "default": 0.0,
            "type": "float",
            "label": "PEG 下限(剔除超低 PEG 价值陷阱/周期股,0=不过滤)",
        },
        "require_pb_positive": {
            "default": True,
            "type": "bool",
            "label": "要求 pbMRQ>0",
        },
        "min_amount_hkd": {
            "default": 0.0,
            "type": "float",
            "label": "近 N 日日均成交额下限(HKD,0=不过滤)",
        },
        "amount_lookback": {
            "default": 60,
            "type": "int",
            "label": "成交额回看交易日",
        },
        "top_n": {
            "default": 20,
            "type": "int",
            "label": "持仓数量",
        },
        "sort_by": {
            "default": "peg",
            "type": "str",
            "label": "排序键:peg | growth | composite | momentum(动量降序) | reversal(反转) | garp_mom(GARP+动量复合)",
        },
        "trend_ma_days": {
            "default": 0,
            "type": "int",
            "label": "趋势过滤:要求 close > N 日均线(0=不过滤)",
        },
        "momentum_days": {
            "default": 0,
            "type": "int",
            "label": "动量回看交易日(用于排序/过滤,0=不算)",
        },
        "min_momentum": {
            "default": -1.0,
            "type": "float",
            "label": "动量下限(过去 momentum_days 涨幅,小数;-1=不过滤)",
        },
        "require_industry": {
            "default": False,
            "type": "bool",
            "label": "仅保留有行业分类的标的(yfinance 覆盖≈龙头/大盘代理)",
        },
        "max_per_sector": {
            "default": 0,
            "type": "int",
            "label": "每个一级行业最多持仓数(0=不限,行业龙头分散)",
        },
        "max_valuation_staleness_days": {
            "default": 10,
            "type": "int",
            "label": "估值数据时效上限(交易日,防退市股 stale)",
        },
        "rebalance_months": {
            "default": [5, 11],
            "type": "list[int]",
            "label": "调仓月份(每年这些月的第一个交易日)",
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

        np_cagr_min = float(self.p.np_cagr_min)
        rev_cagr_min = float(self.p.rev_cagr_min)
        cagr_years = int(self.p.cagr_years)
        roe_min = float(self.p.roe_min)
        roe_years = int(self.p.roe_consistency_years)
        pe_max = float(self.p.pe_max)
        peg_max = float(self.p.peg_max)
        peg_min = float(self.p.peg_min)
        require_pb = bool(self.p.require_pb_positive)
        min_amount = float(self.p.min_amount_hkd)
        amt_lookback = int(self.p.amount_lookback)
        top_n = int(self.p.top_n)
        sort_key = str(self.p.sort_by).lower()
        staleness_days = int(self.p.max_valuation_staleness_days)
        trend_ma_days = int(self.p.trend_ma_days)
        momentum_days = int(self.p.momentum_days)
        min_momentum = float(self.p.min_momentum)
        require_industry = bool(self.p.require_industry)
        max_per_sector = int(self.p.max_per_sector)

        # 单次取够长的历史窗口同时算流动性 / 趋势 / 动量, 避免重复 get_history
        need_hist = max(
            amt_lookback if min_amount > 0 else 0,
            trend_ma_days,
            momentum_days + 1,
        )

        # ---- Stage 1: 估值健康(PIT)+ 时效 + 流动性 + 趋势/动量(全用日线 bar)----
        stage1: list[tuple[str, float, float]] = []  # (sym, pe, momentum)
        for sym in symbols:
            # 行业龙头代理:只保留有行业分类的标的(yfinance 覆盖偏大盘/龙头)
            if require_industry and not hk_industry.has_classification(sym):
                continue
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
            if pe is None or pd.isna(pe) or pe <= 0 or pe > pe_max:
                continue
            if require_pb:
                pb = val.get("pbMRQ")
                if pb is None or pd.isna(pb) or pb <= 0:
                    continue

            momentum = 0.0
            if need_hist > 0:
                bars = ctx.get_history(sym, n=need_hist, period="daily")
                if not bars:
                    continue
                closes = [
                    b["close"]
                    for b in bars
                    if b.get("close") is not None and not pd.isna(b["close"])
                ]
                if not closes:
                    continue
                # 流动性:近 amt_lookback 日 volume×close 均值(HKD,amount 列恒0 故用代理)
                if min_amount > 0:
                    amts = [
                        b["volume"] * b["close"]
                        for b in bars[-amt_lookback:]
                        if b.get("volume") is not None
                        and b.get("close") is not None
                        and not pd.isna(b["volume"])
                        and not pd.isna(b["close"])
                    ]
                    if not amts or (sum(amts) / len(amts)) < min_amount:
                        continue
                # 趋势过滤:current close > N 日均线
                if trend_ma_days > 0:
                    ma_win = closes[-trend_ma_days:]
                    if len(ma_win) < trend_ma_days:
                        continue  # 历史不足, 谨慎剔除
                    if closes[-1] <= sum(ma_win) / len(ma_win):
                        continue
                # 动量:过去 momentum_days 涨幅
                if momentum_days > 0 and len(closes) > momentum_days:
                    base = closes[-(momentum_days + 1)]
                    if base and base > 0:
                        momentum = closes[-1] / base - 1.0
                        if momentum < min_momentum:
                            continue
            stage1.append((sym, float(pe), momentum))
        ctx.log_flow("strategy.valuation_liquidity_trend", passed=len(stage1))

        # ---- Stage 2: 成长 + 质量(发布滞后,防 look-ahead)----
        stage2: list[tuple[str, float, float, float]] = []  # (sym, pe, np_cagr, mom)
        for sym, pe, momentum in stage1:
            np_cagr = growth_hk.net_profit_cagr(sym, cur_str, years=cagr_years)
            if np_cagr is None or np_cagr < np_cagr_min:
                continue
            rev_cagr = growth_hk.revenue_cagr(sym, cur_str, years=cagr_years)
            if rev_cagr is None or rev_cagr < rev_cagr_min:
                continue
            if roe_years > 0:
                if not growth_hk.all_annual_roe_above(
                    sym, cur_str, roe_min, years=roe_years
                ):
                    continue
            else:
                roe = growth_hk.annual_roe(sym, cur_str)
                if roe is None or roe < roe_min:
                    continue
            stage2.append((sym, pe, np_cagr, momentum))
            ctx.record_factor(sym, "NP_CAGR", np_cagr)
            ctx.record_factor(sym, "REV_CAGR", rev_cagr)

        ctx.log_flow("strategy.growth_quality", passed=len(stage2))

        # ---- Stage 3: PEG 上限 ----
        stage3: list[tuple[str, float, float, float]] = []  # (sym, peg, np_cagr, mom)
        for sym, pe, np_cagr, momentum in stage2:
            cagr_pct = np_cagr * 100.0
            if cagr_pct <= 0:
                continue
            peg = pe / cagr_pct
            if peg <= 0 or peg > peg_max or peg < peg_min:
                continue
            stage3.append((sym, peg, np_cagr, momentum))
            ctx.record_factor(sym, "PE", pe)
            ctx.record_factor(sym, "PEG", peg)
            if momentum_days > 0:
                ctx.record_factor(sym, "MOM", momentum)
        ctx.log_flow("strategy.peg", passed=len(stage3))

        # ---- Stage 4: 排序 + Top N ----
        if sort_key == "growth":
            stage3.sort(key=lambda x: -x[2])
        elif sort_key == "momentum":
            stage3.sort(key=lambda x: -x[3])  # 动量降序(追强)
        elif sort_key == "reversal":
            stage3.sort(key=lambda x: x[3])  # 动量升序(抄弱/反转)
        elif sort_key in ("composite", "garp_mom"):
            # rank 之和:低 PEG + 高成长 (+ garp_mom 再叠高动量)
            by_peg = sorted(stage3, key=lambda x: x[1])
            by_g = sorted(stage3, key=lambda x: -x[2])
            rank: dict[str, int] = {}
            for i, t in enumerate(by_peg):
                rank[t[0]] = rank.get(t[0], 0) + i
            for i, t in enumerate(by_g):
                rank[t[0]] = rank.get(t[0], 0) + i
            if sort_key == "garp_mom":
                by_m = sorted(stage3, key=lambda x: -x[3])
                for i, t in enumerate(by_m):
                    rank[t[0]] = rank.get(t[0], 0) + i
            stage3.sort(key=lambda x: rank[x[0]])
        else:
            stage3.sort(key=lambda x: x[1])  # peg 升序

        # ---- 行业龙头分散:每个一级行业最多 max_per_sector 只(贪心,保排序优先级)----
        if max_per_sector > 0:
            sector_count: dict[str, int] = {}
            capped: list[tuple[str, float, float, float]] = []
            for t in stage3:
                sec = hk_industry.get_sector(t[0]) or "__UNKNOWN__"
                if sector_count.get(sec, 0) >= max_per_sector:
                    continue
                sector_count[sec] = sector_count.get(sec, 0) + 1
                capped.append(t)
                if len(capped) >= top_n:
                    break
            stage3 = capped
        selected = [sym for sym, _, _, _ in stage3[:top_n]]
        for sym in selected:
            sec = hk_industry.get_sector(sym)
            if sec:
                ctx.record_factor(sym, "SECTOR", sec)
        for sym in selected:
            ctx.log_pass(sym, "strategy.screen.final")

        ctx.log_flow("strategy.screen.done", input=len(symbols), passed=len(selected))

        self._target_holdings = selected
        self._rebalance_pending = True
        return selected

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
        self._rebalance_pending = False
