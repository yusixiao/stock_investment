from apscheduler.schedulers.background import BackgroundScheduler
from config import SCHEDULER_HOUR, SCHEDULER_MINUTE

scheduler = BackgroundScheduler()


def _snapshot_job():
    import pandas as pd
    from config import RAW_KLINE_DIR
    from services.portfolio.db import get_connection, init_db
    from services.portfolio.manager import PortfolioManager

    current_prices = {}
    latest_date = ""
    for filepath in RAW_KLINE_DIR.glob("*.parquet"):
        symbol = filepath.stem
        df = pd.read_parquet(filepath, columns=["date", "close"])
        if not df.empty:
            current_prices[symbol] = float(df.iloc[0]["close"])
            d = df.iloc[0]["date"]
            if d > latest_date:
                latest_date = d

    if not latest_date:
        return

    conn = get_connection()
    init_db(conn)
    mgr = PortfolioManager(conn)
    mgr.take_all_snapshots(latest_date, current_prices)
    conn.close()


def _market_update_job():
    """每日增量更新三市场 K线数据"""
    import logging

    logger = logging.getLogger(__name__)
    logger.info("Scheduled market update started")
    try:
        from services.market_updater import update_all_markets

        update_all_markets(parallel=True)
    except Exception as e:
        logger.error(f"Scheduled market update failed: {e}")


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
    scheduler.add_job(
        _market_update_job,
        "cron",
        day_of_week="mon-fri",
        hour=6,
        minute=0,
        id="daily_market_update",
        replace_existing=True,
    )
    scheduler.add_job(
        _snapshot_job,
        "cron",
        day_of_week="mon-fri",
        hour=SCHEDULER_HOUR,
        minute=SCHEDULER_MINUTE + 10,
        id="daily_snapshot",
        replace_existing=True,
    )
    scheduler.add_job(
        _backup_job,
        "cron",
        day_of_week="sun",
        hour=3,
        minute=0,
        id="weekly_backup",
        replace_existing=True,
    )
    scheduler.start()


def shutdown_scheduler():
    scheduler.shutdown(wait=False)
