"""验证 HK 股本倒推方案的精度与覆盖率。

对 dividend.years 通过的 1172 只 HK 股全部:
  total_share_推 = PARENT_NETPROFIT / BASIC_EPS
  market_cap_推 = total_share_推 × close
  R = NP × payout / market_cap_推 × 100

输出:
  - 倒推成功率(BASIC_EPS 非空且 > 0 的占比)
  - R 分布(看有多少能 ≥ 5.2)
  - 与 peTTM 直查口径的对照(R_peTTM = payout × 100 / peTTM)
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from services.backtest import data_cache
from services.backtest.context import ScreenContext
from services.backtest.market_data import MarketData
from services.backtest.strategies.utils import conservative
from services.backtest.strategies.utils.dividend import filter_by_dividend_years


START = "2017-01-01"
END = "2026-05-28"


def main():
    print("=== loading HK ===")
    bundle = data_cache.get_market("HK")
    if bundle is None:
        bundle = data_cache._load_market_blocking("HK")
    sliced = data_cache.slice_bundle(bundle, None, START, END)
    print(f"sliced: {len(sliced.stock_data)} stocks")

    md = MarketData(
        stock_data=sliced.stock_data,
        valuation=sliced.valuation_data,
        dividend=sliced.dividend_data,
        financial=sliced.financial_data,
        balance=getattr(sliced, "balance_data", None),
        cashflow=getattr(sliced, "cashflow_data", None),
        income=getattr(sliced, "income_data", None),
        weekly_data=getattr(sliced, "weekly_data", None),
        monthly_data=getattr(sliced, "monthly_data", None),
    )
    ctx = ScreenContext(market_data=md, idx=sliced.iter_start_idx)
    print(f"ctx idx={ctx.current_idx} date={ctx.current_date}")

    all_syms = list(sliced.stock_data.keys())
    print(f"all syms: {len(all_syms)}")

    # 模拟 dividend.years filter
    dyears_pool = filter_by_dividend_years(ctx, all_syms, min_years=5)
    print(f"after dividend.years (≥5): {len(dyears_pool)}")

    stats = {
        "total": 0,
        "fin_none": 0,
        "np_none": 0,
        "eps_none": 0,
        "eps_zero_or_neg": 0,
        "share_derived": 0,
        "close_none": 0,
        "payout_none": 0,
        "r_computed": 0,
        "r_above_threshold": 0,
        "r_petTM_computed": 0,
        "r_petTM_above_threshold": 0,
    }
    samples = []
    r_values_derived = []
    r_values_petTM = []

    for sym in dyears_pool:
        stats["total"] += 1
        fin = ctx.get_financial_annual(sym)
        if not fin:
            stats["fin_none"] += 1
            continue
        np_value = fin.get("PARENTNETPROFIT")
        if np_value is None:
            inc_hist = ctx.get_income_annual_history(sym, 1)
            if inc_hist:
                np_value = inc_hist[0].get("PARENT_NETPROFIT")
        try:
            np_value = float(np_value) if np_value is not None else None
        except Exception:
            np_value = None
        if np_value is None or np_value <= 0:
            stats["np_none"] += 1
            continue

        # try inferred TOTAL_SHARE = NP / EPS
        eps = fin.get("BASIC_EPS")
        if eps is None or (isinstance(eps, float) and eps != eps):  # NaN
            inc_hist = ctx.get_income_annual_history(sym, 1)
            if inc_hist:
                eps = inc_hist[0].get("BASIC_EPS")
        try:
            eps = float(eps) if eps is not None else None
        except Exception:
            eps = None
        if eps is None:
            stats["eps_none"] += 1
            continue
        if eps <= 0:
            stats["eps_zero_or_neg"] += 1
            continue
        total_share = np_value / eps
        stats["share_derived"] += 1

        price = ctx.get_price(sym)
        close = price.get("close") if isinstance(price, dict) else None
        try:
            close = float(close) if close is not None else None
        except Exception:
            close = None
        if close is None or close <= 0:
            stats["close_none"] += 1
            continue

        payout = conservative.compute_payout_ratio_3y(ctx, sym)
        if payout is None:
            stats["payout_none"] += 1
            continue

        market_cap = close * total_share
        r_derived = (np_value * payout) / market_cap * 100.0
        stats["r_computed"] += 1
        r_values_derived.append(r_derived)
        if r_derived >= 5.2:
            stats["r_above_threshold"] += 1

        # cross-check with peTTM
        pe = price.get("peTTM") if isinstance(price, dict) else None
        try:
            pe = float(pe) if pe is not None else None
        except Exception:
            pe = None
        r_pe = None
        if pe and pe > 0:
            r_pe = payout * 100.0 / pe
            stats["r_petTM_computed"] += 1
            r_values_petTM.append(r_pe)
            if r_pe >= 5.2:
                stats["r_petTM_above_threshold"] += 1

        if len(samples) < 15:
            samples.append(
                (
                    sym,
                    np_value,
                    eps,
                    total_share,
                    close,
                    market_cap,
                    payout,
                    r_derived,
                    pe,
                    r_pe,
                )
            )

    print("\n=== stats ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    print("\n=== sample 15 ===")
    print(
        f"{'sym':<10} {'NP':<14} {'EPS':<8} {'share':<14} {'close':<8} {'mcap':<14} {'payout':<7} {'R_d':<8} {'peTTM':<7} {'R_pe':<7}"
    )
    for s in samples:
        sym, np_, eps, ts, c, mc, p, rd, pe, rp = s

        def fmt(v, w=10):
            if v is None:
                return "None".ljust(w)
            if isinstance(v, float):
                if abs(v) >= 1e8:
                    return f"{v:.3e}".ljust(w)
                return f"{v:.4f}".ljust(w)
            return str(v).ljust(w)

        print(
            f"{sym:<10} {fmt(np_, 14)} {fmt(eps, 8)} {fmt(ts, 14)} {fmt(c, 8)} {fmt(mc, 14)} {fmt(p, 7)} {fmt(rd, 8)} {fmt(pe, 7)} {fmt(rp, 7)}"
        )

    if r_values_derived:
        rs = sorted(r_values_derived, reverse=True)
        print(
            f"\nR_derived dist: max={rs[0]:.2f} p90={rs[len(rs) // 10]:.2f} median={rs[len(rs) // 2]:.2f} min={rs[-1]:.2f}"
        )
    if r_values_petTM:
        rs = sorted(r_values_petTM, reverse=True)
        print(
            f"R_peTTM   dist: max={rs[0]:.2f} p90={rs[len(rs) // 10]:.2f} median={rs[len(rs) // 2]:.2f} min={rs[-1]:.2f}"
        )


if __name__ == "__main__":
    main()
