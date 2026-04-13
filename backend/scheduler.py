from apscheduler.schedulers.background import BackgroundScheduler
from config import SCHEDULER_HOUR, SCHEDULER_MINUTE

scheduler = BackgroundScheduler()


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
    scheduler.start()


def shutdown_scheduler():
    scheduler.shutdown(wait=False)
