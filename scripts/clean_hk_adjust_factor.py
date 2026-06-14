"""HK 前复权因子幻灵拆股清理器。

事故背景见 backend/services/adjust_factor_audit.py。yfinance `t.splits` 返回
真实股价中不存在的拆股事件,污染 foreAdjustFactor(01211.HK 比亚迪 2025 假涨
+1910%),进而污染所有 HK qfq 回测的绝对收益。

本脚本用 audit 模块(factor_change vs raw 价跳空比)扫描全部 HK 复权因子 parquet,
剔除幻灵事件并重算累积因子。

用法:
    # 干跑:只扫描出清单,不改任何文件(默认)
    python3 scripts/clean_hk_adjust_factor.py
    # 落盘:备份原文件到 *.parquet.bak 后写回修复结果
    python3 scripts/clean_hk_adjust_factor.py --apply

长任务建议后台执行:
    python3 scripts/bg_launch.py logs/clean_hk_af.log \
        python3 scripts/clean_hk_adjust_factor.py --apply
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from backend.services.market_data.adjust_factor_audit import (  # noqa: E402
    audit_factors,
    recompute_factors,
)
from backend.services.market_data.duckdb_store import get_store  # noqa: E402
from backend.services.market_data.updaters.market_updater import _get_repo  # noqa: E402

def _adjust_dir(market: str) -> Path:
    return ROOT / "data" / "market" / market / "adjust_factor"


def _list_codes(market: str) -> list[str]:
    d = _adjust_dir(market)
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.parquet"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--market",
        default="HK",
        choices=["HK", "US"],
        help="目标市场(yfinance 源,A 股走 baostock 不受此事故影响)",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="实际写回修复结果(默认仅干跑出报告)",
    )
    args = ap.parse_args()
    market = args.market

    # 🚨 安全锁:US 的 v_us_daily_raw 价格本身已做过拆股复权(AAPL 1980 收盘 $0.13 vs 真实 ~$22),
    # 与本检测器的核心假设(真实拆股 raw 会跳空)相反,会把 AAPL/NVDA 等真实拆股全误判为幻灵。
    # 对 US --apply 会摧毁所有真实拆股,故彻底禁止。US 是独立 issue(见 TODOS.md),只允许 dry-run。
    if market == "US" and args.apply:
        ap.error(
            "禁止对 US --apply:美股 raw 已是拆股复权价,本工具会误删真实拆股。"
            "US 是独立 issue(见 TODOS.md),仅允许 dry-run。"
        )

    raw_view = f"v_{market.lower()}_daily_raw"
    report_md = ROOT / "report" / "exported" / f"{market.lower()}_factor_corruption.md"
    report_json = ROOT / "report" / "exported" / f"{market.lower()}_factor_corruption.json"

    store = get_store()
    repo = _get_repo(market)
    codes = _list_codes(market)
    total = len(codes)
    print(
        f"[clean_af:{market}] {'APPLY' if args.apply else 'DRY-RUN'}: {total} codes",
        flush=True,
    )

    # 一次性 bulk-load 全市场 raw 收盘价(按 symbol 分组),避免 per-stock 全 glob 扫描(O(N^2))。
    t_load = time.time()
    raw_df_all = store._conn.execute(
        f"SELECT _symbol, date, close FROM {raw_view} ORDER BY _symbol, date"
    ).fetchdf()
    raw_by_symbol: dict[str, list[tuple[str, float]]] = {}
    for sym, grp in raw_df_all.groupby("_symbol", sort=False):
        raw_by_symbol[sym] = list(zip(grp["date"].tolist(), grp["close"].tolist()))
    print(
        f"[clean_af:{market}] loaded raw closes for {len(raw_by_symbol)} symbols "
        f"in {time.time() - t_load:.1f}s",
        flush=True,
    )

    corrupt: list[dict] = []
    scanned = 0
    fixed = 0
    failed = 0
    t0 = time.time()

    for i, code in enumerate(codes, 1):
        try:
            records = repo.read_adjust_factor(code)  # 升序
            if not records:
                continue
            recs = [(r.dividOperateDate, r.foreAdjustFactor) for r in records]
            raw = raw_by_symbol.get(code, [])
            events = audit_factors(recs, raw)
            scanned += 1
            phantoms = [e for e in events if e.is_phantom]
            if not phantoms:
                continue

            old_f = [f for _, f in recs]
            old_span = max(old_f) / min(old_f) if min(old_f) > 0 else float("inf")
            fixed_recs = recompute_factors(events)
            new_f = [f for _, f in fixed_recs]
            new_span = max(new_f) / min(new_f) if min(new_f) > 0 else float("inf")

            corrupt.append(
                {
                    "code": code,
                    "n_events": len(events),
                    "n_phantom": len(phantoms),
                    "old_factor_span": round(old_span, 2),
                    "new_factor_span": round(new_span, 2),
                    "phantom_events": [
                        {
                            "date": e.date,
                            "change": round(e.change, 4),
                            "raw_ratio": round(e.raw_ratio, 4) if e.raw_ratio else None,
                            "reason": e.reason,
                        }
                        for e in phantoms
                    ],
                }
            )

            if args.apply:
                from backend.models.market import AdjustFactorRecord

                bak = repo._adjust_path(code).with_suffix(".parquet.bak")
                if not bak.exists():
                    shutil.copy2(repo._adjust_path(code), bak)
                new_records = [
                    AdjustFactorRecord(
                        code=code, dividOperateDate=d, foreAdjustFactor=f
                    )
                    for d, f in fixed_recs
                ]
                repo.write_adjust_factor(code, new_records)
                fixed += 1
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"[clean_af:{market}] FAIL {code}: {e}", flush=True)

        if i % 200 == 0 or i == total:
            print(
                f"[clean_af:{market}] {i}/{total} scanned={scanned} "
                f"corrupt={len(corrupt)} fixed={fixed} failed={failed} "
                f"elapsed={time.time() - t0:.0f}s",
                flush=True,
            )

    # 按幻灵事件数 + 旧跨度排序输出
    corrupt.sort(key=lambda c: (c["n_phantom"], c["old_factor_span"]), reverse=True)

    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(corrupt, ensure_ascii=False, indent=2))

    lines = [
        f"# {market} 前复权因子幻灵拆股扫描报告",
        "",
        f"- 模式: {'APPLY(已写回)' if args.apply else 'DRY-RUN(未改文件)'}",
        f"- 扫描标的: {scanned}/{total}",
        f"- 损坏标的: {len(corrupt)}",
        f"- 已修复: {fixed}",
        f"- 失败: {failed}",
        "",
        "## 损坏标的明细(按幻灵事件数排序)",
        "",
        "| code | 事件数 | 幻灵数 | 旧跨度 | 新跨度 | 幻灵事件 |",
        "|---|---|---|---|---|---|",
    ]
    for c in corrupt:
        ev = "; ".join(
            f"{p['date']} change={p['change']} raw={p['raw_ratio']}"
            for p in c["phantom_events"]
        )
        lines.append(
            f"| {c['code']} | {c['n_events']} | {c['n_phantom']} | "
            f"{c['old_factor_span']} | {c['new_factor_span']} | {ev} |"
        )
    report_md.write_text("\n".join(lines))

    print(
        f"[clean_af:{market}] DONE scanned={scanned} corrupt={len(corrupt)} "
        f"fixed={fixed} failed={failed} elapsed={time.time() - t0:.0f}s",
        flush=True,
    )
    print(f"[clean_af:{market}] report: {report_md}", flush=True)


if __name__ == "__main__":
    main()
