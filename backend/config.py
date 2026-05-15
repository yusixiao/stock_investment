from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_KLINE_DIR = DATA_DIR / "kline" / "A" / "raw"
QFQ_KLINE_DIR = DATA_DIR / "kline" / "A" / "qfq"
VALUATION_DIR = DATA_DIR / "valuation" / "A"
DIVIDEND_DIR = DATA_DIR / "dividend" / "A"
FINANCIAL_DIR = DATA_DIR / "financial" / "A"
INDICATOR_DIR = DATA_DIR / "indicators" / "A"
META_DIR = DATA_DIR / "meta"
MARKET_DIR = DATA_DIR / "market"
STRATEGY_DIR = BASE_DIR / "strategies"
LOG_DIR = DATA_DIR / "logs"
PORTFOLIO_DB = DATA_DIR / "portfolio.db"

LOG_DIR.mkdir(parents=True, exist_ok=True)
META_DIR.mkdir(parents=True, exist_ok=True)
VALUATION_DIR.mkdir(parents=True, exist_ok=True)
DIVIDEND_DIR.mkdir(parents=True, exist_ok=True)
FINANCIAL_DIR.mkdir(parents=True, exist_ok=True)

UPDATE_LOG_FILE = LOG_DIR / "update_log.json"
UPDATE_PROGRESS_FILE = LOG_DIR / "update_progress.log"
STOCK_UPDATE_TRACKER_FILE = BASE_DIR / "stock_update_tracker.json"
LOG_RETENTION_DAYS = 90

SCHEDULER_HOUR = 15
SCHEDULER_MINUTE = 30

RETRY_MAX_ATTEMPTS = 20
RETRY_BACKOFF_CAP = 60
