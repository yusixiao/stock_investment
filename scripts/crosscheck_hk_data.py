"""HK 数据交叉检查 — 在跑大量回测前一次性验证港股数据层可信度。

动机(2026-06-13):HK 前复权因子幻灵拆股已修复(571 只),但用户希望在投入
大量回测前做一次**全面交叉检查**,避免"跑很多轮后才发现数据有误"。

五个维度(只读,不改任何数据):
  1. 修复后全市场 re-audit  — 还有没有残留 phantom 事件?(应≈0,或仅保守保留的 unverifiable)
  2. factor 跨度分布 + 分类 — span≥10 的票:是合法仙股合股(raw 跳空印证)还是残留损坏?
  3. 数据质量          — 重复日期 / 非单调 / 非正收盘 / 价格断层。
  4. raw↔qfq 背离      — 2025 窗口 qfq/raw 收益比 = factor 端点比;极端值是否有 raw 跳空解释。
  5. 知名大盘股抽查    — 00700/00005/00388/01299 等近端价格与 factor 合理性。

用法:
    python3 scripts/crosscheck_hk_data.py            # 全量,输出报告
    python3 scripts/crosscheck_hk_data.py --limit 50 # 只查前 50 只(快速冒烟)
"""

from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from backend.services.market_data.adjust_factor_audit import audit_factors  # noqa: E402
from backend.services.market_data.duckdb_store import get_store  # noqa: E402

ADJUST_DIR = ROOT / "data" / "market" / "HK" / "adjust_factor"
REPORT_MD = ROOT / "report" / "exported" / "hk_data_crosscheck.md"

# 2025 窗口(检验"修复后 raw 与 qfq 是否仅差合法分红")
WIN_START, WIN_END = "2025-01-01", "2025-12-31"

# 知名大盘股抽查(港股代码 .HK)
SPOT_CHECK = {
    "00700.HK": "腾讯控股",
    "00005.HK": "汇丰控股",
    "00388.HK": "香港交易所",
    "01299.HK": "友邦保险",
    "00939.HK": "建设银行",
    "01211.HK": "比亚迪股份(事故主角)",
    "03993.HK": "洛阳钼业(2025 top winner)",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只查前 N 只(0=全量)")
    args = ap.parse_args()

    store = get_store()
    conn = store._conn

    # ---- bulk-load raw closes(按 symbol 分组),与 cleaner 同款一次性加载 ----
    t0 = time.time()
    raw_df = conn.execute(
        "SELECT _symbol, date, close FROM v_hk_daily_raw ORDER BY _symbol, date"
    ).fetchdf()
    raw_by: dict[str, tuple[list, list]] = {}
    for sym, grp in raw_df.groupby("_symbol", sort=False):
        raw_by[sym] = (grp["date"].tolist(), grp["close"].tolist())
    print(f"[crosscheck] raw loaded: {len(raw_by)} symbols {time.time()-t0:.1f}s", flush=True)

    # ---- bulk-load 当前(已修复)factor ----
    fac_df = conn.execute(
        "SELECT code, dividOperateDate, foreAdjustFactor "
        "FROM v_hk_adjust_factor ORDER BY code, dividOperateDate"
    ).fetchdf()
    fac_by: dict[str, list[tuple[str, float]]] = {}
    for code, grp in fac_df.groupby("code", sort=False):
        fac_by[code] = list(zip(grp["dividOperateDate"].tolist(), grp["foreAdjustFactor"].tolist()))
    print(f"[crosscheck] factor loaded: {len(fac_by)} codes", flush=True)

    codes = sorted(fac_by.keys())
    if args.limit:
        codes = codes[: args.limit]

    n_bak = len(list(ADJUST_DIR.glob("*.parquet.bak")))

    # ---- 维度 1+2:re-audit + 跨度分类 ----
    residual_phantom: list[dict] = []   # 修复后仍判 phantom(本应≈0)
    large_span_legit: list[dict] = []    # span≥10 且全部大事件被 raw 印证
    large_span_unver: list[dict] = []    # span≥10 但含 unverifiable 大事件(灰区)
    span_buckets = {"<3": 0, "3-10": 0, "10-100": 0, "100-1e3": 0, ">=1e3": 0}

    # ---- 维度 3:数据质量 ----
    dq_dup: list[str] = []        # raw 重复日期
    dq_nonmono: list[str] = []    # raw 日期非单调
    dq_badclose: list[str] = []   # 非正/NaN 收盘

    # ---- 维度 4:raw↔qfq 背离(2025) ----
    win_diverge: list[dict] = []

    for code in codes:
        recs = fac_by[code]
        rdates, rcloses = raw_by.get(code, ([], []))

        # span 分桶
        fvals = [f for _, f in recs if f and f > 0]
        if fvals:
            span = max(fvals) / min(fvals)
            if span < 3:
                span_buckets["<3"] += 1
            elif span < 10:
                span_buckets["3-10"] += 1
            elif span < 100:
                span_buckets["10-100"] += 1
            elif span < 1000:
                span_buckets["100-1e3"] += 1
            else:
                span_buckets[">=1e3"] += 1
        else:
            span = 0.0

        # re-audit
        events = audit_factors(recs, list(zip(rdates, rcloses)))
        phantoms = [e for e in events if e.is_phantom]
        big_events = [e for e in events if e.change and abs(math.log(e.change)) > 0.14]
        unver = [e for e in big_events if e.raw_ratio is None and e.reason.startswith("unver")]

        if phantoms:
            residual_phantom.append(
                {"code": code, "span": round(span, 2), "n": len(phantoms),
                 "ev": [(e.date, round(e.change, 4), e.raw_ratio) for e in phantoms]}
            )
        if span >= 10:
            row = {"code": code, "span": round(span, 2),
                   "n_big": len(big_events), "n_unver": len(unver)}
            (large_span_unver if unver else large_span_legit).append(row)

        # 数据质量(raw)
        if rdates:
            if len(rdates) != len(set(rdates)):
                dq_dup.append(code)
            if any(rdates[i] > rdates[i + 1] for i in range(len(rdates) - 1)):
                dq_nonmono.append(code)
            if any((c is None) or (isinstance(c, float) and math.isnan(c)) or c <= 0
                   for c in rcloses):
                dq_badclose.append(code)

        # 维度 4:2025 窗口 qfq/raw 收益比 = factor 端点比(asof)
        # factor at window start/end via 最近 <= date
        def _factor_asof(target: str) -> float | None:
            best = None
            for d, f in recs:
                if d <= target:
                    best = f
                else:
                    break
            return best

        f_start = _factor_asof(WIN_START)
        f_end = _factor_asof(WIN_END)
        if f_start and f_end and f_start > 0:
            ratio = f_end / f_start
            # 合法分红一年最多 ~1.15;>1.3 或 <0.85 需有 raw 跳空解释
            if ratio > 1.3 or ratio < 0.85:
                win_diverge.append({"code": code, "qfq_over_raw": round(ratio, 3),
                                    "span": round(span, 2)})

    # ---- 维度 5:大盘股抽查 ----
    spot_rows = []
    for code, name in SPOT_CHECK.items():
        rdates, rcloses = raw_by.get(code, ([], []))
        recs = fac_by.get(code, [])
        if not rdates:
            spot_rows.append((code, name, "NO RAW DATA", "", "", ""))
            continue
        first_d, first_c = rdates[0], rcloses[0]
        last_d, last_c = rdates[-1], rcloses[-1]
        fvals = [f for _, f in recs if f and f > 0]
        fspan = (max(fvals) / min(fvals)) if fvals else 0.0
        last_f = recs[-1][1] if recs else None
        spot_rows.append((
            code, name,
            f"{first_d}={first_c:.3f}",
            f"{last_d}={last_c:.2f}",
            f"span={fspan:.2f}",
            f"last_f={last_f}",
        ))

    # ---------- 报告 ----------
    L = []
    L.append("# HK 数据交叉检查报告")
    L.append("")
    L.append(f"- 检查标的: {len(codes)} 只 (factor 票 {len(fac_by)} / raw 票 {len(raw_by)})")
    L.append(f"- .bak 备份文件: {n_bak} (= 曾被 cleaner 修复的票数)")
    L.append("")
    L.append("## 1. 修复后 re-audit:残留 phantom 事件")
    if not residual_phantom:
        L.append("✅ **0 残留 phantom** —— 全市场修复后无任何幻灵拆股事件。")
    else:
        L.append(f"⚠️ **{len(residual_phantom)} 只仍含 phantom**(需复查):")
        L.append("")
        L.append("| code | span | phantom数 | 事件(date,change,raw_ratio) |")
        L.append("|---|---|---|---|")
        for r in residual_phantom[:50]:
            ev = "; ".join(f"{d} c={c} raw={rr}" for d, c, rr in r["ev"])
            L.append(f"| {r['code']} | {r['span']} | {r['n']} | {ev} |")
    L.append("")
    L.append("## 2. factor 跨度分布(修复后)")
    L.append("")
    L.append("| 跨度桶 | 票数 |")
    L.append("|---|---|")
    for k, v in span_buckets.items():
        L.append(f"| {k} | {v} |")
    L.append("")
    L.append(f"- span≥10 且大事件**全被 raw 跳空印证**(合法仙股合股): **{len(large_span_legit)}**")
    L.append(f"- span≥10 但含 **unverifiable 大事件**(灰区,raw 无早期价无法校验): **{len(large_span_unver)}**")
    if large_span_unver:
        L.append("")
        L.append("| code | span | 大事件 | 不可校验 |")
        L.append("|---|---|---|---|")
        for r in sorted(large_span_unver, key=lambda x: -x["span"])[:30]:
            L.append(f"| {r['code']} | {r['span']} | {r['n_big']} | {r['n_unver']} |")
    L.append("")
    L.append("## 3. 数据质量(raw 日线)")
    L.append(f"- 重复日期: **{len(dq_dup)}** {dq_dup[:10]}")
    L.append(f"- 日期非单调: **{len(dq_nonmono)}** {dq_nonmono[:10]}")
    L.append(f"- 非正/NaN 收盘: **{len(dq_badclose)}** {dq_badclose[:10]}")
    L.append("")
    L.append("## 4. raw↔qfq 2025 背离(qfq/raw 收益比 = factor 端点比)")
    L.append("正常分红一年 ratio≈1.0~1.15;偏离需有 raw 跳空(真实合股/拆股)解释。")
    L.append(f"- 偏离 (ratio>1.3 或 <0.85) 的票: **{len(win_diverge)}**")
    if win_diverge:
        L.append("")
        L.append("| code | qfq/raw | span |")
        L.append("|---|---|---|")
        for r in sorted(win_diverge, key=lambda x: -abs(math.log(x["qfq_over_raw"])))[:30]:
            L.append(f"| {r['code']} | {r['qfq_over_raw']} | {r['span']} |")
    L.append("")
    L.append("## 5. 知名大盘股抽查")
    L.append("")
    L.append("| code | 名称 | 最早 raw | 最新 raw | factor跨度 | 末因子 |")
    L.append("|---|---|---|---|---|---|")
    for row in spot_rows:
        L.append("| " + " | ".join(str(x) for x in row) + " |")

    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text("\n".join(L))

    # ---- 控制台摘要 ----
    print("\n========== 交叉检查摘要 ==========")
    print(f"标的: {len(codes)} | .bak: {n_bak}")
    print(f"[1] 残留 phantom: {len(residual_phantom)}  {'✅' if not residual_phantom else '⚠️ 需复查'}")
    print(f"[2] span 分布: {span_buckets}")
    print(f"    span≥10 合法={len(large_span_legit)} 灰区(unver)={len(large_span_unver)}")
    print(f"[3] 数据质量: dup={len(dq_dup)} nonmono={len(dq_nonmono)} badclose={len(dq_badclose)}")
    print(f"[4] 2025 背离: {len(win_diverge)}")
    print(f"[5] 抽查 {len(spot_rows)} 只大盘股(详见报告)")
    print(f"\n报告: {REPORT_MD}")


if __name__ == "__main__":
    main()
