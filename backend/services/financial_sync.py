"""财务 4 表周期同步服务(2026-05-27)。

调度入口:每周日 02:00 拉全 A 股 EastMoney 利润表/资产负债表/现金流量表/财务指标,
通过 `FinancialRepository.append_*` 自动按 REPORT_DATE 去重(等价增量)。

设计原则:
- 个股失败不阻塞:try/except 包住每只股票,失败 code 收集到列表
- 失败列表落盘 `logs/financial_sync_<YYYYMMDD>.failed.txt`,便于 retry
- 全量拉 + append 去重(而非 max+跳过):捕获财报修正(restatement)
- throttle 0.15s:与历史 migrate 脚本一致,避免 EM 接口限速
"""

import logging
import time
from datetime import date
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

DEFAULT_THROTTLE = 0.15
PROGRESS_INTERVAL = 100


def sync_a_share_financial(
    adapter=None,
    repo=None,
    codes: Optional[List[str]] = None,
    throttle: float = DEFAULT_THROTTLE,
    log_dir: Optional[Path] = None,
) -> dict:
    """同步 A 股财务 4 表(可注入依赖,便于测试)。

    Args:
        adapter: 财务数据适配器,默认 EastMoneyAdapter()
        repo: FinancialRepository,默认 FINANCIAL_DIR
        codes: A 股代码列表,默认从 DuckDBStore.list_symbols("A")
        throttle: 每只股票之间 sleep 秒数(避免 EM 限速)
        log_dir: 失败列表写入目录,默认 logs/

    Returns:
        {"total": N, "success": N, "failed": N, "failed_codes": [...], "elapsed": seconds}
    """
    # 默认依赖延迟构造,避免单测引入重型依赖
    if adapter is None:
        from adapters.eastmoney_adapter import EastMoneyAdapter

        adapter = EastMoneyAdapter()
    if repo is None:
        from config import MARKET_DIR
        from repositories.financial_repo import FinancialRepository

        repo = FinancialRepository(MARKET_DIR / "A" / "financial")
    if codes is None:
        from services.duckdb_store import get_store

        codes = get_store().list_symbols("A")
    if log_dir is None:
        from config import DATA_DIR

        log_dir = DATA_DIR.parent / "logs"

    log_dir = Path(log_dir)
    total = len(codes)

    if total == 0:
        logger.info("financial_sync: codes 列表为空,跳过")
        return {
            "total": 0,
            "success": 0,
            "failed": 0,
            "failed_codes": [],
            "elapsed": 0.0,
        }

    log_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"financial_sync 开始:共 {total} 只 A 股")

    success = 0
    failed_codes: List[str] = []
    start = time.time()

    for i, code in enumerate(codes):
        if (i + 1) % PROGRESS_INTERVAL == 0:
            elapsed = time.time() - start
            speed = (i + 1) / elapsed * 3600 if elapsed > 0 else 0
            logger.info(
                f"financial_sync 进度 {i + 1}/{total} 成功={success} "
                f"失败={len(failed_codes)} | {speed:.0f} 只/小时"
            )

        try:
            income = adapter.fetch_income(code)
            balance = adapter.fetch_balance(code)
            cashflow = adapter.fetch_cashflow(code)
            indicator = adapter.fetch_indicator(code)

            # append 内部按 REPORT_DATE 去重,空列表跳过(避免无意义 IO)
            if income:
                repo.append_income(code, income)
            if balance:
                repo.append_balance(code, balance)
            if cashflow:
                repo.append_cashflow(code, cashflow)
            if indicator:
                repo.append_indicator(code, indicator)

            success += 1
        except Exception as e:
            failed_codes.append(code)
            # 失败前 20 条详细日志,后续只计数
            if len(failed_codes) <= 20:
                logger.warning(f"financial_sync {code} 失败: {e}")

        if throttle > 0:
            time.sleep(throttle)

    elapsed = time.time() - start

    # 失败列表落盘(便于人工 retry)
    if failed_codes:
        today = date.today().strftime("%Y%m%d")
        failed_file = log_dir / f"financial_sync_{today}.failed.txt"
        failed_file.write_text("\n".join(failed_codes) + "\n", encoding="utf-8")
        logger.warning(
            f"financial_sync 完成:成功={success} 失败={len(failed_codes)} "
            f"失败列表 → {failed_file}"
        )
    else:
        logger.info(
            f"financial_sync 完成:成功={success}/{total} 耗时={elapsed / 60:.1f} 分钟"
        )

    return {
        "total": total,
        "success": success,
        "failed": len(failed_codes),
        "failed_codes": failed_codes,
        "elapsed": elapsed,
    }
