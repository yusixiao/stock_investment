from apscheduler.schedulers.background import BackgroundScheduler
from config import SCHEDULER_HOUR, SCHEDULER_MINUTE

scheduler = BackgroundScheduler()


def _snapshot_job():
    import pandas as pd
    from config import QFQ_KLINE_DIR
    from services.portfolio.db import get_connection, init_db
    from services.portfolio.manager import PortfolioManager

    current_prices = {}
    latest_date = ""
    for filepath in QFQ_KLINE_DIR.glob("*.parquet"):
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


def start_scheduler():
    from routers.data_update import run_update_task
    scheduler.add_job(
        run_update_task,
        "cron",
        args=["scheduled"],
        day_of_week="mon-fri",
        hour=SCHEDULER_HOUR,
        minute=SCHEDULER_MINUTE,
        id="daily_update",
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
    scheduler.start()


def shutdown_scheduler():
    scheduler.shutdown(wait=False)
