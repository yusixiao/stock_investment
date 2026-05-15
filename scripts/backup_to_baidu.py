"""
每周备份 data/market/ 到百度网盘。

打包为 stock_data.tar.gz，上传覆盖百度网盘上的同一个文件。
首次使用需要运行 `bypy info` 进行百度账号授权。

用法:
    python scripts/backup_to_baidu.py
"""

import logging
import subprocess
import sys
import tarfile
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_MARKET_DIR = BASE_DIR / "data" / "market"
BACKUP_FILE = BASE_DIR / "data" / "stock_data.tar.gz"
REMOTE_PATH = "/stock_investment_backup/stock_data.tar.gz"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def create_archive():
    """打包 data/market/ 为 tar.gz"""
    logger.info(f"Compressing {DATA_MARKET_DIR} -> {BACKUP_FILE}")
    t0 = time.time()

    with tarfile.open(BACKUP_FILE, "w:gz", compresslevel=6) as tar:
        tar.add(DATA_MARKET_DIR, arcname="market")

    size_mb = BACKUP_FILE.stat().st_size / 1024 / 1024
    elapsed = round(time.time() - t0, 1)
    logger.info(f"Archive created: {size_mb:.1f} MB in {elapsed}s")


def upload_to_baidu():
    """上传到百度网盘（覆盖）"""
    logger.info(f"Uploading {BACKUP_FILE} -> {REMOTE_PATH}")
    t0 = time.time()

    result = subprocess.run(
        ["bypy", "upload", str(BACKUP_FILE), REMOTE_PATH],
        capture_output=True,
        text=True,
    )

    elapsed = round(time.time() - t0, 1)
    if result.returncode == 0:
        logger.info(f"Upload complete in {elapsed}s")
    else:
        logger.error(f"Upload failed: {result.stderr}")
        sys.exit(1)


def cleanup():
    """删除本地临时压缩包"""
    if BACKUP_FILE.exists():
        BACKUP_FILE.unlink()
        logger.info("Local archive removed")


def main():
    if not DATA_MARKET_DIR.exists():
        logger.error(f"Data directory not found: {DATA_MARKET_DIR}")
        sys.exit(1)

    create_archive()
    upload_to_baidu()
    cleanup()
    logger.info("Backup done!")


if __name__ == "__main__":
    main()
