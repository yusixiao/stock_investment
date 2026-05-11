import logging
import logging.handlers
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import LOG_DIR

# 日志配置：同时输出到 stdout 和文件（按天轮转，保留90天）
_log_file = LOG_DIR / "app.log"
_file_handler = logging.handlers.TimedRotatingFileHandler(
    _log_file, when="midnight", backupCount=90, encoding="utf-8"
)
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))

_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.INFO)
_console_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"
))

logging.basicConfig(level=logging.DEBUG, handlers=[_file_handler, _console_handler])
# 降低第三方库的日志级别
logging.getLogger("uvicorn").setLevel(logging.INFO)
logging.getLogger("watchfiles").setLevel(logging.WARNING)

from routers.stock import router as stock_router
from routers.data_update import router as data_update_router
from routers.backtest import router as backtest_router
from routers.screener import router as screener_router
from routers.portfolio import router as portfolio_router
from routers.valuation import router as valuation_router
from routers.dividend import router as dividend_router
from routers.financial import router as financial_router
from routers.strategy_group import router as strategy_group_router
from routers.meta import router as meta_router
from scheduler import start_scheduler, shutdown_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    from services.portfolio.db import init_db
    init_db()
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(title="Stock Investment Platform", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stock_router)
app.include_router(data_update_router)
app.include_router(backtest_router)
app.include_router(screener_router)
app.include_router(portfolio_router)
app.include_router(valuation_router)
app.include_router(dividend_router)
app.include_router(financial_router)
app.include_router(strategy_group_router)
app.include_router(meta_router)


@app.get("/api/health")
def health_check():
    return {"status": "ok"}
