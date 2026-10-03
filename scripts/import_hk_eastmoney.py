"""将研究侧 HK 数据导入平台 data/market/HK/ 格式。

研究数据：~/workspace/港股回测/data/raw/all_20150101-20260930_v1.parquet
  - 列：date, ticker, open, high, low, close_raw, close_adj, volume, dividends, splits
  - close_raw：研究侧不复权价格快照
  - dividends：分红金额

目标格式：
  - data/market/HK/daily/{code}.parquet：DailyKlineRecord列表
    - code格式：00700.HK（5位+后缀）
    - close = close_raw（不复权）
    - amount = Eastmoney fqt=0 返回的真实成交额
  - data/market/HK/adjust_factor/{code}.parquet：AdjustFactorRecord列表
    - div_factor = ∏(1 - D/P)，锚定最新=1.0
    - 只含现金分红事件，其他公司行为不在该因子中补造

用法：
    python scripts/import_hk_eastmoney.py [--limit N] [--codes 00700,00005]
"""
import argparse
import sys
from pathlib import Path

# 平台根目录
PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))
sys.path.insert(0, str(PLATFORM_ROOT / "backend"))

import pandas as pd

from backend.services.market_data.hk_adjust_factor import build_dividend_factor_rows
from backend.services.market_data.hk_price_cleaner import clean_transient_scale_spikes

# 研究数据路径
RESEARCH_PARQUET = Path.home() / "workspace/港股回测/data/raw/all_20150101-20260930_v1.parquet"


def ticker_to_code(ticker: str) -> str:
    """00700 -> 00700.HK"""
    return f"{ticker}.HK"


def build_div_factor(dividends: pd.DataFrame, close_map: dict) -> list:
    """构建分红因子，并补齐首个事件前的历史基准因子。"""
    events = []
    for _, row in dividends.iterrows():
        date_value = row["date"]
        date_str = (
            date_value.strftime("%Y-%m-%d")
            if hasattr(date_value, "strftime")
            else str(date_value)[:10]
        )
        events.append((date_str, row["dividends"]))
    return build_dividend_factor_rows(events, close_map)


def fetch_eastmoney_amounts(adapter, code: str, source: pd.DataFrame) -> dict[str, float]:
    """用 Eastmoney fqt=0 的真实成交额覆盖研究快照的估算值。

    API不可达时返回空dict，调用方回退到估算值（close×volume）。
    """
    try:
        start = source["date"].min().strftime("%Y-%m-%d")
        end = source["date"].max().strftime("%Y-%m-%d")
        records = adapter.fetch_daily_kline(code, start, end, fqt=0)
        records = clean_transient_scale_spikes(records)
        amounts = {record.date: float(record.amount) for record in records}
        source_dates = set(source["date"].dt.strftime("%Y-%m-%d"))
        missing = sorted(source_dates - amounts.keys())
        if missing:
            # 缺失日期太多，回退到估算
            return {}
        return amounts
    except Exception:
        # API限流/代理拦截等，回退到估算
        return {}


def build_daily_records(
    source: pd.DataFrame,
    code: str,
    amount_by_date: dict[str, float],
) -> list[dict]:
    """把研究快照转换为平台日线，并清除可识别的瞬时坏 tick。

    amount_by_date为空时回退到 close×volume 估算（会在日志中标注）。
    """
    records = []
    use_estimated = not amount_by_date
    for _, row in source.sort_values("date").iterrows():
        date_str = row["date"].strftime("%Y-%m-%d")
        close = float(row["close_raw"])
        volume = float(row["volume"]) if pd.notna(row["volume"]) else 0.0
        # API不可用时回退到估算值
        amount = amount_by_date.get(date_str, close * volume)
        records.append(
            {
                "date": date_str,
                "code": code,
                "open": float(row["open"]) if pd.notna(row["open"]) else close,
                "high": float(row["high"]) if pd.notna(row["high"]) else close,
                "low": float(row["low"]) if pd.notna(row["low"]) else close,
                "close": close,
                "volume": volume,
                "amount": amount,
            }
        )
    cleaned = clean_transient_scale_spikes(records)
    return cleaned, use_estimated


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="只处理前N只（测试用）")
    parser.add_argument("--codes", type=str, default="", help="指定代码，逗号分隔")
    parser.add_argument("--research-parquet", type=Path, default=RESEARCH_PARQUET)
    parser.add_argument("--dry-run", action="store_true", help="只打印不写入")
    args = parser.parse_args()
    
    print("加载研究数据...", flush=True)
    df = pd.read_parquet(args.research_parquet)
    df["date"] = pd.to_datetime(df["date"])
    print(f"共 {len(df):,} 条，{df['ticker'].nunique()} 只", flush=True)
    
    tickers = sorted(df["ticker"].unique())
    if args.codes:
        tickers = [t for t in args.codes.split(",") if t in tickers]
    if args.limit:
        tickers = tickers[:args.limit]
    
    print(f"处理 {len(tickers)} 只", flush=True)

    from backend.adapters.eastmoney_adapter import EastMoneyAdapter

    amount_adapter = EastMoneyAdapter()
    
    # 目标目录
    daily_dir = PLATFORM_ROOT / "data" / "market" / "HK" / "daily"
    adjust_dir = PLATFORM_ROOT / "data" / "market" / "HK" / "adjust_factor"
    if not args.dry_run:
        daily_dir.mkdir(parents=True, exist_ok=True)
        adjust_dir.mkdir(parents=True, exist_ok=True)
    
    success = 0
    failed = []
    estimated_count = 0
    
    for i, ticker in enumerate(tickers):
        if (i+1) % 100 == 0:
            print(f"[{i+1}/{len(tickers)}] ...", flush=True)
        
        code = ticker_to_code(ticker)
        sub = df[df["ticker"] == ticker].sort_values("date").copy()
        
        try:
            amount_by_date = fetch_eastmoney_amounts(amount_adapter, code, sub)
            daily_records, use_estimated = build_daily_records(sub, code, amount_by_date)
            if use_estimated:
                estimated_count += 1
            close_map = {record["date"]: record["close"] for record in daily_records}
            
            # 2. adjust_factor parquet（分红因子）
            divs = sub[sub["dividends"].notna() & (sub["dividends"] != 0)][["date", "dividends"]]
            divs = divs[divs["date"].dt.strftime("%Y-%m-%d").isin(close_map)]
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
    print(f"其中 {estimated_count} 只使用估算amount（API不可达）", flush=True)
    if failed:
        print("失败列表:", flush=True)
        for t, e in failed[:10]:
            print(f"  {t}: {e}", flush=True)


if __name__ == "__main__":
    main()
