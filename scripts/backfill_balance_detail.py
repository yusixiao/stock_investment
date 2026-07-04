"""回填 A 股资产负债表明细科目(商誉/无形/归母权益/少数股东权益)。

背景(spike 2026-07-02):EastMoneyAdapter.fetch_balance 原用简况报表
RPT_DMSK_FN_BALANCE(57 列),缺明细科目 GOODWILL / INTANGIBLE_ASSET /
TOTAL_PARENT_EQUITY / MINORITY_EQUITY —— 这 4 列在 v_a_balance 100% NULL。
已改 fetch_balance 走 4 张类型明细报表(普通/银行/券商/保险:GBALANCE /
BBALANCE / SBALANCE / IBALANCE,均含明细科目),本脚本据此重抽全 A 股 balance 回填。

机制:复用已测的 sync_a_share_financial,注入「仅 balance」适配器代理
(income/cashflow/indicator 返 [] → sync 内判空跳过,不动这 3 表),只重抽 balance。
append_balance 去重策略「新覆盖旧」(base.py:56)→ 老 NULL 行被富化行覆盖,无需清库。

长任务(~5500 只):务必 nohup 后台。
用法:
  # 冒烟(指定几只,验证富化写盘):
  python scripts/backfill_balance_detail.py --codes 600519.SH,601398.SH,600030.SH
  # 全量(后台):
  nohup python scripts/backfill_balance_detail.py > logs/backfill_balance.log 2>&1 &
"""
import argparse
import logging
import sys
from pathlib import Path

ROOT = Path("/Users/11182300/PycharmProjects/stock_investment")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from adapters.eastmoney_adapter import EastMoneyAdapter  # noqa: E402
from services.market_data.updaters.financial_sync import (  # noqa: E402
    sync_a_share_financial,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("backfill_balance_detail")


class _BalanceOnlyAdapter:
    """仅代理 fetch_balance;其余 3 表返空(sync 内 if 判空跳过),
    使 sync_a_share_financial 只重抽 balance 表,不动 income/cashflow/indicator。"""

    def __init__(self, inner):
        self._inner = inner

    def fetch_income(self, code):
        return []

    def fetch_balance(self, code):
        return self._inner.fetch_balance(code)

    def fetch_cashflow(self, code):
        return []

    def fetch_indicator(self, code):
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", type=str, default="",
                    help="逗号分隔指定代码(冒烟用,优先于 --limit)")
    ap.add_argument("--limit", type=int, default=0,
                    help="仅处理前 N 只(冒烟用);0=全量")
    args = ap.parse_args()

    codes = None
    if args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    elif args.limit > 0:
        from services.market_data.duckdb_store import get_store

        codes = get_store().list_symbols("A")[: args.limit]

    scope = f"{len(codes)} 只(指定)" if codes else "全量 A 股"
    logger.info(f"backfill_balance_detail 启动:{scope}")

    adapter = _BalanceOnlyAdapter(EastMoneyAdapter())
    result = sync_a_share_financial(adapter=adapter, codes=codes)

    logger.info(
        f"backfill_balance_detail 完成: total={result['total']} "
        f"success={result['success']} failed={result['failed']} "
        f"elapsed={result['elapsed'] / 60:.1f}min"
    )
    if result["failed_codes"]:
        logger.warning(
            f"失败 {result['failed']} 只(前20): {result['failed_codes'][:20]}"
        )


if __name__ == "__main__":
    main()
