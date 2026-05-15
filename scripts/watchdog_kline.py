"""
Watchdog: 监控 K线迁移进程，卡死自动重启

启动: caffeinate -s python3 scripts/watchdog_kline.py &
"""

import logging
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = PROJECT_ROOT / "data" / "logs" / "migrate_kline.log"
WATCHDOG_LOG = PROJECT_ROOT / "data" / "logs" / "watchdog_kline.log"
MIGRATE_SCRIPT = PROJECT_ROOT / "scripts" / "migrate_kline_batch.py"
PYTHON = sys.executable

CHECK_INTERVAL = 60
STALL_TIMEOUT = 300
MAX_IDLE_CHECKS = 3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(WATCHDOG_LOG),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("watchdog")


def find_migrate_pid() -> int | None:
    """通过 ps 查找 migrate_kline_batch.py 进程 PID"""
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "migrate_kline_batch.py"], text=True
        ).strip()
        pids = [int(p) for p in out.split("\n") if p]
        my_pid = os.getpid()
        pids = [p for p in pids if p != my_pid]
        return pids[0] if pids else None
    except subprocess.CalledProcessError:
        return None


def parse_last_offset() -> tuple[int, int]:
    """从日志最后几行解析当前 offset 和 total，返回 (current, total)"""
    try:
        out = subprocess.check_output(["tail", "-20", str(LOG_FILE)], text=True)
        matches = re.findall(r"\[(\d+)/(\d+)\]", out)
        if matches:
            current, total = matches[-1]
            return int(current), int(total)
    except Exception:
        pass
    return 0, 0


def kill_process(pid: int):
    """终止进程"""
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(3)
        if find_migrate_pid() == pid:
            os.kill(pid, signal.SIGKILL)
        logger.info(f"已终止进程 PID={pid}")
    except ProcessLookupError:
        pass


def restart_migration(offset: int) -> int:
    """重启迁移脚本，返回新 PID"""
    cmd = [PYTHON, str(MIGRATE_SCRIPT), "--offset", str(offset)]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    logger.info(f"已重启迁移: offset={offset}, 新PID={proc.pid}")
    return proc.pid


def main():
    logger.info("Watchdog 启动")
    idle_count = 0

    while True:
        time.sleep(CHECK_INTERVAL)

        if not LOG_FILE.exists():
            logger.warning("日志文件不存在，等待...")
            continue

        mtime = LOG_FILE.stat().st_mtime
        stale_seconds = time.time() - mtime
        pid = find_migrate_pid()

        if pid is None:
            idle_count += 1
            logger.info(f"迁移进程不存在 (idle_count={idle_count}/{MAX_IDLE_CHECKS})")
            if idle_count >= MAX_IDLE_CHECKS:
                current, total = parse_last_offset()
                if current >= total and total > 0:
                    logger.info(f"迁移已完成 [{current}/{total}]，watchdog 退出")
                else:
                    logger.warning(f"进程消失且未完成 [{current}/{total}]，尝试重启")
                    restart_migration(current)
                    idle_count = 0
                    continue
                break
            continue

        idle_count = 0

        if stale_seconds > STALL_TIMEOUT:
            current, total = parse_last_offset()
            logger.warning(
                f"日志 {stale_seconds:.0f}s 无更新，判定卡死 [{current}/{total}]"
            )
            kill_process(pid)
            time.sleep(2)
            restart_migration(current)
        else:
            current, total = parse_last_offset()
            if current > 0 and current % 100 < 2:
                logger.info(f"运行正常 [{current}/{total}], PID={pid}")

    logger.info("Watchdog 退出")


if __name__ == "__main__":
    main()
