"""重算 HK 复权因子(全量覆盖)。

根因修复后(yfinance_adapter.fetch_adjust_factor 同除权日事件连乘合并),
重新从 yfinance 拉取 divs/splits 并重算所有 HK 标的的 foreAdjustFactor,
全量覆盖写回 data/market/HK/adjust_factor/*.parquet。

长任务:必须 nohup 后台执行。
    nohup python3 scripts/regen_hk_adjust_factor.py > logs/regen_hk_af.log 2>&1 &
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from backend.services.market_data.updaters.market_updater import _get_adapter, _get_repo  # noqa: E402


def main() -> None:
    market = "HK"
    adapter = _get_adapter(market)
    repo = _get_repo(market)

    codes = repo.list_codes()
    total = len(codes)
    print(f"[regen_hk_af] start: {total} HK codes", flush=True)

    updated = 0
    empty = 0
    failed = 0
    t0 = time.time()

    for i, code in enumerate(codes, 1):
        try:
            records = adapter.fetch_adjust_factor(code)
            if records:
                repo.write_adjust_factor(code, records)
                updated += 1
            else:
                empty += 1
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"[regen_hk_af] FAIL {code}: {e}", flush=True)

        if i % 100 == 0 or i == total:
            el = time.time() - t0
            print(
                f"[regen_hk_af] {i}/{total} "
                f"updated={updated} empty={empty} failed={failed} "
                f"elapsed={el:.0f}s",
                flush=True,
            )

    el = time.time() - t0
    print(
        f"[regen_hk_af] DONE updated={updated} empty={empty} "
        f"failed={failed} total={total} elapsed={el:.0f}s",
        flush=True,
    )


if __name__ == "__main__":
    main()
