"""验证 HK 复权因子修复结果。

检查项:
1. 重复组:全市场 (file/symbol, dividOperateDate) 是否仍有重复行 → 期望 0。
2. 单调性:每只标的因子序列按日期升序后,是否单调不减到最新日(分红+正向
   拆股场景成立;含反向拆股/合股的标的会出现 >1 的更早因子,单独列出不算违规)。
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
AF_DIR = ROOT / "data" / "market" / "HK" / "adjust_factor"


def main() -> None:
    files = sorted(AF_DIR.glob("*.parquet"))
    print(f"[verify] {len(files)} HK adjust_factor parquet files", flush=True)

    con = duckdb.connect()

    # 1. 重复组检查:每个文件内同一 dividOperateDate 是否出现多行
    dup_total = 0
    dup_files: list[str] = []
    # 单调性检查
    non_monotonic: list[str] = []
    has_gt1: list[str] = []
    null_files: list[str] = []

    for f in files:
        rows = con.execute(
            "SELECT dividOperateDate, foreAdjustFactor "
            "FROM read_parquet(?) ORDER BY dividOperateDate",
            [str(f)],
        ).fetchall()
        if not rows:
            continue

        dates = [r[0] for r in rows]
        if len(dates) != len(set(dates)):
            dup_files.append(f.stem)
            dup_total += len(dates) - len(set(dates))

        factors = [r[1] for r in rows]
        if any(x is None for x in factors):
            null_files.append(f.stem)
            factors = [x for x in factors if x is not None]
        if not factors:
            continue
        # 单调不减(升序日期)
        if any(factors[i] > factors[i + 1] + 1e-9 for i in range(len(factors) - 1)):
            non_monotonic.append(f.stem)
        if any(x > 1.0 + 1e-9 for x in factors):
            has_gt1.append(f.stem)

    print(f"[verify] 重复组文件数 = {len(dup_files)} (多余行 {dup_total})", flush=True)
    if dup_files:
        print(f"[verify]   样例: {dup_files[:10]}", flush=True)

    print(f"[verify] 含 NULL 因子文件数 = {len(null_files)}", flush=True)
    if null_files:
        print(f"[verify]   样例: {null_files[:10]}", flush=True)

    print(f"[verify] 非单调文件数 = {len(non_monotonic)}", flush=True)
    if non_monotonic:
        print(f"[verify]   样例: {non_monotonic[:20]}", flush=True)

    print(
        f"[verify] 含因子>1(反向拆股/合股)标的数 = {len(has_gt1)} "
        f"(预期非空,属正常,需与非单调集合交叉确认)",
        flush=True,
    )
    if has_gt1:
        print(f"[verify]   样例: {has_gt1[:10]}", flush=True)

    ok = dup_total == 0
    print(f"\n[verify] RESULT: 重复组={'PASS' if ok else 'FAIL'}", flush=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
