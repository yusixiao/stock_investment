"""彼得·林奇「快速增长型(Fast Growers)」A 股量化策略 —— LynchFastGrowersStrategy。

林奇六分类法之一。快速增长型 = 小/中型、利润高速扩张的公司,是林奇组合里
涨幅最大(tenbagger 多出于此)也最需警惕的一类。本策略把林奇定性口径机械化:

林奇对 Fast Growers 的核心描述(《One Up on Wall Street》第 8/9 章):
- **规模**:中小公司(大公司很难再快速翻倍)→ 市值带过滤(mktcap band)。
- **成长**:年利润增速 20%~25%+,但**警惕 >50% 的"不可持续高增"**(低基数/周期反弹
  导致 CAGR 爆表)→ 净利 CAGR ∈ [min, max] 双边带。
- **营收同步**:利润增长须有营收支撑(剔除靠利润率/一次性收益的伪成长)→ rev_cagr_min。
- **质量**:能持续盈利、ROE 健康(不是烧钱换增长)→ roe_min。
- **估值纪律**:林奇最爱 PEG ≤ 1(P/E 不超过盈利增速)→ peg_max=1.0。

实现复用已验证的 AGarpStrategy 选股/调仓骨架(月度调仓、Top N 等权全替换、
真实 NOTICE_DATE 严格 PIT、ST 过滤、可选趋势/行业分散/沪深300 regime 择时),
仅:① 新增市值带过滤(get_total_mv);② 默认值切到快速增长口径。

成交价口径:T+1 + (open+close)/2(项目铁律)。A 股 volume 单位=股。
⚠️ 数据仅含当前在市标的 → 退市股缺失,survivorship bias,结果偏乐观;
   小盘高成长尤其受幸存者偏差影响,实盘前需谨慎打折。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from services.backtest.strategy_base import Strategy
from services.backtest.strategies.utils import growth_long, quality, valuation
from services.backtest.strategies.utils.index_timing import csi300_is_bull
from services.backtest.strategies.utils.st_filter import _is_st_on

YI = 1e8  # 1 亿元(市值带参数单位换算)


class LynchFastGrowersStrategy(Strategy):
    name = "A股 林奇·快速增长型(Fast Growers)"
    description = (
        "林奇六分类·快速增长型:中小市值 + 净利/营收高速增长(CAGR≥25%,带上限剔除"
        "不可持续伪高增)+ ROE 质量 + PEG≤1 估值纪律 → Top N 等权月度调仓。"
        "真实 NOTICE_DATE 防 look-ahead + ST 过滤 + 可选趋势/行业分散/沪深300 择时。"
    )
    frequency = "monthly"
    frequency_overridable = False
    strategy_type = "strategy"

    params = {
        # ---- 成长(快速增长核心:双边带)----
        "np_cagr_min": {
            "default": 0.25,
            "type": "float",
            "label": "N 年归母净利 CAGR 下限(小数,林奇快速增长≥20~25%)",
        },
        "np_cagr_max": {
            "default": 0.50,
            "type": "float",
            "label": "N 年归母净利 CAGR 上限(小数,剔除低基数/周期反弹的不可持续伪高增;0=不过滤)",
        },
        "rev_cagr_min": {
            "default": 0.15,
            "type": "float",
            "label": "N 年营收 CAGR 下限(小数,确保利润增长有营收支撑)",
        },
        "cagr_years": {
            "default": 3,
            "type": "int",
            "label": "CAGR 回看年数",
        },
        # ---- 质量 ----
        "roe_min": {
            "default": 15.0,
            "type": "float",
            "label": "最新年报 ROE 下限(%,高成长须伴随高资本回报)",
        },
        "roe_consistency_years": {
            "default": 0,
            "type": "int",
            "label": "连续 N 年 ROE≥下限(0=只看最新一年)",
        },
        # ---- 财务质量增强(资产负债率 / 经营现金流;0=不过滤)----
        "max_debt_ratio": {
            "default": 0.0,
            "type": "float",
            "label": "资产负债率上限(总负债/总资产,如 0.6=≤60%;0=不过滤。剔除高杠杆脆弱成长股)",
        },
        "min_cfo_np_ratio": {
            "default": 0.0,
            "type": "float",
            "label": "经营现金流/归母净利下限(如 0.01≈要求 CFO 为正;0.5=现金含量≥50%;0=不过滤。剔除纸面利润)",
        },
        # ---- 估值纪律(林奇:PEG≤1)----
        "pe_max": {
            "default": 40.0,
            "type": "float",
            "label": "peTTM 上限(高成长容忍更高 PE,但仍设泡沫上限)",
        },
        "peg_max": {
            "default": 1.0,
            "type": "float",
            "label": "PEG 上限(peTTM / 净利CAGR%,林奇核心:≤1)",
        },
        "peg_min": {
            "default": 0.0,
            "type": "float",
            "label": "PEG 下限(剔除超低 PEG 价值陷阱,0=不过滤)",
        },
        "require_pb_positive": {
            "default": True,
            "type": "bool",
            "label": "要求 pbMRQ>0",
        },
        # ---- 市值带(快速增长 = 偏好中小公司)----
        # 默认值 = 2010-01~2026-06 全 A 股 5 轮 61 配置网格搜索的风险调整最优(15~100 亿带):
        # 年化 +4.48% / 总收益 105% / 回撤 47.5% / Sharpe 0.19,约 2.3× 沪深300(年化 1.94%)。
        # (最高收益变体 = 15~120 亿 + 成长下限 22%:年化 +4.75%,但回撤升至 54.7%。)
        "mktcap_min_yi": {
            "default": 15.0,
            "type": "float",
            "label": "总市值下限(亿元,剔除流动性差的微盘;0=不过滤)",
        },
        "mktcap_max_yi": {
            "default": 100.0,
            "type": "float",
            "label": "总市值上限(亿元,林奇:大公司难再快速翻倍;0=不限)",
        },
        # ---- 流动性 ----
        "min_amount_cny": {
            "default": 1e7,
            "type": "float",
            "label": "近 N 日日均成交额下限(人民币,0=不过滤)",
        },
        "amount_lookback": {
            "default": 60,
            "type": "int",
            "label": "成交额回看交易日",
        },
        # ---- 组合构建 ----
        "top_n": {
            "default": 25,
            "type": "int",
            "label": "持仓数量(网格搜索分散甜区≈25~30,过少波动大、过多稀释 alpha)",
        },
        "sort_by": {
            "default": "peg",
            "type": "str",
            "label": "排序键:peg(升序) | growth(成长降序) | composite(peg+growth 复合)",
        },
        "trend_ma_days": {
            "default": 0,
            "type": "int",
            "label": "趋势过滤:要求 close > N 日均线(0=不过滤)",
        },
        "require_industry": {
            "default": False,
            "type": "bool",
            "label": "仅保留有 F10 行业分类的标的(小盘成长慎开,可能误剔)",
        },
        "max_per_sector": {
            "default": 0,
            "type": "int",
            "label": "每个一级行业最多持仓数(0=不限)",
        },
        "max_valuation_staleness_days": {
            "default": 10,
            "type": "int",
            "label": "估值数据时效上限(交易日,防退市股 stale)",
        },
        "rebalance_months": {
            "default": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
            "type": "list[int]",
            "label": "调仓月份(网格搜索:月度全调仓显著优于仅 5 月年度调仓;PIT 取数已防 look-ahead)",
        },
        # ---- 沪深300 市场 regime 择时(降回撤)----
        "risk_off_exposure": {
            "default": 1.0,
            "type": "float",
            "label": "risk-off(熊市)时目标仓位比例(1.0=关闭择时;0.5=半仓;0=空仓)",
        },
        "regime_ma_days": {
            "default": 200,
            "type": "int",
            "label": "沪深300 regime:close>MA(此窗口)=risk-on,否则 risk-off",
        },
        # ---- 持有期个股止损(每根 bar 检查,独立于月度调仓;0=不启用)----
        "stop_loss_pct": {
            "default": 0.0,
            "type": "float",
            "label": "硬止损:当前价跌破成本×(1-此值)即清仓(如 0.2=亏20%止损;0=不启用)",
        },
        "trailing_stop_pct": {
            "default": 0.0,
            "type": "float",
            "label": "移动止损:当前价跌破持有期最高价×(1-此值)即清仓(如 0.25=回撤25%止损;0=不启用)",
        },
    }

    def __init__(self, param_overrides: dict | None = None):
        super().__init__(param_overrides)
        self._target_holdings: list[str] = []
        self._rebalance_pending: bool = False
        self._target_exposure: float = 1.0  # 本次 rebalance 应用的仓位比例
        self._cur_exposure: float = 1.0  # 当前实际生效的仓位比例
        self._peak: dict[str, float] = {}  # 持有期个股最高价(移动止损用)

    def _regime_exposure(self, cur_str: str) -> float:
        """根据沪深300 regime 计算目标仓位比例。

        risk-on(close>MA)→ 1.0;risk-off → risk_off_exposure。
        risk_off_exposure>=1.0 视为关闭择时。数据不足 → csi300_is_bull 保守返 True(1.0)。
        """
        risk_off = float(self.p.risk_off_exposure)
        if risk_off >= 1.0:
            return 1.0  # 择时关闭
        ma_days = int(self.p.regime_ma_days)
        return 1.0 if csi300_is_bull(cur_str, ma_period=ma_days) else risk_off

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

        # ---- 每月检查沪深300 regime,据此调整目标仓位(即便非调仓月)----
        desired_exposure = self._regime_exposure(cur_str)

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
        np_cagr_max = float(self.p.np_cagr_max)
        rev_cagr_min = float(self.p.rev_cagr_min)
        cagr_years = int(self.p.cagr_years)
        roe_min = float(self.p.roe_min)
        roe_years = int(self.p.roe_consistency_years)
        max_debt_ratio = float(self.p.max_debt_ratio)
        min_cfo_np = float(self.p.min_cfo_np_ratio)
        pe_max = float(self.p.pe_max)
        peg_max = float(self.p.peg_max)
        peg_min = float(self.p.peg_min)
        require_pb = bool(self.p.require_pb_positive)
        mktcap_min = float(self.p.mktcap_min_yi) * YI
        mktcap_max = float(self.p.mktcap_max_yi) * YI
        min_amount = float(self.p.min_amount_cny)
        amt_lookback = int(self.p.amount_lookback)
        top_n = int(self.p.top_n)
        sort_key = str(self.p.sort_by).lower()
        staleness_days = int(self.p.max_valuation_staleness_days)
        trend_ma_days = int(self.p.trend_ma_days)
        require_industry = bool(self.p.require_industry)
        max_per_sector = int(self.p.max_per_sector)

        # 单次取够长的历史窗口同时算流动性 / 趋势, 避免重复 get_history
        need_hist = max(amt_lookback if min_amount > 0 else 0, trend_ma_days)

        # ---- Stage 1: ST 剔除 + 市值带 + 估值健康(PIT)+ 时效 + 流动性 + 趋势 ----
        stage1: list[tuple[str, float]] = []  # (sym, pe)
        for sym in symbols:
            # A 股特有:当日 ST 直接剔除
            if _is_st_on(sym, cur_str):
                continue
            # 行业分类过滤(可选;小盘成长默认关闭)
            if require_industry and quality.get_industry(ctx, sym) is None:
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

            # 市值带:林奇快速增长偏好中小公司(get_total_mv 单位=元)
            if mktcap_min > 0 or mktcap_max > 0:
                mv = valuation.get_total_mv(ctx, sym)
                if mv is None or mv <= 0:
                    continue
                if mktcap_min > 0 and mv < mktcap_min:
                    continue
                if mktcap_max > 0 and mv > mktcap_max:
                    continue

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
                # 流动性:近 amt_lookback 日 volume×close 均值(人民币;A 股 volume 单位=股)
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
            stage1.append((sym, float(pe)))
        ctx.log_flow("strategy.valuation_mktcap_liquidity", passed=len(stage1))

        # ---- Stage 2: 成长(双边带)+ 质量(真实 NOTICE_DATE,防 look-ahead)----
        stage2: list[tuple[str, float, float]] = []  # (sym, pe, np_cagr)
        for sym, pe in stage1:
            np_cagr = growth_long.get_net_profit_cagr(ctx, sym, years=cagr_years)
            if np_cagr is None or np_cagr < np_cagr_min:
                continue
            # 上限:剔除低基数/周期反弹的不可持续伪高增(林奇警告 >50%)
            if np_cagr_max > 0 and np_cagr > np_cagr_max:
                continue
            rev_cagr = growth_long.get_revenue_cagr(ctx, sym, years=cagr_years)
            if rev_cagr is None or rev_cagr < rev_cagr_min:
                continue
            # ROE:roe_years>0 要求连续 N 年达标,否则只看最新一年年报
            if not growth_long.all_roe_above(
                ctx, sym, roe_min, years=max(roe_years, 1)
            ):
                continue
            # 财务质量增强(数据缺失=放行,遵循 quality util 设计原则)
            if max_debt_ratio > 0:
                dr = quality.get_debt_ratio(ctx, sym)
                if dr is not None and dr > max_debt_ratio:
                    continue
            if min_cfo_np > 0:
                cfo_np = quality.get_cfo_to_np_ratio(ctx, sym)
                if cfo_np is not None and cfo_np < min_cfo_np:
                    continue
            stage2.append((sym, pe, np_cagr))
            ctx.record_factor(sym, "NP_CAGR", np_cagr)
            ctx.record_factor(sym, "REV_CAGR", rev_cagr)
        ctx.log_flow("strategy.growth_quality", passed=len(stage2))

        # ---- Stage 3: PEG 上限(林奇核心)----
        stage3: list[tuple[str, float, float]] = []  # (sym, peg, np_cagr)
        for sym, pe, np_cagr in stage2:
            cagr_pct = np_cagr * 100.0
            if cagr_pct <= 0:
                continue
            peg = pe / cagr_pct
            if peg <= 0 or peg > peg_max or peg < peg_min:
                continue
            stage3.append((sym, peg, np_cagr))
            ctx.record_factor(sym, "PE", pe)
            ctx.record_factor(sym, "PEG", peg)
        ctx.log_flow("strategy.peg", passed=len(stage3))

        # ---- Stage 4: 排序 + Top N ----
        if sort_key == "growth":
            stage3.sort(key=lambda x: -x[2])
        elif sort_key == "composite":
            # rank 之和:低 PEG + 高成长
            by_peg = sorted(stage3, key=lambda x: x[1])
            by_g = sorted(stage3, key=lambda x: -x[2])
            rank: dict[str, int] = {}
            for i, t in enumerate(by_peg):
                rank[t[0]] = rank.get(t[0], 0) + i
            for i, t in enumerate(by_g):
                rank[t[0]] = rank.get(t[0], 0) + i
            stage3.sort(key=lambda x: rank[x[0]])
        else:
            stage3.sort(key=lambda x: x[1])  # peg 升序

        # ---- 行业分散:每个一级行业最多 max_per_sector 只(贪心,保排序优先级)----
        if max_per_sector > 0:
            sector_count: dict[str, int] = {}
            capped: list[tuple[str, float, float]] = []
            for t in stage3:
                sec = quality.get_industry(ctx, t[0]) or "__UNKNOWN__"
                if sector_count.get(sec, 0) >= max_per_sector:
                    continue
                sector_count[sec] = sector_count.get(sec, 0) + 1
                capped.append(t)
                if len(capped) >= top_n:
                    break
            stage3 = capped
        selected = [sym for sym, _, _ in stage3[:top_n]]
        for sym in selected:
            sec = quality.get_industry(ctx, sym)
            if sec:
                ctx.record_factor(sym, "SECTOR", sec)
            ctx.log_pass(sym, "strategy.screen.final")

        ctx.log_flow("strategy.screen.done", input=len(symbols), passed=len(selected))

        self._target_holdings = selected
        self._target_exposure = desired_exposure  # 调仓月也应用 regime 仓位
        self._rebalance_pending = True
        return selected

    def on_sell(self, ctx) -> None:
        positions = ctx.get_positions()

        # 清理已清仓 symbol 的峰值缓存(防 re-buy 时复用旧高点导致误触发移动止损)
        if self._peak:
            held = {
                s
                for s, p in positions.items()
                if (p.shares if hasattr(p, "shares") else p.get("shares", 0)) > 0
            }
            for s in list(self._peak.keys()):
                if s not in held:
                    self._peak.pop(s, None)

        # ---- 持有期个股止损(每根 bar 检查,独立于月度调仓)----
        # 引擎在每根 bar 顶部先 fill_orders 再调 on_sell,故此处不存在未决止损单,
        # 无需去重缓存;跌停被拒的卖单会被 broker 丢弃,下一根 bar 自然重试。
        stop_pct = float(self.p.stop_loss_pct)
        trail_pct = float(self.p.trailing_stop_pct)
        stopped: set[str] = set()
        if stop_pct > 0 or trail_pct > 0:
            for sym, pos in list(positions.items()):
                shares = pos.shares if hasattr(pos, "shares") else pos.get("shares", 0)
                if shares <= 0:
                    continue
                cost = pos.cost if hasattr(pos, "cost") else pos.get("cost", 0.0)
                bar = ctx.get_price(sym)
                if not bar:
                    continue
                px = bar.get("close")
                if px is None or pd.isna(px) or px <= 0:
                    continue
                # 持有期最高价(收盘价口径),触发时不 pop(留给顶部 prune,正确处理跌停未成交重试)
                peak = self._peak.get(sym)
                if peak is None or px > peak:
                    peak = px
                    self._peak[sym] = peak
                trigger = (stop_pct > 0 and cost > 0 and px <= cost * (1.0 - stop_pct)) or (
                    trail_pct > 0 and peak > 0 and px <= peak * (1.0 - trail_pct)
                )
                if trigger:
                    ctx.order_shares(sym, -int(shares))
                    stopped.add(sym)
                    try:
                        ctx.target_symbols.discard(sym)
                    except AttributeError:
                        pass

        # ---- 月度调仓卖出:清掉不在目标池的旧持仓(跳过本 bar 已止损的)----
        if not self._rebalance_pending:
            return
        target_set = set(self._target_holdings)
        for sym, pos in list(positions.items()):
            if sym in stopped:
                continue
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
        # regime 仓位比例(exposure=1.0 即满仓),Top N 等权
        exposure = self._target_exposure
        w = exposure / len(target)
        for sym in target:
            ctx.order_target_percent(sym, w)
        self._cur_exposure = exposure
        self._rebalance_pending = False
