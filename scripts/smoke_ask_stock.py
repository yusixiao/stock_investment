"""问股 Phase 1 烟囱测试 — 跑真实 LLM + 真实数据,完整三阶段流水线。

用法(后台执行,长任务):
    nohup python scripts/smoke_ask_stock.py 002594.SZ > /tmp/smoke_ask_stock.log 2>&1 &
    tail -f /tmp/smoke_ask_stock.log

前置:
    - config/system_config.yaml 已配 LLM channel(至少含 LLM_DEFAULT_CHANNEL 或
      显式 LLM_ROUTE_PHASE3_QUANT / _VALUATION)
    - data/portfolio.db 已建表(import main 时自动)
    - DuckDB 视图就绪(data/market/{A,HK,US}/...)

不接前端,直接调 Coordinator,把 SSE 事件打印到 stdout。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol", help="股票码,如 002594.SZ / 600519 / 0700.HK / AAPL")
    parser.add_argument("--message", default=None, help="自定义提问(默认问大概情况)")
    parser.add_argument(
        "--out",
        default=str(ROOT / "report" / "agent_runs"),
        help="工作区根目录(默认 report/agent_runs/)",
    )
    args = parser.parse_args()

    # 注入环境
    os.environ.setdefault("DSA_AGENT_RUNS", args.out)
    os.environ.setdefault("DSA_PORTFOLIO_DB", str(ROOT / "data" / "portfolio.db"))
    os.environ.setdefault(
        "DSA_CONFIG_PATH", str(ROOT / "config" / "system_config.yaml")
    )

    # 延迟 import:在 sys.path 设好之后
    from services.market_data import stock_index
    from services.agent.coordinator import Coordinator
    from services.agent.core.session_repo import SessionRepo
    from services.agent.core.workspace import Workspace
    from services.db_schema import init_chat_tables
    from services.market_data.duckdb_store import (
        get_store,
        init_duckdb_with_health_check,
    )

    # 启动 DuckDB(注册视图)
    init_duckdb_with_health_check()
    store = get_store()

    # 启动 stock_index
    try:
        stock_index.init_stock_index()
    except Exception as e:
        print(f"[warn] stock_index init failed: {e}", file=sys.stderr)

    conn = sqlite3.connect(os.environ["DSA_PORTFOLIO_DB"], check_same_thread=False)
    init_chat_tables(conn)
    repo = SessionRepo(conn)
    ws = Workspace(Path(args.out))

    # 真实 LLM factory(按 phase 解析)
    from routers.agent import build_client_for_phase, _config_kv
    from services.agent.core.tavily_client import TavilyClient

    sid = f"smoke-{int(time.time())}"
    msg = args.message or f"{args.symbol} 这家公司怎么样,值得投吗?"

    async def sse_send(ev: dict) -> None:
        # 简化打印:tool_start/tool_done/error/done 全量;generating 只计数
        t = ev.get("type")
        if t == "generating":
            print(".", end="", flush=True)
            return
        print()
        print(f"[{t}] {json.dumps(ev, ensure_ascii=False)}", flush=True)

    coord = Coordinator(
        sse_send=sse_send,
        repo=repo,
        workspace=ws,
        stock_index=stock_index,
        llm_factory=build_client_for_phase,
        store=store,
        indicators=None,
        tavily=TavilyClient(api_key=_config_kv().get("TAVILY_API_KEY") or None),
    )

    print(f"=== smoke ask_stock: {args.symbol} | sid={sid} ===")
    t0 = time.time()
    await coord.run(session_id=sid, message=msg, context={"symbol": args.symbol})
    print(f"\n=== done in {time.time() - t0:.1f}s ===")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
