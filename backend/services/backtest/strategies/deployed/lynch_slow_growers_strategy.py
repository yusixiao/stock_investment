"""彼得·林奇「缓慢增长型(Slow Growers)」A 股量化策略 —— LynchSlowGrowersStrategy【已发布 / 最终交付】。

林奇六分类法之一。缓慢增长型 = 成熟、体量大、利润低速增长但**持续高分红**的公司
(典型如公用事业、银行、高速公路、煤炭蓝筹)。林奇买这类股的逻辑不是博取股价翻倍,
而是**低估值买入 + 稳定股息回报**;一旦增长停滞或股息中断就应卖出。

林奇对 Slow Growers 的核心描述(《One Up on Wall Street》第 8 章):
- **规模**:大型成熟公司(已过高速成长期)→ 大市值带过滤(与快速增长型相反)。
- **成长**:年利润增速低(个位数),关键是**正增长但不快** → 净利 CAGR ∈ [0, 8%] 双边带。
- **分红**:核心持有理由 = 慷慨且**持续多年**的现金分红 → 连续分红年数 + TTM 股息率下限。
- **估值**:低 PE 买入(成熟股不该给成长溢价)→ pe_max。
- **排序**:按 TTM 股息率降序选最有价值的派息股(不设 PEG:增长太低 → PEG 数学上无意义)。

== 本交付版固化的最优画像(自包含,不依赖 experiments;以下为相对在研默认的覆盖项)==
  min_div_yield     0.03  -> 0.035   TTM 股息率下限抬到 3.5%(更强的股息纪律)
  mktcap_min_yi    200.0  -> 300.0   市值下限抬到 300 亿(更纯粹的大盘成熟蓝筹)
  top_n             20    -> 5        持仓收敛到 5 只等权(R8 全期扫 top_n 5~12,Top5 年化/Sharpe 双优)
  max_per_sector    0     -> 2        每一级行业 ≤2 只(高股息高度集中银行/公用事业,强制分散)
  rebalance_months [1..12] -> [6]     年度调仓、固定 6 月(年报 4/30 披露后,低换手)
  其余沿用在研默认:np_cagr∈[0,8%] / cagr_years=3 / min_div_years=5 / pe_max=25 /
  require_pb_positive / min_amount_cny=1e7 / sort_by=yield / trend 关 / regime 关。

== 回测结论(2010-01 ~ 2026-07,A 股全市场,发布 Top5 口径)==
  年化 15.40% / 累计 960.92% / 最大回撤 42.28% / Sharpe 0.67 / 胜率 70% / 盈亏比 5.55 / 115 笔
  基准 CSI300 同期年化 1.93% → 超额 +13.47pct;100 万 → 1061 万。
  (口径:与用户 UI 实跑 cea7ae62 及 deployed 完整报告三源一致,截止 2026-07-04。
   Top5 系 R8 全期 top_n 5~12 系统扫描的冠军——回撤全档恒 42.28%,Top5 年化/Sharpe 双优、
   换手最低;R8 至 2026-06 的口径为年化 16.11%/105 笔,与此处差异仅来自回测截止日。)

== 稳健性与风险提示(发布 Top5,当前数据)==
  · ✅ 分段稳健:后半程(2018-2026,8.3y)年化 14.71% 且段内回撤仅 19.58%;2014 年后各
    4 年段回撤均 ≤18.8%。16 个 1 年段仅 2 段微负(-1.3% / -0.2%)。
  · ⚠️ 最大回撤 42.28% 是早年一次性事件:分段可验证其完全落在 2010-01~2014-02(四分段第1段
    段内DD即42.28%,且跨2012初——两个2年子段DD仅28%/26%,合起来才够42%)。因 2010-2013 合格池
    极小(2010-06 仅 1 只达标即近乎单票)被迫极端集中,又叠加 2011-2013 A股熊市。此段 Top5≡Top12
    (池 ≤5),故回撤由早年数据决定、与 top_n 无关(R8 全档同为 42.28%);根因是早年满足「连续
    5 年分红」的标的稀少,属数据/市场结构约束而非持续风险。
  · 价值纪律空仓:2011、2015 两年 6 月在「股息率≥3.5%」关筛空 → 全年持现;典型 2015-06 牛市
    顶优质慢增长股无一达标 → 空仓躲过基准随后深度股灾(cea7ae62 决策日志实证零通过)。
  · ⚠️ 旧交付曾记 DD 23.85% / 年化 14.28%(基于 Top12 + 旧数据快照 + 2010-06 起点):已随数据
    修订(分红/财务/行业回填)与画像切换(Top12→Top5)失效,上方为当前数据真实口径。

== 在研记录 ==
  研究版同名策略在 experiments/lynch/lynch_slow_growers/(R1-R8 多轮调参过程,R8 为 top_n 全扫);
  本文件为其最优画像的发布固化版,选股/调仓逻辑完全一致,仅默认参数不同。

成交价口径:T+1 + (open+close)/2(项目铁律)。A 股 volume 单位=股。
⚠️ 数据仅含当前在市标的 → 退市股缺失,survivorship bias,结果偏乐观。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from services.backtest.strategy_base import Strategy
from services.backtest.strategies.utils import growth_long, quality, valuation, yield_factor
from services.backtest.strategies.utils.index_timing import csi300_is_bull
from services.backtest.strategies.utils.st_filter import _is_st_on

YI = 1e8  # 1 亿元(市值带参数单位换算)


class LynchSlowGrowersStrategy(Strategy):
    name = "彼得林奇缓慢增长策略"
    description = (
        "林奇六分类·缓慢增长型【发布最优画像】:市值≥300亿大盘蓝筹 + 净利低速正增长"
        "(CAGR 0~8%)+ 连续≥5年分红 + TTM 股息率≥3.5% + 低 PE(≤25)→ 按股息率降序、"
        "每行业≤2只、Top5 等权、年度 6 月调仓。真实 NOTICE_DATE 防 look-ahead + ST 过滤。"
        "全期(2010-2026)年化 15.40% / 回撤 42.28% / 超额 CSI300 +13.47pct。"
    )
    frequency = "monthly"
    frequency_overridable = False
    strategy_type = "strategy"

    params = {
        # ---- 成长(缓慢增长核心:低速正增长双边带)----
        "np_cagr_min": {
            "default": 0.0,
            "type": "float",
            "label": "N 年归母净利 CAGR 下限(小数,缓慢增长要求正增长不衰退;0=只要不亏损萎缩)",
        },
        "np_cagr_max": {
            "default": 0.08,
            "type": "float",
            "label": "N 年归母净利 CAGR 上限(小数,林奇缓慢增长≤8%;0=不设上限)",
        },
        "cagr_years": {
            "default": 3,
            "type": "int",
            "label": "CAGR 回看年数",
        },
        "require_positive_np_cagr": {
            "default": True,
            "type": "bool",
            "label": "要求净利 CAGR 可计算且为正(剔除亏损/萎缩,缓慢增长≠衰退)",
        },
        # ---- 分红(缓慢增长核心持有理由)----
        "min_div_years": {
            "default": 5,
            "type": "int",
            "label": "连续分红年数下限(截至当前日期、除权日 PIT 过滤,林奇:稳定派息≥5年)",
        },
        "min_div_yield": {
            "default": 0.035,
            "type": "float",
            "label": "TTM 股息率下限(小数,如 0.035=3.5%;高股息是缓慢增长型的收益来源)",
        },
        # ---- 估值纪律(成熟股不给成长溢价)----
        "pe_max": {
            "default": 25.0,
            "type": "float",
            "label": "peTTM 上限(低 PE 买入成熟蓝筹)",
        },
        "pe_min": {
            "default": 0.0,
            "type": "float",
            "label": "peTTM 下限(剔除超低 PE 的潜在价值陷阱;0=不过滤)",
        },
        "require_pb_positive": {
            "default": True,
            "type": "bool",
            "label": "要求 pbMRQ>0",
        },
        # ---- 质量(成熟蓝筹应有稳健 ROE;默认关,缓慢增长 ROE 普遍中等)----
        "roe_min": {
            "default": 0.0,
            "type": "float",
            "label": "最新年报 ROE 下限(%,0=不过滤;缓慢增长型 ROE 普遍中等,慎设过高)",
        },
        "roe_consistency_years": {
            "default": 0,
            "type": "int",
            "label": "连续 N 年 ROE≥下限(0=只看最新一年)",
        },
        # ---- 财务质量增强(资产负债率 / 经营现金流;0=不过滤)----
        # 注:快速增长型实证此二者有害;缓慢增长型预期可能正向(稳健蓝筹特征),留作专轮验证。
        "max_debt_ratio": {
            "default": 0.0,
            "type": "float",
            "label": "资产负债率上限(总负债/总资产,如 0.6=≤60%;0=不过滤)",
        },
        "min_cfo_np_ratio": {
            "default": 0.0,
            "type": "float",
            "label": "经营现金流/归母净利下限(如 0.01≈要求 CFO 为正;1.0=现金含量≥100%;0=不过滤)",
        },
        # ---- 市值带(缓慢增长 = 偏好大盘成熟蓝筹,与快速增长型相反)----
        "mktcap_min_yi": {
            "default": 300.0,
            "type": "float",
            "label": "总市值下限(亿元,缓慢增长偏好大盘蓝筹;0=不过滤)",
        },
        "mktcap_max_yi": {
            "default": 0.0,
            "type": "float",
            "label": "总市值上限(亿元,0=不限,大盘不设上限)",
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
            "default": 5,
            "type": "int",
            "label": "持仓数量(等权;发布冠军=5,全期年化/Sharpe 最优)",
        },
        "sort_by": {
            "default": "yield",
            "type": "str",
            "label": "排序键:yield(股息率降序) | pe(低 PE 升序) | composite(yield+pe 复合)",
        },
        "trend_ma_days": {
            "default": 0,
            "type": "int",
            "label": "趋势过滤:要求 close > N 日均线(0=不过滤)",
        },
        "require_industry": {
            "default": False,
            "type": "bool",
            "label": "仅保留有 F10 行业分类的标的",
        },
        "max_per_sector": {
            "default": 2,
            "type": "int",
            "label": "每个一级行业最多持仓数(0=不限;高股息易集中银行/公用事业,可用此分散)",
        },
        "max_valuation_staleness_days": {
            "default": 10,
            "type": "int",
            "label": "估值数据时效上限(交易日,防退市股 stale)",
        },
        "rebalance_months": {
            "default": [6],
            "type": "list[int]",
            "label": "调仓月份(发布版年度 6 月调仓;年报 4/30 披露后,低换手)",
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
    }

    def __init__(self, param_overrides: dict | None = None):
        super().__init__(param_overrides)
        self._target_holdings: list[str] = []
        self._rebalance_pending: bool = False
        self._target_exposure: float = 1.0  # 本次 rebalance 应用的仓位比例
        self._cur_exposure: float = 1.0  # 当前实际生效的仓位比例

    # ---- 分红连续性(PIT:仅统计除权日 <= 当前日期的派息年)----
    @staticmethod
    def _consecutive_dividend_years(ctx, symbol: str, cur_d: date) -> int:
        """截至 cur_d,连续分红年数(以除权日落在当前日期前为准,防 look-ahead)。

        口径:取 cash_dividend>0 且除权日 <= cur_d 的派息记录,按年汇总得"有派息的年份集合";
        从最近的派息年向前数连续年数。要求最近派息年足够新(>= cur_year-1),否则视为已停派(返 0)。
        """
        df = ctx.get_dividend(symbol) if hasattr(ctx, "get_dividend") else None
        if df is None or len(df) == 0:
            return 0
        if "date" not in df.columns or "cash_dividend" not in df.columns:
            return 0
        cash = pd.to_numeric(df["cash_dividend"], errors="coerce")
        mask = cash.notna() & (cash > 0)
        if not mask.any():
            return 0
        cur_year = cur_d.year
        years: set[int] = set()
        for ds in df.loc[mask, "date"].astype(str):
            d = None
            try:
                d = date.fromisoformat(ds[:10])
            except (ValueError, TypeError):
                continue
            if d > cur_d:  # PIT:除权日在未来 → 剔除,防 look-ahead
                continue
            years.add(d.year)
        if not years:
            return 0
        sorted_years = sorted(years)
        last = sorted_years[-1]
        # 最近派息年须足够新(当年或去年),否则认定已停派
        if last < cur_year - 1:
            return 0
        # 从最近派息年向前数连续年数
        run = 1
        i = len(sorted_years) - 1
        while i > 0 and sorted_years[i] - sorted_years[i - 1] == 1:
            run += 1
            i -= 1
        return run

    def _regime_exposure(self, cur_str: str) -> float:
        """根据沪深300 regime 计算目标仓位比例(risk_off_exposure>=1.0 视为关闭择时)。"""
        risk_off = float(self.p.risk_off_exposure)
        if risk_off >= 1.0:
            return 1.0
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
        cagr_years = int(self.p.cagr_years)
        require_pos_cagr = bool(self.p.require_positive_np_cagr)
        min_div_years = int(self.p.min_div_years)
        min_div_yield = float(self.p.min_div_yield)
        pe_max = float(self.p.pe_max)
        pe_min = float(self.p.pe_min)
        require_pb = bool(self.p.require_pb_positive)
        roe_min = float(self.p.roe_min)
        roe_years = int(self.p.roe_consistency_years)
        max_debt_ratio = float(self.p.max_debt_ratio)
        min_cfo_np = float(self.p.min_cfo_np_ratio)
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

        need_hist = max(amt_lookback if min_amount > 0 else 0, trend_ma_days)

        # ---- Stage 1: ST 剔除 + 大市值带 + 低 PE 健康(PIT)+ 时效 + 流动性 + 趋势 ----
        stage1: list[tuple[str, float]] = []  # (sym, pe)
        for sym in symbols:
            if _is_st_on(sym, cur_str):
                continue
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
            if pe_min > 0 and pe < pe_min:
                continue
            if require_pb:
                pb = val.get("pbMRQ")
                if pb is None or pd.isna(pb) or pb <= 0:
                    continue

            # 大市值带:缓慢增长偏好成熟蓝筹(get_total_mv 单位=元)
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
                if trend_ma_days > 0:
                    ma_win = closes[-trend_ma_days:]
                    if len(ma_win) < trend_ma_days:
                        continue
                    if closes[-1] <= sum(ma_win) / len(ma_win):
                        continue
            stage1.append((sym, float(pe)))
        ctx.log_flow("strategy.valuation_mktcap_liquidity", passed=len(stage1))

        # ---- Stage 2: 低速正增长(双边带)+ 质量(真实 NOTICE_DATE,防 look-ahead)----
        stage2: list[tuple[str, float]] = []  # (sym, pe)
        for sym, pe in stage1:
            np_cagr = growth_long.get_net_profit_cagr(ctx, sym, years=cagr_years)
            if require_pos_cagr and np_cagr is None:
                continue
            if np_cagr is not None:
                if np_cagr < np_cagr_min:
                    continue
                if np_cagr_max > 0 and np_cagr > np_cagr_max:
                    continue
            # ROE(可选;缓慢增长默认关闭)
            if roe_min > 0 and not growth_long.all_roe_above(
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
            stage2.append((sym, pe))
            if np_cagr is not None:
                ctx.record_factor(sym, "NP_CAGR", np_cagr)
        ctx.log_flow("strategy.growth_quality", passed=len(stage2))

        # ---- Stage 3: 分红(连续派息年数 + TTM 股息率,缓慢增长核心)----
        stage3: list[tuple[str, float, float]] = []  # (sym, pe, div_yield)
        for sym, pe in stage2:
            if min_div_years > 0:
                dy = self._consecutive_dividend_years(ctx, sym, cur_d)
                if dy < min_div_years:
                    continue
            div_yield = yield_factor.get_dividend_yield_ttm(ctx, sym)
            if div_yield is None:
                continue
            if min_div_yield > 0 and div_yield < min_div_yield:
                continue
            stage3.append((sym, pe, div_yield))
            ctx.record_factor(sym, "DIV_YIELD", div_yield)
            ctx.record_factor(sym, "PE", pe)
        ctx.log_flow("strategy.dividend", passed=len(stage3))

        # ---- Stage 4: 排序 + Top N ----
        if sort_key == "pe":
            stage3.sort(key=lambda x: x[1])  # 低 PE 升序
        elif sort_key == "composite":
            # rank 之和:高股息 + 低 PE
            by_yield = sorted(stage3, key=lambda x: -x[2])
            by_pe = sorted(stage3, key=lambda x: x[1])
            rank: dict[str, int] = {}
            for i, t in enumerate(by_yield):
                rank[t[0]] = rank.get(t[0], 0) + i
            for i, t in enumerate(by_pe):
                rank[t[0]] = rank.get(t[0], 0) + i
            stage3.sort(key=lambda x: rank[x[0]])
        else:
            stage3.sort(key=lambda x: -x[2])  # 股息率降序(默认)

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
        self._target_exposure = desired_exposure
        self._rebalance_pending = True
        return selected

    def on_sell(self, ctx) -> None:
        if not self._rebalance_pending:
            return
        positions = ctx.get_positions()
        target_set = set(self._target_holdings)
        for sym, pos in list(positions.items()):
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
        exposure = self._target_exposure
        w = exposure / len(target)
        for sym in target:
            ctx.order_target_percent(sym, w)
        self._cur_exposure = exposure
        self._rebalance_pending = False
