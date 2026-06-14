"""诊断 HK R 计算 1172→0 全军覆没的根因。

抽 10 只港股(蓝筹优先),逐变量打印 compute_r 的输入:
  fin = ctx.get_financial_annual(sym)
  PARENTNETPROFIT / TOTAL_SHARE
  income[0].PARENT_NETPROFIT (fallback)
  payout_3y
  price.close

定位是 财务表空 / NP 空 / share 空 / payout 空 / price 空 哪一步。
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

START = "2017-01-01"
END = "2026-05-28"

# 蓝筹大票样本
SAMPLES = [
    "00001.HK",  # 长江和记
    "00005.HK",  # 汇丰
    "00700.HK",  # 腾讯
    "00939.HK",  # 建行
    "01299.HK",  # 友邦
    "00388.HK",  # 港交所
    "02318.HK",  # 平安
    "00027.HK",  # 银娱
    "00011.HK",  # 恒生
    "00016.HK",  # 新地
]


def main():
    print("=== loading HK bundle ===")
    bundle = data_cache.get_market("HK")
    if bundle is None:
        bundle = data_cache._load_market_blocking("HK")
    print(f"HK loaded: {len(bundle.stock_data)} stocks")

    sliced = data_cache.slice_bundle(bundle, None, START, END)
    print(
        f"sliced: {len(sliced.stock_data)} stocks, iter [{sliced.iter_start_idx}, {sliced.iter_end_idx}]"
    )

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

    print(f"\n=== diagnostic at bar idx={sliced.iter_start_idx} ===")
    print(
        f"{'symbol':<10} {'fin':<5} {'NP':<15} {'NP_inc':<15} {'TOTAL_SHARE':<18} {'payout':<8} {'close':<10} {'r':<10}"
    )
    print("-" * 110)

    for sym in SAMPLES:
        fin = ctx.get_financial_annual(sym)
        fin_status = "yes" if fin else "NO"
        np_v = None
        ts_v = None
        if fin:
            np_v = fin.get("PARENTNETPROFIT")
            ts_v = fin.get("TOTAL_SHARE")

        # income fallback
        np_inc = None
        try:
            inc_hist = ctx.get_income_annual_history(sym, 1)
            if inc_hist:
                np_inc = inc_hist[0].get("PARENT_NETPROFIT")
        except Exception as ex:
            np_inc = f"ERR:{ex.__class__.__name__}"

        try:
            payout = conservative.compute_payout_ratio_3y(ctx, sym)
        except Exception as ex:
            payout = f"ERR:{ex.__class__.__name__}"

        try:
            price = ctx.get_price(sym)
            close = price.get("close") if isinstance(price, dict) else None
        except Exception as ex:
            close = f"ERR:{ex.__class__.__name__}"

        try:
            r = conservative.compute_r(ctx, sym)
        except Exception as ex:
            r = f"ERR:{ex.__class__.__name__}"

        def fmt(v, w):
            if v is None:
                return "None".ljust(w)
            if isinstance(v, float):
                return f"{v:.4g}".ljust(w)
            return str(v)[: w - 1].ljust(w)

        print(
            f"{sym:<10} {fin_status:<5} {fmt(np_v, 15)} {fmt(np_inc, 15)} {fmt(ts_v, 18)} {fmt(payout, 8)} {fmt(close, 10)} {fmt(r, 10)}"
        )

    # Also dump fin keys for first sample
    print(f"\n=== {SAMPLES[0]} financial_annual keys ===")
    fin = ctx.get_financial_annual(SAMPLES[0])
    if fin:
        for k, v in fin.items():
            sv = str(v)[:50]
            print(f"  {k}: {sv}")
    else:
        print("  fin is None")

    print(f"\n=== {SAMPLES[0]} income_annual_history(3) ===")
    try:
        hist = ctx.get_income_annual_history(SAMPLES[0], 3)
        print(f"  rows: {len(hist) if hist else 0}")
        if hist:
            for k, v in hist[0].items():
                sv = str(v)[:50]
                print(f"  [0] {k}: {sv}")
    except Exception as ex:
        print(f"  ERR: {ex}")


if __name__ == "__main__":
    main()
