"""§17 衍生指标(技术 + 估值分位)。"""

from __future__ import annotations


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


def build(ref, *, store, stock_index, indicators) -> str:
    snap: dict = {}
    try:
        getter = getattr(indicators, "get_indicator_snapshot", None)
        if callable(getter):
            snap = getter(ref.code) or {}
    except Exception:  # noqa: BLE001
        snap = {}
    return (
        "## §17 衍生指标(技术 + 估值分位)\n\n"
        f"- MA5/MA10/MA20/MA60:{_f(snap, 'MA5')} / {_f(snap, 'MA10')} / "
        f"{_f(snap, 'MA20')} / {_f(snap, 'MA60')}\n"
        f"- MACD(DIF/DEA/BAR):{_f(snap, 'MACD_DIF')} / "
        f"{_f(snap, 'MACD_DEA')} / {_f(snap, 'MACD_BAR')}\n"
        f"- PE 历史分位(5 年):{_pct(snap, 'PE_PCT_5Y')}\n"
        f"- PB 历史分位(5 年):{_pct(snap, 'PB_PCT_5Y')}\n"
    )
