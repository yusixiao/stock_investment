from apscheduler.schedulers.background import BackgroundScheduler
from config import SCHEDULER_HOUR, SCHEDULER_MINUTE

scheduler = BackgroundScheduler()


def _snapshot_job():
    """每日收盘快照:从 DuckDB 取 A 股最新收盘价 → 持仓估值。"""
    from services.duckdb_store import get_store
    from services.portfolio.db import get_connection, init_db
    from services.portfolio.manager import PortfolioManager

    store = get_store()
    # 单条 SQL 取每只 A 股的最新 (date, close)
    df = store.query(
        """
        SELECT _symbol, date, close
        FROM v_a_daily
        QUALIFY row_number() OVER (PARTITION BY _symbol ORDER BY date DESC) = 1
        """
    )
    if df.empty:
        return

    current_prices = {row["_symbol"]: float(row["close"]) for _, row in df.iterrows()}
    latest_date = str(df["date"].max())

    conn = get_connection()
    init_db(conn)
    mgr = PortfolioManager(conn)
    mgr.take_all_snapshots(latest_date, current_prices)
    conn.close()


def _market_update_job():
    """每日增量更新三市场 K线数据;完成后失效 data_cache 并触发后台重建,
    让回测/雷达页 6:30 之后立刻能用最新数据(含预算指标)。"""
    import logging

    logger = logging.getLogger(__name__)
    logger.info("Scheduled market update started")
    try:
        from services.market_updater import update_all_markets

        update_all_markets(parallel=True)
    except Exception as e:
        logger.error(f"Scheduled market update failed: {e}")
        return

    # 数据更新完成 → 失效 data_cache 各市场 → 后台异步重建(含预算指标)
    try:
        from services.backtest import data_cache

        for market in data_cache.SUPPORTED_MARKETS:
            data_cache.invalidate(market)
            data_cache.load_market_async(market)
        logger.info("data_cache invalidated + async rebuild kicked off")
    except Exception as e:
        logger.error(f"data_cache rebuild kickoff failed: {e}")


def _backup_job():
    """每周备份 data/market/ 到百度网盘"""
    import logging
    import subprocess
    from pathlib import Path

    logger = logging.getLogger(__name__)
    logger.info("Scheduled backup started")
    script = Path(__file__).resolve().parent.parent / "scripts" / "backup_to_baidu.py"
    try:
        result = subprocess.run(
            ["python", str(script)],
            capture_output=True,
            text=True,
            timeout=7200,
        )
        if result.returncode == 0:
            logger.info("Scheduled backup completed")
        else:
            logger.error(f"Backup failed: {result.stderr[-500:]}")
    except Exception as e:
        logger.error(f"Backup exception: {e}")


def start_scheduler():
    # misfire_grace_time=3600: 进程在计划时间后 1 小时内启动仍补跑,避免错过定时任务
    scheduler.add_job(
        _market_update_job,
        "cron",
        day_of_week="mon-fri",
        hour=6,
        minute=0,
        id="daily_market_update",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _snapshot_job,
        "cron",
        day_of_week="mon-fri",
        hour=SCHEDULER_HOUR,
        minute=SCHEDULER_MINUTE + 10,
        id="daily_snapshot",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _backup_job,
        "cron",
        day_of_week="sun",
        hour=3,
        minute=0,
        id="weekly_backup",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()


def shutdown_scheduler():
    scheduler.shutdown(wait=False)
