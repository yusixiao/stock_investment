#!/usr/bin/env python3
"""林奇组合 · 2016+ 专用重优化实验 (Exp-4) —— 在「诚实成熟窗口」上重新组队。

缘起(2026-07-04 子区间审计的裁定)
-----------------------------------
audit_subperiod.py 证明: 推荐组合(slow40)的全期 Sharpe 优势几乎全部来自
**2010-2015 早期小样本**(隐蔽资产腿早期年化 26.91% → 成熟期塌回 8.28%)。
在诚实的 2016+ 窗口里, 缓慢增长单打(13.88% / Sharpe 0.92)在收益与 Sharpe
上**双双反超**核心三腿组合(13.24% / 0.87), 组合仅在回撤上略优。

那份审计用的是「把全期净值切片到 2016+」(= 2010 起跑者在 2016+ 的体验)。
本实验换一个更前瞻、可部署的口径: **iter 窗口直接从 2016-01-01 起新跑**
(全历史 daily 仍保留供指标预热, 但只在 2016+ 产生交易与净值)—— 即
「一个 2016 年才入场的新投资者」真实能拿到的曲线。在这个口径下重问:

    「抛开早期幻象, 单看 2016 年以后, 六型里哪些腿还值得组队?
      能否组出一个 Sharpe + CAGR 双双跑赢『缓慢增长单打』的稳健组合?」

与前序实验的关键差异
--------------------
- **腿池 = 全六型**(不再预筛 4 腿)。原来剔除 fast/cyclicals 是基于**全期** merit;
  2016+ 各腿画像已明显变化, 选腿必须由 2016+ 数据重新决定, 故让六型全部进候选池,
  该不该剔由 2016+ 的收益/相关/beta 说话。周期型用**诚实基线**(trailing_stop 0.25,
  ≈全期 6.43%), **不用**过拟合冠军(海市蜃楼)。
- **窗口 = since2016 单一**(2016-01-01 → 2026-06-01), FRESH 口径(iter 从 2016 起),
  与 audit 的「切片」口径互补, 数字会略有出入(初始持仓在首个调仓周期内洗掉)。

方法学(与 Exp-1/Exp-2 保持同口径, 直接复用其函数)
--------------------------------------------------
- 各腿 2016+ 独立满仓回测 → 逐日净值; 派生「日度收益」(权重/指标用)+「月度收益」(相关用)。
- 相关矩阵 = 月度收益 Pearson(_corr_block, 复用 Exp-1)。
- 组合 = 目标权重「月度再平衡」合成日度收益(_combo_daily, 复用 Exp-2);
  指标 CAGR/年化波动/MaxDD/Sharpe 一律 _metrics 自算, 单腿与组合同口径可比。
- 权重方案: 稳健族(等权 / 逆波动 / 最小方差, 覆盖 全六型 / 核心三腿 / 核心三腿+各第4腿)
  + 缓慢增长单打基准(slow_only_ref, 要打败的对象) + 样本内最大 Sharpe(*_OVERFIT, 仅上界参考)。
- 引擎日度指标(annual/mdd/sharpe)另存一份, 便于与各型研究报告交叉核对(口径同 Exp-1)。

产出(自闭环, 落本目录)
  legs_daily_returns_6_since2016.parquet  各腿 2016+ 日收益(6 列, 免重跑迭代权重)
  portfolio_2016plus.json                 全部指标/相关/方案(唯一可复现证据)
  portfolio_2016plus_overview.md          排行 + 相关矩阵 + 「能否跑赢缓慢增长单打」裁决

用法(长任务, 必须后台跑)
  nohup rtk python backend/services/backtest/strategies/experiments/lynch/portfolio/run_portfolio_2016plus.py \
      > logs/lynch_portfolio_2016plus.log 2>&1 &
"""
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("lynch_pf_2016plus")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from services.backtest.strategies.utils import balance_long, growth_long, st_filter
from services.backtest.strategies.experiments.lynch.lynch_slow_growers.lynch_slow_growers_strategy import (
    LynchSlowGrowersStrategy,
)
from services.backtest.strategies.experiments.lynch.lynch_turnarounds.lynch_turnarounds_strategy import (
    LynchTurnaroundsStrategy,
)
from services.backtest.strategies.experiments.lynch.lynch_asset_plays.asset_plays_strategy import (
    LynchAssetPlaysStrategy,
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
# 复用 Exp-2(权重)与 Exp-1(相关)已验证的同口径函数, 不重复造轮子。
from services.backtest.strategies.experiments.lynch.portfolio.run_portfolio_weights import (
    _metrics,
    _combo_daily,
    _grid_weights,
    _csi300_daily_returns,
    _pct,
    _wstr,
)
from services.backtest.strategies.experiments.lynch.portfolio.run_portfolio_corr import (
    _corr_block,
    _equity_monthly_returns,
    _csi300_monthly_returns,
)

OUT_DIR = Path(__file__).resolve().parent
CORE3 = ["slow_growers", "turnarounds", "asset_plays"]

# 六型腿池(诚实/可部署配置, 逐字对齐 Exp-1 TYPES / champions_solo 基线; 周期用诚实基线非过拟合)。
LEGS = [
    ("slow_growers", LynchSlowGrowersStrategy,
     {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 12,
      "max_per_sector": 2, "rebalance_months": [6]}),
    ("turnarounds", LynchTurnaroundsStrategy,
     {"rebalance_months": [3, 6, 9, 12], "top_n": 10, "max_debt_ratio": 0.60}),
    ("asset_plays", LynchAssetPlaysStrategy,
     {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
      "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0, "trend_ma_days": 150}),
    ("stalwarts", LynchStalwartsStrategy,
     {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03, "np_cagr_min": 0.08,
      "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2, "mktcap_min_yi": 250.0}),
    ("fast_growers", LynchFastGrowersStrategy, {}),
    ("cyclicals", LynchCyclicalsStrategy, {"trailing_stop_pct": 0.25}),
]
LEG_NAMES = [n for n, _, _ in LEGS]

WINDOW = ("2016-01-01", "2026-06-01")  # 诚实成熟窗口, FRESH 口径(iter 从 2016 起新跑)


def _run_leg(sliced, cls, ov):
    """跑一腿完整回测(单次), 返回 (日度收益, 月度收益, 引擎指标 dict, 笔数)。

    单次运行同时喂给权重层(日度)与相关层(月度), 避免重复回测。
    引擎指标(annual/mdd/sharpe) = 引擎日度口径, 与各型研究报告一致, 仅作交叉核对;
    权重/组合层一律用 _metrics 自算, 保证单腿与组合可比。
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
        return None, None, {}, 0
    dates = pd.to_datetime([p["date"] for p in ec])
    vals = pd.Series([float(p["total_value"]) for p in ec], index=dates).sort_index()
    daily = vals.pct_change().dropna()
    monthly = _equity_monthly_returns(ec)
    m = res.get("metrics", {})
    eng = {
        "annualized_return": m.get("annualized_return"),
        "total_return": m.get("total_return"),
        "max_drawdown": m.get("max_drawdown"),
        "sharpe_ratio": m.get("sharpe_ratio"),
        "n_trades": len(res.get("raw_trades", [])),
    }
    return daily, monthly, eng, eng["n_trades"]


def _search_subset(R: pd.DataFrame, objective: str, active: list) -> np.ndarray:
    """网格搜索(步长 0.05, 和为 1): 仅在 active 腿上分配, 其余腿权重强制 0。

    objective in {max_sharpe, min_var}。用日度加权代理(R@w)快速评估 → 选权重;
    真实指标由 _combo_daily(月度再平衡)重算。返回全长(=LEG_NAMES)权重向量。
    """
    names = list(R.columns)
    idx = [names.index(n) for n in active]
    Rv = R.values
    best_w, best_score = None, None
    with np.errstate(all="ignore"):
        for wsub in _grid_weights(len(active), step=0.05):
            w = np.zeros(len(names))
            for k, i in enumerate(idx):
                w[i] = wsub[k]
            pr = Rv @ w
            sd = pr.std(ddof=1)
            if objective == "max_sharpe":
                score = (pr.mean() / sd) if sd > 1e-12 else -1e9
            else:  # min_var
                score = -sd
            if best_score is None or score > best_score:
                best_score, best_w = score, w
    return best_w


def _wvec(mapping: dict) -> np.ndarray:
    """按 {腿名: 权重} 构造全长权重向量(顺序 = LEG_NAMES)。"""
    w = np.zeros(len(LEG_NAMES))
    for n, v in mapping.items():
        w[LEG_NAMES.index(n)] = v
    return w


def _schemes(R: pd.DataFrame) -> dict:
    """构造 2016+ 权重方案。稳健族(等权/逆波动/最小方差)覆盖 全六型 / 核心三腿 /
    核心三腿+各第4腿; 另含缓慢增长单打基准(要打败的对象)与样本内最大 Sharpe(过拟合上界)。
    """
    vol = R.std(ddof=1)
    inv = 1.0 / vol.replace(0, np.nan)

    def eq(active):
        return _wvec({n: 1.0 / len(active) for n in active})

    def inv_vol(active):
        sub = inv[active]
        sub = sub / sub.sum()
        return _wvec(sub.to_dict())

    all6 = LEG_NAMES
    schemes = {
        "slow_only_ref": _wvec({"slow_growers": 1.0}),        # 基准: 要打败的对象
        # 核心三腿(slow/turn/asset)
        "equal3_core": eq(CORE3),
        "inv_vol3_core": inv_vol(CORE3),
        "min_var3_core": _search_subset(R, "min_var", CORE3),
        "slow40_3legs": _wvec({"slow_growers": 0.40, "turnarounds": 0.30, "asset_plays": 0.30}),
        "slow50_3legs": _wvec({"slow_growers": 0.50, "turnarounds": 0.25, "asset_plays": 0.25}),
        "max_sharpe3_core_OVERFIT": _search_subset(R, "max_sharpe", CORE3),
        # 全六型
        "equal6": eq(all6),
        "inv_vol6": inv_vol(all6),
        "min_var6": _search_subset(R, "min_var", all6),
        "max_sharpe6_OVERFIT": _search_subset(R, "max_sharpe", all6),
    }
    # 核心三腿 + 各第 4 腿(逆波动): 检验 2016+ 下多加一条腿是否有增量
    for extra in ["stalwarts", "fast_growers", "cyclicals"]:
        schemes[f"inv_vol_core3+{extra}"] = inv_vol(CORE3 + [extra])
    return schemes


def _robust(sname: str) -> bool:
    return sname != "slow_only_ref" and not sname.endswith("_OVERFIT")


def main():
    growth_long.reset_annual_cache()
    balance_long.reset_balance_cache()
    st_filter.reset_st_cache()

    log.info("加载 A bundle ...")
    t0 = time.time()
    bundle = data_cache.get_market("A") or data_cache._load_market_blocking("A")
    log.info("bundle loaded %d stocks in %.1fs", len(bundle.stock_data), time.time() - t0)

    start, end = WINDOW
    log.info("==== window since2016 (%s → %s) FRESH ====", start, end)
    sliced = data_cache.slice_bundle(bundle, None, start, end)
    log.info("sliced %d stocks iter[%d,%d]", len(sliced.stock_data),
             sliced.iter_start_idx, sliced.iter_end_idx)

    # 1) 各腿 2016+ 回测(单次 → 日/月/引擎指标)
    daily_s, monthly_s, eng_metrics, trades = {}, {}, {}, {}
    for name, cls, ov in LEGS:
        t1 = time.time()
        try:
            dr, mr, eng, ntr = _run_leg(sliced, cls, ov)
            if dr is not None and not dr.empty:
                daily_s[name] = dr
            if mr is not None and not mr.empty:
                monthly_s[name] = mr
            eng_metrics[name] = eng
            trades[name] = ntr
            log.info("[since2016/%s] %.1fs trades=%d annual=%s mdd=%s sharpe=%.2f days=%d",
                     name, time.time() - t1, ntr, _pct(eng.get("annualized_return")),
                     _pct(eng.get("max_drawdown")), eng.get("sharpe_ratio") or 0,
                     0 if dr is None else len(dr))
        except Exception as e:
            log.exception("[since2016/%s] FAILED: %s", name, e)
            eng_metrics[name] = {"error": str(e)}

    R = pd.DataFrame(daily_s).dropna(how="any")
    R = R[[n for n in LEG_NAMES if n in R.columns]]
    R.to_parquet(OUT_DIR / "legs_daily_returns_6_since2016.parquet")
    log.info("aligned R shape=%s", R.shape)

    bench_d = _csi300_daily_returns(start, end)
    bench_m = _csi300_monthly_returns(start, end)

    # 2) 单腿指标(自算日度, 与组合同口径)
    legs_metrics = {n: _metrics(R[n]) for n in R.columns}
    if bench_d is not None:
        legs_metrics["CSI300"] = _metrics(bench_d)

    # 3) 月度相关矩阵(含 CSI300)
    mret = dict(monthly_s)
    if bench_m is not None and not bench_m.empty:
        mret["CSI300"] = bench_m
    mret_df = pd.DataFrame(mret).dropna(how="any")
    corr = _corr_block(mret_df) if not mret_df.empty else None

    # 4) 权重方案 → 组合指标(月度再平衡)
    schemes = _schemes(R)
    scheme_rows = {}
    for sname, w in schemes.items():
        w = np.asarray(w, dtype=float)
        cr = _combo_daily(R, w)
        m = _metrics(cr)
        m["weights"] = {LEG_NAMES[i]: round(float(w[i]), 4) for i in range(len(LEG_NAMES))}
        m["robust"] = _robust(sname)
        scheme_rows[sname] = m

    report = {
        "since2016": {
            "window": [start, end],
            "note": "FRESH 口径: iter 从 2016 起新跑(全历史 daily 仅供指标预热)",
            "n_days": int(R.shape[0]),
            "n_months": int(len(mret_df)),
            "trades": trades,
            "engine_metrics": eng_metrics,   # 引擎日度口径(与各型研究报告交叉核对)
            "legs_metrics": legs_metrics,     # 自算日度口径(与组合可比)
            "corr": corr,
            "schemes": scheme_rows,
        }
    }
    (OUT_DIR / "portfolio_2016plus.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str)
    )
    _write_overview(report)
    log.info("ALL DONE -> portfolio_2016plus.json + portfolio_2016plus_overview.md")


def _verdict(blk) -> list:
    """裁决: 最优稳健组合 vs 缓慢增长单打, Sharpe/CAGR 是否双反超。"""
    sc = blk["schemes"]
    ref = sc.get("slow_only_ref", {})
    ref_sh, ref_cagr = ref.get("sharpe"), ref.get("cagr")
    robust = {k: v for k, v in sc.items() if v.get("robust")}
    if not robust or ref_sh is None:
        return ["> 裁决: 数据不足, 无法比较。", ""]
    best = max(robust.items(), key=lambda kv: (kv[1].get("sharpe") or -9))
    bname, bm = best
    beat_sh = (bm.get("sharpe") or -9) > ref_sh
    beat_cagr = (bm.get("cagr") or -9) > (ref_cagr or -9)
    if beat_sh and beat_cagr:
        line = (f"**✅ 找到更优组合**: `{bname}` Sharpe {bm['sharpe']:.2f} / CAGR "
                f"{_pct(bm['cagr'])} **双双跑赢**缓慢增长单打(Sharpe {ref_sh:.2f} / "
                f"CAGR {_pct(ref_cagr)})。")
    elif beat_sh:
        line = (f"**⚠️ 部分更优**: 最优稳健组合 `{bname}` Sharpe {bm['sharpe']:.2f} "
                f"高于单打 {ref_sh:.2f}, 但 CAGR {_pct(bm['cagr'])} 未超单打 {_pct(ref_cagr)}"
                f"(以降波动/回撤换取)。")
    else:
        line = (f"**❌ 未找到更优组合**: 2016+ 下最优稳健组合 `{bname}` "
                f"(Sharpe {bm['sharpe']:.2f} / CAGR {_pct(bm['cagr'])})的 Sharpe 未反超"
                f"缓慢增长单打(Sharpe {ref_sh:.2f} / CAGR {_pct(ref_cagr)}) —— "
                f"诚实窗口下, 组合化未能超越单打。")
    return ["## 裁决(2016+ FRESH)", "", "> " + line, ""]


def _write_overview(report):
    blk = report["since2016"]
    s, e = blk["window"]
    lines = [
        "# 林奇组合 · 2016+ 专用重优化 (Exp-4)",
        "",
        f"> 窗口 `since2016` ({s} → {e}, FRESH: iter 从 2016 起新跑), "
        f"n={blk['n_days']} 日 / {blk['n_months']} 月。",
        "> 缘起: 子区间审计证明 slow40 全期 Sharpe 优势几乎全来自 2010-2015 早期小样本"
        "(隐蔽资产早期 26.91%→成熟 8.28%)。本实验抛开早期幻象, 单看 2016+ 重新组队。",
        "> **腿池 = 全六型**(不预筛), 该不该剔由 2016+ 数据说话; 周期用诚实基线(非过拟合)。",
        "> 指标从「日度收益」自算(CAGR/年化波动/MaxDD/Sharpe rf=0), 单腿与组合同口径可比;",
        "> 组合 = 目标权重「月度再平衡」合成; `*_OVERFIT` 为样本内最优, 仅上界参考, **不推荐**。",
        "> 权重顺序 = slow/turn/asset/stalwarts/fast/cyclicals。",
        "",
    ]
    lines += _verdict(blk)

    # 单腿(自算日度 + 引擎口径交叉核对)
    lines += ["## 单腿 2016+ 表现", "",
              "| 腿 | 笔数 | CAGR(自算) | 年化波动 | MaxDD | Sharpe(自算) | 引擎CAGR | 引擎Sharpe |",
              "|---|---|---|---|---|---|---|---|"]
    for n in LEG_NAMES:
        m = blk["legs_metrics"].get(n, {})
        eng = blk["engine_metrics"].get(n, {})
        if not m:
            continue
        lines.append(
            f"| {n} | {blk['trades'].get(n, '-')} | {_pct(m.get('cagr'))} | "
            f"{_pct(m.get('ann_vol'))} | {_pct(m.get('max_drawdown'))} | "
            f"{(m.get('sharpe') or 0):.2f} | {_pct(eng.get('annualized_return'))} | "
            f"{(eng.get('sharpe_ratio') or 0):.2f} |")
    if "CSI300" in blk["legs_metrics"]:
        m = blk["legs_metrics"]["CSI300"]
        lines.append(f"| CSI300(基准) | - | {_pct(m.get('cagr'))} | {_pct(m.get('ann_vol'))} | "
                     f"{_pct(m.get('max_drawdown'))} | {(m.get('sharpe') or 0):.2f} | - | - |")
    lines.append("")

    # 相关矩阵
    corr = blk.get("corr")
    if corr:
        fmt = lambda v: "-" if v is None else f"{v:.2f}"
        cols = list(corr["matrix"].keys())
        lines += [f"## 月度相关矩阵 (n={blk['n_months']} 月, 平均非对角 {corr['avg_offdiag']})", "",
                  "| | " + " | ".join(cols) + " |",
                  "|" + "---|" * (len(cols) + 1)]
        for c in cols:
            row = " | ".join(fmt(corr["matrix"][c][c2]) for c2 in cols)
            lines.append(f"| **{c}** | {row} |")
        lines += ["", "最低相关对(Top5):"]
        for a, b, v in corr["pairs_sorted"][:5]:
            lines.append(f"- {a} × {b}: **{v}**")
        lines.append("")

    # 组合方案(按 Sharpe 降序)
    rows = sorted(blk["schemes"].items(), key=lambda kv: (kv[1].get("sharpe") or -9), reverse=True)
    lines += ["## 组合权重方案(按 Sharpe 降序)", "",
              "| 方案 | 稳健 | 权重(slow/turn/asset/stalw/fast/cycl) | CAGR | 年化波动 | MaxDD | Sharpe |",
              "|---|---|---|---|---|---|---|"]
    for sname, m in rows:
        w = m["weights"]
        wv = [w[n] for n in LEG_NAMES]
        flag = "基准" if sname == "slow_only_ref" else ("✓" if m.get("robust") else "⚠上界")
        lines.append(f"| {sname} | {flag} | {_wstr(wv)} | {_pct(m.get('cagr'))} | "
                     f"{_pct(m.get('ann_vol'))} | {_pct(m.get('max_drawdown'))} | "
                     f"{(m.get('sharpe') or 0):.2f} |")
    lines.append("")

    (OUT_DIR / "portfolio_2016plus_overview.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
