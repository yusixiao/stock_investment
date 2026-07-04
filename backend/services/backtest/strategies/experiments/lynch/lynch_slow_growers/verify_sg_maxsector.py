#!/usr/bin/env python3
"""slow_growers 下降归因·实锤验证:max_per_sector × 行业数据回归(根因已坐实并修复)。

结论(2026-07-04, 已闭环)
-------------------------
slow_growers 冠军报告头条 = 全期 2010-06 起 **14.28%**(注 2010-01 口径 13.90%)。
曾一度在数据快照上重跑塌到 **9.94%(full)**、笔数 139→31、MaxDD 23.85%→30.81%。
**根因(代码级坐实)**:``INDUSTRY_NAME`` 非 ``BalanceSheet`` 显式字段, 靠 ``extra="allow"``
透传落盘;2026-07-02 ``fetch_balance`` 改为优先取 4 张明细报表(G/B/S/I, 为拿 GOODWILL 等),
而**明细报表不含 INDUSTRY_NAME** → 覆盖从 ~100% 崩到 ~6%。冠军配置含 ``max_per_sector=2``,
策略 ``lynch_slow_growers_strategy.py:451`` 把所有 **行业=None** 并入**单一** "__UNKNOWN__" 桶、
被砍到只留 2 只 → 组合从"~12 只跨行业"塌成"~2-4 只高度集中" → 收益跌/回撤升/笔数骤降。
(注:``require_industry`` 默认 False 且冠军未开 → **非** Stage-1 硬剔除, 已排除。)
**修复**:``fetch_balance`` 命中明细后单请求从 DMSK 补回 INDUSTRY_NAME/INDUSTRY_CODE + 全量重抽,
覆盖回 **94.6%**(残缺均退市/ST)。

本表(修复后重跑)= 坐实证据
---------------------------
固定冠军其余参数(min_div_yield=0.035 / mktcap_min_yi=300 / top_n=12 / rebalance=[6]),
仅扫 ``max_per_sector ∈ {0,1,2(冠军),3}``, 双窗口 full + since2016 同口径:
- ``max_per_sector=0``(不依赖 INDUSTRY_NAME):修复前后 full 均 **12.73%/162 笔** = **一致性对照**;
- ``max_per_sector=2``(冠军):从退化态 9.94%/31 笔 **回升到 13.90%/139 笔(full/2010-01 口径)**,
  且在报告头条起点 2010-06 精确复现 **14.28%/745.72%/DD23.85/139**(见同目录 verify_report_baseline.py)。
→ 退化 = INDUSTRY_NAME 覆盖崩塌经 max_per_sector 桶塌陷传导, 已坐实并随数据修复完全还原。

用法(长任务, 后台;⚠️ Mac 会 idle 休眠冻结后台进程, 须 caffeinate 包裹)
  nohup caffeinate -i -s python backend/services/backtest/strategies/experiments/lynch/lynch_slow_growers/verify_sg_maxsector.py \
      > logs/verify_sg_maxsector.log 2>&1 &
"""
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("verify_sg_maxsector")

from services.backtest import data_cache
from services.backtest.strategies.utils import balance_long, growth_long, st_filter
from services.backtest.strategies.experiments.lynch.lynch_slow_growers.lynch_slow_growers_strategy import (
    LynchSlowGrowersStrategy,
)
from services.backtest.strategies.experiments.lynch.portfolio.run_champions_solo import _run_solo
from services.backtest.strategies.experiments.lynch.portfolio.run_portfolio_shared_pool import (
    _metrics,
    _csi300_daily_returns,
    _pct,
    WINDOWS,
)

OUT_DIR = Path(__file__).resolve().parent

# slow_growers 冠军配置(逐字对齐 run_champions_solo.CHAMPIONS),去掉 max_per_sector 作基座
BASE_OV = {
    "min_div_yield": 0.035,
    "mktcap_min_yi": 300.0,
    "top_n": 12,
    "rebalance_months": [6],
}
# 仅此单一变量被扫描:0=关闭行业分散(一致性对照);2=冠军配置(修复后回升);1/3=敏感性形状
SWEEP = [0, 1, 2, 3]


def main():
    growth_long.reset_annual_cache()
    balance_long.reset_balance_cache()
    st_filter.reset_st_cache()

    log.info("加载 A bundle ...")
    t0 = time.time()
    bundle = data_cache.get_market("A") or data_cache._load_market_blocking("A")
    log.info("bundle loaded %d stocks in %.1fs", len(bundle.stock_data), time.time() - t0)

    report = {
        "purpose": "slow_growers 下降归因:固定冠军配置,仅扫 max_per_sector,验证行业数据回归传导",
        "base_overrides": BASE_OV,
        "sweep_param": "max_per_sector",
        "sweep_values": SWEEP,
        "windows": {},
    }

    for wname, (start, end) in WINDOWS.items():
        log.info("==== window %s (%s → %s) ====", wname, start, end)
        sliced = data_cache.slice_bundle(bundle, None, start, end)
        rows = {}
        for mps in SWEEP:
            ov = {**BASE_OV, "max_per_sector": mps}
            t1 = time.time()
            m = _run_solo(sliced, LynchSlowGrowersStrategy, ov)
            rows[str(mps)] = {"overrides": ov, **m}
            log.info(
                "[%s] max_per_sector=%d %.1fs trades=%s CAGR=%s Sharpe=%.2f MaxDD=%s",
                wname, mps, time.time() - t1, m.get("n_trades"),
                _pct(m.get("cagr")), m.get("sharpe") or 0, _pct(m.get("max_drawdown")),
            )
        bench = _csi300_daily_returns(start, end)
        report["windows"][wname] = {
            "window": [start, end],
            "by_max_per_sector": rows,
            "csi300": _metrics(bench) if bench is not None else None,
        }
        _write_overview(report)

    (OUT_DIR / "verify_sg_maxsector.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str)
    )
    log.info("ALL DONE -> verify_sg_maxsector.json + verify_sg_maxsector_overview.md")


def _write_overview(report):
    lines = [
        "# slow_growers 下降归因·实锤验证 (max_per_sector × 行业数据回归)",
        "",
        "> 固定 slow_growers 冠军其余参数(min_div_yield=0.035 / mktcap_min_yi=300 / "
        "top_n=12 / rebalance=[6]),**仅扫 `max_per_sector`**,双窗口同口径重跑。",
        "> **结论(修复后重跑, 已坐实)**:`INDUSTRY_NAME` 曾因 2026-07-02 `fetch_balance` 明细报表"
        "重构丢失(覆盖 ~100%→6%),经 line 451 `\"__UNKNOWN__\"` 桶塌陷传导, 使冠军 `max_per_sector=2` "
        "一度塌到 9.94%/31 笔(full)。补回 INDUSTRY_NAME + 全量重抽(覆盖 94.6%)后:",
        "> - `max_per_sector=0`(不依赖行业)修复前后 full 均 **12.73%/162 笔** = **一致性对照**;",
        "> - `max_per_sector=2`(冠军)回升到 **13.90%/139 笔(full/2010-01 口径)**, 并在报告头条起点 "
        "2010-06 精确复现 **14.28%/745.72%/DD23.85/139**(见同目录 `verify_report_baseline.py`)。",
        "",
    ]
    for wname, blk in report["windows"].items():
        s, e = blk["window"]
        lines += [
            f"## 窗口 `{wname}` ({s} → {e})",
            "",
            "| max_per_sector | CAGR | 年化波动 | MaxDD | Sharpe | 笔数 | 年化换手 | 说明 |",
            "|---|---|---|---|---|---|---|---|",
        ]
        note_map = {
            "0": "关闭行业分散(不依赖 INDUSTRY_NAME → 修复前后一致=一致性对照)",
            "1": "极端分散(每行业≤1)",
            "2": "冠军配置(修复后回升; full=报告2010-01口径13.90%/139笔, 曾退化9.94%/31笔)",
            "3": "宽松分散(每行业≤3)",
        }
        for mps in map(str, report["sweep_values"]):
            m = blk["by_max_per_sector"].get(mps, {})
            if not m:
                continue
            to = m.get("turnover_ann")
            lines.append(
                f"| {mps} | {_pct(m.get('cagr'))} | {_pct(m.get('ann_vol'))} | "
                f"{_pct(m.get('max_drawdown'))} | {(m.get('sharpe') or 0):.2f} | "
                f"{m.get('n_trades', '-')} | {(to if to is not None else 0):.2f} | "
                f"{note_map.get(mps, '-')} |"
            )
        bench = blk.get("csi300")
        if bench:
            lines.append(
                f"| CSI300(基准) | {_pct(bench.get('cagr'))} | {_pct(bench.get('ann_vol'))} | "
                f"{_pct(bench.get('max_drawdown'))} | {(bench.get('sharpe') or 0):.2f} | - | - | - |"
            )
        lines.append("")

    (OUT_DIR / "verify_sg_maxsector_overview.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
