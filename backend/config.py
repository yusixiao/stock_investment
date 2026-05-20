from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
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

LOG_RETENTION_DAYS = 90

SCHEDULER_HOUR = 15
SCHEDULER_MINUTE = 30
