"""每年(6 月调仓)满足「基本面 + 股息率排序 + 行业≤2 分散」的**全部**标的清单。

背景:task f92d158d(deployed LynchSlowGrowersStrategy,2016-2026,top_n=12)历史上
很少买满 12 只,2026-06 首次买满。为判断"近年符合基本面者是否真的更多",需要把
Stage4 的 `top_n=12` 截断去掉,看每年经「基本面筛选 → 股息率降序 → 每行业≤2 分散」后
**未截断**的合格标的数量与名单。

做法:完整复现该 task 的选股管线(同参数、同 A 全市场、同 2016-01-01→2026-07-04),
唯一改动 `param_overrides={"top_n": 999}` 让截断失效。开启决策日志后,
`strategy.screen.final` 会记录每年分散后存活的全部标的;`strategy.dividend` 记录
分散前通过全部基本面的数量。二者对比即可看出「基本面供给」与「分散后可投」的逐年变化。

自闭环:脚本落本策略目录,产物 json 落本目录。长任务后台跑:
  nohup python backend/services/backtest/strategies/experiments/lynch/lynch_slow_growers/run_lynch_sg_qualifying_by_year.py \
      > logs/lynch_sg_qualifying_by_year.log 2>&1 &
"""

import collections
import json
import logging
import sys
import time
from pathlib import Path

# 本脚本处于 experiments/lynch/lynch_slow_growers/,上溯 7 层到项目根
ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("lynch_sg_qual")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from services.backtest.strategies.deployed.lynch_slow_growers_strategy import (
    LynchSlowGrowersStrategy,
)
from services.backtest.strategies.utils import growth_long, st_filter
from services.market_data import stock_index

START = "2016-01-01"  # 与 task f92d158d 对齐
END = "2026-07-04"
OUT_DIR = Path(__file__).resolve().parent
OUT_JSON = OUT_DIR / "lynch_sg_qualifying_by_year.json"
LOG_DIR = ROOT / "logs" / "backtest" / "lynch_sg_qual_uncapped"


def main():
    t = time.time()
    # PIT 缓存清零,保证年报/ST 时点缓存干净(与其它 runner 一致)
    growth_long.reset_annual_cache()
    st_filter.reset_st_cache()
    try:
        stock_index.init_stock_index()
    except Exception as e:
        log.warning("init_stock_index failed(名称留空): %s", e)

    log.info("加载 A bundle ...")
    bundle = data_cache.get_market("A") or data_cache._load_market_blocking("A")
    sliced = data_cache.slice_bundle(bundle, None, START, END)
    log.info("sliced %d stocks", len(sliced.stock_data))

    # 唯一改动:top_n 放大到 999,关闭 Stage4 截断(其余参数 = 发布版默认 = task 参数)
    strat = LynchSlowGrowersStrategy(param_overrides={"top_n": 999})
    engine = BacktestEngine(
        strategy=strat,
        stock_data=sliced.stock_data,
        valuation_data=sliced.valuation_data,
        dividend_data=sliced.dividend_data,
        financial_data=sliced.financial_data,
        balance_data=sliced.balance_data,
        cashflow_data=sliced.cashflow_data,
        income_data=sliced.income_data,
        weekly_data=sliced.weekly_data,
        monthly_data=sliced.monthly_data,
        iter_start=sliced.iter_start_idx,
        iter_end=sliced.iter_end_idx,
        enable_decision_log=True,
        log_dir=LOG_DIR,
    )
    log.info("running backtest(top_n=999) ...")
    engine.run()
    log.info("run done in %.1fs", time.time() - t)

    # 解析决策日志:screen.final = 分散后存活全部标的;dividend = 分散前基本面通过数
    finals = collections.defaultdict(list)
    for line in open(LOG_DIR / "decisions.jsonl"):
        e = json.loads(line)
        if e.get("stage") == "strategy.screen.final" and e.get("decision") == "pass":
            finals[e["ts"][:10]].append(e["symbol"])

    funnel = collections.defaultdict(dict)
    for line in open(LOG_DIR / "flow.jsonl"):
        e = json.loads(line)
        st = e.get("stage", "")
        if st.startswith("strategy.") and e.get("ts"):
            c = e.get("counts") or {}
            funnel[e["ts"][:10]][st] = c.get("passed", c.get("input"))

    out = []
    for ts in sorted(finals):
        syms = sorted(finals[ts])
        rows = [
            {
                "code": s,
                "name": stock_index.get_name(s) or "",
                "ex": "沪" if s.endswith(".SH") else ("深" if s.endswith(".SZ") else "?"),
            }
            for s in syms
        ]
        fn = funnel.get(ts, {})
        out.append(
            {
                "date": ts,
                "n_fundamentals": fn.get("strategy.dividend"),  # 分散前基本面通过
                "n_qualifying": len(syms),  # 分散后合格(未截断)
                "sh": sum(s.endswith(".SH") for s in syms),
                "sz": sum(s.endswith(".SZ") for s in syms),
                "stocks": rows,
            }
        )

    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    log.info("wrote %s", OUT_JSON)

    print("\n" + "=" * 70)
    print(f"{'调仓日':12}{'基本面通过':>10}{'分散后合格':>10}{'沪':>4}{'深':>4}")
    for y in out:
        print(
            f"{y['date']:12}{str(y['n_fundamentals']):>10}{y['n_qualifying']:>10}{y['sh']:>4}{y['sz']:>4}"
        )
    for y in out:
        print(f"\n=== {y['date']}  基本面通过={y['n_fundamentals']}  分散后合格={y['n_qualifying']} ===")
        for r in y["stocks"]:
            print(f"  {r['ex']} {r['code']}  {r['name']}")


if __name__ == "__main__":
    main()
