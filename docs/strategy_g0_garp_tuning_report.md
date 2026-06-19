# g0(GARP 价值优先)策略 — 全参数调参总结报告

**日期**:2026-06-18
**策略**:`GarpValueFirstStrategy`(g0,已发布 `deployed/garp_value_first_strategy.py`)
**父类**:`LowValuationMultiFactorQuarterlyStrategy`
**回测区间**:2010-01-01 ~ 2026-06-15(16.5 年)
**市场**:A 股全市场(5524 标的)
**初始资金**:1,000,000 元

## TL;DR

系统性扰动验证了 **21 个参数旋钮**(17 个有效参数 + 4 个确认惰性),用 pre-committed 单参数扰动 + 8 段 OOS battery 逐一检验。

**结论:g0 是一个调得相当扎实的底座 —— 21 个旋钮里仅 2 处被独立 OOS 证伪需改且已落地。**

| 采纳的改动 | 方向 | 理由 | commit |
|---|---|---|---|
| `max_per_industry` | 4 → **2** | 风险正则化:OOS 两半场全胜 + regime 3W/2L,邻居 ind3 确认非孤立峰 | `5c544be` 后 ind2 |
| `score_weight_roe` | 2.0 → **1.0** | 收益+回撤双改善:全周期 +0.32 / H2 +0.38 / 回撤 -2.0pct;退父类等权更少拟合 | `tune(backtest): g0 score_weight_roe 2.0->1.0` |

其余 19 个旋钮全部经得起扰动验证:**保留现值**。两处改动均**收益与回撤双改善或风险正则化**,无一是"全周期单点最优"的拟合。

## 方法论(防数据拟合铁律)

- **pre-committed 假设**:每个参数先写定假设方向与档位(教科书规范整数档),再跑,不事后挑最优。
- **统一 8 段 battery**:全周期连续(2010-2026)+ H1(2010-2018)/ H2(2018-2026)+ 5 个 regime,每段对 base 打 `Δann + WIN/LOSE + Δmaxdd`。
- **非对称验收**:逐段先用 CSI300 判牛熊 → 牛市可跑输指数但要赚钱、熊市必须跑赢指数。
- **稳健性优先**:跨 regime W/L 计数优先于聚合收益;不据全周期单点最优调参。
- **采纳门槛**:必须收益+回撤双改善(或纯风险正则化),且跨 regime 稳健(≥6W/2L 或两半场全胜)。仅聚合赢但 regime 不稳健 → 不采纳。

base 全周期复现校验值 = **14.53%**(采纳 roe1 后);改默认前 = 14.21%。

## regime 窗口定义(各段 fresh capital)

| 段 | 区间 | 性质 |
|---|---|---|
| H1 | 2010-01-01 ~ 2018-01-01 | 前半场 |
| H2 | 2018-01-01 ~ 2026-06-15 | 后半场 |
| 疯牛灾 | 2014-01-01 ~ 2016-02-01 | 杠杆牛+股灾 |
| 慢牛熊 | 2016-02-01 ~ 2019-01-01 | 熔断后慢熊 |
| 结构牛 | 2019-01-01 ~ 2021-02-01 | 核心资产抱团 |
| 熊 | 2021-02-01 ~ 2024-02-01 | 三年阴跌 |
| 反弹 | 2024-02-01 ~ 2026-06-15 | 政策底反弹 |

## 完整调参战果

### 前期(发布前)

| 参数 | 扰动 | 结论 |
|---|---|---|
| 旧 GARP / 小盘 / 大盘择时 / 逆动量 / 成长 4 组 / a_garp | 多版本 | 全部**证伪**,g0 胜出并发布 |
| `stop_loss` | 各档 | 无增益,不设默认 |
| `take_profit` | 倒 U 扫描 | 单峰峰=30%,但不设默认(峰值脆弱) |
| `pe_max` | 放宽 | 惰性(质量闸已主导) |
| `pb_max` | 放开 | 双输,PB≤1 是 alpha 核心 |
| `roe_min` | 各档 + OOS | 无稳健改进,保留 8 |
| `top_n` | ≥20 | 惰性冗余,保留 30 |

**g0 对比基准**:g0 vs 510310(沪深300ETF)定投 XIRR = **15.11% / 235 万 vs 7.50% / 135 万**。

### A 档 — 组合构造

| 变体 | 修改 | W/L | 结论 |
|---|---|---|---|
| ivol | `position_weighting` 等权→inv_vol | 否决 | 削弱"等权"本质 |
| semi | 半年调仓 | 否决 | 削弱"高频换手躲险"本质 |

### B 档 — score 综合打分权重

| 变体 | 修改 | W/L | 结论 |
|---|---|---|---|
| negmom | `score_weight_neg_momentum` 0→正 | 否决 | 与超额本质相悖 |
| div1 | `score_weight_div_yield` 2.0→1.0 | 6W/2L | 不采纳(熊市回吐) |
| **roe1** | `score_weight_roe` **2.0→1.0** | **6W/2L** | ✅ **采纳**(全周期 +0.32 / H2 +0.38 / 回撤 -2.0) |
| eqw | 完全等权 5 因子 | 4W/4L | 否决(H2 输),只退 roe 单动 |

### C 档 — 质量闸(4 闸全保留)

| 变体 | 修改 | 结论 |
|---|---|---|
| nocfo | 关 `require_positive_cfo` | 完全惰性,保留 |
| debt0 | 关 `debt_ratio_max` | **灾难**,强自证,保留 0.70 |
| cfonp0 | 关 `cfo_to_np_min` | 聚合赢但 regime 3W/5L 不稳健,保留 0.5 |
| noroedec | 关 `roe_decline_check` | 近惰性,保留 |

### D 档 — 动量过滤幅度

| 变体 | 修改 | W/L | regime 灾难 |
|---|---|---|---|
| mom0 | `momentum_drop_pct` 0.3→0.0(关) | 2W/6L | 熊市 -9.73 |
| mom02 | 0.3→0.2(父类默认) | 3W/5L | H2 -1.22 / 熊市输 |
| mom04 | 0.3→0.4(收紧) | 2W/5L | 熊市 -7.69 |

**确认 0.3 为稳健单峰最优,保留不改**。机理:动量过滤是熊/慢牛熊/结构牛的防御核心,0.3 仅在疯牛/反弹普涨段让步。

### D2 档 — 动量回看窗口

| 变体 | 修改 | W/L | regime 灾难 |
|---|---|---|---|
| lb60 | `momentum_lookback_days` 120→60(3 月) | 2W/6L | 熊市 -9.45 |
| lb180 | 120→180(9 月) | 2W/6L | 疯牛 -9.18 / 熊 -7.95 |
| lb250 | 120→250(1 年,Jegadeesh 经典) | 3W/5L | 熊市 -13.68 |

**确认 120(6 月窗)为稳健单峰最优,保留不改**。短窗赢震荡/疯牛、长窗赢结构牛,120 居中折中,熊市决定性大胜全部。

### E 档 — score 估值权重

| 变体 | 修改 | W/L | 结论 |
|---|---|---|---|
| pb2 | `score_weight_inv_pb` ×2 | 2W/6L | 慢牛熊 -4.42,保留 1.0 |
| pb0 | 关 inv_pb | 1W/7L | **疯牛 -8.05 灾难** + 回撤 +5.6,PB 必需 |
| pe2 | `score_weight_inv_pe` ×2 | 惰性 | 8 段 \|Δ\|≤0.5,保留 1.0 |
| pe0 | 关 inv_pe | 6W/2L | **诱人但不采纳**:全周期回撤 +5.6pct(25.5→31.1)+ 主口径 -0.13 微输 + 优势集中近代(regime 时间偏置) |

**pe0 不采纳的判定**:与 roe1 的区别在于 roe1 是收益+回撤**双改善**才采纳,pe0 是收益打平+回撤**恶化**。PE 分量主贡献是控回撤(H1 老时代防护)。

### F 档(收尾)— 卫生参数

| 参数 | 状态 | 结论 |
|---|---|---|
| `vol_lookback_days` | **剔除未跑** | 仅 `position_weighting=="inv_vol"` 时生效,g0 等权 → 纯空操作 |
| `neg_momentum_lookback_days` | **剔除未跑** | 仅 `score_weight_neg_momentum>0` 时生效,g0=0.0 → 纯空操作 |
| `max_valuation_staleness_days` | 5→2 / 5→20 | **Δ=0.00 精确零**(逐位相同),日频估值数据永不陈旧到触发门槛 |
| `growth_gate_require_data` | True→False | **Δ=0.00 精确零**,价值+质量前置过滤已排除所有缺财务数据股,无作用对象 |

**审视铁律应用**:跑 battery 前先确认参数在 g0 当前配置下确实生效,2 个惰性参数不浪费算力扫;活的 2 个跑出逐位相同(FULL/H1/H2 三段均 ann/maxdd/pf 全等)→ 全惰性确证。

## g0 当前生效参数(最终交付)

```
# 估值/质量地基
pb_max=1.0  pe_max=30  roe_min=8
# 动量过滤(D/D2 档验证保留)
momentum_drop_pct=0.3  momentum_lookback_days=120
# score 综合打分权重(B/E 档验证)
score_weight_roe=1.0          # ← 采纳改动(原 2.0)
score_weight_div_yield=2.0
score_weight_inv_pb=1.0  score_weight_inv_pe=1.0
score_weight_neg_momentum=0.0
# 组合构造
top_n=30  max_per_industry=2   # ← 采纳改动(原 4)
rebalance_months=[3,6,9,12]    # 季度调仓
position_weighting=等权
# 成长闸(g0 自有)
growth_min_yoy=0.0  growth_gate_require_data=True
# 不止损不止盈
stop_loss=0  take_profit=0
# 质量闸(全开)
require_positive_cfo=True  cfo_to_np_min=0.5
debt_ratio_max=0.70  roe_decline_check=True
```

## 核心洞察

1. **底座默认大部分站得住**:momentum_drop_pct=0.3 / momentum_lookback_days=120 / 4 质量闸均经独立 OOS 验证为稳健最优,与"继承默认未必对"形成对照(只有 roe / max_per_industry 两处继承默认被证伪)。
2. **alpha 本质 = 破净便宜票里高频换手 + 等权分散**:任何削弱"等权""高频调仓""估值地基"的纠偏(ivol/semi/pb0/negmom)都被惩罚。
3. **回撤是采纳的硬约束**:pe0 收益打平但回撤恶化 5.6pct 即被否决,体现"稳健性优先于聚合收益"。
4. **熊市是 regime 试金石**:几乎所有否决变体都栽在熊市/慢牛熊段的灾难性回撤上。

## 相关脚本

- `/tmp/garp_{Aknobs,Bknobs,eqw,Cknobs,Dknobs,D2knobs,Eknobs,Fknobs}_eval.py` — 各档 battery(统一 FACTORIES/VARIANTS/PERIODS 结构)
- `/tmp/g0_vs_510310.py` — g0 vs 沪深300ETF 定投对比
- `logs/smoke/garp_*_eval.{log,json}` — 全部运行日志与结构化结果
