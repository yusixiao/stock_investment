"""
对照脚本：抽样 N 只 A 股股票，对比新数据管线（data/market/A/）与旧数据管线
（data/kline/A/）的输出是否一致，用于 D8 迁移验证（Phase 4 风险缓解）。

对比两段：
  Section A — Raw 不复权：
    data/market/A/daily/{sym}.parquet  vs  data/kline/A/raw/{sym}.parquet
    比较 schema(columns) / 行数 / close 最大绝对差

  Section B — QFQ 前复权：
    DuckDBStore.query_qfq_kline("A", sym)  vs  qfq_cache.get_qfq_kline(sym)
    比较行数 / 日期对齐 / close 最大绝对差(在交集日期上)

每行评级：
  OK   diff < threshold（默认 1e-4）
  WARN threshold ≤ diff < 1e-2
  FAIL diff ≥ 1e-2，或行数不匹配，或新管线侧无数据
  SKIP 旧路径文件不存在（无对照基准）

用法:
    python scripts/diff_market_vs_kline.py --samples 10
    python scripts/diff_market_vs_kline.py --samples 5 --seed 1 --max-diff 1e-3

退出码:
    0  全部 OK / WARN / SKIP
    1  存在 FAIL
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

# 项目根 + backend/ 都加入 sys.path（与 backend/main.py 保持一致）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BACKEND_DIR = _PROJECT_ROOT / "backend"
for _p in (_PROJECT_ROOT, _BACKEND_DIR):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="抽样对比 data/market 新管线 与 data/kline 旧管线的 raw / qfq 输出",
    )
    p.add_argument("--samples", type=int, default=10, help="抽样股票数（默认 10）")
    p.add_argument("--seed", type=int, default=42, help="随机种子（默认 42，可复现）")
    p.add_argument(
        "--max-diff",
        type=float,
        default=1e-4,
        dest="max_diff",
        help="OK 阈值；超过此值 < 1e-2 标 WARN，≥ 1e-2 标 FAIL（默认 1e-4）",
    )
    return p


# 评级阈值
WARN_LIMIT = 1e-2

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"
SKIP = "SKIP"


def _grade(diff: float, ok_thr: float) -> str:
    if diff < ok_thr:
        return OK
    if diff < WARN_LIMIT:
        return WARN
    return FAIL


def _sample_symbols(daily_dir: Path, n: int, seed: int) -> list[str]:
    files = sorted(p.stem for p in daily_dir.glob("*.parquet"))
    if not files:
        return []
    rng = random.Random(seed)
    n = min(n, len(files))
    return rng.sample(files, n)


def _diff_raw(sym: str, market_dir: Path, kline_raw_dir: Path, ok_thr: float) -> dict:
    """Section A：raw 数据对照。返回行 dict。"""
    import pandas as pd

    new_path = market_dir / f"{sym}.parquet"
    old_path = kline_raw_dir / f"{sym}.parquet"

    if not new_path.exists():
        return {
            "symbol": sym,
            "section": "raw",
            "status": FAIL,
            "detail": "new path missing",
        }
    if not old_path.exists():
        return {
            "symbol": sym,
            "section": "raw",
            "status": SKIP,
            "detail": "old path missing",
        }

    new_df = pd.read_parquet(new_path)
    old_df = pd.read_parquet(old_path)

    new_cols = set(new_df.columns)
    old_cols = set(old_df.columns)
    common_cols = new_cols & old_cols
    schema_diff = new_cols ^ old_cols

    rows_match = len(new_df) == len(old_df)

    # 在公共列里找 close，按 date 对齐做 max abs diff
    if "date" in common_cols and "close" in common_cols:
        a = new_df[["date", "close"]].copy()
        b = old_df[["date", "close"]].copy()
        merged = a.merge(b, on="date", suffixes=("_new", "_old"), how="inner")
        if merged.empty:
            close_diff = float("inf")
        else:
            close_diff = float((merged["close_new"] - merged["close_old"]).abs().max())
    else:
        close_diff = float("inf")

    if not rows_match:
        status = FAIL
    else:
        status = _grade(close_diff, ok_thr)

    detail = f"rows={len(new_df)}/{len(old_df)} close_max_abs={close_diff:.2e}"
    if schema_diff:
        detail += f" schema_diff={sorted(schema_diff)}"
    return {"symbol": sym, "section": "raw", "status": status, "detail": detail}


def _diff_qfq(sym: str, store, get_qfq_kline, ok_thr: float) -> dict:
    """Section B：qfq 数据对照。"""
    import pandas as pd

    try:
        new_df = store.query_qfq_kline("A", sym)
    except Exception as e:
        return {
            "symbol": sym,
            "section": "qfq",
            "status": FAIL,
            "detail": f"new err: {e}",
        }

    try:
        old_df = get_qfq_kline(sym)
    except Exception as e:
        return {
            "symbol": sym,
            "section": "qfq",
            "status": FAIL,
            "detail": f"old err: {e}",
        }

    if old_df is None or old_df.empty:
        # 旧 qfq 缓存依赖 kline/A/raw/，本环境可能整体不存在 — 标 SKIP
        return {
            "symbol": sym,
            "section": "qfq",
            "status": SKIP,
            "detail": f"old qfq empty (raw missing?), new rows={len(new_df)}",
        }
    if new_df is None or new_df.empty:
        return {
            "symbol": sym,
            "section": "qfq",
            "status": FAIL,
            "detail": "new qfq empty",
        }

    rows_match = len(new_df) == len(old_df)

    a = new_df[["date", "close"]].copy()
    b = old_df[["date", "close"]].copy()
    # 两侧 date 类型对齐成字符串
    a["date"] = a["date"].astype(str)
    b["date"] = b["date"].astype(str)
    merged = a.merge(b, on="date", suffixes=("_new", "_old"), how="inner")

    if merged.empty:
        close_diff = float("inf")
    else:
        close_diff = float((merged["close_new"] - merged["close_old"]).abs().max())

    if not rows_match:
        status = FAIL
    else:
        status = _grade(close_diff, ok_thr)

    detail = (
        f"rows={len(new_df)}/{len(old_df)} "
        f"intersect={len(merged)} close_max_abs={close_diff:.2e}"
    )
    return {"symbol": sym, "section": "qfq", "status": status, "detail": detail}


def _print_table(rows: list[dict]):
    headers = ["SYMBOL", "SECTION", "STATUS", "DETAIL"]
    widths = [10, 8, 6, 80]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    line = "-" * (sum(widths) + 2 * (len(widths) - 1))
    print(fmt.format(*headers))
    print(line)
    for r in rows:
        print(
            fmt.format(r["symbol"], r["section"], r["status"], r["detail"][: widths[3]])
        )
    print(line)


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)

    # 延迟导入，让 --help 不被重型依赖拖慢
    from config import DATA_DIR
    from services.duckdb_store import get_store
    from services.qfq_cache import get_qfq_kline

    market_daily = DATA_DIR / "market" / "A" / "daily"
    kline_raw = DATA_DIR / "kline" / "A" / "raw"

    if not market_daily.exists():
        print(f"[ERROR] {market_daily} 不存在；无法采样", file=sys.stderr)
        return 1

    symbols = _sample_symbols(market_daily, args.samples, args.seed)
    if not symbols:
        print("[ERROR] 没有可采样的 parquet", file=sys.stderr)
        return 1

    print(
        f"[INFO] sampling {len(symbols)} symbols (seed={args.seed}, max_diff={args.max_diff})"
    )
    print(f"[INFO] symbols: {symbols}")

    store = get_store()
    rows: list[dict] = []
    for sym in symbols:
        rows.append(_diff_raw(sym, market_daily, kline_raw, args.max_diff))
        rows.append(_diff_qfq(sym, store, get_qfq_kline, args.max_diff))

    _print_table(rows)

    counts = {OK: 0, WARN: 0, FAIL: 0, SKIP: 0}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(
        f"Summary: OK={counts[OK]} WARN={counts[WARN]} "
        f"FAIL={counts[FAIL]} SKIP={counts[SKIP]} (total={len(rows)})"
    )

    return 1 if counts[FAIL] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
