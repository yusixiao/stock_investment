"""分红事件相关 utils 函数(单数据源:dividend)。

迁移自 strategies/examples/dividend_years_screener.py(2026-05-18 重构)。
"""

import math


def count_dividend_years(ctx, symbol: str) -> int | None:
    """统计该股票历史上有几个不同的年度发生过现金分红 (cash > 0)。

    无分红数据 / 缺少分红比例列 → 返回 None
    返回:有效分红年数(int)或 None
    """
    df = ctx.get_dividend(symbol)
    if df is None:
        return None
    col = "现金分红-现金分红比例"
    if col not in df.columns:
        return None

    years: set[str] = set()
    for idx, val in df[col].items():
        if not isinstance(val, (int, float)):
            continue
        if math.isnan(val) or val <= 0:
            continue
        report_date = str(df.loc[idx, "报告期"])
        if len(report_date) >= 4:
            years.add(report_date[:4])

    return len(years)


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
