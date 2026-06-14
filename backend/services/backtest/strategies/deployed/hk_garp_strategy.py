"""港股 GARP(合理价格成长股)策略 —— HkGarpStrategy。

目标:在全 H股(2734 只)2010-2026 上探索能否达到平均年化 ≥15%。

逻辑(GARP = Growth At Reasonable Price):
- **成长**:3 年归母净利 CAGR + 营收 CAGR(年报口径,发布滞后防 look-ahead)
- **质量**:年报 ROE 门槛(可选连续 N 年)
- **估值**:peTTM / pbMRQ(来自日线 bar,天然 point-in-time);PEG 上限
- **排序**:PEG 升序 / 成长降序 / 复合,取 Top N 等权,定期调仓完全替换

数据源:
- 成长/ROE:`services.backtest.strategies.utils.growth_hk`(v_hk_income + v_hk_indicator,发布滞后
  年报 +120 天 / 中报 +90 天,严防未来函数)
- 估值:`ctx.get_valuation`(日线 peTTM / pbMRQ,PIT)

⚠️ 已知偏差:数据仅含当前在市港股,**退市股缺失 → survivorship bias**,
   结果偏乐观。HK 无 ST 机制,不做 ST 过滤。
成交价口径:T+1 + (open+close)/2(项目铁律)。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from services.backtest.strategy_base import Strategy
from services.backtest.strategies.utils import growth_hk, hk_industry


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
            "default": 5,
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
            "default": 15.0,
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
            "default": 1e7,
            "type": "float",
            "label": "近 N 日日均成交额下限(HKD,0=不过滤)",
        },
        "amount_lookback": {
            "default": 60,
            "type": "int",
            "label": "成交额回看交易日",
        },
        "top_n": {
            "default": 12,
            "type": "int",
            "label": "持仓数量",
        },
        "sort_by": {
            "default": "peg",
            "type": "str",
            "label": "排序键:peg | growth | composite | momentum(动量降序) | reversal(反转) | garp_mom(GARP+动量复合)",
        },
        "trend_ma_days": {
            "default": 90,
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
            "default": True,
            "type": "bool",
            "label": "仅保留有行业分类的标的(yfinance 覆盖≈龙头/大盘代理)",
        },
        "max_per_sector": {
            "default": 2,
            "type": "int",
            "label": "每个一级行业最多持仓数(0=不限,行业龙头分散)",
        },
        "max_valuation_staleness_days": {
            "default": 10,
            "type": "int",
            "label": "估值数据时效上限(交易日,防退市股 stale)",
        },
        "rebalance_months": {
            "default": [6],
            "type": "list[int]",
            "label": "调仓月份(每年这些月的第一个交易日)",
        },
        # ---- R18: HSI 市场 regime 择时(降回撤)----
        "risk_off_exposure": {
            "default": 1.0,
            "type": "float",
            "label": "risk-off(熊市)时目标仓位比例(1.0=关闭择时;0.5=半仓;0=空仓)",
        },
        "regime_index": {
            "default": "HSI",
            "type": "str",
            "label": "regime 参考指数代码(market=HK)",
        },
        "regime_mode": {
            "default": "close_ma",
            "type": "str",
            "label": "regime 信号:close_ma(收盘>MA) | ma_cross(快MA>慢MA)",
        },
        "regime_ma_days": {
            "default": 200,
            "type": "int",
            "label": "close_ma 模式:MA 窗口(收盘 > 此 MA = risk-on)",
        },
        "regime_fast_ma": {
            "default": 50,
            "type": "int",
            "label": "ma_cross 模式:快线窗口",
        },
        "regime_slow_ma": {
            "default": 200,
            "type": "int",
            "label": "ma_cross 模式:慢线窗口",
        },
        # ---- R19: 个股波动率加权(降回撤,不依赖指数择时)----
        "weight_scheme": {
            "default": "equal",
            "type": "str",
            "label": "组合权重方案:equal(1/N 等权)| invvol(∝1/σ)| invvar(∝1/σ²)",
        },
        "vol_lookback": {
            "default": 120,
            "type": "int",
            "label": "波动率回看天数(已实现日收益标准差;equal 时忽略)",
        },
        "weight_cap_mult": {
            "default": 2.5,
            "type": "float",
            "label": "单股权重上限 = 此倍数 × 等权(防超低波动股霸盘;0=不封顶)",
        },
    }

    def __init__(self, param_overrides: dict | None = None):
        super().__init__(param_overrides)
        self._target_holdings: list[str] = []
        self._rebalance_pending: bool = False
        self._target_exposure: float = 1.0  # 本次 rebalance 应用的仓位比例
        self._cur_exposure: float = 1.0  # 当前实际生效的仓位比例
        # HSI regime 序列(PIT:懒加载全序列,使用时按 current_date 截断)
        self._regime_dates: list[date] = []
        self._regime_closes: list[float] = []
        self._regime_loaded: bool = False
        # R19: 个股波动率(screen 阶段 PIT 计算,on_buy 用于加权)
        self._sym_vol: dict[str, float] = {}

    def _load_regime(self) -> None:
        """懒加载 HSI 指数全序列(升序)。只加载一次;PIT 截断在 _regime_exposure 里做。"""
        if self._regime_loaded:
            return
        self._regime_loaded = True
        try:
            from services.duckdb_store import get_store

            df = get_store().query_index("HK", str(self.p.regime_index))
            if df is not None and not df.empty and "close" in df.columns:
                for d_str, c in zip(df["date"], df["close"]):
                    if c is None or pd.isna(c):
                        continue
                    try:
                        self._regime_dates.append(date.fromisoformat(str(d_str)[:10]))
                        self._regime_closes.append(float(c))
                    except (ValueError, TypeError):
                        continue
        except Exception:
            # 指数缺失 → regime 不可用,退化为永远 risk-on(不 de-risk)
            self._regime_dates = []
            self._regime_closes = []

    def _regime_exposure(self, cur_d: date) -> float:
        """根据 HSI regime 计算目标仓位比例。PIT:只用 date <= cur_d 的指数数据。

        risk-on → 1.0;risk-off → risk_off_exposure。risk_off_exposure>=1.0 视为关闭择时。
        数据不足 / 指数缺失 → 1.0(谨慎:不主动空仓)。
        """
        import bisect

        risk_off = float(self.p.risk_off_exposure)
        if risk_off >= 1.0:
            return 1.0  # 择时关闭
        self._load_regime()
        dates = self._regime_dates
        closes = self._regime_closes
        if not dates:
            return 1.0
        # 最后一个 date <= cur_d 的位置(严格 PIT,不含未来)
        idx = bisect.bisect_right(dates, cur_d) - 1
        if idx < 0:
            return 1.0

        mode = str(self.p.regime_mode).lower()
        if mode == "ma_cross":
            fast = int(self.p.regime_fast_ma)
            slow = int(self.p.regime_slow_ma)
            if idx + 1 < slow:
                return 1.0  # 历史不足
            fast_ma = sum(closes[idx - fast + 1 : idx + 1]) / fast
            slow_ma = sum(closes[idx - slow + 1 : idx + 1]) / slow
            return 1.0 if fast_ma > slow_ma else risk_off
        # close_ma
        ma_days = int(self.p.regime_ma_days)
        if idx + 1 < ma_days:
            return 1.0  # 历史不足
        ma = sum(closes[idx - ma_days + 1 : idx + 1]) / ma_days
        return 1.0 if closes[idx] > ma else risk_off

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

        # ---- R18: 每月检查 HSI regime,据此调整目标仓位(即便非调仓月)----
        desired_exposure = self._regime_exposure(cur_d)

        if cur_d.month not in set(rebal_months):
            # 非调仓月:不重新选股,但若 regime 翻转则把现有持仓重标到新仓位
            if (
                self._target_holdings
                and abs(desired_exposure - self._cur_exposure) > 1e-9
            ):
                self._target_exposure = desired_exposure
                self._rebalance_pending = True
                ctx.log_flow(
                    "strategy.regime.adjust",
                    exposure=round(desired_exposure, 3),
                    prev=round(self._cur_exposure, 3),
                )
            else:
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
        weight_scheme = str(self.p.weight_scheme).lower()
        vol_lookback = int(self.p.vol_lookback)

        # R19: 个股波动率加权时, 需要 vol_lookback+1 根历史算日收益标准差
        vol_need = (vol_lookback + 1) if (weight_scheme in ("invvol", "invvar") and vol_lookback > 0) else 0
        sym_vol: dict[str, float] = {}

        # 单次取够长的历史窗口同时算流动性 / 趋势 / 动量 / 波动率, 避免重复 get_history
        need_hist = max(
            amt_lookback if min_amount > 0 else 0,
            trend_ma_days,
            momentum_days + 1,
            vol_need,
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
                # R19: PIT 已实现波动率 = 近 vol_lookback 日日收益标准差(样本std)
                if vol_need > 0 and len(closes) > vol_lookback:
                    window = closes[-(vol_lookback + 1):]
                    rets = [
                        window[i] / window[i - 1] - 1.0
                        for i in range(1, len(window))
                        if window[i - 1]
                    ]
                    if len(rets) >= 2:
                        mean = sum(rets) / len(rets)
                        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
                        if var > 0:
                            sym_vol[sym] = var ** 0.5
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
        self._target_exposure = desired_exposure  # R18: 调仓月也应用 regime 仓位
        self._sym_vol = sym_vol  # R19: 个股波动率(on_buy 加权用)
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
        # R18: regime 仓位比例(exposure=1.0 即满仓)。R19: 在 exposure 内按方案分配个股权重
        exposure = self._target_exposure
        weights = self._compute_weights(target)  # 归一化(sum=1)的个股权重
        for sym in target:
            ctx.order_target_percent(sym, exposure * weights[sym])
        self._cur_exposure = exposure
        self._rebalance_pending = False

    def _compute_weights(self, target: list[str]) -> dict[str, float]:
        """R19: 计算归一化(sum=1)的个股权重。

        equal → 1/N;invvol → ∝1/σ;invvar → ∝1/σ²。
        缺失波动率的股票用已知股票均值回填。最后按 weight_cap_mult×等权 迭代封顶 +
        把超额重分配给未封顶股票,直到稳定(经典 capped risk-weighting)。
        """
        n = len(target)
        if n == 0:
            return {}
        scheme = str(self.p.weight_scheme).lower()
        eq = 1.0 / n

        if scheme not in ("invvol", "invvar") or not self._sym_vol:
            return {s: eq for s in target}

        # 原始风险倒数权重
        raw: dict[str, float | None] = {}
        for s in target:
            v = self._sym_vol.get(s)
            if v is None or v <= 0:
                raw[s] = None
            else:
                raw[s] = (1.0 / v) if scheme == "invvol" else (1.0 / (v * v))
        known = [w for w in raw.values() if w is not None]
        fill = (sum(known) / len(known)) if known else 1.0
        weights = {s: (w if w is not None else fill) for s, w in raw.items()}

        total = sum(weights.values()) or 1.0
        weights = {s: w / total for s, w in weights.items()}

        # 封顶 + 重分配
        cap_mult = float(self.p.weight_cap_mult)
        if cap_mult > 0:
            cap = cap_mult * eq
            for _ in range(n):  # 最多 N 轮收敛
                over = {s: w for s, w in weights.items() if w > cap + 1e-12}
                if not over:
                    break
                excess = sum(w - cap for s, w in over.items())
                for s in over:
                    weights[s] = cap
                under = {s: w for s, w in weights.items() if w < cap - 1e-12}
                under_total = sum(under.values())
                if under_total <= 0:
                    break  # 全部触顶, 无法再分配
                for s in under:
                    weights[s] += excess * (weights[s] / under_total)
        return weights
