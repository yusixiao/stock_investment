from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
# 业务数据唯一来源:data/market/{A,HK,US}/{daily,adjust_factor,dividend,financial/...}
# 旧路径 (data/{kline,valuation,dividend,financial,indicators}/A/) 已废弃,见 AGENTS.md 铁律
META_DIR = DATA_DIR / "meta"
MARKET_DIR = DATA_DIR / "market"
# 策略已迁入回测子系统:backend/services/backtest/strategies/(2026-06-14)
STRATEGY_DIR = Path(__file__).resolve().parent / "services" / "backtest" / "strategies"
# UI/回测只加载已发布策略:.../strategies/deployed/。在研策略放 .../strategies/experiments/,不进 UI
DEPLOYED_STRATEGY_DIR = STRATEGY_DIR / "deployed"
LOG_DIR = BASE_DIR / "logs"
PORTFOLIO_DB = DATA_DIR / "portfolio.db"

LOG_DIR.mkdir(parents=True, exist_ok=True)
META_DIR.mkdir(parents=True, exist_ok=True)
MARKET_DIR.mkdir(parents=True, exist_ok=True)

LOG_RETENTION_DAYS = 90

SCHEDULER_HOUR = 15
SCHEDULER_MINUTE = 30
