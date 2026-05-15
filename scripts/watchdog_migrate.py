"""
Watchdog: 监控三个数据迁移任务（美股K线、美股财务、港股indicator），卡死/崩溃自动重启

启动: caffeinate -s python3 scripts/watchdog_migrate.py &
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
PYTHON = sys.executable
WATCHDOG_LOG = PROJECT_ROOT / "data" / "logs" / "watchdog_migrate.log"

CHECK_INTERVAL = 60
STALL_TIMEOUT = 300
MAX_IDLE_CHECKS = 3

WATCHDOG_LOG.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(WATCHDOG_LOG),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("watchdog_migrate")

TASKS = [
    {
        "name": "美股K线",
        "script": "scripts/migrate_kline_us.py",
        "log": "data/logs/migrate_kline_us.log",
        "pgrep_pattern": "migrate_kline_us.py",
        "offset_flag": "--offset",
    },
    {
        "name": "美股财务",
        "script": "scripts/migrate_financial_us.py",
        "log": "data/logs/migrate_financial_us.log",
        "pgrep_pattern": "migrate_financial_us.py",
        "offset_flag": "--offset",
    },
    {
        "name": "港股indicator",
        "script": "scripts/fix_hk_indicator.py",
        "log": "data/logs/fix_hk_indicator.log",
        "pgrep_pattern": "fix_hk_indicator.py",
        "offset_flag": None,
    },
]


def find_pid(pattern: str) -> int | None:
    try:
        out = subprocess.check_output(["pgrep", "-f", pattern], text=True).strip()
        pids = [int(p) for p in out.split("\n") if p]
        my_pid = os.getpid()
        pids = [p for p in pids if p != my_pid]
        return pids[0] if pids else None
    except subprocess.CalledProcessError:
        return None


def parse_progress(log_path: Path) -> tuple[int, int]:
    try:
        out = subprocess.check_output(["tail", "-30", str(log_path)], text=True)
        matches = re.findall(r"\[(\d+)/(\d+)\]", out)
        if matches:
            current, total = matches[-1]
            return int(current), int(total)
    except Exception:
        pass
    return 0, 0


def is_completed(log_path: Path) -> bool:
    try:
        out = subprocess.check_output(["tail", "-5", str(log_path)], text=True)
        return "完成" in out and re.search(r"总计=\d+", out) is not None
    except Exception:
        return False


def kill_process(pid: int):
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(3)
        try:
            os.kill(pid, 0)
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        logger.info(f"已终止进程 PID={pid}")
    except ProcessLookupError:
        pass


def restart_task(task: dict, offset: int) -> int:
    script = str(PROJECT_ROOT / task["script"])
    cmd = [PYTHON, script]
    if task["offset_flag"] and offset > 0:
        cmd.extend([task["offset_flag"], str(offset)])
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    logger.info(f"[{task['name']}] 已重启: offset={offset}, 新PID={proc.pid}")
    return proc.pid


def main():
    logger.info("Watchdog 启动 — 监控 3 个迁移任务")

    idle_counts = {t["name"]: 0 for t in TASKS}
    completed = {t["name"]: False for t in TASKS}

    while True:
        time.sleep(CHECK_INTERVAL)

        all_done = True

        for task in TASKS:
            name = task["name"]

            if completed[name]:
                continue

            log_path = PROJECT_ROOT / task["log"]

            if not log_path.exists():
                logger.warning(f"[{name}] 日志不存在，跳过")
                all_done = False
                continue

            if is_completed(log_path):
                if not completed[name]:
                    current, total = parse_progress(log_path)
                    logger.info(f"[{name}] 已完成 [{current}/{total}]")
                    completed[name] = True
                continue

            all_done = False
            mtime = log_path.stat().st_mtime
            stale_seconds = time.time() - mtime
            pid = find_pid(task["pgrep_pattern"])

            if pid is None:
                idle_counts[name] += 1
                if idle_counts[name] >= MAX_IDLE_CHECKS:
                    current, total = parse_progress(log_path)
                    if current >= total and total > 0:
                        logger.info(f"[{name}] 已完成 [{current}/{total}]")
                        completed[name] = True
                    else:
                        logger.warning(
                            f"[{name}] 进程消失未完成 [{current}/{total}]，重启"
                        )
                        restart_task(task, current)
                        idle_counts[name] = 0
                else:
                    logger.info(
                        f"[{name}] 进程不存在 (idle={idle_counts[name]}/{MAX_IDLE_CHECKS})"
                    )
            else:
                idle_counts[name] = 0
                if stale_seconds > STALL_TIMEOUT:
                    current, total = parse_progress(log_path)
                    logger.warning(
                        f"[{name}] 卡死 {stale_seconds:.0f}s [{current}/{total}]，重启"
                    )
                    kill_process(pid)
                    time.sleep(2)
                    restart_task(task, current)
                else:
                    current, total = parse_progress(log_path)
                    pct = current / total * 100 if total > 0 else 0
                    if current > 0 and current % 200 < 2:
                        logger.info(
                            f"[{name}] 正常 [{current}/{total}] {pct:.1f}% PID={pid}"
                        )

        if all_done:
            break

    logger.info("所有任务已完成，Watchdog 退出")


if __name__ == "__main__":
    main()
