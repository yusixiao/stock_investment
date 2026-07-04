#!/usr/bin/env python3
"""林奇六型「单打冠军」· 新数据同口径重跑 (Option A)。

目的
----
单型研究报告(``林奇六类型策略研究报告.md``)里每型的冠军成绩是在**当时的数据快照**上、
且各型**各自的窗口/口径**下得到的(如缓慢增长 2010-06 起、困境反转 2010-01 起全期等)。
本脚本把**六型冠军配置逐字固化**,在**当前数据快照**上、用**完全统一的口径**重跑一遍:
- 统一窗口:since2016(主, 2016-01-01→2026-06-01)+ full(辅, 2010-01-01→2026-06-01)。
- 统一引擎/成本/成交价:``BacktestEngine.run()``(一份现金 + 整手 + T+1 + 佣金万3 +
  印花税千1 + 滑点),与组合 Exp-3 完全一致。
- 统一指标:复用 ``run_portfolio_shared_pool._metrics``(CAGR/年化波动/MaxDD/Sharpe rf=0)。

这样得到一张**干净可比**的「六型冠军单打 vs 推荐组合 slow40」对照表,回答:
「把每型冠军单独跑在同一份新数据上,谁强?组合化(slow40)是否跑赢最强的单型冠军?」

冠军配置来源(逐字对齐单型报告 + 各策略类默认)
-----------------------------------------------
- slow_growers  : 已发布冠军(与组合 LEG_CONFIGS 逐字一致)。
- stalwarts     : §3.2「冠军 D基」(进取/max 收益变体, 报告全期 11.24%)。
- fast_growers  : §4「默认画像冠军」= 类默认(param_overrides={}; 报告全期 4.48%)。
                  注:报告 §4.2 正文写 CAGR∈[25%,100%] 与 §4 教训「取消上限最差」及
                  已发布类默认 np_cagr_max=0.50 矛盾, 以**类默认 0.50** 为准(=报告 4.48% 口径)。
- cyclicals     : 跑两版 —— ①诚实基线(§5.6 推荐的可部署配置, 全期 ~6.4%);
                  ②全样本过拟合冠军(§5.3 的 11.11%, 报告判定为 2015 泡沫「海市蜃楼·禁部署」,
                  仅作对照, 预期在新数据/近窗口塌回基线)。
- turnarounds   : 低杠杆冠军(与组合 LEG_CONFIGS 逐字一致; 报告全期 15.88%)。
- asset_plays   : §7「冠军 K4」(trend150; 与组合 LEG_CONFIGS 逐字一致; 报告全期 14.73% / 2016+ 8.38%)。

组合对照行直接读 ``portfolio_shared_pool.json``(Exp-3 已跑完的 slow40 真回测), 不重跑。

用法(长任务, 后台跑)
  nohup python backend/services/backtest/strategies/experiments/lynch/portfolio/run_champions_solo.py \
      > logs/lynch_champions_solo.log 2>&1 &
"""
import json
import logging
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("lynch_champions_solo")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from services.backtest.strategies.utils import balance_long, growth_long, st_filter
from services.backtest.strategies.experiments.lynch.lynch_slow_growers.lynch_slow_growers_strategy import (
    LynchSlowGrowersStrategy,
)
from services.backtest.strategies.experiments.lynch.lynch_stalwarts.lynch_stalwarts_strategy import (
    LynchStalwartsStrategy,
)
from services.backtest.strategies.experiments.lynch.lynch_fast_growers.lynch_fast_growers_strategy import (
    LynchFastGrowersStrategy,
)
from services.backtest.strategies.experiments.lynch.lynch_cyclicals.lynch_cyclicals_strategy import (
    LynchCyclicalsStrategy,
)
from services.backtest.strategies.experiments.lynch.lynch_turnarounds.lynch_turnarounds_strategy import (
    LynchTurnaroundsStrategy,
)
from services.backtest.strategies.experiments.lynch.lynch_asset_plays.asset_plays_strategy import (
    LynchAssetPlaysStrategy,
)
from services.backtest.strategies.experiments.lynch.portfolio.run_portfolio_shared_pool import (
    _metrics,
    _csi300_daily_returns,
    _pct,
    WINDOWS,
)

OUT_DIR = Path(__file__).resolve().parent

# 六型「单打冠军」配置(逐字对齐单型报告)。tuple = (key, 中文标签, 策略类, param_overrides, 报告原值备注)
CHAMPIONS = [
    ("slow_growers", "缓慢增长(已发布冠军)", LynchSlowGrowersStrategy,
     {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 12,
      "max_per_sector": 2, "rebalance_months": [6]},
     "报告 14.28% (2010-06 起全期, ✅已采纳发布)"),
    ("stalwarts", "稳健增长 D基(进取冠军)", LynchStalwartsStrategy,
     {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
      "np_cagr_min": 0.08, "np_cagr_max": 0.20, "max_per_sector": 2,
      "mktcap_min_yi": 250.0},
     "报告 11.24% (全期, ⏳暂定; 均衡变体 Sh0.56/DD37%)"),
    ("fast_growers", "快速增长(默认画像冠军)", LynchFastGrowersStrategy,
     {},
     "报告 4.48% (全期, ⏳暂定; 收益弱风险高)"),
    ("cyclicals_baseline", "周期·诚实基线(可部署)", LynchCyclicalsStrategy,
     {"trailing_stop_pct": 0.25},
     "报告 6.43% (全期基线; 近5年 11.57%/DD22%, 唯一可泛化配置)"),
    ("cyclicals_overfit", "周期·全样本冠军(海市蜃楼·仅对照)", LynchCyclicalsStrategy,
     {"sector_tier": "core_no_prop", "mktcap_max_yi": 100.0,
      "max_per_sector": 2, "trailing_stop_pct": 0.25},
     "报告 11.11% (全期; 判定2015泡沫过拟合·禁部署)"),
    ("turnarounds", "困境反转(低杠杆冠军)", LynchTurnaroundsStrategy,
     {"rebalance_months": [3, 6, 9, 12], "top_n": 10, "max_debt_ratio": 0.60},
     "报告 15.88% (2010-01 起全期, 达标存疑/幸存者偏差重)"),
    ("asset_plays", "隐蔽资产 K4(冠军)", LynchAssetPlaysStrategy,
     {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
      "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0, "trend_ma_days": 150},
     "报告 14.73% 全期 / 8.38% 2016+ (诚实值 ~8%)"),
]


def _run_solo(sliced, cls, ov: dict) -> dict:
    """把单个策略(冠军配置)直接作为引擎策略真回测一次 → 指标 dict。

    与 ``run_portfolio_shared_pool._run_pool`` 完全同口径(同引擎/成本/成交价/_metrics),
    唯一区别:这里 strategy 直接是该型策略本体(满仓单打), 而非 meta 组合封装。
    """
    strat = cls(param_overrides=ov)
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
    )
    res = engine.run()
    ec = res.get("equity_curve") or []
    if not ec:
        return {"cagr": None, "n_trades": 0, "n_days": 0}
    dates = pd.to_datetime([p["date"] for p in ec])
    vals = pd.Series([float(p["total_value"]) for p in ec], index=dates).sort_index()
    daily = vals.pct_change().dropna()

    raw = res.get("raw_trades", []) or []
    buy_val = sum(float(t["shares"]) * float(t["price"])
                  for t in raw if t.get("direction") == "buy")
    sell_val = sum(float(t["shares"]) * float(t["price"])
                   for t in raw if t.get("direction") == "sell")
    cost = sum(float(t.get("commission", 0)) + float(t.get("tax", 0)) for t in raw)
    final_val = float(vals.iloc[-1])
    avg_eq = float(vals.mean())
    years = max((vals.index[-1] - vals.index[0]).days, 1) / 365.25
    turnover_ann = ((buy_val + sell_val) / 2.0 / avg_eq / years) if avg_eq > 0 else None

    m = _metrics(daily)
    m.update({
        "n_trades": len(raw),
        "total_cost": round(cost, 2),
        "cost_pct_of_final": (cost / final_val) if final_val else None,
        "final_value": round(final_val, 2),
        "turnover_ann": turnover_ann,
    })
    return m


def _load_combo_rows() -> dict:
    """读 Exp-3 已跑结果, 抽 slow40 组合 (on_change/monthly) 各窗口指标作对照行。"""
    p = OUT_DIR / "portfolio_shared_pool.json"
    if not p.exists():
        log.warning("缺 %s, 组合对照行留空", p.name)
        return {}
    data = json.loads(p.read_text())
    out = {}
    for wname, blk in data.items():
        modes = blk.get("modes", {})
        out[wname] = {
            "on_change": modes.get("on_change", {}),
            "monthly": modes.get("monthly", {}),
        }
    return out


def main():
    growth_long.reset_annual_cache()
    balance_long.reset_balance_cache()
    st_filter.reset_st_cache()

    log.info("加载 A bundle ...")
    t0 = time.time()
    bundle = data_cache.get_market("A") or data_cache._load_market_blocking("A")
    log.info("bundle loaded %d stocks in %.1fs",
             len(bundle.stock_data), time.time() - t0)

    combo = _load_combo_rows()
    report = {"windows": {}, "champions_meta": [
        {"key": k, "label": lb, "overrides": ov, "report_note": note}
        for k, lb, _, ov, note in CHAMPIONS
    ]}

    for wname, (start, end) in WINDOWS.items():
        log.info("==== window %s (%s → %s) ====", wname, start, end)
        sliced = data_cache.slice_bundle(bundle, None, start, end)
        blk = {"window": [start, end], "champions": {}, "combo_slow40": combo.get(wname, {})}

        for key, label, cls, ov, note in CHAMPIONS:
            t1 = time.time()
            m = _run_solo(sliced, cls, ov)
            blk["champions"][key] = {"label": label, "report_note": note, "overrides": ov, **m}
            log.info("[%s/%s] %.1fs trades=%s CAGR=%s Sharpe=%.2f MaxDD=%s cost=%s",
                     wname, key, time.time() - t1, m.get("n_trades"),
                     _pct(m.get("cagr")), m.get("sharpe") or 0,
                     _pct(m.get("max_drawdown")), _pct(m.get("cost_pct_of_final")))

        bench = _csi300_daily_returns(start, end)
        if bench is not None:
            blk["csi300"] = _metrics(bench)

        report["windows"][wname] = blk
        _write_overview(report)

    (OUT_DIR / "champions_solo.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str)
    )
    log.info("ALL DONE -> champions_solo.json + champions_solo_overview.md")


def _write_overview(report):
    lines = [
        "# 林奇六型「单打冠军」· 新数据同口径重跑 (Option A)",
        "",
        "> 六型冠军配置**逐字固化**, 在**当前数据快照**上、用**完全统一口径**"
        "(同引擎/成本/成交价/窗口/指标)各自满仓单打, 再与推荐组合 **slow40**"
        "(slow .40 / turn .30 / asset .30, Exp-3 真回测)对照。",
        "> 「报告原值」列 = 单型研究报告在**旧数据快照 + 各自窗口**下的冠军成绩, 仅供参照,"
        "**不可与本表新数据列直接比大小**(数据版本 + 窗口口径均不同)。",
        "> 周期型跑两版:诚实基线(可部署)+ 全样本过拟合冠军(报告判定海市蜃楼, 仅对照)。",
        "",
    ]
    for wname, blk in report["windows"].items():
        s, e = blk["window"]
        lines += [f"## 窗口 `{wname}` ({s} → {e})", "",
                  "| 类型(冠军) | CAGR | 年化波动 | MaxDD | Sharpe | 笔数 | 年化换手 | 成本/终值 | 报告原值(旧数据) |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for key, label, _, _, _ in CHAMPIONS:
            m = blk["champions"].get(key, {})
            if not m:
                continue
            to = m.get("turnover_ann")
            lines.append(
                f"| {label} | {_pct(m.get('cagr'))} | {_pct(m.get('ann_vol'))} | "
                f"{_pct(m.get('max_drawdown'))} | {(m.get('sharpe') or 0):.2f} | "
                f"{m.get('n_trades', '-')} | {(to if to is not None else 0):.2f} | "
                f"{_pct(m.get('cost_pct_of_final'))} | {m.get('report_note', '-')} |"
            )
        # 组合对照
        cb = blk.get("combo_slow40", {})
        for mode in ("on_change", "monthly"):
            m = cb.get(mode, {})
            if not m:
                continue
            to = m.get("turnover_ann")
            lines.append(
                f"| **组合 slow40 ({mode})** | {_pct(m.get('cagr'))} | {_pct(m.get('ann_vol'))} | "
                f"{_pct(m.get('max_drawdown'))} | {(m.get('sharpe') or 0):.2f} | "
                f"{m.get('n_trades', '-')} | {(to if to is not None else 0):.2f} | "
                f"{_pct(m.get('cost_pct_of_final'))} | Exp-3 真回测(新数据) |"
            )
        bench = blk.get("csi300")
        if bench:
            lines.append(
                f"| CSI300(基准) | {_pct(bench.get('cagr'))} | {_pct(bench.get('ann_vol'))} | "
                f"{_pct(bench.get('max_drawdown'))} | {(bench.get('sharpe') or 0):.2f} | "
                f"- | - | - | - |"
            )
        lines.append("")

    (OUT_DIR / "champions_solo_overview.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
