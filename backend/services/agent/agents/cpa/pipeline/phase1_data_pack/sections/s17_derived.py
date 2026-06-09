"""§17 衍生指标(技术 + 估值分位 + 绝对估值预计算)。

- §17(头部)兼容旧 indicators.get_indicator_snapshot 接口(MA/MACD/PE PB 分位)
- §17.8 绝对估值预计算:从 DuckDBStore 实时拉数计算
    * 总市值 = TOTAL_SHARE × 最新收盘价
    * 扣除现金 PE = (市值 − 货币资金) / 归母净利润(年报最新)
    * FCF Yield = (经营现金流净额 − 资本开支) / 市值
    * 净负债/权益 = (总负债 − 货币资金) / 股东权益
    * EV/EBITDA = (市值 + 总负债 − 现金) / (经营利润 + D&A) ← 真实值,
      D&A 来自 EastMoneyAdapter.fetch_da_breakdown(GCASHFLOW 接口),A 股专用
    * EV/EBIT = (市值 + 总负债 − 现金) / 经营利润 ← 参考值;D&A 不可得时为唯一估值
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


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
        import math

        n = float(num)
        d = float(den)
        if math.isnan(n) or math.isnan(d) or d == 0:
            return None
        return n / d
    except (TypeError, ValueError):
        return None


def _clean(v):
    """None / NaN 统一为 None,数值原样返回。Parquet 缺失值常以 NaN 出现。"""
    if v is None:
        return None
    try:
        import math

        if isinstance(v, float) and math.isnan(v):
            return None
    except Exception:  # noqa: BLE001
        pass
    return v


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


def _is_a_share(code: str) -> bool:
    upper = (code or "").upper()
    return upper.endswith((".SH", ".SZ", ".BJ"))


def _resolve_em_adapter(em_adapter, code: str):
    if em_adapter is not None:
        return em_adapter
    try:
        from adapters.eastmoney_adapter import EastMoneyAdapter

        return EastMoneyAdapter()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"§17 EastMoneyAdapter 初始化失败 {code}: {exc}")
        return None


def _fetch_da(code: str, report_date: Optional[str], em_adapter) -> Optional[dict]:
    """获取指定报告期的 D&A 五项明细。失败 / 非 A 股 → None。"""
    if not report_date or not _is_a_share(code):
        return None
    adapter = _resolve_em_adapter(em_adapter, code)
    if adapter is None:
        return None
    fn = getattr(adapter, "fetch_da_breakdown", None)
    if fn is None:
        return None
    try:
        return fn(code, str(report_date)[:10])
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"§17 D&A 获取失败 {code} {report_date}: {exc}")
        return None


def _da_total(da: Optional[dict]) -> Optional[float]:
    """五项 D&A 加总。全 None → None;部分 None 视为 0。"""
    if not da:
        return None
    fields = (
        "FA_IR_DEPR",
        "IA_AMORTIZE",
        "LPE_AMORTIZE",
        "USERIGHT_ASSET_AMORTIZE",
        "DEFER_INCOME_AMORTIZE",
    )
    vals = [da.get(k) for k in fields]
    if all(v is None for v in vals):
        return None
    return float(sum((v or 0) for v in vals))


def _build_valuation_subsection(store, code: str, em_adapter=None) -> str:
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

    # HK balance.CASH_EQUIVALENTS 数据源经常为 NaN(yfinance/EastMoney HK 特点);
    # 退化用 cashflow.END_CASH(年末现金及现金等价物)兜底,语义等价
    cash = _clean(balance.get("MONETARY_FUND")) or _clean(cashflow.get("END_CASH"))
    total_liab = _clean(balance.get("TOTAL_LIABILITIES"))
    total_equity = _clean(balance.get("TOTAL_EQUITY"))
    netprofit = _clean(income.get("PARENT_NETPROFIT")) or _clean(
        income.get("NETPROFIT")
    )
    operate_profit = _clean(income.get("OPERATE_PROFIT"))
    netcash_op = _clean(cashflow.get("NETCASH_OPERATE"))
    capex = _clean(cashflow.get("CONSTRUCT_LONG_ASSET"))
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

    # D&A → 真实 EBITDA(GCASHFLOW 接口,A 股专用,失败降级)
    da_payload = _fetch_da(code, balance.get("REPORT_DATE"), em_adapter)
    da_total = _da_total(da_payload)
    ebitda: Optional[float] = None
    if operate_profit is not None and da_total is not None:
        ebitda = float(operate_profit) + da_total
    ev_to_ebitda = _safe_div(ev, ebitda)

    da_block = ""
    if da_total is not None and da_payload is not None:
        da_block = (
            f"- D&A 明细(报告期 {da_payload.get('REPORT_DATE', '—')}):"
            f"固定资产折旧 {_fmt_yi(da_payload.get('FA_IR_DEPR'))} + "
            f"无形资产摊销 {_fmt_yi(da_payload.get('IA_AMORTIZE'))} + "
            f"长期待摊 {_fmt_yi(da_payload.get('LPE_AMORTIZE'))} + "
            f"使用权资产摊销 {_fmt_yi(da_payload.get('USERIGHT_ASSET_AMORTIZE'))} + "
            f"递延收益摊销 {_fmt_yi(da_payload.get('DEFER_INCOME_AMORTIZE'))} = "
            f"**{_fmt_yi(da_total)}**\n"
            f"- EBITDA = 经营利润 + D&A = {_fmt_yi(ebitda)}\n"
        )
        ebitda_line = (
            f"- EV / EBITDA(标准估值倍数):{_fmt_num(ev_to_ebitda)}x\n"
            f"- EV / EBIT(参考):{_fmt_num(ev_to_ebit)}x\n"
        )
        note = ""
    else:
        ebitda_line = (
            f"- EV / EBIT(**EBITDA 代理值,D&A 数据不可得**):{_fmt_num(ev_to_ebit)}x\n"
        )
        note = (
            "\n_注:标准 EV/EBITDA 需 D&A 数据,当前(非 A 股 / GCASHFLOW 接口失败 / "
            '该报告期无明细)不可得,以 EV/EBIT 代理;引用请明确标注"代理值"。_\n'
        )

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
        + da_block
        + "\n**估值倍数(请按字段名原样引用,不要重命名):**\n\n"
        f"- 扣除现金 PE(Cash-Adjusted PE):{_fmt_num(cash_adj_pe)}x\n"
        f"- FCF Yield(自由现金流收益率):{_fmt_pct(fcf_yield)}\n"
        f"- 净负债权益比(Net Debt / Equity,**不是** Net Debt / EBITDA):"
        f"{_fmt_pct(net_debt_to_equity)}\n" + ebitda_line + note
    )


def build(
    ref,
    *,
    store=None,
    stock_index=None,
    indicators=None,
    em_adapter=None,
    **_,
) -> str:
    legacy = _build_legacy_header_with_code(indicators, ref.code)
    valuation = _build_valuation_subsection(store, ref.code, em_adapter=em_adapter)
    return "## §17 衍生指标(技术 + 估值分位)\n\n" + legacy + valuation
