"""低估值多因子季度调仓策略(LowValuationQuarterlyStrategy 的演进版本)。

相对原策略的 4 项核心增强(2026-06-10):

1. **质量过滤层**(P1#5)— Stage 1 后插入,剔除"价值陷阱":
   - 经营现金流 > 0(金融业豁免)
   - CFO/净利润 ≥ 0.5(金融业豁免,剔除应收账款堆积的假利润)
   - 资产负债率 ≤ 70%(金融业豁免)
   - ROE 不连续 2 年下降 ≥ 30%(质量恶化信号)

2. **ROE 阈值上调**(P0#3)— 默认 8.0(原 5.0),用户可调 5/8/10/12

3. **多因子复合 score 排序**(P0#2)— 替代单 PB 升序:
   `score = z(1/PB) + z(ROE) + z(div_yield_ttm) + z(1/PE)`
   每个因子 z-score 标准化(均值 0,标准差 1),等权相加。
   动机:深度破净银行扎堆 → 单 PB 排序无法区分质量 → 多因子缓解集中度。

4. **行业集中度上限**(P0#1)— 单一行业最多 max_per_industry 只(默认 3),
   按 score 降序贪心去重,确保 15 只跨 ≥ 5 个行业。

兼容性:沿用原策略的 staleness 检查、ST 过滤、动量过滤、5/9/11 调仓节奏、
等权 1/N 仓位、on_sell + on_buy 调仓逻辑。仅 Stage1.5/2/4/5 改动。
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from strategies.base import Strategy
from strategies.deployed.low_valuation_quarterly_strategy import _is_st_on
from strategies.utils import financial, quality, yield_factor


def _z_score(values: np.ndarray) -> np.ndarray:
    """单列 z-score。std=0 时全返 0(等权时该因子无区分度,不参与排序)。"""
    mu = float(np.mean(values))
    sd = float(np.std(values))
    if sd == 0:
        return np.zeros_like(values)
    return (values - mu) / sd


class LowValuationMultiFactorQuarterlyStrategy(Strategy):
    name = "低估值多因子季度调仓"
    description = (
        "A 股 5/9/11 月调仓:在原低估值季度调仓基础上加 4 项增强 — "
        "(1)质量过滤(CFO>0、CFO/NP≥0.5、资产负债率≤70%、ROE 不连续大跌)避价值陷阱;"
        "(2)ROE 默认 8% 抬高质量门槛;"
        "(3)多因子复合 score = z(1/PB) + z(ROE) + z(div_yield) + z(1/PE) 替代单 PB 排序;"
        "(4)单行业最多 3 只防止扎堆破净银行。等权 1/N 仓位、5/9/11 月调仓不变。"
    )
    frequency = "monthly"
    frequency_overridable = False
    strategy_type = "strategy"

    params = {
        # ---- 估值过滤 ----
        "pb_max": {"default": 1.0, "type": "float", "label": "PB 上限"},
        "pe_max": {
            "default": 30.0,
            "type": "float",
            "label": "PE 上限(0=不限制)",
        },
        "roe_min": {
            "default": 8.0,
            "type": "float",
            "label": "最低 ROE %(年报 NOTICE-as-of)",
        },
        "max_valuation_staleness_days": {
            "default": 5,
            "type": "int",
            "label": "估值数据时效上限(交易日)",
        },
        # ---- 动量过滤 ----
        "momentum_lookback_days": {
            "default": 120,
            "type": "int",
            "label": "动量回看天数",
        },
        "momentum_drop_pct": {
            "default": 0.2,
            "type": "float",
            "label": "动量最差分位剔除(0=不过滤)",
        },
        # ---- 质量过滤 ----
        "require_positive_cfo": {
            "default": True,
            "type": "bool",
            "label": "要求经营现金流 > 0(金融业豁免)",
        },
        "cfo_to_np_min": {
            "default": 0.5,
            "type": "float",
            "label": "CFO/净利润 下限(0=不限制,金融业豁免)",
        },
        "debt_ratio_max": {
            "default": 0.70,
            "type": "float",
            "label": "资产负债率上限(0=不限制,金融业豁免)",
        },
        "roe_decline_check": {
            "default": True,
            "type": "bool",
            "label": "ROE 不连续 2 年大跌检查",
        },
        # ---- 多因子 score 权重 ----
        "score_weight_inv_pb": {
            "default": 1.0,
            "type": "float",
            "label": "score 权重:z(1/PB)",
        },
        "score_weight_roe": {
            "default": 1.0,
            "type": "float",
            "label": "score 权重:z(ROE)",
        },
        "score_weight_div_yield": {
            "default": 1.0,
            "type": "float",
            "label": "score 权重:z(股息率)",
        },
        "score_weight_inv_pe": {
            "default": 1.0,
            "type": "float",
            "label": "score 权重:z(1/PE)",
        },
        "score_weight_neg_momentum": {
            "default": 0.0,
            "type": "float",
            "label": "score 权重:z(-动量)逆动量加分",
        },
        "neg_momentum_lookback_days": {
            "default": 60,
            "type": "int",
            "label": "逆动量回看天数",
        },
        # ---- 持仓权重 ----
        "position_weighting": {
            "default": "equal",
            "type": "str",
            "label": "仓位加权方式 equal|inv_vol",
        },
        "vol_lookback_days": {
            "default": 60,
            "type": "int",
            "label": "波动回看天数(inv_vol 用)",
        },
        # ---- 卖出止损/止盈(每根 bar 检查,独立于调仓日)----
        "stop_loss_pct": {
            "default": 0.0,
            "type": "float",
            "label": "止损线 %(0=不启用,e.g. 0.20 = 个股跌 20% 清仓)",
        },
        "take_profit_pct": {
            "default": 0.0,
            "type": "float",
            "label": "止盈线 %(0=不启用,e.g. 0.50 = 个股涨 50% 清仓)",
        },
        # ---- 持仓 + 调仓 ----
        "top_n": {"default": 15, "type": "int", "label": "持仓数量"},
        "max_per_industry": {
            "default": 3,
            "type": "int",
            "label": "单行业最大持仓数(0=不限制)",
        },
        "rebalance_months": {
            "default": [5, 9, 11],
            "type": "list[int]",
            "label": "调仓月份",
        },
    }

    def __init__(self, param_overrides: dict | None = None):
        super().__init__(param_overrides)
        self._target_holdings: list[str] = []
        self._rebalance_pending: bool = False

    # ===== 选股 =====
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

        pb_max = float(self.p.pb_max)
        pe_max = float(self.p.pe_max)
        roe_min = float(self.p.roe_min)
        lookback = int(self.p.momentum_lookback_days)
        drop_pct = float(self.p.momentum_drop_pct)
        top_n = int(self.p.top_n)
        max_per_industry = int(self.p.max_per_industry)
        staleness_days = int(self.p.max_valuation_staleness_days)

        # ---- Stage 1: PB / PE / ST + 时效性 四联过滤 ----
        stage1: list[tuple[str, float, float]] = []  # (sym, pb, pe)
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
            pb = val.get("pbMRQ")
            if pd.isna(pb) or pb <= 0 or pb > pb_max:
                continue
            pe = val.get("peTTM")
            if pd.isna(pe) or pe <= 0:
                continue
            if pe_max > 0 and pe > pe_max:
                continue
            if _is_st_on(sym, cur_str):
                continue
            stage1.append((sym, float(pb), float(pe)))
            ctx.record_factor(sym, "PB", float(pb))
            ctx.record_factor(sym, "PE", float(pe))
        ctx.log_flow("strategy.pb_pe_st", passed=len(stage1))

        # ---- Stage 1.5: 质量过滤(剔除价值陷阱)----
        stage1_5: list[tuple[str, float, float]] = []
        for sym, pb, pe in stage1:
            ok, reason = quality.passes_quality_filter(
                ctx,
                sym,
                require_positive_cfo=bool(self.p.require_positive_cfo),
                cfo_to_np_min=(
                    float(self.p.cfo_to_np_min)
                    if float(self.p.cfo_to_np_min) > 0
                    else None
                ),
                debt_ratio_max=(
                    float(self.p.debt_ratio_max)
                    if float(self.p.debt_ratio_max) > 0
                    else None
                ),
                roe_decline_check=bool(self.p.roe_decline_check),
            )
            if not ok:
                ctx.log_reject(sym, "strategy.quality", reason)
                continue
            stage1_5.append((sym, pb, pe))
        ctx.log_flow("strategy.quality", passed=len(stage1_5))

        # ---- Stage 2: 年报 ROE(NOTICE-as-of)----
        stage2: list[tuple[str, float, float, float]] = []  # (sym, pb, pe, roe)
        for sym, pb, pe in stage1_5:
            roe = financial.get_roe_annual_as_of_notice(ctx, sym)
            if roe is None or roe <= roe_min:
                continue
            stage2.append((sym, pb, pe, roe))
            ctx.record_factor(sym, "ROE", roe)
        ctx.log_flow("strategy.roe_annual_notice", passed=len(stage2))

        # ---- Stage 3: 动量过滤 ----
        if drop_pct > 0 and stage2 and lookback > 0:
            mom_rows: list[tuple[str, float, float, float, float]] = []
            for sym, pb, pe, roe in stage2:
                bars = ctx.get_history(sym, n=lookback + 1, period="daily")
                if not bars or len(bars) < 2:
                    continue
                old_close = bars[0].get("close")
                new_close = bars[-1].get("close")
                if old_close is None or new_close is None or float(old_close) <= 0:
                    continue
                mom = float(new_close) / float(old_close) - 1.0
                mom_rows.append((sym, pb, pe, roe, mom))
            if mom_rows:
                moms = np.array([r[4] for r in mom_rows])
                cutoff = float(np.quantile(moms, drop_pct))
                survivors = [r for r in mom_rows if r[4] >= cutoff]
                for sym, _, _, _, mom in survivors:
                    ctx.record_factor(sym, "Momentum6M", mom)
                stage3 = [(sym, pb, pe, roe) for sym, pb, pe, roe, _ in survivors]
            else:
                stage3 = []
            ctx.log_flow("strategy.momentum", passed=len(stage3))
        else:
            stage3 = list(stage2)

        if not stage3:
            ctx.log_flow("strategy.screen.done", input=len(symbols), passed=0)
            self._target_holdings = []
            self._rebalance_pending = True
            return []

        # ---- Stage 4: 多因子复合 score 排序 ----
        # 收集每只股票的因子原值,然后 z-score 标准化加权求和
        # 因子集合:1/PB, 1/PE, ROE, div_yield, -momentum(逆动量)
        w_neg_mom = float(self.p.score_weight_neg_momentum)
        neg_mom_lookback = int(self.p.neg_momentum_lookback_days)

        rows = []  # (sym, pb, pe, roe, div_yield, neg_momentum)
        for sym, pb, pe, roe in stage3:
            dy = yield_factor.get_dividend_yield_ttm(ctx, sym)
            if dy is None:
                dy = 0.0  # 无价格异常 → 当 0 处理
            # 逆动量因子(下跌幅度大 → 值大):仅在权重 > 0 时计算
            neg_mom = 0.0
            if w_neg_mom > 0 and neg_mom_lookback > 0:
                bars = ctx.get_history(sym, n=neg_mom_lookback + 1, period="daily")
                if bars and len(bars) >= 2:
                    o = bars[0].get("close")
                    n = bars[-1].get("close")
                    if o and n and float(o) > 0:
                        # -动量:近 N 日跌幅越大 → neg_mom 越大
                        neg_mom = -(float(n) / float(o) - 1.0)
            rows.append((sym, pb, pe, roe, dy, neg_mom))
            ctx.record_factor(sym, "DivYieldTTM", dy)
            if w_neg_mom > 0:
                ctx.record_factor(sym, "NegMomentum", neg_mom)

        inv_pb = np.array([1.0 / r[1] for r in rows])
        inv_pe = np.array([1.0 / r[2] for r in rows])
        roes = np.array([r[3] for r in rows])
        dys = np.array([r[4] for r in rows])
        neg_moms = np.array([r[5] for r in rows])

        z_inv_pb = _z_score(inv_pb)
        z_roe = _z_score(roes)
        z_dy = _z_score(dys)
        z_inv_pe = _z_score(inv_pe)
        z_neg_mom = _z_score(neg_moms)

        w_pb = float(self.p.score_weight_inv_pb)
        w_roe = float(self.p.score_weight_roe)
        w_dy = float(self.p.score_weight_div_yield)
        w_pe = float(self.p.score_weight_inv_pe)

        scores = (
            w_pb * z_inv_pb
            + w_roe * z_roe
            + w_dy * z_dy
            + w_pe * z_inv_pe
            + w_neg_mom * z_neg_mom
        )
        for i, (sym, *_) in enumerate(rows):
            ctx.record_factor(sym, "Score", float(scores[i]))

        # 按 score 降序排序候选
        ranked = sorted(
            zip([r[0] for r in rows], scores.tolist(), strict=False),
            key=lambda x: -x[1],
        )

        # ---- Stage 5: 行业集中度去重 + 取 top_n ----
        if max_per_industry > 0:
            industry_counts: dict[str, int] = {}
            selected: list[str] = []
            for sym, _score in ranked:
                ind = quality.get_industry(ctx, sym) or "_unknown"
                if industry_counts.get(ind, 0) >= max_per_industry:
                    ctx.log_reject(sym, "strategy.industry_cap", f"industry_full_{ind}")
                    continue
                selected.append(sym)
                industry_counts[ind] = industry_counts.get(ind, 0) + 1
                ctx.record_factor(sym, "Industry", ind)
                if len(selected) >= top_n:
                    break
        else:
            selected = [sym for sym, _ in ranked[:top_n]]

        for sym in selected:
            ctx.log_pass(sym, "strategy.screen.final")
        ctx.log_flow("strategy.screen.done", input=len(symbols), passed=len(selected))

        self._target_holdings = selected
        self._rebalance_pending = True
        return selected

    # ===== 每 bar 止损/止盈检查(独立于调仓日)=====
    def _check_stop_loss_take_profit(self, ctx) -> None:
        sl = float(self.p.stop_loss_pct)
        tp = float(self.p.take_profit_pct)
        if sl <= 0 and tp <= 0:
            return
        positions = list(ctx.get_positions().items())
        for sym, pos in positions:
            shares = pos.shares if hasattr(pos, "shares") else pos.get("shares", 0)
            cost = pos.cost if hasattr(pos, "cost") else pos.get("cost", 0.0)
            if shares <= 0 or cost <= 0:
                continue
            price = ctx.get_price(sym)
            if not price or price.get("close") is None:
                continue
            cur = float(price["close"])
            pnl_pct = (cur - cost) / cost
            reason = None
            if sl > 0 and pnl_pct <= -sl:
                reason = "stop_loss"
            elif tp > 0 and pnl_pct >= tp:
                reason = "take_profit"
            if reason is None:
                continue
            ctx.order_shares(sym, -int(shares))
            try:
                ctx.target_symbols.discard(sym)
            except AttributeError:
                pass
            # 同时从本策略 target_holdings 移除,防止 rebalance 当日 on_buy 又买回
            try:
                self._target_holdings.remove(sym)
            except ValueError:
                pass
            if hasattr(ctx, "log_exec"):
                ctx.log_exec(
                    reason,
                    sym,
                    shares=int(shares),
                    price=cur,
                    note=f"pnl_pct={pnl_pct:.4f}",
                )

    # ===== 卖出:止损止盈(每 bar)+ 调仓日清非目标 =====
    def on_sell(self, ctx) -> None:
        # 1) 止损/止盈每 bar 检查(SL/TP 关闭则 no-op)
        self._check_stop_loss_take_profit(ctx)
        # 2) 调仓日清掉非目标持仓
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

    # ===== 买入:等权 1/N 或 inv_vol(1/σ_60 反向波动加权)=====
    def _compute_inv_vol_weights(
        self, ctx, target: list[str], lookback: int
    ) -> dict[str, float]:
        """计算 inv_vol 权重。σ_i = 近 lookback 日 daily-return std。
        weight_i = (1/σ_i) / Σ(1/σ_j)。σ=0 或数据不足的 symbol 用中位数 σ 兜底,
        全部失败则全部回退等权。
        """
        n = len(target)
        sigmas: list[float | None] = []
        for sym in target:
            bars = ctx.get_history(sym, n=lookback + 1, period="daily")
            if not bars or len(bars) < 3:
                sigmas.append(None)
                continue
            closes = np.array(
                [float(b["close"]) for b in bars if b.get("close") is not None]
            )
            if len(closes) < 3:
                sigmas.append(None)
                continue
            rets = np.diff(closes) / closes[:-1]
            sd = float(np.std(rets))
            sigmas.append(sd if sd > 0 else None)

        valid = [s for s in sigmas if s is not None and s > 0]
        if not valid:
            # 全部失败 → 等权
            eq = 1.0 / float(n)
            return {sym: eq for sym in target}
        median_sigma = float(np.median(valid))
        filled = np.array(
            [s if (s is not None and s > 0) else median_sigma for s in sigmas]
        )
        inv = 1.0 / filled
        weights = inv / inv.sum()
        return dict(zip(target, weights.tolist(), strict=False))

    def on_buy(self, ctx) -> None:
        if not self._rebalance_pending:
            return
        target = self._target_holdings
        if not target:
            self._rebalance_pending = False
            return

        weighting = str(self.p.position_weighting).lower().strip()
        if weighting == "inv_vol":
            vol_lb = int(self.p.vol_lookback_days)
            weights = self._compute_inv_vol_weights(ctx, target, vol_lb)
        else:
            eq = 1.0 / float(len(target))
            weights = {sym: eq for sym in target}

        for sym in target:
            target_pct = float(weights.get(sym, 0.0))
            ctx.order_target_percent(sym, target_pct)
            if hasattr(ctx, "log_pass"):
                ctx.log_pass(sym, "strategy.rebalance_buy", target_pct=target_pct)
        self._rebalance_pending = False
