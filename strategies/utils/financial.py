"""财务三表 + 指标相关 utils 函数(单数据源:financial)。

迁移自 strategies/examples/roe_screener.py(2026-05-18 重构)。
"""


def _get_field(ctx, symbol: str, field: str):
    fin = ctx.get_financial(symbol)
    if fin is None:
        return None
    return fin.get(field)


def get_roe(ctx, symbol: str) -> float | None:
    """净资产收益率(%)。English schema:ROEJQ(EastMoney indicator)。"""
    return _get_field(ctx, symbol, "ROEJQ")


def get_eps(ctx, symbol: str) -> float | None:
    """基本每股收益。English schema:EPSJB。"""
    return _get_field(ctx, symbol, "EPSJB")


def get_net_profit_growth(ctx, symbol: str) -> float | None:
    """归母净利润同比增长率(%)。English schema:PARENTNETPROFITTZ(EastMoney 累计同比)。"""
    return _get_field(ctx, symbol, "PARENTNETPROFITTZ")


def filter_by_roe(ctx, symbols: list[str], *, min_roe: float = 10.0) -> list[str]:
    """筛选 ROE >= min_roe 的股票。

    stage = "financial.roe"
    """
    stage = "financial.roe"
    result: list[str] = []
    for sym in symbols:
        roe = get_roe(ctx, sym)
        if roe is None:
            ctx.log_reject(sym, stage, "no_data", threshold=min_roe)
            continue
        # 因子收集 — 策略雷达展示 ROE 实际值
        ctx.record_factor(sym, "ROE", roe)
        if roe >= min_roe:
            ctx.log_pass(sym, stage, roe=roe, threshold=min_roe)
            result.append(sym)
        else:
            ctx.log_reject(sym, stage, "below_threshold", roe=roe, threshold=min_roe)
    ctx.log_flow(stage, input=len(symbols), passed=len(result))
    return result
