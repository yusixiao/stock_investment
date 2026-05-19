"""K 线相关 utils 函数(单数据源:kline)。

包含:
  - 纯计算 getter: get_ma / get_macd  (不打日志)
  - 形态检测函数: detect_ma_tangle_breakout / is_at_history_low /
                has_consecutive_red_bars  (打日志,见后续 task)

迁移自 strategies/examples/{ma_tangle_breakout,monthly_low,monthly_volume_red}_screener.py
(2026-05-18 重构)。
"""


def get_ma(ctx, symbol: str, window: int, *, freq: str = "daily") -> float | None:
    """最近 window 根 K 线 close 的简单移动平均。

    数据不足 → None。freq 决定从何种周期取数据。
    """
    bars = ctx.get_history(symbol, window, period=freq)
    if not bars or len(bars) < window:
        return None
    return sum(b["close"] for b in bars[-window:]) / window


def _ema(values: list[float], window: int) -> list[float]:
    """指数移动平均(标准公式 alpha = 2/(N+1))。

    返回与输入等长的列表;前 window-1 个位置用 SMA 初始化为同值,
    第 window 个起按 EMA 递推。
    """
    if len(values) < window:
        return []
    alpha = 2.0 / (window + 1)
    out: list[float] = []
    sma = sum(values[:window]) / window
    out.extend([sma] * window)
    for v in values[window:]:
        out.append(out[-1] + alpha * (v - out[-1]))
    return out


def get_macd(
    ctx,
    symbol: str,
    field: str = "dif",
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    freq: str = "daily",
) -> float | None:
    """MACD 三个分量之一。

    field: "dif" | "dea" | "hist"
    hist = 2 * (DIF - DEA)  (项目约定,与通达信一致)
    数据不足(< slow + signal)→ None。
    """
    if field not in {"dif", "dea", "hist"}:
        raise ValueError(f"field must be 'dif'/'dea'/'hist', got {field!r}")

    need = slow + signal
    bars = ctx.get_history(symbol, need + 1, period=freq)
    if not bars or len(bars) < slow:
        return None

    closes = [b["close"] for b in bars]
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    if not ema_fast or not ema_slow:
        return None

    # 对齐到较短的列表(取 slow 之后才有有效 DIF)
    aligned_len = min(len(ema_fast), len(ema_slow))
    dif_series = [
        ema_fast[-aligned_len + i] - ema_slow[-aligned_len + i]
        for i in range(aligned_len)
    ]
    if field == "dif":
        return dif_series[-1]

    dea_series = _ema(dif_series, signal)
    if not dea_series:
        return None
    if field == "dea":
        return dea_series[-1]

    # hist = 2 × (DIF - DEA),项目硬性约定
    return 2.0 * (dif_series[-1] - dea_series[-1])


def is_at_history_low(
    ctx, symbol: str, *,
    years: int = 3, range_pct: float = 20.0,
    freq: str = "monthly",
) -> bool:
    """当月 low 是否处于过去 N 年同周期最低 low 的 (1 + range_pct%) 范围内。

    迁移自 MonthlyLowScreener。
    stage = "kline.history_low"
    lookback bar 数:monthly→12*years, weekly→52*years, daily→250*years
    """
    stage = "kline.history_low"
    bars_per_year = {"monthly": 12, "weekly": 52, "daily": 250}.get(freq, 12)
    lookback = years * bars_per_year

    bars = ctx.get_history(symbol, lookback + 1, period=freq)
    if not bars or len(bars) < lookback + 1:
        ctx.log_reject(symbol, stage, "no_data",
                       have=len(bars) if bars else 0, need=lookback + 1)
        return False

    range_ratio = 1.0 + range_pct / 100.0
    current_low = bars[-1]["low"]
    past_lows = [b["low"] for b in bars[-(lookback + 1):-1]]
    hist_min = min(past_lows)
    threshold = hist_min * range_ratio

    if current_low <= threshold:
        ctx.log_pass(symbol, stage,
                     current_low=current_low, hist_min=hist_min,
                     threshold=threshold, range_pct=range_pct)
        return True
    ctx.log_reject(symbol, stage, "above_threshold",
                   current_low=current_low, hist_min=hist_min,
                   threshold=threshold, range_pct=range_pct)
    return False


def has_consecutive_red_bars(
    ctx, symbol: str, *,
    n: int = 4, freq: str = "monthly",
) -> bool:
    """最近 n 根 K 线全部满足 close >= open(阳线/平收)。

    迁移自 MonthlyVolumeRedScreener。
    stage = "kline.consecutive_red"
    """
    stage = "kline.consecutive_red"
    bars = ctx.get_history(symbol, n, period=freq)
    if not bars or len(bars) < n:
        ctx.log_reject(symbol, stage, "no_data",
                       have=len(bars) if bars else 0, need=n)
        return False

    recent = bars[-n:]
    if all(b["close"] >= b["open"] for b in recent):
        ctx.log_pass(symbol, stage, n=n)
        return True
    ctx.log_reject(symbol, stage, "not_all_red", n=n)
    return False
