"""一次性抓取沪深300 指数(000300.SH)全历史 K 线。

数据源:BaoStock(指数原生支持)
- code 映射:000300.SH → sh.000300

落盘:data/market/INDEX/daily/000300.SH.parquet
Schema(10 列):
  date(str, 日期降序)/ code
  open / high / low / close / preclose / volume / amount / pctChg

注:指数无复权概念,只有一份 OHLC。后续若需扩展上证指数/中证500/创业板指/
   科创50,直接复用本脚本结构(只改 BAOSTOCK_CODE / OUT_FILE 即可)。

跑法:
  python scripts/fetch_index_000300.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import baostock as bs
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "market" / "INDEX" / "daily"
OUT_FILE = OUT_DIR / "000300.SH.parquet"

BAOSTOCK_CODE = "sh.000300"
OUTPUT_CODE = "000300.SH"
START = "1991-01-01"
END = "2030-12-31"
FIELDS = "date,code,open,high,low,close,preclose,volume,amount,pctChg"


def main() -> int:
    print("=== 抓取 000300.SH 沪深300 指数全历史 ===")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    lg = bs.login()
    if lg.error_code != "0":
        print(f"!!! BaoStock login 失败: {lg.error_msg}")
        return 1

    try:
        rs = bs.query_history_k_data_plus(
            BAOSTOCK_CODE,
            FIELDS,
            start_date=START,
            end_date=END,
            frequency="d",
        )
        if rs.error_code != "0":
            print(f"!!! query 失败: {rs.error_msg}")
            return 1

        rows = []
        while rs.next():
            rows.append(rs.get_row_data())

        if not rows:
            print("!!! 0 行返回,中止")
            return 1

        df = pd.DataFrame(rows, columns=FIELDS.split(","))

        # 数值列转 float
        for col in [
            "open",
            "high",
            "low",
            "close",
            "preclose",
            "volume",
            "amount",
            "pctChg",
        ]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # code 列改成项目惯例的 .SH 后缀
        df["code"] = OUTPUT_CODE

        # 日期降序(对齐项目其他 daily parquet 的惯例)
        df = df.sort_values("date", ascending=False).reset_index(drop=True)

        df.to_parquet(OUT_FILE, index=False)

        print(f"\n=== 落盘 {OUT_FILE} ===")
        print(f"  shape={df.shape}")
        print(f"  range={df['date'].iloc[-1]} → {df['date'].iloc[0]}")
        print(f"  size={OUT_FILE.stat().st_size:,} bytes")
        print("\n首 3 行(最新):")
        print(df.head(3).to_string(index=False))
        print("\n末 3 行(最早):")
        print(df.tail(3).to_string(index=False))
        return 0
    finally:
        bs.logout()


if __name__ == "__main__":
    sys.exit(main())
