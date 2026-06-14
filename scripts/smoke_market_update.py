"""
轻量 smoke test: 跑少量股票的增量更新,
验证新的限流检测 + 节流 + 错误统计是否生效。

用法: python scripts/smoke_market_update.py [A|HK|US] [LIMIT]
"""

import sys
import logging
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from services.market_data.updaters import market_updater
from services.market_data.updaters.market_updater import _update_market_kline, _get_repo

MARKET = sys.argv[1] if len(sys.argv) > 1 else "US"
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 20

# 用一个包装 repo:list_codes 只返回前 LIMIT 个,其他方法透传
_real_get_repo = market_updater._get_repo


class _LimitedRepo:
    def __init__(self, inner, limit):
        self._inner = inner
        self._limit = limit

    def list_codes(self):
        return self._inner.list_codes()[: self._limit]

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _patched_get_repo(market):
    return _LimitedRepo(_real_get_repo(market), LIMIT)


market_updater._get_repo = _patched_get_repo

print(f"=== Smoke test: {MARKET}, limit={LIMIT} ===")
print(f"Symbols: {_patched_get_repo(MARKET).list_codes()}")

result = _update_market_kline(MARKET)
print("\n=== RESULT ===")
print(f"updated={result.updated} skipped={result.skipped} failed={result.failed}")
print(f"elapsed={result.elapsed_sec}s")
if result.errors:
    print(f"errors ({len(result.errors)}):")
    for e in result.errors[:10]:
        print(f"  - {e}")
