"""一次性抓取 510310 沪深300ETF易方达 全历史 K 线(2013-03-25 至今)。

数据源:EastMoney push2his.eastmoney.com/api/qt/stock/kline/get
- BaoStock 不支持 ETF / LOF / 基金,实测覆盖 0
- EastMoney 通用 K 线接口对 ETF / LOF / 指数 / 可转债通通可用

落盘:data/market/ETF/daily/510310.SH.parquet
Schema(13 列):
  date(str, 日期降序)/ code
  open / high / low / close / volume / amount      ← 不复权(fqt=0)
  open_qfq / high_qfq / low_qfq / close_qfq        ← 前复权(fqt=1)
  pctChg                                           ← 由 close 算

跑法:
  python scripts/fetch_etf_510310.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "market" / "ETF" / "daily"
OUT_FILE = OUT_DIR / "510310.SH.parquet"

URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
SECID = "1.510310"  # 1=SH, 0=SZ
START = "20130101"
END = "20991231"


def fetch(fqt: int) -> pd.DataFrame:
    """抓 fqt 复权模式的 K 线。fqt: 0=不复权,1=前复权,2=后复权。"""
    params = {
        "secid": SECID,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "klt": 101,  # 日 K
        "fqt": fqt,
        "beg": START,
        "end": END,
    }
    r = requests.get(URL, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()["data"]
    name = data["name"]
    klines = data["klines"]
    rows = []
    for line in klines:
        # f51..f58: date,open,close,high,low,volume,amount,amplitude
        parts = line.split(",")
        rows.append(
            {
                "date": parts[0],
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": float(parts[5]),
                "amount": float(parts[6]),
            }
        )
    df = pd.DataFrame(rows)
    print(
        f"  fqt={fqt} name={name} rows={len(df)} range={df['date'].iloc[0]}..{df['date'].iloc[-1]}"
    )
    return df


def main() -> int:
    print(f"=== 抓取 510310 沪深300ETF易方达 全历史 ===")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    raw = fetch(0)  # 不复权
    qfq = fetch(1)  # 前复权

    if len(raw) != len(qfq):
        print(f"!!! raw vs qfq 行数不一致 raw={len(raw)} qfq={len(qfq)},中止")
        return 1

    # 按 date 合并(EastMoney 两份返回顺序应该一致,但显式 merge 更安全)
    qfq_renamed = qfq.rename(
        columns={
            "open": "open_qfq",
            "high": "high_qfq",
            "low": "low_qfq",
            "close": "close_qfq",
        }
    )[["date", "open_qfq", "high_qfq", "low_qfq", "close_qfq"]]

    df = raw.merge(qfq_renamed, on="date", how="inner")
    if len(df) != len(raw):
        print(f"!!! merge 后丢行 raw={len(raw)} merged={len(df)},中止")
        return 1

    # 算 pctChg(基于 raw close)
    df = df.sort_values("date").reset_index(drop=True)
    df["pctChg"] = df["close"].pct_change() * 100
    df["pctChg"] = df["pctChg"].fillna(0.0).round(4)

    # code 列
    df["code"] = "510310.SH"

    # 列序 + 日期降序(对齐项目惯例)
    df = df[
        [
            "date",
            "code",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "open_qfq",
            "high_qfq",
            "low_qfq",
            "close_qfq",
            "pctChg",
        ]
    ]
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


if __name__ == "__main__":
    sys.exit(main())
