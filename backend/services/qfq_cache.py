import pandas as pd
import numpy as np


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
