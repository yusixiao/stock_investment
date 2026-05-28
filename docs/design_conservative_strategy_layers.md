# 现金流保守策略 — 三层筛选模型(Roadmap)

> **状态**:三层 Roadmap 完成 + **CPA 原口径 buyer/seller 全部落地**(2026-05-28)
> - L1.R + L1.3 信誉评级 + L2 5 项 + L2.5 trap_rating + L3 仓位矩阵(4 档:full/p70/observe/skip)
> - **Buyer**:`CpaTierBatchBuyer`(tier-based 单股配比,N 周爬坡 `order_target_percent`)
> - **Seller**:CPA 7 条基本面止损(critical 清仓 / warning 减仓 50%)+ 入场 baseline
>
> **定位**:把 cpa Agent 的 11 步精算定性框架尽可能机械化,作为可全市场扫描的回测策略;**不等于** cpa LLM 精算 KK,只是其低成本近似。
>
> **创建**:2026-05-27 · **重大更新**:2026-05-28(L3 矩阵改 CPA 原口径 + 新 buyer/seller)· **维护**:有架构调整时同步更新

---

## 背景与目标

cpa Agent 的 phase3 流程(`phase3_quantitative.md` 11 步精算 + `phase3_valuation.md` JJ→KK 修正)依赖 LLM 读年报附注做定性判断,**不可机械化、不可批量回测**。

但其内部框架可以拆分出**可量化的近似版本**,用于:
1. 给 cpa Agent 提供候选股票池(5400+ → 几十只)
2. 作为 cpa LLM 真实精算结果的**回测基线对比**(回答「LLM 精算到底比粗算贵那么多 token,赚的多吗」)

设计成三层流水线 + 一个仓位矩阵。

---

## 三层完整定义

### Layer 1 — 估值因子(可机械化的 KK 近似)

#### L1 主因子:R / KK
- **粗算 R**(已实现):`R = NP × 近3年支付率均值 / 市值`,门槛 5.2%(II 4.7% + 安全边际 0.5pct)
  - `RF_CHINA_10Y = 0.027` / 港股口径见 `shared_tables.md`
  - 支付率口径:**年度 DPS / 年度 EPSJB**(同币种)
- **精算 KK**(未实现):cpa 11 步 V1-V5 / 6.X2 / 7 / 8 流程 → JJ → 周期修正 KK
  - 字段建议(若做):`excess_yield`(=JJ)/ `adj_excess_yield`(=KK)
  - 周期修正:`cycle_position` 参数(non_cyclical 默认 KK = JJ)

#### L1.3 信誉评级(✅ 已实现 2026-05-27)
三维度独立评分 A/B/C → 聚合 high / mid / low:

| 维度 | 数据源 | 口径 | A 阈值 | C 阈值 |
|---|---|---|---|---|
| 5 年营收 CV | `v_a_income.TOTAL_OPERATE_INCOME` | 总体方差(÷N)开方 / \|均值\| | < 0.15 | > 0.30 |
| 利润调整幅度 | `v_a_income.{PARENT_NETPROFIT, DEDUCT_PARENT_NETPROFIT}` | 5 年 \|归母−扣非\|/\|归母\| 均值 | < 0.10 | > 0.25 |
| λ warning | balance + cashflow(对齐 §13) | 4 项检查命中数(高杠杆/商誉/净现金/FCF) | 0 | ≥ 2 |

**聚合规则**:全 A → `high`,含 C → `low`,其余 → `mid`。数据缺失维度计 B(中性,不阻塞)。

**实现位置**:`strategies/utils/conservative.py::compute_credibility_rating / record_credibility_factors`(`ConservativeRoughStrategy.screen()` 末尾调用,只记录 factor,不筛除)。

**用途**:Layer 3 仓位矩阵的输入维度之一。

---

### Layer 2 — 价值陷阱识别

#### L2.1-L2.5 五项 disqualifier(已实现,**当前为硬否决**)

| 检查项 | 公式 | 否决条件 | 缺失策略 |
|---|---|---|---|
| 行业排除 | `INDUSTRY_NAME` 含「银行/保险/证券」 | 命中 | 缺失保守放行 |
| 商誉占比 | `GOODWILL / TOTAL_PARENT_EQUITY` | > 30% | 缺失保守放行;权益≤0 直接否决 |
| 净现金转负 | `MONETARYFUNDS − TOTAL_LIABILITIES` | < 0 | 缺失保守放行 |
| FCF 持续负 | 年报 `NETCASH_OPERATE − CONSTRUCT_LONG_ASSET` | 近 2 年都 ≤ 0 | 单年异常不算 |
| ROE 三年下降 | `(ROE_oldest − ROE_latest) / \|ROE_oldest\|`(`ROEJQ`,3 年年报) | > 30% | 缺失/不足 3 年/起始 ROE ≤ 0 → 放行 |

#### L2.5 trap_rating 聚合(✅ 已实现 2026-05-27)
把 L2.2-L2.5 四项检查(商誉/净现金/FCF/ROE 下降)从「硬否决」改为「软评分」:

```
触发数 0 → trap_rating = low(健康)
触发数 1 → trap_rating = mid(警惕)
触发数 ≥2 → trap_rating = high(高风险)
```

**金融股(L2.1)不参与软评分** — cpa 框架方法论盲点,始终硬否决。
**数据缺失维度计为「未触发」** — 对齐保守放行语义。

**实现位置**:`compute_trap_rating(ctx, symbol) → (rating, triggered_keys)` + `record_trap_rating(ctx, symbols)`。

**策略接入**:`ConservativeRoughStrategy.use_trap_rating_soft` 开关
- `False`(默认):走原 4 项硬否决,只额外记录 trap_rating factor
- `True`:跳过逐项硬否决,改为「rating == high 才剔除」(只杀 ≥2 项触发的)

**为什么要软化**:粗算版命中即出局会过度筛选(候选池可能过小);软化后让 Layer 3 决定「轻仓观察 vs 跳过」。

---

### Layer 3 — 仓位决策矩阵(✅ 2026-05-28 重写为 CPA 原口径 4 档)

#### L3.1 三维查找表

```
f(R_pct, credibility, trap_rating) → tier ∈ {full, p70, observe, skip}
```

> 粗算版用 R 替代 cpa 精算 KK,把"粗算安全边际"= R − threshold 对标 CPA 的 KK,口径与 `filter_by_r` 一致。

**仓位等级语义**(对齐 CPA 原文 `phase3_valuation.md` 仓位矩阵):
- `full` — 满仓买入(单股目标 = `max_per_stock_pct × 100%`)
- `p70` — 70% 仓位(估值便宜但信誉/陷阱有瑕疵,单股目标 = `max_per_stock_pct × 70%`)
- `observe` — 不买入,加观察池
- `skip` — 完全跳过

**用户口径(2026-05-28)**:KK 0.5~1.5pct 区间一律归 observe,**不再有 50% 这一档**。所以从原 5 档矩阵简化为 4 档(full / p70 / observe / skip)。`full_bonus = 1.5pct`(对齐 CPA 原文 KK ≥ 1.5pct 阈值)。

**查表规则**(优先级自上而下,首个命中即返回):

| 优先级 | 条件 | tier |
|---|---|---|
| 1 | `credibility == low` | **skip** |
| 2 | `R_pct < threshold_pct`(默认 5.2,对应 KK<0)| **skip** |
| 3 | `trap_rating == high` | **observe** |
| 4 | `R ≥ threshold + 1.5`(KK≥1.5)+ `cred=high` + `trap=low` | **full**(100%) |
| 5 | `R ≥ threshold + 1.5` + `cred=high` + `trap=mid` | **p70**(70%) |
| 6 | `R ≥ threshold + 1.5` + `cred=mid` + `trap=low` | **p70**(70%) |
| 7 | 其他(含 KK 0~1.5pct 区间) | **observe** |

**实现位置**:`strategies/utils/conservative.py::compute_position_tier` + `record_position_tier(ctx, symbols, *, include_observe=False)` + `TIER_PCT = {"full": 1.0, "p70": 0.7, "observe": 0.0, "skip": 0.0}` 常量。

#### L3.2 策略接入(2026-05-28 简化)
`ConservativeRoughStrategy` 现在**始终启用**仓位矩阵(buyer 需要 tier),不再有 `use_position_tier` / `include_observe` 开关。`screen()` 末尾固定调 `record_position_tier(include_observe=False)`,只保留 full + p70。

#### L3.3 Buyer:`CpaTierBatchBuyer`(2026-05-28 替换 MarketCapWeightedBatchBuyer)

**抛弃市值加权**,改用 CPA 原口径"绝对上限 + tier 按比例缩减":
- 单股目标仓位 = `max_per_stock_pct × TIER_PCT[tier]`
- 默认 `max_per_stock_pct = 0.20` → full=20% / p70=14% / observe=skip=0
- N 周等额爬坡:逐周 `order_target_percent(sym, target_pct × week_idx / buy_weeks)`
- tier 缺失 / observe / skip → 不分配
- seller 已平仓(`sym ∉ ctx.target_symbols`)→ 计划终止

**实现位置**:`strategies/utils/composite/cpa_tier_batch_buyer.py`。

> 注意:`MarketCapWeightedBatchBuyer.tier_weights` 参数**保留不删** — 其他价值策略(三因子等)仍使用 MarketCapWeightedBatchBuyer + tier_weights={"full":2,"half":1}。本策略独占新 buyer。

---

### Layer 4 — CPA 7 条基本面止损(✅ 2026-05-28 新增)

#### L4.1 入场 baseline 记录
`on_buy` 中首次见到 `ctx.new_symbols` 中的 sym 时调 `record_entry_baseline(ctx, sym)`,存入 `self._entry_baselines: dict[sym, dict]`:

| 字段 | 数据源 | 用途 |
|---|---|---|
| `debt_equity` | `TOTAL_LIABILITIES / TOTAL_PARENT_EQUITY`(balance) | 规则 4 对比 |
| `gross_margin` | `XSMLL`(financial annual,百分比) | 规则 6 对比 |
| `payout` | `compute_payout_ratio_3y`(0-1) | 规则 7 对比 |

任一字段缺失 → 该字段为 None,对应规则跳过(保守:不让数据缺失误杀持仓)。

#### L4.2 7 条止损规则(`phase3_valuation.md` §10.2 表格)

| # | 指标 | 触发条件 | 严重度 | reason_id |
|---|---|---|---|---|
| 1 | 净现金 | < 0 | critical | `net_cash_negative` |
| 2 | FCF yield | < 5% | critical | `fcf_yield_below_5pct` |
| 3 | FCF | 连续 2 期 < 0 | critical | `fcf_negative_2y` |
| 4 | 债务权益比 | > max(baseline×1.5, 1.0) | warning | `debt_equity_above_1.5x_baseline` |
| 5 | 营收同比 | < -20% | warning | `revenue_yoy_below_-20pct` |
| 6 | 毛利率 | < baseline × 0.8 | warning | `gross_margin_below_0.8x_baseline` |
| 7 | 支付率 | 较 baseline 相对降幅 > 30% | warning | `payout_decline_above_30pct` |

> 规则 4 兜底:baseline 缺失或 baseline × 1.5 < 1.0 时,使用绝对阈值 1.0。
>
> 规则 6/7:baseline 缺失 → 整条规则跳过(无对比基准)。

#### L4.3 严重度处理(用户口径)
- **critical**(任一触发)→ **清仓**(`order_shares(sym, -shares)` + `remove_target` + 清 baseline / warning 状态)
- **warning** → 减仓到当前持仓的 50%,且**每个 reason_id 只触发一次**(`_warning_seen[sym]: set[reason]` 去重)
  - 避免每根 bar runaway 减半导致流氓清仓
  - 新 reason 出现 → 再减一次半;同 reason 重复触发 → noop
- 全部未触发 → noop

**实现位置**:
- `strategies/utils/conservative_sell.py::cpa_fundamental_stop_loss(ctx, sym, baseline) → (severity, reasons)`
- `ConservativeRoughStrategy.on_sell` 集成 critical/warning 分支

---

## 与现状的实现差异

| 层 | Roadmap 设计 | 当前实现(粗算版) | 备注 |
|---|---|---|---|
| L1 主因子 | KK(精算 + 周期修正) | **R**(粗算) | 退化原因见下 |
| L1.3 | 三维信誉评级 | ✅ **已实现**(2026-05-27) | high/mid/low,记录 factor |
| L2.1-L2.5 | 5 项 disqualifier | ✅ 5 项**硬否决**(默认) | L2.1 永远硬否决 |
| L2.5 trap_rating | 聚合 0/1/≥2 → low/mid/high | ✅ **已实现**(2026-05-27,可选软评分) | 通过策略 flag 启用 |
| L3 工具+筛选 | 三维查表 + 4 档仓位 | ✅ **已实现**(2026-05-28 改 CPA 原口径 4 档) | full/p70/observe/skip,默认启用 |
| L3.3 Buyer | tier 加权 | ✅ **CpaTierBatchBuyer**(2026-05-28) | 抛弃市值加权,改 tier 按比例缩减 |
| L4 卖出 | CPA 7 条基本面止损 | ✅ **已实现**(2026-05-28) | critical 清仓 / warning 减半 + 入场 baseline |

---

## KK → R 退化决策日志

**2026-05-27 上午**:首次尝试 `ConservativeKKStrategy`(commit `ccd7b9a` + `d02d1d8`),按 KK 精算路径写,但很快意识到:

1. **KK 精算需要的字段不可机械化** — V1-V5 非经常分类要读年报附注、6.X2 隐性必要支出要读 MD&A,SQL/numpy 写不出
2. **回测要求每根 bar 全市场扫描** — LLM 调用成本无法承受(5400 只 × 每只数十 K token)
3. **粗算 R 已能把 5400 → 几十**作为候选池足够用,精算让 cpa Agent 单股深度做

**决策**:`git reset --hard 59597e8` 删 KK 两个 commit,改实现简化的 `ConservativeRoughStrategy`(粗算 R + 4 项硬否决,不做 L1.3 / L2.5 / L3)。

**长期路线**:L1.3 / L2.5 / L3 是可机械化的(都是数值聚合 + 查表),后续可补全;但 KK 精算本身放弃机械化,让 cpa Agent 处理。

---

## 实施顺序建议(若继续推进)

| 优先级 | 任务 | 说明 | 依赖 |
|---|---|---|---|
| ✅ | L2 加 ROE 三年下降 disqualifier | 补齐 5 项检查 | 2026-05-27 完成 |
| ✅ | L1.3 信誉评级实现 | 三维度计算 + 聚合 high/mid/low | 2026-05-27 完成 |
| ✅ | L2.5 trap_rating 聚合 | 把硬否决改为软评分(可选模式) | 2026-05-27 完成 |
| ✅ | L3 三维查表实现 | `compute_position_tier` + `record_position_tier` | 2026-05-27 完成 |
| ✅ | Buyer tier 加权(MarketCap) | `MarketCapWeightedBatchBuyer.tier_weights` | 2026-05-27 完成 |
| ✅ | L3 矩阵改 CPA 原口径 4 档 | full/p70/observe/skip,full_bonus 1.5pct | 2026-05-28 完成 |
| ✅ | `CpaTierBatchBuyer` | tier-based 单股配比,N 周 `order_target_percent` 爬坡 | 2026-05-28 完成 |
| ✅ | L4 CPA 7 条基本面止损 | critical/warning 严重度 + 入场 baseline | 2026-05-28 完成 |
| P2 | 真实回测验证 | 全市场跑 v3 → 与旧 MarketCap 版本对比超额收益 | 完整链路稳定后 |
| P3 | KK 精算路径(可选) | 如果有办法用 LLM batch 离线打标后入库 | LLM 离线管道 |

每个 P 阶段独立 commit 并跑全量回归,符合 TDD 铁律。

---

## 相关文件

### 已实现(粗算版,2026-05-28 状态)
- `strategies/utils/conservative.py` — 粗算 R + 5 项 disqualifier + L1.3 信誉评级 + L2.5 trap_rating + L3 仓位矩阵 4 档 + `TIER_PCT` 常量
- `strategies/utils/conservative_sell.py` — CPA 7 条基本面止损 + 入场 baseline 记录
- `strategies/utils/composite/cpa_tier_batch_buyer.py` — tier-based 单股配比分批买入器
- `strategies/examples/conservative_rough_strategy.py` — `ConservativeRoughStrategy`(monthly,frequency_overridable=False;参数:`min_dividend_years` / `r_threshold_pct` / `max_goodwill_ratio` / `max_roe_decline` / `use_trap_rating_soft` / `max_per_stock_pct` / `buy_weeks` / `max_holdings`)
- `backend/tests/test_utils_conservative.py` — R + L2.1-L2.4
- `backend/tests/test_utils_conservative_roe_decline.py` — L2 第 5 项
- `backend/tests/test_utils_conservative_credibility.py` — L1.3
- `backend/tests/test_utils_conservative_trap_rating.py` — L2.5
- `backend/tests/test_utils_conservative_position_tier.py` — L3 矩阵 4 档
- `backend/tests/test_utils_conservative_sell.py` — 25 测试(CPA 7 条止损规则 + baseline)
- `backend/tests/test_utils_cpa_tier_batch_buyer.py` — 13 测试(buyer)
- `backend/tests/test_conservative_rough_strategy.py` — 策略 screen 集成
- `backend/tests/test_conservative_rough_sell.py` — 9 测试(策略 on_sell + on_buy 集成)
- `backend/services/backtest/{data_cache,market_data,context,engine}.py` — 扩 balance/cashflow/income API + `order_target_percent`

### cpa 框架原文(只读参考)
- `backend/services/agent/agents/cpa/prompts/references/shared_tables.md` — R/II/Q 公式 + 税率表
- `backend/services/agent/agents/cpa/prompts/phase3_quantitative.md` — 11 步精算流程
- `backend/services/agent/agents/cpa/prompts/phase3_valuation.md` — JJ→KK 周期修正、仓位矩阵原型

### 历史决策追溯
- claude-mem 项目 key:`stock_investment`(完整路径 `/Users/11182300/PycharmProjects/stock_investment` 也存在,有早期记录)
- 关键观察记录时间:`2026-05-27T04:11:51.205Z` "Roadmap for ConservativeKKStrategy enhancements and value trap criteria"
