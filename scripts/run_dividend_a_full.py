"""一次性脚本:A 股全量 dividend 抓取(BaoStock,~16 小时)。

用法:
    nohup python scripts/run_dividend_a_full.py \
        > data/logs/dividend_a_full_$(date +%Y%m%d_%H%M%S).log 2>&1 &

进度查看:
    tail -f data/logs/dividend_a_full_*.log
    ls data/market/A/dividend/ | wc -l   # 当前已落地股票数
"""

import sys
import time
from pathlib import Path

# 把项目根加入 sys.path(后端没有 __init__.py)
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "backend"))

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from services.dividend_market_updater import update_a_dividend


def main():
    t0 = time.time()
    logging.info("=== A 股 dividend 全量抓取开始(incremental=True)===")
    result = update_a_dividend(incremental=True, max_workers=1)
    elapsed = time.time() - t0
    logging.info(
        f"=== 完成 === updated={result.updated} skipped={result.skipped} "
        f"failed={result.failed} elapsed={elapsed / 3600:.1f}h"
    )
    if result.errors:
        logging.warning(f"前 {len(result.errors)} 个错误样本:")
        for e in result.errors[:20]:
            logging.warning(f"  {e}")


if __name__ == "__main__":
    main()
