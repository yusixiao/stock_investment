from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_KLINE_DIR = DATA_DIR / "kline" / "A" / "raw"
LOG_DIR = DATA_DIR / "logs"

LOG_DIR.mkdir(parents=True, exist_ok=True)

UPDATE_LOG_FILE = LOG_DIR / "update_log.json"
LOG_RETENTION_DAYS = 90

SCHEDULER_HOUR = 15
SCHEDULER_MINUTE = 30

RETRY_MAX_ATTEMPTS = 20
RETRY_BACKOFF_CAP = 60
