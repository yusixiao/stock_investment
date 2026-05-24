"""§7 控股股东与管理层 — EastMoney F10 三表渲染。

数据来源(2026-05-24 决策):
- 十大股东 ← RPT_F10_EH_HOLDERS
- 十大流通股东 ← RPT_F10_EH_FREEHOLDERS
- 股东户数 ← RPT_HOLDERNUMLATEST(自带 PRE_END_DATE 上期对比)

未接入(后续单独迭代):
- 股权质押 — F10 接口 reportName 无命中,需另寻数据源
- 高管变动 — 同上
"""

from __future__ import annotations

from services.agent.agents.cpa.pipeline.phase1_data_pack.sections._table import (
    fmt_num,
    md_table,
)


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
    header = ["排名", "股东名称", f"持股比例(%)", "持股数(股)", "较上期变动"]
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


def build(ref, *, store, stock_index=None, indicators=None, **_) -> str:
    top10 = _safe_query(store, "query_top10_holders", ref.code, latest_n_periods=2)
    top10_free = _safe_query(
        store, "query_top10_free_holders", ref.code, latest_n_periods=2
    )
    holder_count = _safe_query(store, "query_holder_count", ref.code)

    parts = ["## §7 控股股东与管理层", ""]
    parts.append(_render_top10(top10, "十大股东", ratio_key="HOLD_NUM_RATIO"))
    parts.append(
        _render_top10(top10_free, "十大流通股东", ratio_key="FREE_HOLDNUM_RATIO")
    )
    parts.append(_render_holder_count(holder_count))
    parts.append(
        "### 股权质押 / 高管变动\n\n"
        "> 数据待补 — EastMoney F10 暂无可用 reportName,后续单独接入数据源迭代。\n"
    )
    return "\n".join(parts)
