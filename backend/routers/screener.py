"""选股 API(Phase 6.2 适配单一 Strategy 模型)。

旧多策略 pipeline 已废弃,现仅接受单一 Strategy class。前端仍以 pipeline=[item]
形式提交,后端取首项作为 Strategy。
"""

from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

from services.backtest.market_data import MarketData
from services.backtest.strategy_loader import load_strategy_from_file
from services.duckdb_store import get_store
from strategies.base import Strategy


router = APIRouter(prefix="/api/screener", tags=["screener"])

_latest_result: dict | None = None


@router.post("/run")
def api_run_screener(body: dict = Body(...)):
    global _latest_result
    pipeline = body.get("pipeline", [])
    param_overrides = body.get("param_overrides", {})

    if not pipeline:
        raise HTTPException(status_code=400, detail="Pipeline cannot be empty")

    item = pipeline[0]
    filepath = Path(item["filepath"])
    class_name = item["class_name"]
    overrides = param_overrides.get(class_name, {})
    classes = load_strategy_from_file(filepath)
    cls = next((c for c in classes if c.__name__ == class_name), None)
    if cls is None:
        raise HTTPException(
            status_code=400, detail=f"Strategy class {class_name} not found"
        )
    instance = cls(param_overrides=overrides)
    if not isinstance(instance, Strategy):
        raise HTTPException(status_code=400, detail=f"{class_name} is not a Strategy")

    stock_data = {}
    store = get_store()
    for symbol in store.list_symbols("A"):
        df = store.query_qfq_kline("A", symbol)
        if not df.empty:
            stock_data[symbol] = df

    # 仅在最后一根 bar 上调 screen():用一个最小化 Context 包装 MarketData
    market_data = MarketData(stock_data=stock_data, frequency=instance.frequency)
    last_idx = len(market_data.dates) - 1 if market_data.dates else 0

    class _ScreenStub:
        """选股阶段不需要 broker / log_sink,提供必要属性即可。"""

        def __init__(self, md, idx):
            self.current_idx = idx
            self.current_date = md.dates[idx] if md.dates else None
            self._market_data = md
            self.target_symbols = set()
            self.new_symbols = []

        def get_price(self, sym, period="daily"):
            return self._market_data.get_price(sym, period=period, idx=self.current_idx)

        def get_history(self, sym, n, period="daily"):
            return self._market_data.get_history(
                sym, n=n, period=period, idx=self.current_idx
            )

        def get_valuation(self, sym):
            return self._market_data.get_valuation(sym, date=self.current_date)

        def get_dividend(self, sym):
            return self._market_data.get_dividend(sym, date=self.current_date)

        def get_financial(self, sym):
            return self._market_data.get_financial(sym, date=self.current_date)

        def indicator(self, name, sym, **kwargs):
            return self._market_data.indicator(
                name, sym, idx=self.current_idx, **kwargs
            )

        def log_pass(self, *a, **kw):
            pass

        def log_reject(self, *a, **kw):
            pass

        def log_flow(self, *a, **kw):
            pass

    ctx = _ScreenStub(market_data, last_idx)
    screened = list(instance.screen(ctx, list(stock_data.keys())))

    _latest_result = {
        "screened_symbols": screened,
        "count": len(screened),
        "pipeline": [item["class_name"]],
    }
    return _latest_result


@router.get("/result")
def api_get_screener_result():
    if _latest_result is None:
        return {"screened_symbols": [], "count": 0, "pipeline": []}
    return _latest_result
