"""端到端集成验证 — run_qualitative 真实跑通。

跑法:
    cd backend && python ../scripts/spike_qualitative_e2e.py 600519.SH 贵州茅台

输出:
- 6 维度事件流
- 每维度耗时
- 落盘路径 data/qualitative/<code>_<name>/
- 14 参数 JSON 摘要
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

# 让脚本能直接 run(无 cd backend)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from backend.services.agent.core.qualitative import run_qualitative
from backend.services.agent.core.qualitative.cache import QualitativeCache
from backend.services.agent.core.qualitative.dimensions import MOCK_DIMENSION_FNS
from backend.services.agent.core.symbol import StockRef
from backend.services.agent.core.tavily_client import TavilyClient
from backend.services.market_data.duckdb_store import get_store
from backend.services.system_config.channels import (
    get_channel,
    reconstruct_channels,
    flatten_channels,
)
from backend.services.system_config.llm_client import build_client
from backend.services.system_config.store import ConfigStore


def build_llm():
    """加载 system_config.yaml 取默认 channel,构造 LLM client。"""
    cfg_path = ROOT / "config" / "system_config.yaml"
    kv = ConfigStore(cfg_path).load()
    channels = reconstruct_channels(kv)
    if not channels:
        raise RuntimeError("没有可用 channel,检查 config/system_config.yaml")
    default_name = kv.get("LLM_DEFAULT_CHANNEL") or channels[0].name
    ch = get_channel(flatten_channels(channels), default_name) or channels[0]
    print(f"[LLM] channel={ch.name} provider={ch.provider} model={ch.model}")
    return build_client(ch)


def build_tavily():
    cfg_path = ROOT / "config" / "system_config.yaml"
    kv = ConfigStore(cfg_path).load()
    api_key = kv.get("TAVILY_API_KEY") or None
    print(f"[Tavily] api_key={'set' if api_key else 'NOT SET'}")
    return TavilyClient(api_key=api_key)


async def main(code: str, name: str) -> int:
    ref = StockRef(code=code, name=name, market="A")
    print(f"\n=== 端到端定性分析:{ref.code} {ref.name} ===\n")

    store = get_store()
    print(f"[Store] DuckDB ready,视图数:{len(getattr(store, '_views', []))}")

    llm = build_llm()
    tavily = build_tavily()

    cache_dir = ROOT / "data" / "qualitative"
    cache = QualitativeCache(cache_dir)

    # 事件计时
    timings: dict[str, float] = {}
    last_start: dict[str, float] = {}

    async def on_event(ev: dict) -> None:
        t = ev.get("type")
        now = time.time()
        if t == "cache_hit":
            print(f"  [cache_hit] report_date={ev.get('report_date')}")
        elif t == "dimension_start":
            n = ev["name"]
            last_start[n] = now
            print(f"  [{n} 开始] {ev.get('title')}")
        elif t == "dimension_done":
            n = ev["name"]
            elapsed = now - last_start.get(n, now)
            timings[n] = elapsed
            print(f"  [{n} 完成] {elapsed:.1f}s")
        elif t == "dimension_failed":
            n = ev["name"]
            elapsed = now - last_start.get(n, now)
            timings[n] = elapsed
            print(f"  [{n} 失败] {elapsed:.1f}s err={ev.get('error')}")

    t0 = time.time()
    try:
        report = await run_qualitative(
            ref,
            cache=cache,
            dimension_fns=MOCK_DIMENSION_FNS,  # 别名 → 真实实现
            current_report_date=None,  # TTL only
            on_event=on_event,
            store=store,
            tavily=tavily,
            llm=llm,
            force_refresh=True,  # 端到端验证强制重跑
        )
    except Exception as e:
        print(f"\n!!! run_qualitative 失败:{type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        return 1

    total = time.time() - t0
    print(f"\n=== 完成 {total:.1f}s,各维度耗时 ===")
    for k, v in timings.items():
        print(f"  {k}: {v:.1f}s")

    print(f"\n=== 14 参数 ===")
    print(json.dumps(report.params.model_dump(), ensure_ascii=False, indent=2))

    print(f"\n=== 6 维度叙事(预览前 200 字)===")
    for d in report.dimensions:
        head = d.narrative[:200].replace("\n", " ")
        print(
            f"\n[{d.name}] {d.title}\n  {head}{'...' if len(d.narrative) > 200 else ''}"
        )

    # 落盘检查
    out_dir = cache_dir / f"{ref.code}_{ref.name}"
    print(f"\n=== 产物落盘 {out_dir} ===")
    if out_dir.exists():
        for p in sorted(out_dir.iterdir()):
            print(f"  {p.name} ({p.stat().st_size:,} bytes)")
    else:
        print("  (目录未创建,异常)")

    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    code = args[0] if args else "600519.SH"
    name = args[1] if len(args) > 1 else "贵州茅台"
    sys.exit(asyncio.run(main(code, name)))
