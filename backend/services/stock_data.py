import math

import pandas as pd
from pathlib import Path
from typing import Optional

from config import RAW_KLINE_DIR


def symbol_to_exchange(code: str) -> str:
    if code.startswith("6"):
        return "SH"
    return "SZ"


def symbol_to_filepath(code: str) -> Path:
    exchange = symbol_to_exchange(code)
    return RAW_KLINE_DIR / f"{code}.{exchange}.parquet"


def get_latest_date(filepath: Path) -> Optional[str]:
    df = pd.read_parquet(filepath, columns=["date"])
    if df.empty:
        return None
    return df.iloc[0]["date"]


def get_kline(
    filepath: Path,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    df = pd.read_parquet(filepath)
    if start_date:
        df = df[df["date"] >= start_date]
    if end_date:
        df = df[df["date"] <= end_date]
    return df


def aggregate_kline(df: pd.DataFrame, period: str = "weekly") -> pd.DataFrame:
    asc = df.sort_values("date").reset_index(drop=True)
    asc["date_dt"] = pd.to_datetime(asc["date"])
    if period == "weekly":
        asc["period_key"] = asc["date_dt"].dt.to_period("W-FRI")
    else:
        asc["period_key"] = asc["date_dt"].dt.to_period("M")

    grouped = asc.groupby("period_key", sort=True)
    result = pd.DataFrame({
        "date": grouped["date"].last(),
        "open": grouped["open"].first(),
        "high": grouped["high"].max(),
        "low": grouped["low"].min(),
        "close": grouped["close"].last(),
        "volume": grouped["volume"].sum(),
        "amount": grouped["amount"].sum(),
    }).reset_index(drop=True)

    is_desc = df.iloc[0]["date"] > df.iloc[-1]["date"] if len(df) > 1 else False
    if is_desc:
        result = result.sort_values("date", ascending=False).reset_index(drop=True)
    return result


def list_stocks(
    data_dir: Optional[Path] = None,
    search: Optional[str] = None,
) -> list[dict]:
    if data_dir is None:
        data_dir = RAW_KLINE_DIR
    results = []
    for f in sorted(data_dir.glob("*.parquet")):
        symbol = f.stem
        if search and search.lower() not in symbol.lower():
            continue
        df = pd.read_parquet(f, columns=["date", "close", "volume"])
        latest = df.iloc[0] if not df.empty else {}
        close_val = float(latest.get("close", 0))
        volume_val = float(latest.get("volume", 0))
        if math.isnan(close_val) or math.isinf(close_val):
            close_val = 0.0
        if math.isnan(volume_val) or math.isinf(volume_val):
            volume_val = 0.0
        results.append({
            "symbol": symbol,
            "latest_date": latest.get("date", ""),
            "close": close_val,
            "volume": volume_val,
        })
    return results
