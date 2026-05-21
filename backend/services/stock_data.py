"""K 线辅助工具:日线 → 周/月线聚合(供 routers/stock + market_data 使用)。"""

import pandas as pd


def aggregate_kline(df: pd.DataFrame, period: str = "weekly") -> pd.DataFrame:
    """日线聚合到周/月线。
    - weekly:周五为 period_key(W-FRI)
    - monthly:自然月(M)
    输出 7 列;若输入 df 为日期降序,输出保持降序;否则升序。
    """
    asc = df.sort_values("date").reset_index(drop=True)
    asc["date_dt"] = pd.to_datetime(asc["date"])
    if period == "weekly":
        asc["period_key"] = asc["date_dt"].dt.to_period("W-FRI")
    else:
        asc["period_key"] = asc["date_dt"].dt.to_period("M")

    grouped = asc.groupby("period_key", sort=True)
    result = pd.DataFrame(
        {
            "date": grouped["date"].last(),
            "open": grouped["open"].first(),
            "high": grouped["high"].max(),
            "low": grouped["low"].min(),
            "close": grouped["close"].last(),
            "volume": grouped["volume"].sum(),
            "amount": grouped["amount"].sum(),
        }
    ).reset_index(drop=True)

    is_desc = df.iloc[0]["date"] > df.iloc[-1]["date"] if len(df) > 1 else False
    if is_desc:
        result = result.sort_values("date", ascending=False).reset_index(drop=True)
    return result
