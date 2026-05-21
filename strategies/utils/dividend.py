"""分红事件相关 utils 函数(单数据源:dividend)。

迁移自 strategies/examples/dividend_years_screener.py(2026-05-18 重构)。
"""

import pandas as pd

# 用于在 df.attrs 中存放 count 结果的 key;-1 为 sentinel,表示「列缺失,应返回 None」。
_CACHE_KEY = "_count_dividend_years_cache"
_NONE_SENTINEL = -1


def count_dividend_years(ctx, symbol: str) -> int | None:
    """统计该股票历史上有几个不同的年度发生过现金分红 (cash > 0)。

    无分红数据 / 缺少分红比例列 → 返回 None
    返回:有效分红年数(int)或 None

    性能(Round 4):该结果与日期无关 — 全历史 dividend 表本身在回测期不变。
    旧实现按 row 循环 + ``df.loc[idx, "报告期"]`` 标签查找,5429 syms × ~113 月线
    screen ≈ 613K 次调用,cProfile 占 screen() 49%(0.72s)。
    新实现:
    1. 用 ``pd.to_numeric`` + 布尔 mask 一次性过滤 cash > 0
    2. 通过 ``df.attrs`` 把结果 memoize 在 dataframe 上(df 生命周期 = 回测期),
       同一只股票每次回测仅计算一次。
    """
    df = ctx.get_dividend(symbol)
    if df is None:
        return None

    # 走 df.attrs memoize:DataFrame 自带的 user metadata dict,不会污染列结构,
    # 且与 df 一同释放,避免 id() 复用引发的脏缓存问题。
    cached = df.attrs.get(_CACHE_KEY) if hasattr(df, "attrs") else None
    if cached is not None:
        return None if cached == _NONE_SENTINEL else cached

    col = "现金分红-现金分红比例"
    if col not in df.columns:
        if hasattr(df, "attrs"):
            df.attrs[_CACHE_KEY] = _NONE_SENTINEL
        return None

    # 向量化:to_numeric(errors=coerce) 把非数值变 NaN,> 0 mask 一次过滤,
    # 避开 per-row isinstance + math.isnan + df.loc 标签查找
    vals = pd.to_numeric(df[col], errors="coerce")
    mask = vals.notna() & (vals > 0)
    if not mask.any():
        result = 0
    else:
        # 取报告期前 4 位为年份字符串,去重 + 过滤掉长度不足 4 的
        report_year = df.loc[mask, "报告期"].astype(str).str[:4]
        # str.len() 对 NaN 返回 NaN,但 astype(str) 后已不会有 NaN
        valid = report_year[report_year.str.len() >= 4]
        result = int(valid.nunique())

    if hasattr(df, "attrs"):
        df.attrs[_CACHE_KEY] = result
    return result


def filter_by_dividend_years(
    ctx, symbols: list[str], *, min_years: int = 5
) -> list[str]:
    """筛选累计现金分红年数 >= min_years 的股票。

    stage = "dividend.years"
    日志:
      log_pass(symbol, stage, years=N, threshold=min_years)
      log_reject(symbol, stage, "below_threshold", years=N, threshold=min_years)
      log_reject(symbol, stage, "no_data", threshold=min_years)
      log_flow(stage, input=len(symbols), passed=len(result))
    """
    stage = "dividend.years"
    result: list[str] = []
    for sym in symbols:
        years = count_dividend_years(ctx, sym)
        if years is None:
            ctx.log_reject(sym, stage, "no_data", threshold=min_years)
            continue
        if years >= min_years:
            ctx.log_pass(sym, stage, years=years, threshold=min_years)
            result.append(sym)
        else:
            ctx.log_reject(
                sym, stage, "below_threshold", years=years, threshold=min_years
            )
    ctx.log_flow(stage, input=len(symbols), passed=len(result))
    return result
