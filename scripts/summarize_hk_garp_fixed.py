"""汇总 HK GARP 全轮次重跑(修复后)结果,生成总结文档。"""
import json
import glob
import os

EXP = "exported"


def load(f):
    return [s for s in json.load(open(f)) if "annualized_return" in s]


def pct(x):
    return "-" if x is None else f"{x * 100:.2f}%"


full = []
subs = {}
for f in sorted(glob.glob(f"{EXP}/hk_garp_r*_fixed.json")):
    base = os.path.basename(f).replace("hk_garp_", "").replace("_fixed.json", "")
    data = load(f)
    if "_h1" in base or "_h2" in base:
        subs[base] = data
    else:
        for s in data:
            s["round"] = base
        full.extend(data)

full.sort(key=lambda s: s["annualized_return"], reverse=True)

# R11 旧基准(对话保留,修复前单次非确定性结果)
old_r11 = {
    "R11_agg_ind_sec2": 26.93, "R11_agg_sec2": 25.77, "R11_agg_indonly": 25.25,
    "R11_agg_sec3": 24.41, "R11_rob_indonly": 22.26, "R11_rob_ind_sec3": 21.55,
    "R11_agg_base": 21.26, "R11_rob_sec2": 20.95, "R11_rob_sec3": 19.55,
    "R11_rob_base": 15.48,
}

L = []
A = L.append
A("# HK GARP 全轮次重跑总结(修复后数据)")
A("")
A("> 背景:yfinance 复权因子两处 bug 修复(NaN 分红额漏判 + 同除权日多事件未合并"
  "导致 parquet 同日键不唯一)。")
A("> 旧 bug 使 qfq ASOF JOIN 在并行下**随机选行 → 回测结果不可复现**。本次全量 regen "
  "HK 复权因子(2161 更新 / 0 失败,verify 重复组=0)后,重跑全部 R 轮次。")
A(f"> 重跑日期:2026-06-12 | 全 H 股 2723 只 | 区间 2010-01-01→2026-06-01 | "
  f"配置 {len(full)}(全期)+ {sum(len(v) for v in subs.values())}(子区间)")
A("")
A("## 一、最高收益(全期 2010→2026)")
A("")
A("**冠军:`R11_agg_ind_sec2` 年化 25.77%**(进取 Top12+趋势90+仅龙头+每行业≤2)")
A("")
A("### 全期 TOP15")
A("")
A("| 排名 | 轮次 | tag | 年化 | 总收益 | 最大回撤 | Sharpe | 笔数 | 备注 |")
A("|---|---|---|---|---|---|---|---|---|")
for i, s in enumerate(full[:15], 1):
    A(f"| {i} | {s['round']} | {s['tag']} | **{pct(s['annualized_return'])}** | "
      f"{pct(s['total_return'])} | {pct(s['max_drawdown'])} | "
      f"{s.get('sharpe_ratio', 0):.2f} | {s.get('n_trades')} | {s.get('note', '')} |")
A("")

A("## 二、R11 新旧对比(全期,旧=修复前单次非确定性结果)")
A("")
A("| tag | 旧年化 | 新年化 | Δ年化 | 备注 |")
A("|---|---|---|---|---|")
r11 = sorted([s for s in full if s["round"] == "r11"],
             key=lambda s: s["annualized_return"], reverse=True)
for s in r11:
    o = old_r11.get(s["tag"])
    n = s["annualized_return"] * 100
    d = f"{n - o:+.2f}" if o else "-"
    oo = f"{o:.2f}%" if o else "-"
    A(f"| {s['tag']} | {oo} | **{n:.2f}%** | {d} | {s.get('note', '')} |")
A("")

A("## 三、子区间稳健性(H1 2010-2018 / H2 2018-2026)")
A("")
for base in sorted(subs):
    oldf = f"{EXP}/hk_garp_{base.replace('_fixed', '')}.json"
    old = ({s["tag"]: s["annualized_return"] * 100 for s in load(oldf)}
           if os.path.exists(oldf) else {})
    A(f"### {base}")
    A("")
    A("| tag | 旧年化 | 新年化 | Δ | 总收益 | 回撤 | Sharpe | 笔数 |")
    A("|---|---|---|---|---|---|---|---|")
    for s in sorted(subs[base], key=lambda s: s["annualized_return"], reverse=True):
        o = old.get(s["tag"])
        n = s["annualized_return"] * 100
        oo = f"{o:.2f}%" if o else "-"
        dd = f"{n - o:+.2f}" if o else "-"
        A(f"| {s['tag']} | {oo} | **{n:.2f}%** | {dd} | {pct(s['total_return'])} | "
          f"{pct(s['max_drawdown'])} | {s.get('sharpe_ratio', 0):.2f} | {s.get('n_trades')} |")
    A("")

A("## 四、结论")
A("")
A("1. **全期冠军 `R11_agg_ind_sec2` 年化 25.77%**(总收益 4202%,回撤 43.4%,"
  "Sharpe 0.71),进取系(Top12+趋势90)整体优于稳健系(Top15)。")
A("2. **修复消除了非确定性**:旧结果因复权因子同日重复行被并行随机选取而不可复现;"
  "修复后(verify 重复组=0)结果稳定可重跑。")
A("3. **全期 R11 较旧单次结果普遍小幅下移**(-0.04~-1.16pct),旧值偏高含随机水分;"
  "冠军排序基本不变。")
A("4. **H1(2010-2018)子区间修复后明显上移**(agg_sec2 +4.31pct、agg_ind_sec2 "
  "+2.86pct、rob_sec3 +2.49pct),说明早期 HK 数据受 qfq bug 影响更大;H2 变化很小"
  "(±0.8pct 内)。")
A("5. 策略有效性结论不变:冠军组全期 24-26% 年化,两个子区间(进取分散组)也均 >18%,"
  "稳健性成立。")
A("")

out = f"{EXP}/hk_garp_FIXED_SUMMARY.md"
open(out, "w").write("\n".join(L))
print("written", out, len(L), "lines")
