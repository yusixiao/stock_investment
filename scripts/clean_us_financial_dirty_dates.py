"""清理 US 财务 4 表中 REPORT_DATE > 今天的脏数据(2026-05-27)。

背景:yfinance 早期写入产生了 2027-2039 的未来日期(EVOH 2039-08-31、
PMT 系列 7 只 2027/2028/2029-12-31),共 23 行,污染 v_us_income/balance/indicator。

策略:
- 遍历 data/market/US/financial/{income,balance,cashflow,indicator}/*.parquet
- 过滤 REPORT_DATE > 今天的行,重写 parquet
- 保持 schema 与排序(REPORT_DATE 降序)
- 幂等:无脏行时不重写
- --dry-run:只打印不写

用法:
    python scripts/clean_us_financial_dirty_dates.py --dry-run
    python scripts/clean_us_financial_dirty_dates.py
"""

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

US_FINANCIAL_DIR = (
    Path(__file__).resolve().parent.parent / "data" / "market" / "US" / "financial"
)
TABLES = ("income", "balance", "cashflow", "indicator")


def clean_table(table_dir: Path, cutoff: str, dry_run: bool) -> dict:
    """清理一类表(income/balance/cashflow/indicator)。返回统计。"""
    files = list(table_dir.glob("*.parquet"))
    affected = 0
    rows_removed = 0
    affected_files = []

    for f in files:
        df = pd.read_parquet(f)
        if "REPORT_DATE" not in df.columns:
            continue
        bad_mask = df["REPORT_DATE"].astype(str) > cutoff
        bad_n = int(bad_mask.sum())
        if bad_n == 0:
            continue
        affected += 1
        rows_removed += bad_n
        affected_files.append((f.stem, bad_n))
        if not dry_run:
            cleaned = df[~bad_mask].sort_values("REPORT_DATE", ascending=False)
            cleaned.to_parquet(f, index=False)

    return {
        "table": table_dir.name,
        "total_files": len(files),
        "affected_files": affected,
        "rows_removed": rows_removed,
        "details": affected_files,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只打印不写")
    parser.add_argument(
        "--cutoff",
        default=date.today().strftime("%Y-%m-%d"),
        help="REPORT_DATE > cutoff 视为脏(默认今天)",
    )
    args = parser.parse_args()

    print(f"[clean_us_financial] cutoff={args.cutoff} dry_run={args.dry_run}")
    print(f"[clean_us_financial] base dir: {US_FINANCIAL_DIR}")

    total_rows = 0
    for table in TABLES:
        table_dir = US_FINANCIAL_DIR / table
        if not table_dir.exists():
            print(f"  {table}: 目录不存在,跳过")
            continue
        stat = clean_table(table_dir, args.cutoff, args.dry_run)
        total_rows += stat["rows_removed"]
        print(
            f"  {stat['table']}: 文件 {stat['total_files']}, 受影响 "
            f"{stat['affected_files']}, 移除 {stat['rows_removed']} 行"
        )
        for sym, n in stat["details"]:
            print(f"    - {sym}: -{n} 行")

    print(
        f"[clean_us_financial] 完成,共移除 {total_rows} 行"
        + (" (dry-run)" if args.dry_run else "")
    )


if __name__ == "__main__":
    main()
