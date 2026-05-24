"""§17 衍生指标(技术 + 估值分位 + 绝对估值预计算)。

- §17(头部)兼容旧 indicators.get_indicator_snapshot 接口(MA/MACD/PE PB 分位)
- §17.8 绝对估值预计算:从 DuckDBStore 实时拉数计算
    * 总市值 = TOTAL_SHARE × 最新收盘价
    * 扣除现金 PE = (市值 − 货币资金) / 归母净利润(年报最新)
    * FCF Yield = (经营现金流净额 − 资本开支) / 市值
    * 净负债/权益 = (总负债 − 货币资金) / 股东权益
    * EV/EBIT(代理 EBITDA)= (市值 + 总负债 − 现金) / 经营利润
"""

from __future__ import annotations

from typing import Optional


def _f(snap: dict, key: str, digits: int = 2) -> str:
    v = snap.get(key)
    if v is None:
        return "—"
    if isinstance(v, (int, float)):
        return f"{v:,.{digits}f}"
    return str(v)


def _pct(snap: dict, key: str) -> str:
    v = snap.get(key)
    if v is None:
        return "—"
    try:
        return f"{int(float(v) * 100)}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_num(v: Optional[float], digits: int = 2) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):,.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_pct(v: Optional[float], digits: int = 2) -> str:
    """v 为小数(0.05 → 5.00%)。"""
    if v is None:
        return "—"
    try:
        return f"{float(v) * 100:,.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_yi(v: Optional[float]) -> str:
    """金额(元)→ 亿元字符串。"""
    if v is None:
        return "—"
    try:
        return f"{float(v) / 1e8:,.2f} 亿"
    except (TypeError, ValueError):
        return "—"


def _safe_div(num: Optional[float], den: Optional[float]) -> Optional[float]:
    if num is None or den is None:
        return None
    try:
        d = float(den)
        if d == 0:
            return None
        return float(num) / d
    except (TypeError, ValueError):
        return None


def _build_legacy_header(indicators) -> str:
    """兼容旧 indicators.get_indicator_snapshot 接口的技术指标行。"""
    snap: dict = {}
    try:
        getter = getattr(indicators, "get_indicator_snapshot", None)
        if callable(getter):
            snap = getter(getattr(indicators, "_code", None)) or {}
    except Exception:  # noqa: BLE001
        snap = {}
    return (
        f"- MA5/MA10/MA20/MA60:{_f(snap, 'MA5')} / {_f(snap, 'MA10')} / "
        f"{_f(snap, 'MA20')} / {_f(snap, 'MA60')}\n"
        f"- MACD(DIF/DEA/BAR):{_f(snap, 'MACD_DIF')} / "
        f"{_f(snap, 'MACD_DEA')} / {_f(snap, 'MACD_BAR')}\n"
        f"- PE 历史分位(5 年):{_pct(snap, 'PE_PCT_5Y')}\n"
        f"- PB 历史分位(5 年):{_pct(snap, 'PB_PCT_5Y')}\n"
    )


def _build_legacy_header_with_code(indicators, code: str) -> str:
    """旧接口签名是 get_indicator_snapshot(code),不是属性。"""
    snap: dict = {}
    try:
        getter = getattr(indicators, "get_indicator_snapshot", None)
        if callable(getter):
            snap = getter(code) or {}
    except Exception:  # noqa: BLE001
        snap = {}
    return (
        f"- MA5/MA10/MA20/MA60:{_f(snap, 'MA5')} / {_f(snap, 'MA10')} / "
        f"{_f(snap, 'MA20')} / {_f(snap, 'MA60')}\n"
        f"- MACD(DIF/DEA/BAR):{_f(snap, 'MACD_DIF')} / "
        f"{_f(snap, 'MACD_DEA')} / {_f(snap, 'MACD_BAR')}\n"
        f"- PE 历史分位(5 年):{_pct(snap, 'PE_PCT_5Y')}\n"
        f"- PB 历史分位(5 年):{_pct(snap, 'PB_PCT_5Y')}\n"
    )


def _latest_close(store, code: str) -> Optional[float]:
    """取最新一根日线收盘价。"""
    try:
        rows = store.query_qfq_kline_for_section(code, freq="D", limit=1, order="desc")
    except Exception:  # noqa: BLE001
        return None
    if not rows:
        return None
    try:
        return float(rows[0].get("close"))
    except (TypeError, ValueError):
        return None


def _latest_annual(rows: list) -> dict:
    """财务表 query 已按 REPORT_DATE DESC 返回,首行即最新年报。"""
    if not rows:
        return {}
    return rows[0] or {}


def _build_valuation_subsection(store, code: str) -> str:
    """§17.8 绝对估值预计算 — 从 store 实时拉数。"""
    if store is None:
        return "\n### §17.8 绝对估值预计算\n\n_数据缺失:store 不可用_\n"

    # 1) 价格 + 总股本
    close = _latest_close(store, code)
    total_share: Optional[int] = None
    try:
        total_share = store.query_total_shares_for_section(code)
    except Exception:  # noqa: BLE001
        total_share = None

    market_cap: Optional[float] = None
    if close is not None and total_share:
        market_cap = float(close) * float(total_share)

    # 2) 三表年报最新
    try:
        income = _latest_annual(
            store.query_financial_for_section(code, "income", years=1)
        )
    except Exception:  # noqa: BLE001
        income = {}
    try:
        balance = _latest_annual(
            store.query_financial_for_section(code, "balance", years=1)
        )
    except Exception:  # noqa: BLE001
        balance = {}
    try:
        cashflow = _latest_annual(
            store.query_financial_for_section(code, "cashflow", years=1)
        )
    except Exception:  # noqa: BLE001
        cashflow = {}

    cash = balance.get("MONETARY_FUND")
    total_liab = balance.get("TOTAL_LIABILITIES")
    total_equity = balance.get("TOTAL_EQUITY")
    netprofit = income.get("PARENT_NETPROFIT") or income.get("NETPROFIT")
    operate_profit = income.get("OPERATE_PROFIT")
    netcash_op = cashflow.get("NETCASH_OPERATE")
    capex = cashflow.get("CONSTRUCT_LONG_ASSET")
    report_date = (
        balance.get("REPORT_DATE")
        or income.get("REPORT_DATE")
        or cashflow.get("REPORT_DATE")
        or "—"
    )

    # 3) 衍生计算
    cash_adj_pe = _safe_div(
        (market_cap - float(cash))
        if (market_cap is not None and cash is not None)
        else None,
        netprofit,
    )
    fcf = None
    if netcash_op is not None:
        fcf = float(netcash_op) - float(capex or 0)
    fcf_yield = _safe_div(fcf, market_cap)
    net_debt = None
    if total_liab is not None and cash is not None:
        net_debt = float(total_liab) - float(cash)
    net_debt_to_equity = _safe_div(net_debt, total_equity)
    ev = None
    if market_cap is not None and total_liab is not None and cash is not None:
        ev = market_cap + float(total_liab) - float(cash)
    ev_to_ebit = _safe_div(ev, operate_profit)

    return (
        "\n### §17.8 绝对估值预计算\n\n"
        f"- 数据基准:报告期 {report_date},最新收盘价 {_fmt_num(close)},"
        f"总股本 {_fmt_yi(total_share)}股\n"
        f"- 总市值:{_fmt_yi(market_cap)}\n"
        f"- 货币资金:{_fmt_yi(cash)} | 总负债:{_fmt_yi(total_liab)} | "
        f"股东权益:{_fmt_yi(total_equity)}\n"
        f"- 归母净利润:{_fmt_yi(netprofit)} | 经营利润:{_fmt_yi(operate_profit)}\n"
        f"- 经营现金流:{_fmt_yi(netcash_op)} | 资本开支:{_fmt_yi(capex)} | "
        f"自由现金流:{_fmt_yi(fcf)}\n"
        "\n**估值倍数(EBITDA 缺 D&A,以 EBIT 代理):**\n\n"
        f"- 扣除现金 PE:{_fmt_num(cash_adj_pe)}x\n"
        f"- FCF Yield:{_fmt_pct(fcf_yield)}\n"
        f"- 净负债 / 股东权益:{_fmt_pct(net_debt_to_equity)}\n"
        f"- EV / EBIT(代理):{_fmt_num(ev_to_ebit)}x\n"
        "\n_注:EV/EBITDA 需 D&A 字段,当前 EastMoney cashflow 视图未抽取 "
        "DEPRECIATION_FA,以 EV/EBIT 代理。_\n"
    )


def build(ref, *, store=None, stock_index=None, indicators=None, **_) -> str:
    legacy = _build_legacy_header_with_code(indicators, ref.code)
    valuation = _build_valuation_subsection(store, ref.code)
    return "## §17 衍生指标(技术 + 估值分位)\n\n" + legacy + valuation
