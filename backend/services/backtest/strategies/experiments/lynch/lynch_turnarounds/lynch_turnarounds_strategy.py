"""彼得·林奇「困境反转型(Turnarounds)」A 股量化策略 —— LynchTurnaroundsStrategy。

林奇六分类法之一。困境反转型 = 曾陷入亏损/经营重挫、如今正从谷底爬出的公司
("battered, depressed companies")。与周期型(靠行业景气规律涨落)不同,困境反转
是**公司特质性的**:困境可发生在任何行业,反转靠自救(削债、剥离、扭亏),
其涨跌与大盘相关性最低——这正是林奇最看重的一点。本策略把这套定性口径机械化。

林奇对 Turnarounds 的核心描述(《One Up on Wall Street》困境反转章节):
- **困境准入(本类的定义性前提)**:标的必须**曾经陷入困境**——近年出现过亏损、
  或利润大幅回撤、或 ROE 深度低迷(distress_mode)。这是把"反转"从"一直便宜的
  普通股"里区分出来的关键门槛。
- **反转信号(灵魂)**:盈利正从底部往上拐 → recovery_mode,**默认 np_turn(扭亏为盈)**
  ——由亏转盈是最强、最经典的困境反转拐点。另有 np_improve(利润同比大幅改善,含亏损收窄)
  / roe_recover(ROE 回升)。用 growth_long.get_annual_history 取年报序列(NOTICE_DATE 严格 PIT),
  **刻意不调 get_recent_net_profit_yoy**(其在上年净利≤0 时返 None,恰好把"扭亏"这种最强信号漏掉)。
- **🚨 市盈率悖论(与周期型同):** 困境公司谷底 E 被压到极低甚至为负 → PE 高/负是常态,
  "低 PE = 便宜"完全失效。故**默认不设 pe_max、不要求 pe>0**;估值锚改用 **PB**
  (账面价值远比困境期利润稳定)→ 低 PB / 破净才是困境价的标志。
- **资产负债表存活性检验(林奇困境反转的核心)**:"How is the company going to survive?
  Is it reducing debt?" → 去杠杆信号(dele_mode:资产负债率逐年下降)+ 经营现金流转正
  (min_cfo_np_ratio)。债务恶化的困境股 = 走向破产而非反转,须剔除。
- **排除金融**:银行/保险/证券资产负债率天然 ≥90%、FCFF/去杠杆框架不适用,整类排除;
  可选连地产一并排除(地产 survivorship bias 最重)。

实现复用已验证的周期型/Stalwarts 选股/调仓骨架(月度筛选、Top N 等权全替换、
真实 NOTICE_DATE 严格 PIT、ST 过滤、可选趋势/行业分散/沪深300 regime 择时、个股止损/移动止损)。
去杠杆信号走 balance_long(NOTICE_DATE 严格 PIT,规避 ctx.get_balance_annual_history 的
REPORT_DATE as-of 在月度调仓下的 ~4 月前视)。卖出靠调仓自然轮出 + 可选移动止损。

成交价口径:T+1 + (open+close)/2(项目铁律)。A 股 volume 单位=股。
⚠️⚠️ 幸存者偏差在本类**最严重**:困境公司真实破产/退市/违约率远高于其它型,而数据仅含
   当前在市标的——"死亡样本"(真反转失败者)系统性缺失,回测收益显著偏乐观,须打足折扣。
⚠️ ST/*ST 是 A 股最极端的困境反转标的(连亏 2 年戴帽→摘帽),但项目 ST 过滤会剔除它们,
   故本策略只能捕捉**非 ST 的困境股**(亏损/重挫但未至 ST,或已摘帽)。这是机械化的固有局限,
   结论须注明"未覆盖最极端反转段"。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from services.backtest.strategy_base import Strategy
from services.backtest.strategies.utils import (
    balance_long,
    growth_long,
    quality,
    valuation,
)
from services.backtest.strategies.utils.index_timing import csi300_is_bull
from services.backtest.strategies.utils.st_filter import _is_st_on

YI = 1e8  # 1 亿元(市值带参数单位换算)

# ── 行业排除(困境反转不设白名单:困境可发生在任何行业;只排除框架不适用者)──
# 金融:银行/保险/证券资产负债率天然 ≥90%,去杠杆/FCFF 框架不适用 → 复用 quality.is_financial_industry
# 地产:退市/违约 survivorship bias 最重的一类,可选一并排除(子串匹配「地产」,覆盖房地产开发/服务/Ⅱ 等)
_REALESTATE_KEYWORDS = ("房地产", "地产")


def _is_realestate_industry(industry_name) -> bool:
    if not industry_name:
        return False
    return any(kw in industry_name for kw in _REALESTATE_KEYWORDS)


def _sector_excluded(industry_name, exclude_mode: str) -> bool:
    """按 exclude_mode 判断该行业是否应被排除。

    - none:不排除任何行业(industry=None 也放行)
    - financial(默认):排除金融业
    - financial_realestate:排除金融 + 地产
    行业未知(None)时:金融关键字无法命中 → 视为不排除(放行,交由其它因子把关)。
    """
    if exclude_mode == "none":
        return False
    if quality.is_financial_industry(industry_name):
        return True
    if exclude_mode == "financial_realestate" and _is_realestate_industry(industry_name):
        return True
    return False


class LynchTurnaroundsStrategy(Strategy):
    name = "A股 林奇·困境反转型(Turnarounds)"
    description = (
        "林奇六分类·困境反转型:排除金融(可选连地产)+ 困境准入(曾亏损/重挫/ROE 低迷)"
        "+ 低 PB 破净估值锚(刻意不卡 PE,规避市盈率悖论)+ 反转信号(默认扭亏为盈)"
        "+ 可选去杠杆(资产负债率逐年下降)/现金流转正 → Top N 等权月度调仓。"
        "真实 NOTICE_DATE 防 look-ahead + ST 过滤 + 可选趋势/行业分散/沪深300 择时/移动止损。"
    )
    frequency = "monthly"
    frequency_overridable = False
    strategy_type = "strategy"

    params = {
        # ---- 行业排除(困境反转不设白名单:困境可发生在任何行业,只排除框架不适用者)----
        "exclude_sectors": {
            "default": "financial",
            "type": "str",
            "label": "行业排除:none(不排除) | financial(排除金融:银行/保险/证券,去杠杆框架不适用) | "
            "financial_realestate(再排除地产,规避地产幸存者偏差最重的一类)",
        },
        # ---- 估值锚:PB(困境公司=破净/低 PB;刻意不用 PE,见 use_pe_filter)----
        "pb_max": {
            "default": 2.0,
            "type": "float",
            "label": "pbMRQ 上限(困境反转估值锚,破净/低 PB 才便宜;0=不过滤)",
        },
        "pb_min": {
            "default": 0.0,
            "type": "float",
            "label": "pbMRQ 下限(剔除极低 PB 价值陷阱/退市边缘;0=不过滤)",
        },
        "require_pb_positive": {
            "default": True,
            "type": "bool",
            "label": "要求 pbMRQ>0(账面价值健康性底线)",
        },
        # ---- 🚨 市盈率悖论:困境股默认不卡 PE(谷底/亏损期 PE 高/负是常态,低 PE 反而是复苏尾声)----
        "use_pe_filter": {
            "default": False,
            "type": "bool",
            "label": "是否启用 PE 过滤(困境反转默认 False;开启则要求 0<peTTM≤pe_max,慎用,与林奇悖论相悖)",
        },
        "pe_max": {
            "default": 0.0,
            "type": "float",
            "label": "peTTM 上限(仅 use_pe_filter=True 时生效;0=不过滤)",
        },
        # ---- 反转信号(灵魂:盈利刚从底部往上拐;困境反转默认 np_turn 扭亏为盈)----
        "recovery_mode": {
            "default": "np_turn",
            "type": "str",
            "label": "反转信号:np_turn(净利由亏转盈,最经典的困境反转拐点) | "
            "np_improve(净利同比改善,含亏损收窄) | rev_improve(营收同比改善) | "
            "roe_recover(ROE 较上年回升) | none(纯低PB破净深价值)",
        },
        "recovery_min_pct": {
            "default": 0.0,
            "type": "float",
            "label": "复苏幅度门槛(%,仅对 *_improve 生效:要求改善幅度≥此值;0=只要为正即可。亏损基数下按绝对额判断)",
        },
        # ---- 困境准入(本类定义性门槛:标的必须"曾陷困境",把反转从普通低估股里区分出来)----
        "distress_mode": {
            "default": "none",
            "type": "str",
            "label": "困境准入:none(不额外设,靠 np_turn 扭亏隐含困境) | "
            "prior_loss(近 distress_lookback 年内至少 1 年净利≤0) | "
            "prior_low_roe(窗口内最低 ROE≤distress_roe_max,曾深度低迷) | "
            "np_drawdown(净利曾从窗口峰值回撤≥distress_np_drop_pct%)",
        },
        "distress_lookback": {
            "default": 3,
            "type": "int",
            "label": "困境回看年数(distress_mode 的年报窗口)",
        },
        "distress_roe_max": {
            "default": 2.0,
            "type": "float",
            "label": "prior_low_roe 阈值(%,窗口内最低 ROE≤此值才算曾困境)",
        },
        "distress_np_drop_pct": {
            "default": 50.0,
            "type": "float",
            "label": "np_drawdown 阈值(%,净利从窗口峰值回撤≥此值才算曾重挫)",
        },
        # ---- 质量底线(困境反转谷底 ROE 天然低甚至为负,默认全关,设下限会过滤掉真正的底部)----
        "roe_min": {
            "default": 0.0,
            "type": "float",
            "label": "最新年报 ROE 下限(%,0=不过滤;困境股谷底 ROE 常低/负,设此值会过滤掉真正的反转起点)",
        },
        "roe_max": {
            "default": 0.0,
            "type": "float",
            "label": "最新年报 ROE 上限(%,0=不过滤;困境反转一般不设上限,除非想剔除已完全康复的票)",
        },
        # ---- 财务质量增强(资产负债率 / 经营现金流;0=不过滤)----
        "max_debt_ratio": {
            "default": 0.0,
            "type": "float",
            "label": "资产负债率上限(总负债/总资产,如 0.7=≤70%;0=不过滤。困境股高杠杆者易走向破产而非反转)",
        },
        "min_cfo_np_ratio": {
            "default": 0.0,
            "type": "float",
            "label": "经营现金流/归母净利下限(如 0.01≈要求 CFO 为正;0=不过滤。剔除纸面利润)",
        },
        # ---- 去杠杆信号(林奇困境反转核心存活性检验:资产负债表是否在改善)----
        # 走 balance_long(NOTICE_DATE 严格 PIT),规避 ctx.get_balance_annual_history 的 REPORT_DATE 前视
        "dele_mode": {
            "default": "none",
            "type": "str",
            "label": "去杠杆信号:none(不要求) | debt_down(资产负债率较 dele_lookback 期前下降) | "
            "debt_down_pct(下降幅度≥dele_min_drop 个百分点)",
        },
        "dele_min_drop": {
            "default": 0.0,
            "type": "float",
            "label": "去杠杆幅度门槛(小数,如 0.02=至少降 2 个百分点;仅 debt_down_pct 生效;0=只要下降)",
        },
        "dele_lookback": {
            "default": 2,
            "type": "int",
            "label": "去杠杆比较年数(2=最新年报较上年;3=较前 2 年)",
        },
        # ---- 市值带(困境股常已被杀成中小盘;默认仅设小盘下限避开微盘退市/流动性陷阱)----
        "mktcap_min_yi": {
            "default": 50.0,
            "type": "float",
            "label": "总市值下限(亿元,默认 50 亿避开微盘流动性/退市陷阱;0=不限)",
        },
        "mktcap_max_yi": {
            "default": 0.0,
            "type": "float",
            "label": "总市值上限(亿元,0=不限)",
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
            "default": 20,
            "type": "int",
            "label": "持仓数量(困境股个股波动大,Top20 兼顾分散与集中;分散尤为重要)",
        },
        "sort_by": {
            "default": "pb",
            "type": "str",
            "label": "排序键:pb(低 PB 升序,谷底优先) | recovery(复苏强度降序) | composite(低PB+强复苏 复合)",
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

    @staticmethod
    def _recovery_signal(hist, mode: str, min_pct: float) -> tuple[bool, float]:
        """根据年报序列(NOTICE_DATE 升序,≥2 行)判断盈利是否从底部回升。

        返回 (是否通过, 复苏强度分数);分数仅用于 recovery / composite 排序。
        - none:不设信号,全通过(分数=0,排序退化为纯低 PB 深价值)
        - np_improve:净利同比改善(含亏损收窄:cur>prev 且改善幅度≥min_pct)
        - np_turn:净利由亏(≤0)转盈(>0)—— 最强困境反转拐点信号
        - rev_improve:营收同比改善(营收比利润稳定,信号更平滑)
        - roe_recover:ROE 较上年回升(回升点数≥min_pct)

        改善幅度按 |上年基数| 归一化为百分比;亏损基数(prev≤0)下扭亏给大正分。
        """
        if mode == "none":
            return True, 0.0
        cur, prev = hist.iloc[-1], hist.iloc[-2]

        def _imp_pct(c, p) -> float | None:
            if c is None or p is None or pd.isna(c) or pd.isna(p):
                return None
            c, p = float(c), float(p)
            denom = abs(p)
            if denom < 1e-9:
                return 999.0 if c > p else (0.0 if c == p else -999.0)
            return max(min((c - p) / denom * 100.0, 999.0), -999.0)

        if mode in ("np_improve", "np_turn"):
            c, p = cur.get("PARENTNETPROFIT"), prev.get("PARENTNETPROFIT")
            if c is None or p is None or pd.isna(c) or pd.isna(p):
                return False, 0.0
            c, p = float(c), float(p)
            imp = _imp_pct(c, p)
            if mode == "np_turn":
                ok = p <= 0.0 < c
            else:
                ok = c > p and imp is not None and imp >= min_pct
            return bool(ok), float(imp if imp is not None else 0.0)

        if mode == "rev_improve":
            c, p = cur.get("TOTALOPERATEREVE"), prev.get("TOTALOPERATEREVE")
            imp = _imp_pct(c, p)
            if imp is None:
                return False, 0.0
            ok = float(c) > float(p) and imp >= min_pct
            return bool(ok), float(imp)

        if mode == "roe_recover":
            c, p = cur.get("ROEJQ"), prev.get("ROEJQ")
            if c is None or p is None or pd.isna(c) or pd.isna(p):
                return False, 0.0
            delta = float(c) - float(p)  # ROE 回升点数
            return bool(delta > 0 and delta >= min_pct), delta

        return True, 0.0

    @staticmethod
    def _distress_signal(
        hist, mode: str, lookback: int, roe_max: float, np_drop_pct: float
    ) -> bool:
        """困境准入门槛:标的近 lookback 年是否**曾陷入困境**(本类的定义性前提)。

        hist:年报序列(NOTICE_DATE 升序,[-1]=最新);取末尾 lookback 行为窗口。
        - none:不设门槛,全通过(反转由 recovery 信号隐含,如 np_turn 已要求上年亏损)
        - prior_loss:窗口内任一年净利 ≤ 0(曾亏损)
        - prior_low_roe:窗口内最低 ROE ≤ roe_max(曾深度低迷)
        - np_drawdown:净利从窗口内某高点回撤 ≥ np_drop_pct%(曾重挫;仅从正峰值计,配合
          running-peak 保证是"先高后低"的真实回撤,而非单纯波动)
        数据缺失 → 保守返 False(无法证明曾困境 → 不准入,避免把普通股当反转)。
        """
        if mode == "none":
            return True
        if hist is None or len(hist) < 2:
            return False
        win = hist.tail(max(2, lookback))

        if mode == "prior_loss":
            for v in win["PARENTNETPROFIT"].values:
                if v is not None and not pd.isna(v) and float(v) <= 0.0:
                    return True
            return False

        if mode == "prior_low_roe":
            roes = [
                float(v)
                for v in win["ROEJQ"].values
                if v is not None and not pd.isna(v)
            ]
            return bool(roes) and min(roes) <= roe_max

        if mode == "np_drawdown":
            nps = [
                float(v)
                for v in win["PARENTNETPROFIT"].values
                if v is not None and not pd.isna(v)
            ]
            if len(nps) < 2:
                return False
            peak = nps[0]
            max_dd = 0.0
            for v in nps:
                if v > peak:
                    peak = v
                if peak > 0:  # 仅从正峰值计回撤(全程亏损归 prior_loss 处理)
                    dd = (peak - v) / abs(peak) * 100.0
                    max_dd = max(max_dd, dd)
            return max_dd >= np_drop_pct

        return True

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

        exclude_mode = str(self.p.exclude_sectors).lower()
        pb_max = float(self.p.pb_max)
        pb_min = float(self.p.pb_min)
        require_pb = bool(self.p.require_pb_positive)
        use_pe_filter = bool(self.p.use_pe_filter)
        pe_max = float(self.p.pe_max)
        recovery_mode = str(self.p.recovery_mode).lower()
        recovery_min_pct = float(self.p.recovery_min_pct)
        distress_mode = str(self.p.distress_mode).lower()
        distress_lookback = int(self.p.distress_lookback)
        distress_roe_max = float(self.p.distress_roe_max)
        distress_np_drop = float(self.p.distress_np_drop_pct)
        roe_min = float(self.p.roe_min)
        roe_max = float(self.p.roe_max)
        max_debt_ratio = float(self.p.max_debt_ratio)
        min_cfo_np = float(self.p.min_cfo_np_ratio)
        dele_mode = str(self.p.dele_mode).lower()
        dele_min_drop = float(self.p.dele_min_drop)
        dele_lookback = int(self.p.dele_lookback)
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

        # ---- Stage 1: ST 剔除 + 行业排除(金融/可选地产) + 低 PB 估值锚 + 市值带 + 时效 + 流动性 + 趋势 ----
        stage1: list[tuple[str, float]] = []  # (sym, pb) —— PB 是困境反转估值锚(破净修复)
        for sym in symbols:
            # A 股特有:当日 ST 直接剔除(⚠️ 这也剔除了最极端的 *ST 反转标的,见模块 docstring 局限)
            if _is_st_on(sym, cur_str):
                continue
            # 行业排除(困境反转不设白名单):排除金融(去杠杆框架不适用)+ 可选地产
            industry = quality.get_industry(ctx, sym)
            if _sector_excluded(industry, exclude_mode):
                continue
            # require_industry:仅保留有 F10 行业分类的标的(用于确保能识别并排除金融)
            if require_industry and industry is None:
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
            # 估值锚:PB(困境=破净/低 PB)。require_pb 保证账面健康,pb_max/pb_min 限定破净区间
            pb = val.get("pbMRQ")
            pb_ok = pb is not None and not pd.isna(pb)
            if require_pb and (not pb_ok or pb <= 0):
                continue
            if pb_max > 0 and (not pb_ok or pb > pb_max):
                continue
            if pb_min > 0 and (not pb_ok or pb < pb_min):
                continue
            pb_val = float(pb) if pb_ok else float("nan")
            # 🚨 市盈率悖论:默认不卡 PE。仅 use_pe_filter=True 时才要求 0<peTTM≤pe_max
            if use_pe_filter:
                pe = val.get("peTTM")
                if pe is None or pd.isna(pe) or pe <= 0:
                    continue
                if pe_max > 0 and pe > pe_max:
                    continue

            # 市值带(get_total_mv 单位=元):默认仅设小盘下限避开微盘
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
            stage1.append((sym, pb_val))
        ctx.log_flow("strategy.sector_pb_mktcap_liquidity", passed=len(stage1))

        # ---- Stage 2: 困境准入 + 反转信号 + 去杠杆 + 质量底线(真实 NOTICE_DATE 年报序列,防 look-ahead)----
        # distress_mode 需要足够长的年报窗口;recovery 只用最后 2 行,故一次取够 max(2, lookback)
        hist_years = max(2, distress_lookback) if distress_mode != "none" else 2
        stage3: list[tuple[str, float, float]] = []  # (sym, pb, recovery_score)
        for sym, pb_val in stage1:
            hist = growth_long.get_annual_history(ctx, sym, n_years=hist_years)
            if hist is None or len(hist) < 2:
                continue
            # ROE 质量底线(最新年报 ROEJQ;默认全关,困境谷底 ROE 天然低/负)
            if roe_min > 0 or roe_max > 0:
                latest_roe = hist.iloc[-1].get("ROEJQ")
                if latest_roe is None or pd.isna(latest_roe):
                    if roe_min > 0:
                        continue  # 要求 ROE 下限但缺失 → 谨慎剔除
                else:
                    lr = float(latest_roe)
                    if roe_min > 0 and lr < roe_min:
                        continue
                    if roe_max > 0 and lr > roe_max:
                        continue  # ROE 已完全康复 → 可选剔除
            # 🚨 困境准入(定义性门槛):标的必须曾陷困境,否则不是"反转"
            if not self._distress_signal(
                hist, distress_mode, distress_lookback, distress_roe_max, distress_np_drop
            ):
                continue
            # 反转信号(灵魂):盈利/营收/ROE 是否从底部往上拐(默认 np_turn 扭亏)
            passed_rec, rec_score = self._recovery_signal(
                hist, recovery_mode, recovery_min_pct
            )
            if not passed_rec:
                continue
            # 去杠杆信号(林奇存活性检验):资产负债率是否逐年下降(balance_long 严格 PIT)
            if dele_mode != "none":
                min_drop = dele_min_drop if dele_mode == "debt_down_pct" else 0.0
                dele = balance_long.is_deleveraging(
                    ctx, sym, min_drop=min_drop, lookback=dele_lookback
                )
                # 数据不足(None)→ 无法证明去杠杆 → 剔除(去杠杆是主动要求的正向门槛)
                if dele is not True:
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
            stage3.append((sym, pb_val, rec_score))
            ctx.record_factor(sym, "PB", pb_val)
            ctx.record_factor(sym, "RECOVERY", rec_score)
        ctx.log_flow("strategy.distress_recovery_quality", passed=len(stage3))

        # ---- Stage 4: 排序 + Top N ----
        if sort_key == "recovery":
            stage3.sort(key=lambda x: -x[2])  # 复苏强度降序
        elif sort_key == "composite":
            # rank 之和:低 PB + 强复苏
            by_pb = sorted(stage3, key=lambda x: x[1])
            by_rec = sorted(stage3, key=lambda x: -x[2])
            rank: dict[str, int] = {}
            for i, t in enumerate(by_pb):
                rank[t[0]] = rank.get(t[0], 0) + i
            for i, t in enumerate(by_rec):
                rank[t[0]] = rank.get(t[0], 0) + i
            stage3.sort(key=lambda x: rank[x[0]])
        else:
            stage3.sort(key=lambda x: x[1])  # pb 升序(谷底优先)

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
