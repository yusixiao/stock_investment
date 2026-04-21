from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.stock import router as stock_router
from routers.data_update import router as data_update_router
from routers.backtest import router as backtest_router
from routers.screener import router as screener_router
from routers.portfolio import router as portfolio_router
from routers.valuation import router as valuation_router
from routers.dividend import router as dividend_router
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


@app.get("/api/health")
def health_check():
    return {"status": "ok"}
