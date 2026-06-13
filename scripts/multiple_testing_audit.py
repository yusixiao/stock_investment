"""多重检验 / data-snooping 审计(2026-06-14,TODOS 方法论层第 5 项)。

动机:HK GARP 冠军(R21_pe15)是在【同一段 2010-2026】上反复搜索 100+ 配置后选出的。
反复搜索会抬高"最优配置"的表观收益(选择偏差 / 多重检验):即便所有配置真实
收益相同,纯噪声也会让 best-of-N 看起来很突出。本脚本量化这个搜索预算并给出统计语境。

口径(关键):只统计 **factor 修复后(2026-06-13 11:00 之后)重跑的干净全期结果**,
即 plain `hk_garp_r{N}.json`(无 `_fixed`/`_h*`/`_p*`/`_H*`/`_annual` 后缀)。
所有这些都在同一区间 2010-01-01 → 2026-06-01、同一干净 factor 上跑,彼此严格可比。

纯读 JSON,不跑回测。输出 exported/hk_multiple_testing_audit.{md,json}。

用法:
  python scripts/multiple_testing_audit.py
"""

import json
import math
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).parent.parent
EXPORTED = ROOT / "exported"

# 干净全期结果文件名:hk_garp_r<纯数字>.json
CLEAN_RE = re.compile(r"^hk_garp_r(\d+)\.json$")

# 冠军 / 关键参照 tag
CHAMPION_TAG = "R21_pe15"
# "无便宜度过滤"基座(便宜度增益的对照锚点)
BASE_TAGS = {"R21_base", "R14_base", "R1_base"}


def _canon_overrides(ov):
    """把 overrides dict 规整为可哈希的标准串(排序键 + 规整数值),用于去重。"""
    if not isinstance(ov, dict):
        return "{}"
    items = []
    for k in sorted(ov):
        v = ov[k]
        if isinstance(v, float):
            v = round(v, 6)
        items.append(f"{k}={v}")
    return "|".join(items)


def load_clean_configs():
    """读所有干净全期 JSON,返回 (all_trials, unique_by_overrides)。

    all_trials: 每个 config 运行一条记录(含重复运行的同参数配置)。
    unique_by_overrides: 按 overrides 去重(同参数多次跑只算一次搜索)。
    """
    all_trials = []
    for path in sorted(EXPORTED.glob("hk_garp_r*.json")):
        if not CLEAN_RE.match(path.name):
            continue
        round_num = int(CLEAN_RE.match(path.name).group(1))
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        for entry in data:
            ar = entry.get("annualized_return")
            if ar is None:
                continue
            all_trials.append({
                "round": round_num,
                "tag": entry.get("tag", "?"),
                "annual": ar,
                "sharpe": entry.get("sharpe_ratio"),
                "mdd": entry.get("max_drawdown"),
                "overrides_key": _canon_overrides(entry.get("overrides", {})),
            })

    # 按 overrides 去重:同一参数集多轮重复跑,只保留一条(取 annual 作代表)
    unique = {}
    for t in all_trials:
        key = t["overrides_key"]
        # 同参数若多次出现,保留首个(干净数据下应一致)
        if key not in unique:
            unique[key] = t
    return all_trials, list(unique.values())


def main():
    all_trials, unique = load_clean_configs()
    if not unique:
        print("未找到干净全期 JSON,先跑 run_hk_garp_search.py")
        return

    annuals = sorted((u["annual"] for u in unique), reverse=True)
    n = len(annuals)
    mean = statistics.mean(annuals)
    median = statistics.median(annuals)
    std = statistics.pstdev(annuals)
    amax, amin = annuals[0], annuals[-1]

    def pct(x):
        return "-" if x is None else f"{x * 100:.2f}%"

    # 找冠军与基座
    champ = next((t for t in all_trials if t["tag"] == CHAMPION_TAG), None)
    bases = {t["tag"]: t for t in all_trials if t["tag"] in BASE_TAGS}

    # 冠军 z-score 与百分位(在 unique 分布上)
    champ_z = champ_pctile = None
    if champ:
        champ_z = (champ["annual"] - mean) / std if std > 0 else None
        n_below = sum(1 for a in annuals if a < champ["annual"])
        champ_pctile = 100.0 * n_below / n

    # 多重检验直觉:在 N 个独立标准正态抽样下,最大值的期望约 sqrt(2 ln N)。
    # 把它换算回收益尺度 = mean + std * sqrt(2 ln N),作为"纯噪声下 best-of-N 的
    # 期望表观最优"的粗略基准。冠军若显著高于它才算超出运气可解释范围。
    expected_max_z = math.sqrt(2.0 * math.log(n)) if n > 1 else 0.0
    expected_max_return = mean + std * expected_max_z

    # 超额(冠军 vs 无便宜度过滤基座)
    base_ref = bases.get("R21_base")
    excess_over_base = (champ["annual"] - base_ref["annual"]) if (champ and base_ref) else None

    summary = {
        "scope": "factor 修复后干净全期(2010-01-01→2026-06-01)plain hk_garp_r{N}.json",
        "n_trials_run": len(all_trials),
        "n_unique_configs": n,
        "distribution": {
            "mean": mean, "median": median, "pstd": std,
            "max": amax, "min": amin,
        },
        "champion": champ,
        "champion_z": champ_z,
        "champion_percentile": champ_pctile,
        "expected_max_z_under_null": expected_max_z,
        "expected_max_return_under_null": expected_max_return,
        "excess_over_base_r21": excess_over_base,
        "bases": bases,
    }
    (EXPORTED / "hk_multiple_testing_audit.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2))

    L = []
    L.append("# HK GARP 多重检验 / data-snooping 审计")
    L.append("")
    L.append("> 口径:仅统计 **factor 修复后(2026-06-13 11:00+)重跑的干净全期结果** "
             "(plain `hk_garp_r{N}.json`,排除 `_fixed`/`_h*`/`_p*`/`_H*`/`_annual`)。")
    L.append("> 全部在同一区间 2010-01-01 → 2026-06-01、同一干净 factor 上跑,严格可比。")
    L.append("")
    L.append("## 1. 搜索预算(data-snooping budget)")
    L.append("")
    L.append(f"- 干净全期**运行次数**(含同参数重复跑):**{len(all_trials)}**")
    L.append(f"- 去重后**唯一参数配置数**:**{n}**")
    L.append("- ⚠️ 这是在【同一段历史】上的搜索次数。搜得越多,表观最优越容易是噪声。")
    L.append("  真正的防线是**样本外验证**(已做:R16/R21 H1→H2 + 2/4/8/16 切片,见 walk-forward)。")
    L.append("")
    L.append("## 2. 全期年化收益分布(唯一配置)")
    L.append("")
    L.append(f"| 统计量 | 值 |")
    L.append(f"|---|---|")
    L.append(f"| 配置数 N | {n} |")
    L.append(f"| 均值 | {pct(mean)} |")
    L.append(f"| 中位数 | {pct(median)} |")
    L.append(f"| 标准差(总体) | {pct(std)} |")
    L.append(f"| 最大 | {pct(amax)} |")
    L.append(f"| 最小 | {pct(amin)} |")
    L.append("")
    L.append("## 3. 冠军在分布中的位置")
    L.append("")
    if champ:
        L.append(f"- 冠军 **{CHAMPION_TAG}** 全期年化 = **{pct(champ['annual'])}**")
        L.append(f"- z-score = (冠军 − 均值) / 标准差 = **{champ_z:.2f}σ**")
        L.append(f"- 百分位 = **{champ_pctile:.1f}%**(高于 {champ_pctile:.1f}% 的配置)")
        if excess_over_base is not None:
            L.append(f"- 相对无便宜度过滤基座 `R21_base`({pct(base_ref['annual'])})"
                     f"超额 = **+{excess_over_base * 100:.2f}pct**")
    else:
        L.append(f"- ⚠️ 未在干净 JSON 中找到 {CHAMPION_TAG}")
    L.append("")
    L.append("## 4. 多重检验语境(best-of-N 的运气上界)")
    L.append("")
    L.append(f"- 若所有配置真实收益相同、仅差噪声,N={n} 次抽样下表观最优的期望 z ≈ "
             f"√(2·lnN) = **{expected_max_z:.2f}σ**。")
    L.append(f"- 换算回收益尺度 ≈ 均值 + {expected_max_z:.2f}·标准差 = **{pct(expected_max_return)}**"
             f"(纯运气可解释的「最好成绩」粗略上界)。")
    if champ:
        verdict = ("**高于**" if champ["annual"] > expected_max_return else "**未明显高于**")
        L.append(f"- 冠军 {pct(champ['annual'])} {verdict}该运气上界 {pct(expected_max_return)}。")
        if champ["annual"] > expected_max_return:
            L.append("  → 冠军超额**超出**单纯多重检验噪声可解释的范围(必要非充分条件,仍以样本外为准)。")
        else:
            L.append("  → 冠军优势可能部分来自搜索运气,**必须**以样本外结果为最终依据。")
    L.append("")
    L.append("## 5. 结论与免责")
    L.append("")
    L.append(f"1. **搜索预算透明**:本研究在同一段历史上跑了 {len(all_trials)} 次回测、"
             f"{n} 个唯一配置;报告冠军时必须附带此数。")
    L.append("2. **样本内排名 ≠ 真实优势**:第 3-4 节是样本内统计,只说明冠军在搜索池里有多突出,"
             "**不能**单独作为「非过拟合」的证据。")
    L.append("3. **唯一可信的防线 = 样本外**:R21_pe15 已通过 H1(2010-2018 训练)→ "
             "H2(2018-2026 封存测试)#2/5、2/4/8/16 切片抗跌 Score 全场第一(见 "
             "`hk_walk_forward.md` / `hk_garp_r21_H{1,2}_overview.md`),这才是反 data-snooping 的核心论据。")
    L.append("4. **便宜度族(PE≤15~25)整体稳健**,统计上 pe15/pe20/pe25 不可强区分;"
             "对外报告应说「PE 上限便宜度族」而非「pe15 单点最优」。")
    (EXPORTED / "hk_multiple_testing_audit.md").write_text("\n".join(L))

    print(f"OK: {len(all_trials)} trials, {n} unique configs")
    print(f"分布 mean={pct(mean)} std={pct(std)} max={pct(amax)}")
    if champ:
        print(f"冠军 {CHAMPION_TAG}={pct(champ['annual'])} z={champ_z:.2f} pctile={champ_pctile:.1f}%")
    print(f"运气上界(best-of-N)≈ {pct(expected_max_return)}")
    print("→ exported/hk_multiple_testing_audit.{md,json}")


if __name__ == "__main__":
    main()
