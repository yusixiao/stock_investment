"""§7 控股股东与管理层 — EastMoney F10 三表 + 高管增减持渲染。

数据来源(2026-05-24 / 2026-05-26 决策):
- 十大股东 ← RPT_F10_EH_HOLDERS (DuckDB)
- 十大流通股东 ← RPT_F10_EH_FREEHOLDERS (DuckDB)
- 股东户数 ← RPT_HOLDERNUMLATEST (DuckDB,自带 PRE_END_DATE)
- 高管增减持 ← emweb F10 CompanyManagement/PageAjax 的 cgbd 字段 (实时 HTTP,A 股专用)

未接入(后续单独迭代):
- 股权质押 — F10 接口 reportName 无命中,emweb PageAjax 全 302,需另寻数据源
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from services.agent.agents.cpa.pipeline.phase1_data_pack.sections._table import (
    fmt_num,
    md_table,
)

logger = logging.getLogger(__name__)

HOLD_CHANGE_WINDOW_DAYS = 365  # 近 12 月


def _safe_query(store, method_name: str, *args, **kwargs):
    fn = getattr(store, method_name, None)
    if fn is None:
        return []
    try:
        return fn(*args, **kwargs) or []
    except Exception:  # noqa: BLE001
        return []


def _fmt_int(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{int(float(v)):,}"
    except (TypeError, ValueError):
        return "—"


def _render_top10(rows: list[dict], title: str, ratio_key: str) -> str:
    """十大股东 / 十大流通股东 共用渲染。

    rows 已按 END_DATE desc 排好,取最近一期。ratio_key 区分总股本占比 vs 流通占比。
    """
    if not rows:
        return f"### {title}\n\n数据缺失\n"
    latest_date = rows[0].get("END_DATE") or "—"
    latest = [r for r in rows if r.get("END_DATE") == latest_date]
    latest = sorted(latest, key=lambda r: r.get("HOLDER_RANK") or 99)[:10]
    header = ["排名", "股东名称", "持股比例(%)", "持股数(股)", "较上期变动"]
    body = []
    for r in latest:
        rank = r.get("HOLDER_RANK") or "—"
        name = r.get("HOLDER_NAME") or "—"
        ratio = fmt_num(r.get(ratio_key), 2)
        num = _fmt_int(r.get("HOLD_NUM"))
        change = (
            r.get("HOLDER_STATEE") or r.get("HOLDER_STATE") or r.get("HOLD_NUM_CHANGE")
        )
        body.append([str(rank), str(name), ratio, num, str(change or "—")])
    return (
        f"### {title}(报告期 {str(latest_date)[:10]})\n\n"
        + md_table(header, body)
        + "\n"
    )


def _render_holder_count(rows: list[dict]) -> str:
    if not rows:
        return "### 股东户数\n\n数据缺失\n"
    latest = rows[0]
    end_date = str(latest.get("END_DATE") or "—")[:10]
    pre_date = str(latest.get("PRE_END_DATE") or "—")[:10]
    cur = _fmt_int(latest.get("HOLDER_NUM"))
    pre = _fmt_int(latest.get("PRE_HOLDER_NUM"))
    chg = fmt_num(latest.get("HOLDER_NUM_RATIO"), 2)
    avg_hold = fmt_num(latest.get("AVG_HOLD_NUM"), 0)
    avg_mcap = fmt_num(latest.get("AVG_MARKET_CAP"), 0)
    return (
        "### 股东户数\n\n"
        + md_table(
            ["指标", "数值"],
            [
                [f"当期 ({end_date})", cur],
                [f"上期 ({pre_date})", pre],
                ["较上期变动 (%)", chg],
                ["户均持股数(股)", avg_hold],
                ["户均持股市值(元)", avg_mcap],
            ],
        )
        + "\n"
    )


def _is_a_share(code: str) -> bool:
    upper = (code or "").upper()
    return upper.endswith((".SH", ".SZ", ".BJ"))


def _within_window(end_date: str, today: date | None = None) -> bool:
    try:
        d = datetime.strptime(end_date[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return False
    cutoff = (today or date.today()) - timedelta(days=HOLD_CHANGE_WINDOW_DAYS)
    return d >= cutoff


def _fetch_hold_changes(code: str, em_adapter) -> list:
    """获取近 12 月高管增减持记录。失败 / 非 A 股 → []。"""
    if not _is_a_share(code):
        return []
    adapter = em_adapter
    if adapter is None:
        try:
            from adapters.eastmoney_adapter import EastMoneyAdapter

            adapter = EastMoneyAdapter()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"§7 EastMoneyAdapter 初始化失败 {code}: {exc}")
            return []
    try:
        _execs, changes = adapter.fetch_company_management(code)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"§7 高管增减持获取失败 {code}: {exc}")
        return []
    return [c for c in (changes or []) if _within_window(c.end_date)]


def _render_hold_changes(changes: list) -> str:
    """近 12 月高管增减持表格渲染。"""
    if not changes:
        return "### 高管增减持(近 12 月)\n\n近 12 月无高管增减持记录。\n"
    rows = sorted(changes, key=lambda c: c.end_date, reverse=True)
    header = [
        "日期",
        "高管",
        "职务",
        "关系",
        "变动股数",
        "均价(元)",
        "变动后持股",
        "方式",
    ]
    body = []
    for c in rows:
        sign = "+" if c.change_num > 0 else ""
        body.append(
            [
                c.end_date,
                c.executive_name,
                c.position or "—",
                c.executive_relation or "—",
                f"{sign}{c.change_num:,.0f}",
                fmt_num(c.average_price, 2),
                _fmt_int(c.change_after_holdnum),
                c.trade_way or "—",
            ]
        )
    return "### 高管增减持(近 12 月)\n\n" + md_table(header, body) + "\n"


def build(
    ref, *, store, stock_index=None, indicators=None, em_adapter=None, **_
) -> str:
    top10 = _safe_query(store, "query_top10_holders", ref.code, latest_n_periods=2)
    top10_free = _safe_query(
        store, "query_top10_free_holders", ref.code, latest_n_periods=2
    )
    holder_count = _safe_query(store, "query_holder_count", ref.code)
    hold_changes = _fetch_hold_changes(ref.code, em_adapter)

    parts = ["## §7 控股股东与管理层", ""]
    parts.append(_render_top10(top10, "十大股东", ratio_key="HOLD_NUM_RATIO"))
    parts.append(
        _render_top10(top10_free, "十大流通股东", ratio_key="FREE_HOLDNUM_RATIO")
    )
    parts.append(_render_holder_count(holder_count))
    parts.append(_render_hold_changes(hold_changes))
    parts.append(
        "### 股权质押\n\n"
        "> 数据待补 — EastMoney F10 接口 reportName 全无命中,emweb PageAjax 返 302,"
        "需独立 spike(`data.eastmoney.com/gpzy/` XHR)单独接入。\n"
    )
    return "\n".join(parts)
