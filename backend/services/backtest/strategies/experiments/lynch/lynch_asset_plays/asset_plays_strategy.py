"""彼得·林奇「隐蔽资产型(Asset Plays)」A 股量化策略 —— LynchAssetPlaysStrategy。

林奇六分类法的最后一类。隐蔽资产型 = 拥有市场尚未察觉的、被低估资产的公司:土地/物业、
资源储量、品牌/专利、长期股权投资、递延税盈、账上净现金等。林奇的打法是**买入其资产的
市场折价**,等价值被重估或释放(变卖/分拆/回购/被并购)。

🚨 诚实边界(务必先读):真正的「隐蔽资产」(重估增值的土地、矿产储量、品牌溢价、股权公允价值)
   **无法从标准财报纯机械提取** —— 财报按历史成本计量,恰恰藏住了这些增值。因此本策略只能用
   **可量化代理指标**逼近「资产被低估」这一命题,天花板受此约束:
   - **破净锚**(pbMRQ:市值 < 账面净资产)—— 账面折价的第一道。
   - **有形账面折价**(灵魂,剔虚):有形账面价值 TBV = 归母权益 − 商誉 − 无形资产,
     有形PB = 市值 / TBV。因 TBV ≤ 净资产,有形PB ≥ 普通PB,这一步比单纯 PB<1 更严 ——
     **过滤掉「账面破净但剔掉商誉/无形后并不便宜」的假折价**。
   - **净现金增强**(路径 A 降级为可选因子):净现金 = 货币资金 − 总负债,净现金/市值 越高越像
     格雷厄姆式「钱袋子」(现金是最不可造假的隐蔽资产)。
   - **质量底线防价值陷阱**:破净股最大的坑是持续亏损/退市边缘的僵尸股 → 默认要求最新年报
     归母净利 > 0;可选加 ROE 下限 / 资产负债率上限。

实现复用已验证的 Cyclicals/Stalwarts 选股/调仓骨架(月度筛选、Top N 等权全替换、真实
NOTICE_DATE 严格 PIT、ST 过滤、可选趋势/行业分散/沪深300 regime 择时、个股止损/移动止损)。
卖出靠调仓自然轮出(资产折价修复/跌出目标池)+ 可选移动止损。

成交价口径:T+1 + (open+close)/2(项目铁律)。A 股 volume 单位=股。
⚠️ 数据仅含当前在市标的 → 退市股缺失,survivorship bias。**破净股集中于银行/地产/钢铁/建筑,
   其中地产 2021+ 违约退市率高,缺失的「死亡样本」会让回测偏乐观**;破净又常与「低估值风格周期」
   (2014 底、2021-24 价值回归)绑定,结论须做子区间审计 + 幸存者偏差折扣。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from services.backtest.strategy_base import Strategy
from services.backtest.strategies.utils import balance_long, growth_long, quality, valuation
from services.backtest.strategies.utils.index_timing import csi300_is_bull
from services.backtest.strategies.utils.st_filter import _is_st_on

YI = 1e8  # 1 亿元(市值带参数单位换算)


class LynchAssetPlaysStrategy(Strategy):
    name = "A股 林奇·隐蔽资产型(Asset Plays)"
    description = (
        "林奇六分类·隐蔽资产型:破净锚 + 有形账面折价(剔商誉/无形的真便宜)+ 净现金增强 "
        "+ 归母净利>0 质量底线防僵尸 → Top N 等权月度调仓。"
        "真实 NOTICE_DATE 防 look-ahead + ST 过滤 + 可选趋势/行业分散/沪深300 择时/移动止损。"
    )
    frequency = "monthly"
    frequency_overridable = False
    strategy_type = "strategy"

    params = {
        # ---- 破净锚(账面折价第一道)----
        "pb_max": {
            "default": 1.5,
            "type": "float",
            "label": "pbMRQ 上限(破净锚,账面折价;含接近破净;0=不过滤)",
        },
        "pb_min": {
            "default": 0.0,
            "type": "float",
            "label": "pbMRQ 下限(剔极低 PB 退市边缘/价值陷阱;0=不过滤)",
        },
        "require_pb_positive": {
            "default": True,
            "type": "bool",
            "label": "要求 pbMRQ>0(账面价值健康底线,剔负净资产)",
        },
        # ---- 有形账面折价(灵魂:剔虚)----
        "tangible_pb_max": {
            "default": 1.0,
            "type": "float",
            "label": "有形 PB 上限 = 市值/(归母权益−商誉−无形);剔虚后仍破净才算真便宜;0=不过滤",
        },
        "require_positive_tbv": {
            "default": True,
            "type": "bool",
            "label": "要求有形账面价值>0(净资产不能全靠商誉/无形撑起)",
        },
        # ---- 质量底线(防破净价值陷阱)----
        "require_positive_np": {
            "default": True,
            "type": "bool",
            "label": "要求最新年报归母净利>0(剔持续亏损/退市风险僵尸股)",
        },
        "roe_min": {
            "default": 0.0,
            "type": "float",
            "label": "最新年报 ROE 下限(%,0=不过滤;破净股 ROE 天然偏低,慎设)",
        },
        "max_debt_ratio": {
            "default": 0.0,
            "type": "float",
            "label": "资产负债率上限(总负债/总资产,如 0.7=≤70%;0=不过滤,防高杠杆爆雷)",
        },
        # ---- 净现金增强(路径 A 降级为可选因子)----
        "min_net_cash_ratio": {
            "default": 0.0,
            "type": "float",
            "label": "净现金率下限 =(货币资金−总负债)/市值(如 0.3=净现金≥3成市值;0=不过滤)",
        },
        # ---- 市值带 ----
        "mktcap_min_yi": {
            "default": 50.0,
            "type": "float",
            "label": "总市值下限(亿元,默认 50 亿避微盘流动性陷阱;0=不限)",
        },
        "mktcap_max_yi": {
            "default": 0.0,
            "type": "float",
            "label": "总市值上限(亿元,0=不限)",
        },
        # ---- 流动性 ----
        "min_amount_cny": {
            "default": 5e7,
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
            "default": 20,
            "type": "int",
            "label": "持仓数量(Top N 等权)",
        },
        "sort_by": {
            "default": "tangible_pb",
            "type": "str",
            "label": "排序键:tangible_pb(有形PB升序,剔虚最便宜优先) | pb(PB升序) | "
            "net_cash(净现金率降序) | composite(有形PB+净现金 复合)",
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
            "default": 0,
            "type": "int",
            "label": "每个一级行业最多持仓数(0=不限;破净集中于银行/地产/钢铁,分散尤重要)",
        },
        "max_valuation_staleness_days": {
            "default": 10,
            "type": "int",
            "label": "估值数据时效上限(交易日,防退市股 stale)",
        },
        "rebalance_months": {
            "default": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
            "type": "list[int]",
            "label": "调仓月份(价值型月度易 churn,可搜 [6]/[6,12] 降换手;PIT 取数已防 look-ahead)",
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

        pb_max = float(self.p.pb_max)
        pb_min = float(self.p.pb_min)
        require_pb = bool(self.p.require_pb_positive)
        tangible_pb_max = float(self.p.tangible_pb_max)
        require_tbv = bool(self.p.require_positive_tbv)
        require_np = bool(self.p.require_positive_np)
        roe_min = float(self.p.roe_min)
        max_debt_ratio = float(self.p.max_debt_ratio)
        min_net_cash_ratio = float(self.p.min_net_cash_ratio)
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

        # ---- Stage 1: ST 剔除 + 破净锚(PB 带)+ 市值(必算,tangible_pb/net_cash 分母)+ 时效 + 流动性 + 趋势 ----
        stage1: list[tuple[str, float, float]] = []  # (sym, pb, mv)
        for sym in symbols:
            # A 股特有:当日 ST 直接剔除
            if _is_st_on(sym, cur_str):
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
            # 破净锚:PB 带。require_pb 保证账面健康,pb_max/pb_min 限定折价区间
            pb = val.get("pbMRQ")
            pb_ok = pb is not None and not pd.isna(pb)
            if require_pb and (not pb_ok or pb <= 0):
                continue
            if pb_max > 0 and (not pb_ok or pb > pb_max):
                continue
            if pb_min > 0 and (not pb_ok or pb < pb_min):
                continue
            pb_val = float(pb) if pb_ok else float("nan")
            # 市值(单位=元):隐蔽资产型必算 —— 有形PB、净现金率都以市值为分母
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
            stage1.append((sym, pb_val, mv))
        ctx.log_flow("strategy.pb_mktcap_liquidity", passed=len(stage1))

        # ---- Stage 2: 有形账面折价(剔虚)+ 质量底线 + 净现金增强(真实 NOTICE_DATE 年报,防 look-ahead)----
        stage2: list[tuple[str, float, float, float]] = []  # (sym, pb, tangible_pb, net_cash_ratio)
        for sym, pb_val, mv in stage1:
            # 有形账面价值 TBV = 归母权益 − 商誉 − 无形(剔虚灵魂)
            tbv = balance_long.get_tangible_equity(ctx, sym)
            if require_tbv and (tbv is None or tbv <= 0):
                continue
            # 有形 PB = 市值 / TBV(核心折价锚)
            tangible_pb = float("nan")
            if tbv is not None and tbv > 0:
                tangible_pb = mv / tbv
                if tangible_pb_max > 0 and tangible_pb > tangible_pb_max:
                    continue
            elif tangible_pb_max > 0:
                # 需要有形 PB 上限但 TBV 无效 → 无法判定折价, 保守剔除
                continue

            # 质量底线:最新年报归母净利>0 / ROE 下限(NOTICE_DATE 严格 PIT)
            if require_np or roe_min > 0:
                hist = growth_long.get_annual_history(ctx, sym, n_years=1)
                if hist is None or len(hist) < 1:
                    if require_np:
                        continue  # 要求盈利底线但缺年报数据 → 谨慎剔除
                else:
                    latest = hist.iloc[-1]
                    if require_np:
                        npr = latest.get("PARENTNETPROFIT")
                        if npr is None or pd.isna(npr) or float(npr) <= 0:
                            continue  # 持续亏损/僵尸股, 破净价值陷阱
                    if roe_min > 0:
                        roe = latest.get("ROEJQ")
                        if roe is None or pd.isna(roe) or float(roe) < roe_min:
                            continue

            # 净现金率 =(货币资金−总负债)/ 市值。min>0 时作硬门槛;否则仅算出供排序/记录
            net_cash_ratio = float("nan")
            nc = balance_long.get_net_cash(ctx, sym)
            if nc is not None:
                net_cash_ratio = nc / mv
            if min_net_cash_ratio > 0:
                if pd.isna(net_cash_ratio) or net_cash_ratio < min_net_cash_ratio:
                    continue

            # 资产负债率上限(数据缺失=放行,遵循 quality util 设计原则)
            if max_debt_ratio > 0:
                dr = quality.get_debt_ratio(ctx, sym)
                if dr is not None and dr > max_debt_ratio:
                    continue

            stage2.append((sym, pb_val, tangible_pb, net_cash_ratio))
            ctx.record_factor(sym, "PB", pb_val)
            if not pd.isna(tangible_pb):
                ctx.record_factor(sym, "TANGIBLE_PB", tangible_pb)
            if not pd.isna(net_cash_ratio):
                ctx.record_factor(sym, "NET_CASH_RATIO", net_cash_ratio)
        ctx.log_flow("strategy.tangible_quality", passed=len(stage2))

        # ---- Stage 3: 排序 + Top N ----
        # nan 兜底:升序键给大值(排最后),降序键给极小值(排最后)
        def _tpb_key(x):
            return x[2] if not pd.isna(x[2]) else 1e18

        def _nc_key(x):
            return x[3] if not pd.isna(x[3]) else -1e18

        if sort_key == "pb":
            stage2.sort(key=lambda x: x[1] if not pd.isna(x[1]) else 1e18)
        elif sort_key == "net_cash":
            stage2.sort(key=lambda x: -_nc_key(x))  # 净现金率降序
        elif sort_key == "composite":
            # rank 之和:有形 PB 低(便宜) + 净现金率高(现金厚)
            by_tpb = sorted(stage2, key=_tpb_key)
            by_nc = sorted(stage2, key=lambda x: -_nc_key(x))
            rank: dict[str, int] = {}
            for i, t in enumerate(by_tpb):
                rank[t[0]] = rank.get(t[0], 0) + i
            for i, t in enumerate(by_nc):
                rank[t[0]] = rank.get(t[0], 0) + i
            stage2.sort(key=lambda x: rank[x[0]])
        else:  # tangible_pb(默认):剔虚后最便宜优先
            stage2.sort(key=_tpb_key)

        # ---- 行业分散:每个一级行业最多 max_per_sector 只(贪心,保排序优先级)----
        if max_per_sector > 0:
            sector_count: dict[str, int] = {}
            capped: list[tuple[str, float, float, float]] = []
            for t in stage2:
                sec = quality.get_industry(ctx, t[0]) or "__UNKNOWN__"
                if sector_count.get(sec, 0) >= max_per_sector:
                    continue
                sector_count[sec] = sector_count.get(sec, 0) + 1
                capped.append(t)
                if len(capped) >= top_n:
                    break
            stage2 = capped
        elif require_industry:
            stage2 = [t for t in stage2 if quality.get_industry(ctx, t[0])]

        selected = [t[0] for t in stage2[:top_n]]
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
