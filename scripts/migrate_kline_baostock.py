"""
Phase 5 迁移脚本 — BaoStock K线数据获取 + 与本地 AKShare 数据对比验证

用法:
    # 第一步：对比验证（随机50只股票，对比相同字段）
    python scripts/migrate_kline_baostock.py --verify

    # 第二步：全量迁移（获取全市场K线到新目录）
    python scripts/migrate_kline_baostock.py --migrate

    # 只迁移指定股票
    python scripts/migrate_kline_baostock.py --migrate --codes 000001.SZ 600000.SH
"""

import argparse
import logging
import random
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.adapters.baostock_adapter import BaoStockAdapter
from backend.repositories.market_repo import MarketRepository
from backend.config import RAW_KLINE_DIR, DATA_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

NEW_DAILY_DIR = DATA_DIR / "market" / "A" / "daily"
NEW_ADJUST_FACTOR_DIR = DATA_DIR / "market" / "A" / "adjust_factor"

COMPARE_FIELDS = ["open", "high", "low", "close", "volume", "amount"]
TOLERANCE = 0.0001  # 精确匹配（允许浮点精度误差）


def get_all_stock_codes() -> list:
    """从本地 raw 目录获取所有股票代码"""
    files = sorted(RAW_KLINE_DIR.glob("*.parquet"))
    codes = [f.stem for f in files]
    return [c for c in codes if c != ""]


def verify_comparison(n_samples: int = 50):
    """对比验证：随机选择N只股票，对比BaoStock与本地AKShare的K线数据"""
    all_codes = get_all_stock_codes()
    non_empty = []
    for code in all_codes:
        df = pd.read_parquet(RAW_KLINE_DIR / f"{code}.parquet")
        if len(df) > 100:
            non_empty.append(code)

    if len(non_empty) < n_samples:
        sample_codes = non_empty
    else:
        sample_codes = random.sample(non_empty, n_samples)

    logger.info(f"开始对比验证，共 {len(sample_codes)} 只股票")

    adapter = BaoStockAdapter()
    results = []

    for i, code in enumerate(sample_codes):
        logger.info(f"[{i + 1}/{len(sample_codes)}] 对比 {code}")

        local_df = pd.read_parquet(RAW_KLINE_DIR / f"{code}.parquet")
        local_df = local_df.sort_values("date").reset_index(drop=True)

        start_date = (
            local_df["date"].iloc[-30]
            if len(local_df) > 30
            else local_df["date"].iloc[0]
        )
        end_date = local_df["date"].iloc[-1]

        try:
            bs_records = adapter.fetch_daily_kline(code, start_date, end_date)
        except Exception as e:
            logger.warning(f"  获取 {code} 失败: {e}")
            results.append({"code": code, "status": "error", "detail": str(e)})
            continue

        if not bs_records:
            logger.warning(f"  {code} BaoStock 返回空数据")
            results.append({"code": code, "status": "empty"})
            continue

        bs_df = pd.DataFrame([r.model_dump() for r in bs_records])
        bs_df = bs_df.sort_values("date").reset_index(drop=True)

        local_range = local_df[
            (local_df["date"] >= start_date) & (local_df["date"] <= end_date)
        ].reset_index(drop=True)

        merged = pd.merge(local_range, bs_df, on="date", suffixes=("_ak", "_bs"))

        if merged.empty:
            logger.warning(f"  {code} 无重叠日期")
            results.append({"code": code, "status": "no_overlap"})
            continue

        mismatches = []
        for field in COMPARE_FIELDS:
            ak_col = f"{field}_ak"
            bs_col = f"{field}_bs"
            if ak_col not in merged.columns or bs_col not in merged.columns:
                continue

            ak_vals = merged[ak_col].astype(float)
            bs_vals = merged[bs_col].astype(float)

            mask = (ak_vals != 0) & (bs_vals != 0)
            if mask.sum() == 0:
                continue

            diff_pct = ((ak_vals[mask] - bs_vals[mask]) / ak_vals[mask]).abs()
            max_diff = diff_pct.max()
            if max_diff > TOLERANCE:
                mismatches.append(f"{field}: max_diff={max_diff:.6f}")

        if mismatches:
            logger.warning(f"  {code} 存在差异: {mismatches}")
            results.append({"code": code, "status": "mismatch", "detail": mismatches})
        else:
            logger.info(f"  {code} 验证通过 ({len(merged)}行)")
            results.append({"code": code, "status": "ok", "rows": len(merged)})

        time.sleep(0.1)

    ok_count = sum(1 for r in results if r["status"] == "ok")
    fail_count = sum(1 for r in results if r["status"] == "mismatch")
    error_count = sum(
        1 for r in results if r["status"] in ("error", "empty", "no_overlap")
    )

    logger.info(f"\n===== 对比验证完成 =====")
    logger.info(f"通过: {ok_count}/{len(results)}")
    logger.info(f"差异: {fail_count}/{len(results)}")
    logger.info(f"异常: {error_count}/{len(results)}")

    if fail_count > 0:
        logger.warning("存在差异的股票:")
        for r in results:
            if r["status"] == "mismatch":
                logger.warning(f"  {r['code']}: {r['detail']}")

    return fail_count == 0


def migrate_kline(codes: list = None):
    """全量迁移：获取BaoStock K线数据写入新目录"""
    NEW_DAILY_DIR.mkdir(parents=True, exist_ok=True)
    NEW_ADJUST_FACTOR_DIR.mkdir(parents=True, exist_ok=True)

    if codes is None:
        codes = get_all_stock_codes()

    adapter = BaoStockAdapter()
    market_repo = MarketRepository(NEW_DAILY_DIR, NEW_ADJUST_FACTOR_DIR)

    success_count = 0
    fail_count = 0
    total = len(codes)

    for i, code in enumerate(codes):
        if (i + 1) % 100 == 0 or i == 0:
            logger.info(f"进度: {i + 1}/{total}")

        try:
            records = adapter.fetch_daily_kline(code, "1990-01-01", "2026-12-31")
            if records:
                market_repo.write_daily_kline(code, records)
                success_count += 1
            else:
                logger.debug(f"  {code} 无数据")
        except Exception as e:
            logger.error(f"  {code} 失败: {e}")
            fail_count += 1

        try:
            factors = adapter.fetch_adjust_factor(code)
            if factors:
                market_repo.write_adjust_factor(code, factors)
        except Exception as e:
            logger.debug(f"  {code} 复权因子失败: {e}")

        time.sleep(0.05)

    logger.info(f"\n===== 迁移完成 =====")
    logger.info(f"成功: {success_count}/{total}")
    logger.info(f"失败: {fail_count}/{total}")
    logger.info(f"数据目录: {NEW_DAILY_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BaoStock K线数据迁移")
    parser.add_argument(
        "--verify", action="store_true", help="对比验证模式（50只股票）"
    )
    parser.add_argument("--migrate", action="store_true", help="全量迁移模式")
    parser.add_argument("--codes", nargs="+", help="指定股票代码（仅迁移模式）")
    parser.add_argument("--samples", type=int, default=50, help="验证模式采样数量")
    args = parser.parse_args()

    if args.verify:
        passed = verify_comparison(n_samples=args.samples)
        sys.exit(0 if passed else 1)
    elif args.migrate:
        migrate_kline(codes=args.codes)
    else:
        parser.print_help()
