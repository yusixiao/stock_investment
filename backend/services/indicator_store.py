import pandas as pd
from pathlib import Path

from config import INDICATOR_DIR, QFQ_KLINE_DIR
from services.indicator import calc_ma, calc_macd, calc_kdj, calc_boll
from services.stock_data import aggregate_kline

_FREQS = ["daily", "weekly", "monthly"]
_MA_WINDOWS = [5, 10, 20, 60]


def _indicator_path(symbol: str, freq: str) -> Path:
    return INDICATOR_DIR / freq / f"{symbol}.parquet"


def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    asc = df.sort_values("date").reset_index(drop=True)
    ma_df = calc_ma(asc, windows=_MA_WINDOWS)
    macd_df = calc_macd(asc)
    kdj_df = calc_kdj(asc)
    boll_df = calc_boll(asc)

    result = asc[["date"]].copy()
    for w in _MA_WINDOWS:
        result[f"ma{w}"] = ma_df[f"ma{w}"].values
    result["dif"] = macd_df["dif"].values
    result["dea"] = macd_df["dea"].values
    result["macd"] = macd_df["macd"].values
    result["k"] = kdj_df["k"].values
    result["d"] = kdj_df["d"].values
    result["j"] = kdj_df["j"].values
    result["boll_mid"] = boll_df["boll_mid"].values
    result["boll_upper"] = boll_df["boll_upper"].values
    result["boll_lower"] = boll_df["boll_lower"].values
    return result


def compute_and_save(symbol: str, df: pd.DataFrame):
    daily_df = df.sort_values("date").reset_index(drop=True)
    weekly_df = aggregate_kline(daily_df, period="weekly")
    monthly_df = aggregate_kline(daily_df, period="monthly")

    for freq, src in [("daily", daily_df), ("weekly", weekly_df), ("monthly", monthly_df)]:
        if src.empty:
            continue
        ind_df = _compute_indicators(src)
        path = _indicator_path(symbol, freq)
        path.parent.mkdir(parents=True, exist_ok=True)
        ind_df.to_parquet(path, index=False)


def load_indicators(symbol: str, freq: str) -> pd.DataFrame | None:
    path = _indicator_path(symbol, freq)
    if not path.exists():
        return None
    return pd.read_parquet(path)


def run_full_precompute(progress_callback=None):
    files = list(QFQ_KLINE_DIR.glob("*.parquet"))
    total = len(files)
    for i, filepath in enumerate(files, 1):
        symbol = filepath.stem
        try:
            df = pd.read_parquet(filepath)
            compute_and_save(symbol, df)
        except Exception as e:
            if progress_callback:
                progress_callback(f"指标预计算失败 {symbol}: {e}")
        if progress_callback and (i % 500 == 0 or i == total):
            progress_callback(f"指标预计算进度 {i}/{total}")
