"""估值数据相关 utils 函数(单数据源:valuation)。

迁移自 strategies/examples/pe_pb_product_screener.py(2026-05-18 重构)。
"""


def _get_field(ctx, symbol: str, field: str):
    val = ctx.get_valuation(symbol)
    if val is None:
        return None
    return val.get(field)


def get_pe(ctx, symbol: str) -> float | None:
    """PE(TTM)。"""
    return _get_field(ctx, symbol, "pe_ttm")


def get_pb(ctx, symbol: str) -> float | None:
    """PB。"""
    return _get_field(ctx, symbol, "pb")


def get_total_mv(ctx, symbol: str) -> float | None:
    """总市值(单位:元)。"""
    return _get_field(ctx, symbol, "total_mv")


def filter_by_pe_pb_product(
    ctx,
    symbols: list[str],
    *,
    min_value: float = 0.0,
    max_value: float = 22.0,
) -> list[str]:
    """筛选 PE(TTM) * PB ∈ [min_value, max_value] 的股票。

    stage = "valuation.pe_pb_product"
    reject reason: "no_data" | "below_min" | "above_max"
    """
    stage = "valuation.pe_pb_product"
    result: list[str] = []
    for sym in symbols:
        pe = get_pe(ctx, sym)
        pb = get_pb(ctx, sym)
        if pe is None or pb is None:
            ctx.log_reject(sym, stage, "no_data", min=min_value, max=max_value)
            continue
        product = pe * pb
        if product < min_value:
            ctx.log_reject(
                sym,
                stage,
                "below_min",
                pe=pe,
                pb=pb,
                product=product,
                min=min_value,
                max=max_value,
            )
        elif product > max_value:
            ctx.log_reject(
                sym,
                stage,
                "above_max",
                pe=pe,
                pb=pb,
                product=product,
                min=min_value,
                max=max_value,
            )
        else:
            ctx.log_pass(
                sym, stage, pe=pe, pb=pb, product=product, min=min_value, max=max_value
            )
            result.append(sym)
    ctx.log_flow(stage, input=len(symbols), passed=len(result))
    return result
