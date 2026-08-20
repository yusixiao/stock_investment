"""运维脚本(2026-07-01):串行增量更新 HK / US 日线。

背景:07-01 定时/手动更新因 yfinance 被 Yahoo 限速失败,HK 缺 06-30、
US 缺 06-30~07-01。限速已解除后补数据。刻意串行(先 HK 后 US)而非
update_all_markets 的 3 线程并行,降低 Yahoo 瞬时请求密度以规避再次限速,
同时避开 backend.xxx 在子线程的 import 陷阱。
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
log = logging.getLogger("manual_update_hkus")

from services.market_data.updaters.market_updater import update_single_market

log.info("=== manual HK/US serial update start ===")
for mkt in ["HK", "US"]:
    log.info("--- %s begin ---", mkt)
    try:
        r = update_single_market(mkt)
        log.info(
            "--- %s done: updated=%s skipped=%s failed=%s elapsed=%ss ---",
            mkt, r.updated, r.skipped, r.failed, r.elapsed_sec,
        )
    except Exception as e:
        log.exception("--- %s CRASHED: %s ---", mkt, e)
log.info("=== manual HK/US serial update end ===")
