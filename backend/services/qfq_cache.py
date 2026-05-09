import json
from pathlib import Path

import pandas as pd
import numpy as np

from config import RAW_KLINE_DIR, QFQ_KLINE_DIR, DIVIDEND_DIR

QFQ_META_FILE = QFQ_KLINE_DIR / "_meta.json"


def _load_meta() -> dict:
    if QFQ_META_FILE.exists():
        return json.loads(QFQ_META_FILE.read_text(encoding="utf-8"))
    return {}


def _save_meta(meta: dict):
    QFQ_META_FILE.parent.mkdir(parents=True, exist_ok=True)
    QFQ_META_FILE.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def _get_implemented_dividends(dividend_df: pd.DataFrame) -> pd.DataFrame:
    if dividend_df is None or dividend_df.empty:
        return pd.DataFrame()
    mask = dividend_df["方案进度"].str.contains("实施", na=False)
    filtered = dividend_df[mask].copy()
    filtered["除权除息日"] = pd.to_datetime(filtered["除权除息日"], errors="coerce")
    filtered = filtered.dropna(subset=["除权除息日"])
    return filtered.sort_values("除权除息日").reset_index(drop=True)


def compute_qfq(raw_df: pd.DataFrame, dividend_df: pd.DataFrame) -> pd.DataFrame:
    if raw_df is None or raw_df.empty:
        return raw_df

    dividends = _get_implemented_dividends(dividend_df)
    if dividends.empty:
        return raw_df.copy()

    was_descending = False
    df = raw_df.copy()
    df["date"] = pd.to_datetime(df["date"])

    if len(df) > 1 and df["date"].iloc[0] > df["date"].iloc[-1]:
        was_descending = True
        df = df.sort_values("date").reset_index(drop=True)

    factors = np.ones(len(df))

    for _, row in dividends.iterrows():
        ex_date = row["除权除息日"]
        cash = row.get("现金分红-现金分红比例", 0)
        bonus = row.get("送转股份-送股比例", 0)
        transfer = row.get("送转股份-转股比例", 0)

        cash = 0 if pd.isna(cash) else cash
        bonus = 0 if pd.isna(bonus) else bonus
        transfer = 0 if pd.isna(transfer) else transfer

        per_share_cash = cash / 10
        per_share_bonus = bonus / 10
        per_share_transfer = transfer / 10

        pre_close_mask = df["date"] < ex_date
        if not pre_close_mask.any():
            continue

        pre_close_idx = df[pre_close_mask].index[-1]
        pre_close = df.loc[pre_close_idx, "close"]

        if pre_close == 0:
            continue

        single_factor = (pre_close - per_share_cash) / (pre_close * (1 + per_share_bonus + per_share_transfer))

        before_ex_mask = df["date"] < ex_date
        factors[before_ex_mask] *= single_factor

    price_cols = ["open", "high", "low", "close"]
    for col in price_cols:
        df[col] = df[col] * factors

    df[price_cols] = df[price_cols].round(2)
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")

    if was_descending:
        df = df.sort_values("date", ascending=False).reset_index(drop=True)

    return df


def get_latest_ex_date(symbol: str) -> str | None:
    div_path = DIVIDEND_DIR / f"{symbol}.parquet"
    if not div_path.exists():
        return None
    div_df = pd.read_parquet(div_path)
    impl = _get_implemented_dividends(div_df)
    if impl.empty:
        return None
    return impl["除权除息日"].iloc[-1].strftime("%Y-%m-%d")


def _is_cache_valid(symbol: str, meta: dict) -> tuple[str, bool]:
    entry = meta.get(symbol)
    if entry is None:
        return "miss", False

    cache_path = QFQ_KLINE_DIR / f"{symbol}.parquet"
    if not cache_path.exists():
        return "miss", False

    current_ex_date = get_latest_ex_date(symbol) or ""
    cached_ex_date = entry.get("last_ex_date", "")
    if current_ex_date != cached_ex_date:
        return "ex_date_changed", False

    raw_path = RAW_KLINE_DIR / f"{symbol}.parquet"
    if not raw_path.exists():
        return "no_raw", False
    raw_df = pd.read_parquet(raw_path, columns=["date"])
    raw_latest = raw_df["date"].iloc[0] if not raw_df.empty else ""
    cached_latest = entry.get("raw_latest_date", "")
    if raw_latest > cached_latest:
        return "raw_newer", False

    return "valid", True


def get_qfq_kline(symbol: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    QFQ_KLINE_DIR.mkdir(parents=True, exist_ok=True)
    meta = _load_meta()
    cache_path = QFQ_KLINE_DIR / f"{symbol}.parquet"

    status, valid = _is_cache_valid(symbol, meta)

    if valid:
        df = pd.read_parquet(cache_path)
    else:
        raw_path = RAW_KLINE_DIR / f"{symbol}.parquet"
        if not raw_path.exists():
            return pd.DataFrame()
        raw_df = pd.read_parquet(raw_path)
        div_path = DIVIDEND_DIR / f"{symbol}.parquet"
        div_df = pd.read_parquet(div_path) if div_path.exists() else pd.DataFrame()
        df = compute_qfq(raw_df, div_df)
        if df is not None and not df.empty:
            df.to_parquet(cache_path, index=False)
            raw_latest = raw_df["date"].iloc[0] if not raw_df.empty else ""
            meta[symbol] = {
                "last_ex_date": get_latest_ex_date(symbol) or "",
                "raw_latest_date": raw_latest,
            }
            _save_meta(meta)

    if df is None or df.empty:
        return pd.DataFrame()

    if start_date:
        df = df[df["date"] >= start_date]
    if end_date:
        df = df[df["date"] <= end_date]
    return df


def invalidate_cache(symbols: list[str]):
    meta = _load_meta()
    for symbol in symbols:
        cache_path = QFQ_KLINE_DIR / f"{symbol}.parquet"
        if cache_path.exists():
            cache_path.unlink()
        meta.pop(symbol, None)
    _save_meta(meta)


def invalidate_all():
    for f in QFQ_KLINE_DIR.glob("*.parquet"):
        f.unlink()
    _save_meta({})
