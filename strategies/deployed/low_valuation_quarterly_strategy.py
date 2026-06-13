"""低估值季度调仓策略(LowValuationQuarterlyStrategy)。

A 股 2010-2025 全样本回测最优配方(R25 = R20 + 年报 ROE 口径),独立脚本
CAGR 13.92% / Sharpe 0.83 / DD -28.2%(详见 scripts/backtest_low_pb_value.py)。

核心逻辑:
1. 在每年 5/9/11 月的第一个交易日(由 frequency="monthly" + 月份 gate 实现)做一次:
   - 全 A 股池 → PB ∈ (0, max] 且 isST==0 且 peTTM > 0
   - 排除最新已披露**年报** ROEJQ ≤ roe_min%(NOTICE_DATE-as-of,严防 look-ahead;
     **只用 REPORT_DATE 月=12 的年报**,避免 Q1/H1/Q3 累计同期 ROE 季节性扰动)
   - 排除过去 momentum_lookback_days 涨跌幅最差 momentum_drop_pct 分位数
   - 按 PB 升序取 top_n,等权
2. 调仓机制 = 完全替换:把不在新目标里的全部清仓,目标里的 order_target_percent(1/N)
3. 非调仓月 screen 返回空,positions 自然漂移

⚠️ 行业集中风险:历史回测中持仓清一色国有银行/城商农商行/央企基建(交行/光大/
   中信/北京银行/中铁/中建等),实质是「破净银行+基建组合」。预期未来表现高度
   依赖该子板块的均值回归,而非全市场 alpha。

⚠️ 关于 ROE 口径选择(2026-06-09 决策):对比 V0=统一 5%(11.82%)/ V1=季度归一化
   (12.02%)/ V2=仅年报(13.92%),V2 显著最优。原因:5 月调仓时 Q1 报告刚披露,
   累计同期 ROEJQ 仅 1-3%,统一 5% 阈值会把所有正常股刷掉(系统性踏空);用上一
   年完整年报反而更稳定。本策略采用 V2。

⚠️ 与 ctx.get_financial 默认接口的差异:本策略 ROE 走
   filter_by_roe_annual_as_of_notice(NOTICE_DATE 防 look-ahead + 仅年报),
   不走 ctx.get_financial(REPORT_DATE)。回测启动时一次性预加载 v_a_indicator
   年报子集 + v_a_daily isST 稀疏表,首次调仓略慢(几秒),后续 O(log N)。

⚠️ 退市股防护(2026-06-09 修复):stage1 加 valuation 时效性检查,要求估值数据
   日期与当前回测日间隔 ≤ max_valuation_staleness_days(默认 5 交易日)。
   防止已退市股(如西水股份 600291.SH 2022-06 退市)的 stale pbMRQ 被 ASOF
   查找到,误进选股池后导致 T+1 buy 永久 pending → 全空仓 bug。

成交价口径:遵循项目铁律(broker T+1 + (open+close)/2 中位价),与脚本「D 收盘价
开仓」会有 ~0.1-0.2pp 偏离,实盘可达。
"""

from __future__ import annotations

import threading
from datetime import date

import numpy as np
import pandas as pd

from strategies.base import Strategy
from strategies.utils import financial


# ===== isST 稀疏 cache(只装 isST=='1' 的 (sym, date) 对,A 股专用) =====

_ST_LOOKUP: dict[str, set[str]] | None = None
_ST_LOCK = threading.Lock()


def _build_st_lookup() -> dict[str, set[str]]:
    """从 v_a_daily 拉所有 isST='1' 的 (sym, date),按 sym 聚成 set。

    A 股全市场 ST 历史记录稀疏(约 1% 行),预计百万级,几十 MB。
    """
    from services.duckdb_store import get_store

    store = get_store()
    sql = """
        SELECT _symbol AS code, date
        FROM v_a_daily
        WHERE isST = '1'
    """
    df = store._conn.execute(sql).fetchdf()
    df["date"] = df["date"].astype(str)
    out: dict[str, set[str]] = {}
    for code, sub in df.groupby("code"):
        out[code] = set(sub["date"].tolist())
    return out


def _get_st_lookup() -> dict[str, set[str]]:
    global _ST_LOOKUP
    if _ST_LOOKUP is not None:
        return _ST_LOOKUP
    with _ST_LOCK:
        if _ST_LOOKUP is None:
            _ST_LOOKUP = _build_st_lookup()
    return _ST_LOOKUP


def reset_st_cache() -> None:
    """测试 / 数据更新后重置 cache。"""
    global _ST_LOOKUP
    with _ST_LOCK:
        _ST_LOOKUP = None


def _is_st_on(symbol: str, date_str: str) -> bool:
    return date_str in _get_st_lookup().get(symbol, set())


# ===== 主策略 =====


class LowValuationQuarterlyStrategy(Strategy):
    name = "低估值季度调仓"
    description = (
        "A 股每年 5/9/11 月初做一次调仓:筛 PB<1 + 非 ST + 盈利 + 年报 ROE 达标 + "
        "排过去 6 月动量最差分位,按 PB 升序取 top N 等权。基于 R25 配方"
        "(R20 + 年报 ROE,2010-2025 CAGR 13.92% / DD -28.2% / Sharpe 0.83)。"
        "⚠️ 行业高度集中于破净银行 + 央企基建,持仓多样性差。"
    )
    frequency = "monthly"
    frequency_overridable = False
    strategy_type = "strategy"

    params = {
        "pb_max": {
            "default": 1.0,
            "type": "float",
            "label": "PB 上限(<= 此值)",
        },
        "roe_min": {
            "default": 5.0,
            "type": "float",
            "label": "最低 ROE(%,年报 NOTICE_DATE-as-of)",
        },
        "max_valuation_staleness_days": {
            "default": 5,
            "type": "int",
            "label": "估值数据时效上限(交易日,防退市股 stale 数据)",
        },
        "momentum_lookback_days": {
            "default": 120,
            "type": "int",
            "label": "动量回看交易日数(~6 月)",
        },
        "momentum_drop_pct": {
            "default": 0.2,
            "type": "float",
            "label": "动量最差分位剔除比例(0=不过滤)",
        },
        "top_n": {
            "default": 15,
            "type": "int",
            "label": "持仓数量",
        },
        "rebalance_months": {
            "default": [5, 9, 11],
            "type": "list[int]",
            "label": "调仓月份(每年这些月的第一个交易日)",
        },
    }

    def __init__(self, param_overrides: dict | None = None):
        super().__init__(param_overrides)
        # 调仓状态:screen() 在调仓月命中时填,on_sell + on_buy 消费
        self._target_holdings: list[str] = []
        self._rebalance_pending: bool = False

    # ===== 选股:仅在调仓月运行 =====
    def screen(self, ctx, symbols: list[str]) -> list[str]:
        cur_str = ctx.current_date
        if not cur_str:
            return []
        try:
            cur_d = date.fromisoformat(cur_str[:10])
        except (ValueError, TypeError):
            return []

        rebal_months = self.p.rebalance_months
        # 防御:可能从 UI 传 str
        if isinstance(rebal_months, str):
            rebal_months = [int(x) for x in rebal_months.split(",") if x.strip()]
        if cur_d.month not in set(rebal_months):
            ctx.log_flow("strategy.screen.skip", reason="not_rebalance_month")
            return []

        ctx.log_flow("strategy.screen.start", input=len(symbols))

        pb_max = float(self.p.pb_max)
        roe_min = float(self.p.roe_min)
        lookback = int(self.p.momentum_lookback_days)
        drop_pct = float(self.p.momentum_drop_pct)
        top_n = int(self.p.top_n)
        staleness_days = int(self.p.max_valuation_staleness_days)

        # ---- Stage 1: PB / peTTM / ST + 时效性 四联过滤 ----
        # staleness 检查防退市股:get_valuation 走 ASOF (`<= date` 最近一行),
        # 退市股(如 600291.SH 2022 退市)在 2026 查询会返回 2022 stale pbMRQ。
        # 这里要求 valuation 行的 date 与 cur_str 间隔 ≤ staleness_days(日历日近似)。
        stage1: list[tuple[str, float]] = []
        cur_d_obj = cur_d  # 已 parse 的 date
        for sym in symbols:
            # 取完整 valuation 行(含 date 字段),用于 staleness 检查
            val = ctx.get_valuation(sym) if hasattr(ctx, "get_valuation") else None
            if val is None:
                continue
            val_date = val.get("date")
            if val_date is not None:
                try:
                    vd = date.fromisoformat(str(val_date)[:10])
                    # 用日历日做近似(staleness_days 含义:交易日 ≈ 日历日 × 1.4),
                    # 5 交易日 ~ 7 日历日,放宽到 staleness_days * 2 防春节/国庆假期误杀
                    if (cur_d_obj - vd).days > staleness_days * 2:
                        continue
                except (ValueError, TypeError):
                    pass  # 日期解析失败时不强制 staleness 过滤
            pb = val.get("pbMRQ")
            # NaN 防御:HK/US pbMRQ 由 DuckDB 用 BPS>0 派生,负净资产公司返 NaN;
            # NaN 与任何数比较都返 False,会绕过 `pb<=0/pb>pb_max` 全部判断,
            # 必须用 pd.isna 显式拦截(覆盖 None+NaN 两种缺失)。
            # 历史 bug:fab04c35 任务 06158.HK 因 BPS=-2.57 → NaN PB → 误选
            if pd.isna(pb) or pb <= 0 or pb > pb_max:
                continue
            pe = val.get("peTTM")
            if pd.isna(pe) or pe <= 0:
                continue
            if _is_st_on(sym, cur_str):
                continue
            stage1.append((sym, float(pb)))
            ctx.record_factor(sym, "PB", float(pb))
        ctx.log_flow("strategy.pb_pe_st", passed=len(stage1))

        # ---- Stage 2: 年报 ROE(NOTICE_DATE-as-of)----
        # 用 filter_by_roe_annual_as_of_notice:仅 REPORT_DATE 月=12 的年报。
        # 不用 get_roe_as_of_notice(季度累计 ROEJQ),因为 5 月调仓拿到的是 Q1 报告
        # ROEJQ 只是年化的 1/4(2-4%),阈值 5% 会把所有正常股刷掉,导致系统性踏空。
        stage2: list[tuple[str, float, float]] = []
        for sym, pb in stage1:
            roe = financial.get_roe_annual_as_of_notice(ctx, sym)
            if roe is None or roe <= roe_min:
                continue
            stage2.append((sym, pb, roe))
            ctx.record_factor(sym, "ROE", roe)
        ctx.log_flow("strategy.roe_annual_notice", passed=len(stage2))

        # ---- Stage 3: 动量过滤(剔除最差分位)----
        if drop_pct > 0 and stage2 and lookback > 0:
            mom_rows: list[tuple[str, float, float, float]] = []
            for sym, pb, roe in stage2:
                # ctx.get_history 返回最近 n 根 daily(qfq)bars,含当根
                bars = ctx.get_history(sym, n=lookback + 1, period="daily")
                if not bars or len(bars) < 2:
                    continue
                old_close = bars[0].get("close")
                new_close = bars[-1].get("close")
                if old_close is None or new_close is None or float(old_close) <= 0:
                    continue
                mom = float(new_close) / float(old_close) - 1.0
                mom_rows.append((sym, pb, roe, mom))
            if mom_rows:
                moms = np.array([r[3] for r in mom_rows])
                cutoff = float(np.quantile(moms, drop_pct))
                survivors = [r for r in mom_rows if r[3] >= cutoff]
                for sym, pb, roe, mom in survivors:
                    ctx.record_factor(sym, "Momentum6M", mom)
                stage3 = [(sym, pb) for sym, pb, _, _ in survivors]
            else:
                stage3 = []
            ctx.log_flow("strategy.momentum", passed=len(stage3))
        else:
            stage3 = [(sym, pb) for sym, pb, _ in stage2]

        # ---- Stage 4: PB 升序,取 top_n ----
        stage3.sort(key=lambda x: x[1])
        selected = [sym for sym, _ in stage3[:top_n]]
        for sym in selected:
            ctx.log_pass(sym, "strategy.screen.final")

        ctx.log_flow(
            "strategy.screen.done",
            input=len(symbols),
            passed=len(selected),
        )

        # 锁定目标 → 触发 on_sell + on_buy 重平衡
        self._target_holdings = selected
        self._rebalance_pending = True
        return selected

    # ===== 卖出:清掉不在新目标里的持仓 =====
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
            # 同步移出 engine 的 target_symbols(避免引擎认为还需要持仓)
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

    # ===== 买入:对新目标 order_target_percent(1/N)=====
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
