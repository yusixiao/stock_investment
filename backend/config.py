from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
# 业务数据唯一来源:data/market/{A,HK,US}/{daily,adjust_factor,dividend,financial/...}
# 旧路径 (data/{kline,valuation,dividend,financial,indicators}/A/) 已废弃,见 AGENTS.md 铁律
META_DIR = DATA_DIR / "meta"
MARKET_DIR = DATA_DIR / "market"
# 问股 · 纯派生过程缓存(可随时删,自动重建,不进备份)
# CACHE_DIR 统一收纳问股各类中间缓存:tavily 搜索缓存 + 定性分析缓存
CACHE_DIR = DATA_DIR / "cache"
# 定性分析缓存(cpa Phase 0 / BA agent 共享读写),30 天 TTL,归 cache 不是 report
QUALITATIVE_DIR = CACHE_DIR / "qualitative"
# 策略已迁入回测子系统:backend/services/backtest/strategies/(2026-06-14)
STRATEGY_DIR = Path(__file__).resolve().parent / "services" / "backtest" / "strategies"
# UI/回测只加载已发布策略:.../strategies/deployed/。在研策略放 .../strategies/experiments/,不进 UI
DEPLOYED_STRATEGY_DIR = STRATEGY_DIR / "deployed"
LOG_DIR = BASE_DIR / "logs"
PORTFOLIO_DB = DATA_DIR / "portfolio.db"

LOG_DIR.mkdir(parents=True, exist_ok=True)
META_DIR.mkdir(parents=True, exist_ok=True)
MARKET_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)
QUALITATIVE_DIR.mkdir(parents=True, exist_ok=True)

LOG_RETENTION_DAYS = 90

SCHEDULER_HOUR = 15
SCHEDULER_MINUTE = 30
