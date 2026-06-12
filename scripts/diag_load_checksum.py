"""跨进程对比:load HK bundle 后,对各类数据算 checksum,定位哪块非确定。"""
import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from services.backtest import data_cache  # noqa: E402
from strategies.utils import growth_hk, hk_industry  # noqa: E402

growth_hk.reset_cache()
hk_industry.reset_cache()
bundle = data_cache.get_market("HK") or data_cache._load_market_blocking("HK")


def ck(d: dict) -> str:
    """对 {sym: df} 按 sym 排序后拼接所有数值列求 md5。"""
    h = hashlib.md5()
    for sym in sorted(d.keys()):
        df = d[sym]
        if df is None or len(df) == 0:
            h.update(sym.encode())
            continue
        num = df.select_dtypes(include=[np.number]).to_numpy()
        h.update(sym.encode())
        h.update(np.ascontiguousarray(num).tobytes())
    return h.hexdigest()[:12]


for name in ["stock_data", "valuation_data", "income_data", "financial_data",
             "balance_data", "cashflow_data", "weekly_data", "monthly_data"]:
    d = getattr(bundle, name, None)
    if isinstance(d, dict):
        print(f"{name:16s} n={len(d):5d} ck={ck(d)}", flush=True)

# growth_hk 内部缓存(income+indicator join 结果)
growth_hk._load()
gk = growth_hk._HK_LOOKUP
hg = hashlib.md5()
for sym in sorted(gk.keys()):
    hg.update(sym.encode())
    hg.update(np.ascontiguousarray(
        gk[sym].select_dtypes(include=[np.number]).to_numpy()).tobytes())
print(f"growth_hk_lookup n={len(gk):5d} ck={hg.hexdigest()[:12]}", flush=True)
