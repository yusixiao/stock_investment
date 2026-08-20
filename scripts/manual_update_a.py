"""运维脚本(2026-07-02):增量更新 A 股日线(baostock)。

背景:07-01 A 股更新中断,仅入库 177/5524 只。baostock 数据源与 HK/US 的
yfinance 完全独立(不共享 Yahoo 限速),故可与正在跑的 HK/US 更新并行,互不
冲突。baostock 在单进程内 login 一次复用 session、单线程串行拉取。
"""
import sys
import os
import logging

R = "/Users/11182300/PycharmProjects/stock_investment"
sys.path.insert(0, os.path.join(R, "backend"))
sys.path.insert(0, R)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("manual_update_a")

from services.market_data.updaters.market_updater import update_single_market

log.info("=== manual A-share update start (baostock) ===")
try:
    r = update_single_market("A")
    log.info(
        "--- A done: updated=%s skipped=%s failed=%s elapsed=%ss ---",
        r.updated, r.skipped, r.failed, r.elapsed_sec,
    )
except Exception as e:
    log.exception("--- A CRASHED: %s ---", e)
log.info("=== manual A-share update end ===")
