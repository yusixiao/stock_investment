"""元数据相关 API — 流通股数等。"""

from fastapi import APIRouter

from services.market_data.updaters.circulating_shares import (
    update_circulating_shares,
    get_circulating_shares,
)
from services.api_utils import BackgroundTaskRunner
from services.market_data.duckdb_store import reload_views, get_store

router = APIRouter(prefix="/api/meta", tags=["meta"])

_runner = BackgroundTaskRunner()


def _run_circulating_update(on_progress=None, **kwargs):
    """适配 BackgroundTaskRunner 的签名，将 on_progress 映射为 on_phase。"""

    def on_phase(p):
        if on_progress:
            on_progress(0, 0, p)

    return update_circulating_shares(on_phase=on_phase)


@router.post("/circulating-shares/update")
def api_update_circulating_shares():
    """触发流通股数快照更新（后台执行）。"""
    if not _runner.start(_run_circulating_update):
        status = _runner.get_status()
        return {
            "message": "already running",
            "phase": status.get("progress", {}).get("phase"),
        }
    return {"message": "started"}


@router.get("/circulating-shares/status")
def api_circulating_shares_status():
    """查询更新状态。"""
    status = _runner.get_status()
    progress = status.get("progress") or {}
    return {
        "status": status["status"],
        "phase": progress.get("phase"),
        "result": status["result"],
    }


@router.post("/duckdb/reload")
def api_reload_duckdb_views():
    """运行期重新注册所有 DuckDB 视图(补落新数据后刷新,无需重启进程)。"""
    reload_views()
    store = get_store()
    views = (
        store._conn.execute("SELECT view_name FROM duckdb_views() ORDER BY view_name")
        .fetchdf()["view_name"]
        .tolist()
    )
    return {"status": "ok", "views": views}


@router.get("/duckdb/diag")
def api_duckdb_diag():
    """诊断:store id + 业务视图行数 + bulk 抽样。"""
    store = get_store()
    out = {"store_id": id(store)}
    try:
        out["v_a_dividend_count"] = store._conn.execute(
            "SELECT COUNT(*) FROM v_a_dividend"
        ).fetchone()[0]
    except Exception as e:
        out["v_a_dividend_count_error"] = str(e)
    try:
        bulk = store.query_dividend_bulk("A", None)
        out["dividend_bulk_keys"] = len(bulk)
    except Exception as e:
        out["dividend_bulk_error"] = str(e)
    try:
        val = store.query_valuation_bulk("A", ["600519.SH"])
        out["val_sample"] = list(val.keys())
    except Exception as e:
        out["val_error"] = str(e)
    return out


@router.get("/circulating-shares")
def api_get_circulating_shares():
    """获取当前流通股数快照。"""
    df = get_circulating_shares()
    if df is None:
        return {"data": [], "update_date": None}
    update_date = df["update_date"].iloc[0] if len(df) > 0 else None
    records = df[["symbol", "circulating_shares"]].to_dict(orient="records")
    return {"data": records, "update_date": update_date}
