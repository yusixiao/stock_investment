"""将研究侧Eastmoney HK数据导入平台data/market/HK/格式

研究数据：~/workspace/港股回测/data/raw/all_20150101-20260930_v1.parquet
  - 列：date, ticker, open, high, low, close_raw, close_adj, volume, dividends, splits
  - close_raw：拆股已调整到2026（出厂）
  - dividends：分红金额

目标格式：
  - data/market/HK/daily/{code}.parquet：DailyKlineRecord列表
    - code格式：00700.HK（5位+后缀）
    - close = close_raw（拆股已调，分红未调）
    - amount = close * volume（估算）
  - data/market/HK/adjust_factor/{code}.parquet：AdjustFactorRecord列表
    - div_factor = ∏(1 - D/P)，锚定最新=1.0
    - 只含分红事件（拆股已在close_raw中）

用法：
    python scripts/import_hk_eastmoney.py [--limit N] [--codes 00700,00005]
"""
import argparse
import sys
from pathlib import Path

# 平台根目录
PLATFORM_ROOT = Path("/home/hatch/workspace/stock_investment")
sys.path.insert(0, str(PLATFORM_ROOT))
sys.path.insert(0, str(PLATFORM_ROOT / "backend"))

import pandas as pd
import numpy as np
from datetime import datetime

# 研究数据路径
RESEARCH_PARQUET = Path("/home/hatch/workspace/港股回测/data/raw/all_20150101-20260930_v1.parquet")


def ticker_to_code(ticker: str) -> str:
    """00700 -> 00700.HK"""
    return f"{ticker}.HK"


def build_div_factor(dividends: pd.DataFrame, close_map: dict) -> list:
    """构建分红调整因子
    
    Args:
        dividends: DataFrame[date, dividends]，按日期升序
        close_map: {date_str: close_raw}，用于计算D/P的分母
    
    Returns:
        [(date_str, factor)]，按日期升序，锚定最新=1.0
    """
    if len(dividends) == 0:
        return []
    
    # 按日期倒序累乘
    events = []  # [(date_str, factor_change)]
    for _, row in dividends.iterrows():
        date_str = row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else str(row["date"])[:10]
        amount = float(row["dividends"])
        if amount <= 0:
            continue
        
        # 找除权日前一个交易日的收盘价
        prev_dates = [d for d in close_map.keys() if d < date_str]
        if not prev_dates:
            continue
        prev_date = max(prev_dates)
        prev_close = close_map[prev_date]
        if prev_close <= 0:
            continue
        
        factor_change = (prev_close - amount) / prev_close
        if factor_change <= 0 or factor_change > 1:
            continue
        events.append((date_str, factor_change))
    
    if not events:
        return []
    
    # 同日合并
    merged = {}
    for d, c in events:
        merged[d] = merged.get(d, 1.0) * c
    events = sorted(merged.items())
    
    # 从后往前累乘，锚定最新=1.0
    n = len(events)
    factors = [0.0] * n
    factors[n-1] = 1.0
    for i in range(n-2, -1, -1):
        factors[i] = factors[i+1] * events[i+1][1]
    
    return [(d, round(f, 6)) for (d, _), f in zip(events, factors)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="只处理前N只（测试用）")
    parser.add_argument("--codes", type=str, default="", help="指定代码，逗号分隔")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写入")
    args = parser.parse_args()
    
    print("加载研究数据...", flush=True)
    df = pd.read_parquet(RESEARCH_PARQUET)
    df["date"] = pd.to_datetime(df["date"])
    print(f"共 {len(df):,} 条，{df['ticker'].nunique()} 只", flush=True)
    
    tickers = sorted(df["ticker"].unique())
    if args.codes:
        tickers = [t for t in args.codes.split(",") if t in tickers]
    if args.limit:
        tickers = tickers[:args.limit]
    
    print(f"处理 {len(tickers)} 只", flush=True)
    
    # 目标目录
    daily_dir = PLATFORM_ROOT / "data" / "market" / "HK" / "daily"
    adjust_dir = PLATFORM_ROOT / "data" / "market" / "HK" / "adjust_factor"
    if not args.dry_run:
        daily_dir.mkdir(parents=True, exist_ok=True)
        adjust_dir.mkdir(parents=True, exist_ok=True)
    
    success = 0
    failed = []
    
    for i, ticker in enumerate(tickers):
        if (i+1) % 100 == 0:
            print(f"[{i+1}/{len(tickers)}] ...", flush=True)
        
        code = ticker_to_code(ticker)
        sub = df[df["ticker"] == ticker].sort_values("date").copy()
        
        try:
            # 1. daily parquet
            daily_records = []
            close_map = {}
            for _, row in sub.iterrows():
                date_str = row["date"].strftime("%Y-%m-%d")
                close = float(row["close_raw"])
                volume = float(row["volume"]) if pd.notna(row["volume"]) else 0.0
                # amount估算：close * volume
                amount = close * volume
                
                daily_records.append({
                    "date": date_str,
                    "code": code,
                    "open": float(row["open"]) if pd.notna(row["open"]) else close,
                    "high": float(row["high"]) if pd.notna(row["high"]) else close,
                    "low": float(row["low"]) if pd.notna(row["low"]) else close,
                    "close": close,
                    "volume": volume,
                    "amount": amount,
                })
                close_map[date_str] = close
            
            # 2. adjust_factor parquet（分红因子）
            divs = sub[sub["dividends"].notna() & (sub["dividends"] != 0)][["date", "dividends"]]
            factors = build_div_factor(divs, close_map)
            
            adjust_records = [
                {
                    "code": code,
                    "dividOperateDate": date_str,
                    "foreAdjustFactor": factor,
                }
                for date_str, factor in factors
            ]
            
            if not args.dry_run:
                # 写入daily（日期降序，符合平台惯例）
                daily_df = pd.DataFrame(daily_records).sort_values("date", ascending=False)
                daily_df.to_parquet(daily_dir / f"{code}.parquet", index=False)
                
                # 写入adjust_factor（日期升序）
                if adjust_records:
                    adjust_df = pd.DataFrame(adjust_records).sort_values("dividOperateDate")
                    adjust_df.to_parquet(adjust_dir / f"{code}.parquet", index=False)
            
            success += 1
            
        except Exception as e:
            failed.append((ticker, str(e)))
            print(f"  {ticker} 失败: {e}", flush=True)
    
    print(f"\n完成：成功 {success}/{len(tickers)}，失败 {len(failed)}", flush=True)
    if failed:
        print("失败列表:", flush=True)
        for t, e in failed[:10]:
            print(f"  {t}: {e}", flush=True)


if __name__ == "__main__":
    main()
