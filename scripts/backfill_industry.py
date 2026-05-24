"""一次性回填 A 股 stock_list.parquet 的 industry 字段。

baostock query_stock_basic 不返回 industry,历史采集留空。本脚本调
query_stock_industry 拉取证监会行业分类后,merge 进 stock_list.parquet。

用法(后台执行):
    nohup python scripts/backfill_industry.py > /tmp/backfill_industry.log 2>&1 &
    tail -f /tmp/backfill_industry.log
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))


def main() -> int:
    from adapters.baostock_adapter import BaoStockAdapter
    from repositories.basic_repo import BasicRepository

    print("[1/3] 用 BaoStockAdapter 拉新版 stock_list(自动 merge industry)...")
    adapter = BaoStockAdapter()
    records = adapter.fetch_stock_list()
    if not records:
        print("FAIL: baostock 返回空,退出")
        return 1

    total = len(records)
    with_ind = sum(1 for r in records if r.industry)
    print(
        f"  total={total}, industry not null={with_ind} ({with_ind / total * 100:.1f}%)"
    )

    print("[2/3] 写入 data/basic/A/stock_list.parquet ...")
    basic_dir = ROOT / "data" / "basic" / "A"
    repo = BasicRepository(basic_dir)
    repo.write_stock_list(records)

    print("[3/3] 校验...")
    import pandas as pd

    df = pd.read_parquet(basic_dir / "stock_list.parquet")
    print(f"  rows={len(df)}, industry not null={df['industry'].notna().sum()}")
    print("  样本:")
    print(
        df[df["industry"].notna()][["code", "name", "industry"]]
        .head(5)
        .to_string(index=False)
    )
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
