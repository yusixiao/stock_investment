"""
清理 2026-05-21 上午误写入的盘中 partial bar。

港股 09:30 开盘后启动了增量更新,2018 个 HK + 235 个 US 文件被写入了
非收盘的 partial bar。本脚本删除这些文件中 date == TARGET_DATE 的行。

US 文件是真正的 today=05-21 之前的数据(美股 21:30 EDT 才开盘,北京 09:30+)
但保险起见也清理一下。

用法: python scripts/clean_partial_bars.py [DATE]
默认 DATE=2026-05-21
"""

import sys
from pathlib import Path
from datetime import datetime

import pandas as pd

ROOT = Path(__file__).parent.parent
TARGET_DATE = sys.argv[1] if len(sys.argv) > 1 else "2026-05-21"
SINCE = datetime.strptime("2026-05-21 09:26", "%Y-%m-%d %H:%M")


def clean_market(market: str):
    daily_dir = ROOT / "data" / "market" / market / "daily"
    if not daily_dir.exists():
        return
    files = [
        p
        for p in daily_dir.glob("*.parquet")
        if datetime.fromtimestamp(p.stat().st_mtime) >= SINCE
    ]
    print(f"[{market}] {len(files)} files modified since {SINCE}")
    cleaned = 0
    untouched = 0
    for p in files:
        df = pd.read_parquet(p)
        if "date" not in df.columns:
            continue
        mask = df["date"] == TARGET_DATE
        if not mask.any():
            untouched += 1
            continue
        df = df[~mask].reset_index(drop=True)
        df.to_parquet(p, index=False)
        cleaned += 1
    print(f"[{market}] cleaned={cleaned}, untouched={untouched}")


for m in ("HK", "US"):
    clean_market(m)
