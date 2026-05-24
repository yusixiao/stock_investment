"""K 线相关 utils 函数(单数据源:kline)。

包含:
  - 纯计算 getter: get_ma / get_macd  (不打日志)
  - 形态检测函数: detect_ma_tangle_breakout / is_at_history_low /
                has_consecutive_red_bars  (打日志,见后续 task)

迁移自 strategies/examples/{ma_tangle_breakout,monthly_low,monthly_volume_red}_screener.py
(2026-05-18 重构)。
"""

import pandas as _pd  # 局部命名,避免与 utils 公共 namespace 冲突


def get_ma(ctx, symbol: str, window: int, *, freq: str = "daily") -> float | None:
    """最近 window 根 K 线 close 的简单移动平均。

    优先走 ctx.get_indicator 查表(window ∈ 标准 5/10/20/30 时命中预算列,
    O(1) 列下标);未命中则 fallback 到 history-based 计算。
    数据不足 → None。
    """
    # fast path:标准窗口直接查预算 ma{N} 列(命中即返回 float / None)
    if hasattr(ctx, "get_indicator"):
        v = ctx.get_indicator("ma", symbol, period=freq, window=window)
        if v is not None:
            return v
        # 命中 None 有两种可能:1) 非标准窗口(resolve 返回 None 列)
        # 2) 数据不足窗口期(NaN)。这里无法区分,统一 fallback 到 history,
        # 数据不足时 history 路径也会返回 None,语义一致。
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

    # fast path:默认 12/26/9 参数命中预算列(macd_dif/macd_dea/macd_hist),
    # 非默认参数走 fallback。命中 None 同样可能是数据不足,统一 fallback。
    if (fast, slow, signal) == (12, 26, 9) and hasattr(ctx, "get_indicator"):
        v = ctx.get_indicator("macd", symbol, period=freq, field=field)
        if v is not None:
            return v

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


def get_macd_hist_series(
    ctx,
    symbol: str,
    n: int = 2,
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    freq: str = "weekly",
) -> list[float] | None:
    """返回最近 n 根 K 线的 MACD hist 序列(末尾为最新)。

    用于"本周 MACD vs 上周 MACD"等多期比较场景。
    hist = 2 × (DIF - DEA)(项目硬性约定)。
    数据不足(< slow + signal + n)→ None。
    """
    if n <= 0:
        return None
    need = slow + signal + n
    bars = ctx.get_history(symbol, need + 5, period=freq)
    if not bars or len(bars) < slow + signal + n:
        return None
    closes = [b["close"] for b in bars]
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    if not ema_fast or not ema_slow:
        return None
    aligned_len = min(len(ema_fast), len(ema_slow))
    dif_series = [
        ema_fast[-aligned_len + i] - ema_slow[-aligned_len + i]
        for i in range(aligned_len)
    ]
    dea_series = _ema(dif_series, signal)
    if not dea_series:
        return None
    aligned = min(len(dif_series), len(dea_series))
    hist = [
        2.0 * (dif_series[-aligned + i] - dea_series[-aligned + i])
        for i in range(aligned)
    ]
    if len(hist) < n:
        return None
    return hist[-n:]


def filter_by_ma_close(
    ctx,
    symbols: list[str],
    *,
    fast: int = 5,
    slow: int = 20,
    threshold: float = 0.01,
    freq: str = "monthly",
) -> list[str]:
    """筛选 |MA(fast) - MA(slow)| / MA(slow) <= threshold 的股票。

    threshold=0.01 即 1%。使用 ``get_ma()`` 取两条均线最新值,
    任一为 None(数据不足)→ 视作未通过。

    stage = "kline.ma_close"
    日志:
      log_pass(symbol, stage, fast=N, slow=N, ratio=R, threshold=T)
      log_reject(symbol, stage, "no_data", ...)
      log_reject(symbol, stage, "above_threshold", ratio=R, threshold=T)
    Factor 记录:
      "MA{fast}-MA{slow}差%" → ratio*100
    """
    stage = "kline.ma_close"
    result: list[str] = []
    for sym in symbols:
        ma_fast = get_ma(ctx, sym, fast, freq=freq)
        ma_slow = get_ma(ctx, sym, slow, freq=freq)
        if ma_fast is None or ma_slow is None or ma_slow == 0:
            ctx.log_reject(sym, stage, "no_data", fast=fast, slow=slow)
            continue
        ratio = abs(ma_fast - ma_slow) / abs(ma_slow)
        if ratio <= threshold:
            ctx.log_pass(
                sym, stage, fast=fast, slow=slow, ratio=ratio, threshold=threshold
            )
            ctx.record_factor(sym, f"MA{fast}-MA{slow}差%", round(ratio * 100, 3))
            result.append(sym)
        else:
            ctx.log_reject(
                sym,
                stage,
                "above_threshold",
                fast=fast,
                slow=slow,
                ratio=ratio,
                threshold=threshold,
            )
    ctx.log_flow(stage, input=len(symbols), passed=len(result))
    return result


def filter_by_close_above_ma(
    ctx,
    symbols: list[str],
    *,
    ma_window: int = 20,
    freq: str = "monthly",
) -> list[str]:
    """筛选最近一根 K 线 close > MA(ma_window) 的股票(简单趋势择时)。

    数据不足或 MA 缺失视作未通过。stage = "kline.close_above_ma"
    日志:
      log_pass(symbol, stage, window=N, close=C, ma=M, premium_pct=P)
      log_reject(symbol, stage, "no_data" | "no_price" | "below_ma", ...)
    Factor:
      "close>MA{N}溢价%" → (close/ma - 1) * 100
    """
    stage = "kline.close_above_ma"
    result: list[str] = []
    for sym in symbols:
        ma_val = get_ma(ctx, sym, ma_window, freq=freq)
        if ma_val is None or ma_val == 0:
            ctx.log_reject(sym, stage, "no_data", window=ma_window)
            continue
        # 取当前 bar 的 close(period 取与 MA 一致,保证语义对齐)
        price = ctx.get_price(sym, period=freq)
        close = price.get("close") if price else None
        if close is None:
            ctx.log_reject(sym, stage, "no_price", window=ma_window)
            continue
        if close > ma_val:
            premium_pct = (close / ma_val - 1.0) * 100
            ctx.log_pass(
                sym,
                stage,
                window=ma_window,
                close=close,
                ma=ma_val,
                premium_pct=premium_pct,
            )
            ctx.record_factor(sym, f"close>MA{ma_window}溢价%", round(premium_pct, 3))
            result.append(sym)
        else:
            ctx.log_reject(
                sym,
                stage,
                "below_ma",
                window=ma_window,
                close=close,
                ma=ma_val,
            )
    ctx.log_flow(stage, input=len(symbols), passed=len(result))
    return result


def is_at_history_low(
    ctx,
    symbol: str,
    *,
    years: int = 3,
    range_pct: float = 20.0,
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
        ctx.log_reject(
            symbol, stage, "no_data", have=len(bars) if bars else 0, need=lookback + 1
        )
        return False

    range_ratio = 1.0 + range_pct / 100.0
    current_low = bars[-1]["low"]
    past_lows = [b["low"] for b in bars[-(lookback + 1) : -1]]
    hist_min = min(past_lows)
    threshold = hist_min * range_ratio

    if current_low <= threshold:
        ctx.log_pass(
            symbol,
            stage,
            current_low=current_low,
            hist_min=hist_min,
            threshold=threshold,
            range_pct=range_pct,
        )
        return True
    ctx.log_reject(
        symbol,
        stage,
        "above_threshold",
        current_low=current_low,
        hist_min=hist_min,
        threshold=threshold,
        range_pct=range_pct,
    )
    return False


def has_consecutive_red_bars(
    ctx,
    symbol: str,
    *,
    n: int = 4,
    freq: str = "monthly",
) -> bool:
    """最近 n 根 K 线全部满足 close >= open(阳线/平收)。

    迁移自 MonthlyVolumeRedScreener。
    stage = "kline.consecutive_red"
    """
    stage = "kline.consecutive_red"
    bars = ctx.get_history(symbol, n, period=freq)
    if not bars or len(bars) < n:
        ctx.log_reject(symbol, stage, "no_data", have=len(bars) if bars else 0, need=n)
        return False

    recent = bars[-n:]
    if all(b["close"] >= b["open"] for b in recent):
        ctx.log_pass(symbol, stage, n=n)
        return True
    ctx.log_reject(symbol, stage, "not_all_red", n=n)
    return False


def _is_tangle(
    df,
    end: int,
    col_f: str,
    col_m: str,
    col_s: str,
    tangle_months: int,
    threshold: float,
) -> bool:
    """end 索引处往前 tangle_months 根都满足 |MA - avg|/avg <= threshold。
    最后一根额外要求 MA_slow < MA_fast(为后续向上发散预留)。"""
    if end < tangle_months - 1:
        return False
    for i in range(end - tangle_months + 1, end + 1):
        row = df.iloc[i]
        avg = (row[col_f] + row[col_m] + row[col_s]) / 3.0
        if avg == 0:
            return False
        if (
            abs(row[col_f] - avg) / avg > threshold
            or abs(row[col_m] - avg) / avg > threshold
            or abs(row[col_s] - avg) / avg > threshold
        ):
            return False
    last = df.iloc[end]
    return last[col_s] < last[col_f]


def _check_spread_bar(
    row, col_f: str, col_m: str, col_s: str, spread_threshold: float
) -> bool:
    avg = (row[col_f] + row[col_m] + row[col_s]) / 3.0
    if avg == 0:
        return False
    if (
        abs(row[col_f] - avg) / avg <= spread_threshold
        or abs(row[col_s] - avg) / avg <= spread_threshold
    ):
        return False
    return row[col_f] > row[col_m] > row[col_s]


def _macd_hist_on_closes(
    closes: list[float],
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> list[float]:
    """对一段 closes 计算完整 MACD hist 序列(等长于 closes)。

    hist = 2 × (DIF - DEA),与 ``get_macd`` / ``get_macd_hist_series`` 一致。
    数据不足(< slow)→ 返回空列表。
    """
    if len(closes) < slow:
        return []
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    if not ema_fast or not ema_slow:
        return []
    aligned_len = min(len(ema_fast), len(ema_slow))
    dif = [
        ema_fast[-aligned_len + i] - ema_slow[-aligned_len + i]
        for i in range(aligned_len)
    ]
    dea = _ema(dif, signal)
    if not dea:
        return []
    aligned = min(len(dif), len(dea))
    return [2.0 * (dif[-aligned + i] - dea[-aligned + i]) for i in range(aligned)]


def detect_ma_tangle_breakout(
    ctx,
    symbol: str,
    *,
    fast: int = 5,
    mid: int = 10,
    slow: int = 20,
    tangle_threshold: float = 0.05,
    tangle_months: int = 2,
    spread_months: int = 6,
    spread_threshold: float = 0.01,
    macd_red_bars: int = 4,
    freq: str = "monthly",
) -> bool:
    """月线均线缠绕→发散→末尾 MACD 连续 N 根红柱 突破检测。

    返回 True 当且仅当 history 末尾存在某次「缠绕(N根)→发散(M根)」事件
    覆盖到最后一根 bar,**且**最后 ``macd_red_bars`` 根 K 线 MACD hist > 0
    (红柱,动能确认向上)。``macd_red_bars <= 0`` 时跳过该闸门。

    数据需求:历史 bar 数 >= slow + tangle_months + spread_months;若启用
    MACD 闸门,还需 >= 26 + 9 + macd_red_bars 根用以算 hist 序列。
    stage = "kline.ma_tangle"
    """
    stage = "kline.ma_tangle"
    need = slow + tangle_months + spread_months
    bars = ctx.get_history(symbol, max(need, 500), period=freq)
    if not bars:
        ctx.log_reject(symbol, stage, "no_data", have=0, need=need)
        return False
    if len(bars) < need:
        ctx.log_reject(symbol, stage, "insufficient_history", have=len(bars), need=need)
        return False

    df = _pd.DataFrame(bars)
    col_f, col_m, col_s = f"ma{fast}", f"ma{mid}", f"ma{slow}"
    for w, col in [(fast, col_f), (mid, col_m), (slow, col_s)]:
        df[col] = df["close"].rolling(window=w, min_periods=w).mean()
    df = df.dropna(subset=[col_f, col_m, col_s]).reset_index(drop=True)

    n = len(df)
    if n < tangle_months + 1:
        ctx.log_reject(
            symbol,
            stage,
            "insufficient_history_after_ma",
            have=n,
            need=tangle_months + 1,
        )
        return False

    last_idx = n - 1
    matched = False
    skip_until = -1

    for tangle_end in range(tangle_months - 1, n - 1):
        if tangle_end <= skip_until:
            continue
        if not _is_tangle(
            df, tangle_end, col_f, col_m, col_s, tangle_months, tangle_threshold
        ):
            continue

        spread_start = tangle_end + 1
        if last_idx < spread_start:
            continue

        if spread_months > 0:
            spread_window_end = min(spread_start + spread_months, n)
            spread_rows = df.iloc[spread_start:spread_window_end]
            all_spread = all(
                _check_spread_bar(
                    spread_rows.iloc[j], col_f, col_m, col_s, spread_threshold
                )
                for j in range(len(spread_rows))
            )
            if not all_spread:
                continue
        else:
            spread_window_end = spread_start + 1

        # MACD 闸门只在「发散窗口覆盖到最后一根 bar」时才有意义,
        # 且统一基于 df["close"] 计算 MACD hist。
        if spread_window_end - 1 >= last_idx:
            if macd_red_bars > 0:
                # 用原始 bars 的 closes(未经 MA dropna),保证有足够长度
                # 计算 MACD(slow=26 + signal=9)。bars[-1] 即 df.iloc[-1],
                # 所以 hist[-1] 对应当前 last_idx 的 MACD hist。
                hist = _macd_hist_on_closes([b["close"] for b in bars])
                if len(hist) < macd_red_bars or not all(
                    h > 0 for h in hist[-macd_red_bars:]
                ):
                    skip_until = spread_window_end - 1
                    continue
            matched = True
        skip_until = spread_window_end - 1

    if matched:
        ctx.log_pass(
            symbol,
            stage,
            fast=fast,
            mid=mid,
            slow=slow,
            tangle_months=tangle_months,
            spread_months=spread_months,
        )
        return True
    ctx.log_reject(symbol, stage, "no_breakout_at_current_bar")
    return False
