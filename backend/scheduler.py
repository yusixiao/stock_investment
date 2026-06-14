from apscheduler.schedulers.background import BackgroundScheduler
from config import SCHEDULER_HOUR, SCHEDULER_MINUTE

scheduler = BackgroundScheduler()


def _snapshot_job():
    """每日收盘快照:从 DuckDB 取 A 股最新收盘价 → 持仓估值。"""
    from services.market_data.duckdb_store import get_store
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
        from services.market_data.updaters.market_updater import update_all_markets

        update_all_markets(parallel=True)
    except Exception as e:
        logger.error(f"Scheduled market update failed: {e}")
        return

    # 刷新流通股快照(依赖 v_a_indicator 财务指标视图,需在市场更新之后)
    # data_pack §2 市值/流通市值 + EV/EBITDA 等衍生指标依赖此 parquet
    try:
        from services.market_data.updaters.circulating_shares import update_circulating_shares

        result = update_circulating_shares()
        logger.info(f"circulating_shares refreshed: {result}")
    except Exception as e:
        logger.error(f"circulating_shares refresh failed: {e}")

    # 数据更新完成 → 失效 data_cache 各市场 → 后台异步重建(含预算指标)
    try:
        from services.backtest import data_cache

        for market in data_cache.SUPPORTED_MARKETS:
            data_cache.invalidate(market)
            data_cache.load_market_async(market)
        logger.info("data_cache invalidated + async rebuild kicked off")
    except Exception as e:
        logger.error(f"data_cache rebuild kickoff failed: {e}")


def _financial_sync_job():
    """每周日 02:00 同步全 A 股财务 4 表(EastMoney → parquet,append 去重)。

    选 02:00 是为了在 03:00 备份任务前完成。EM 接口对全市场 ~5800 只股票
    在 0.15s throttle 下约 30-60 分钟跑完。失败个股自动落 logs/<date>.failed.txt。
    """
    import logging

    logger = logging.getLogger(__name__)
    logger.info("Scheduled financial sync started")
    try:
        from services.market_data.updaters.financial_sync import sync_a_share_financial

        result = sync_a_share_financial()
        logger.info(
            f"financial_sync done: success={result['success']}/{result['total']} "
            f"failed={result['failed']} elapsed={result['elapsed'] / 60:.1f}min"
        )
    except Exception as e:
        logger.error(f"Scheduled financial sync failed: {e}")


def _hk_connect_refresh_job():
    """每周一 06:30 刷新港股通成分股快照(EastMoney push2)。
    放在 06:00 市场更新之后,不强依赖。"""
    import logging

    logger = logging.getLogger(__name__)
    logger.info("Scheduled hk_connect refresh started")
    try:
        from services.market_data.updaters.hk_connect_updater import fetch_and_save_hk_connect

        result = fetch_and_save_hk_connect()
        logger.info(f"hk_connect refresh done: {result}")
    except Exception as e:
        logger.error(f"hk_connect refresh failed: {e}")


def _hk_industry_refresh_job():
    """每周一 07:00 刷新港股 sector/industry(yfinance)。
    放在 06:30 hk_connect 名单刷新之后,确保拿到最新成分股。"""
    import logging

    logger = logging.getLogger(__name__)
    logger.info("Scheduled hk_industry refresh started")
    try:
        from services.market_data.updaters.hk_industry_updater import fetch_and_save_hk_industry

        result = fetch_and_save_hk_industry()
        logger.info(f"hk_industry refresh done: {result}")
    except Exception as e:
        logger.error(f"hk_industry refresh failed: {e}")


def _index_update_job():
    """每日 06:15 增量更新指数日线(HSI / 恒生科技 / 沪深300)。
    放在 06:00 市场更新之后,与个股数据同源刷新。"""
    import logging

    logger = logging.getLogger(__name__)
    logger.info("Scheduled index update started")
    try:
        from services.market_data.updaters.index_updater import update_all_indices

        results = update_all_indices(full=False)
        logger.info(f"index update done: {results}")
    except Exception as e:
        logger.error(f"index update failed: {e}")


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
        _financial_sync_job,
        "cron",
        day_of_week="sun",
        hour=2,
        minute=0,
        id="weekly_financial_sync",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _index_update_job,
        "cron",
        day_of_week="mon-fri",
        hour=6,
        minute=15,
        id="daily_index_update",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _hk_connect_refresh_job,
        "cron",
        day_of_week="mon",
        hour=6,
        minute=30,
        id="weekly_hk_connect_refresh",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _hk_industry_refresh_job,
        "cron",
        day_of_week="mon",
        hour=7,
        minute=0,
        id="weekly_hk_industry_refresh",
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
