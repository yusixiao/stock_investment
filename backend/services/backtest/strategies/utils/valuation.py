"""估值数据相关 utils 函数(单数据源:valuation)。

迁移自 strategies/examples/pe_pb_product_screener.py(2026-05-18 重构)。
"""


def _get_field(ctx, symbol: str, field: str):
    val = ctx.get_valuation(symbol)
    if val is None:
        return None
    return val.get(field)


def get_pe(ctx, symbol: str) -> float | None:
    """PE(TTM)。English schema:peTTM(BaoStock daily)。"""
    return _get_field(ctx, symbol, "peTTM")


def get_pb(ctx, symbol: str) -> float | None:
    """PB。English schema:pbMRQ(BaoStock daily)。"""
    return _get_field(ctx, symbol, "pbMRQ")


def get_total_mv(ctx, symbol: str) -> float | None:
    """总市值(单位:元)= 当前 close × 最近报告期 TOTAL_SHARE。
    English schema:从 financial(indicator)取 TOTAL_SHARE,从 K 线最新 bar 取 close。
    无任一数据 → None。
    """
    fin = ctx.get_financial(symbol)
    if fin is None:
        return None
    total_share = fin.get("TOTAL_SHARE")
    if total_share is None:
        return None
    # 取当前日期最近一根日 K 线 close
    price = ctx.get_price(symbol)
    if price is None:
        return None
    close = price.get("close")
    if close is None:
        return None
    return float(close) * float(total_share)


def filter_by_pe(
    ctx,
    symbols: list[str],
    *,
    min_value: float = 0.0,
    max_value: float = 30.0,
) -> list[str]:
    """筛选 PE(TTM) ∈ [min_value, max_value] 的股票。

    stage = "valuation.pe"
    reject reason: "no_data" | "below_min" | "above_max"
    """
    stage = "valuation.pe"
    result: list[str] = []
    for sym in symbols:
        pe = get_pe(ctx, sym)
        if pe is None:
            ctx.log_reject(sym, stage, "no_data", min=min_value, max=max_value)
            continue
        ctx.record_factor(sym, "PE", pe)
        if pe < min_value:
            ctx.log_reject(sym, stage, "below_min", pe=pe, min=min_value, max=max_value)
        elif pe > max_value:
            ctx.log_reject(sym, stage, "above_max", pe=pe, min=min_value, max=max_value)
        else:
            ctx.log_pass(sym, stage, pe=pe, min=min_value, max=max_value)
            result.append(sym)
    ctx.log_flow(stage, input=len(symbols), passed=len(result))
    return result


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
        # 因子收集:无论是否最终通过,都先记录(策略雷达只在 hits 上读取,
        # 不会读到被淘汰的;而最终通过的命中股票需要 PE / PB / PE*PB 三个值)
        ctx.record_factor(sym, "PE", pe)
        ctx.record_factor(sym, "PB", pb)
        ctx.record_factor(sym, "PE*PB", product)
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
