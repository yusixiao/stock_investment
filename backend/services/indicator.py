import pandas as pd
import numpy as np


def _ensure_ascending(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values("date").reset_index(drop=True)


def _restore_order(df: pd.DataFrame, original: pd.DataFrame) -> pd.DataFrame:
    if original.iloc[0]["date"] > original.iloc[-1]["date"]:
        return df.sort_values("date", ascending=False).reset_index(drop=True)
    return df


def calc_ma(df: pd.DataFrame, windows: list[int] = None) -> pd.DataFrame:
    if windows is None:
        windows = [5, 10, 20, 60]
    asc = _ensure_ascending(df.copy())
    for w in windows:
        asc[f"ma{w}"] = asc["close"].rolling(w).mean()
    return _restore_order(asc, df)


def calc_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    asc = _ensure_ascending(df.copy())
    ema_fast = asc["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = asc["close"].ewm(span=slow, adjust=False).mean()
    asc["dif"] = ema_fast - ema_slow
    asc["dea"] = asc["dif"].ewm(span=signal, adjust=False).mean()
    asc["macd"] = (asc["dif"] - asc["dea"]) * 2
    return _restore_order(asc, df)


def calc_kdj(
    df: pd.DataFrame,
    n: int = 9,
    m1: int = 3,
    m2: int = 3,
) -> pd.DataFrame:
    asc = _ensure_ascending(df.copy())
    low_n = asc["low"].rolling(n).min()
    high_n = asc["high"].rolling(n).max()
    rsv = (asc["close"] - low_n) / (high_n - low_n) * 100
    rsv = rsv.fillna(50)

    k = pd.Series(np.zeros(len(asc)), dtype=float)
    d = pd.Series(np.zeros(len(asc)), dtype=float)
    k.iloc[0] = 50
    d.iloc[0] = 50
    for i in range(1, len(asc)):
        k.iloc[i] = (m1 - 1) / m1 * k.iloc[i - 1] + 1 / m1 * rsv.iloc[i]
        d.iloc[i] = (m2 - 1) / m2 * d.iloc[i - 1] + 1 / m2 * k.iloc[i]

    asc["k"] = k
    asc["d"] = d
    asc["j"] = 3 * k - 2 * d
    return _restore_order(asc, df)


def calc_boll(
    df: pd.DataFrame,
    window: int = 20,
    num_std: float = 2.0,
) -> pd.DataFrame:
    asc = _ensure_ascending(df.copy())
    asc["boll_mid"] = asc["close"].rolling(window).mean()
    std = asc["close"].rolling(window).std()
    asc["boll_upper"] = asc["boll_mid"] + num_std * std
    asc["boll_lower"] = asc["boll_mid"] - num_std * std
    return _restore_order(asc, df)
