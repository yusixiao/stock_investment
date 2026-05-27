# 现金流保守策略 — 三层筛选模型(Roadmap)

> **状态**:L1.R + L1.3 + L2 硬否决已落地(`ConservativeRoughStrategy`),L2.5 / L3 仓位矩阵待补。
> **定位**:把 cpa Agent 的 11 步精算定性框架尽可能机械化,作为可全市场扫描的回测策略;**不等于** cpa LLM 精算 KK,只是其低成本近似。
> **创建**:2026-05-27 · **维护**:有架构调整时同步更新

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

#### L2.1-L2.4 四项 disqualifier(已实现,**当前为硬否决**)

| 检查项 | 公式 | 否决条件 | 缺失策略 |
|---|---|---|---|
| 行业排除 | `INDUSTRY_NAME` 含「银行/保险/证券」 | 命中 | 缺失保守放行 |
| 商誉占比 | `GOODWILL / TOTAL_PARENT_EQUITY` | > 30% | 缺失保守放行;权益≤0 直接否决 |
| 净现金转负 | `MONETARYFUNDS − TOTAL_LIABILITIES` | < 0 | 缺失保守放行 |
| FCF 持续负 | 年报 `NETCASH_OPERATE − CONSTRUCT_LONG_ASSET` | 近 2 年都 ≤ 0 | 单年异常不算 |

> ⚠️ 原 Roadmap 还有第 5 项 **ROE 三年下降 > 30%**,本会话粗算版未实现,可在 L2.5 补全时一起加。

#### L2.5 trap_rating 聚合(未实现)
把 4(或 5)项检查从「硬否决」改为「软评分」:

```
触发数 0 → trap_rating = low(健康)
触发数 1 → trap_rating = mid(警惕)
触发数 ≥2 → trap_rating = high(高风险)
```

**为什么要软化**:粗算版命中即出局会过度筛选(候选池可能过小);软化后让 Layer 3 决定「轻仓观察 vs 跳过」。

---

### Layer 3 — 仓位决策矩阵(未实现)

#### L3.1 三维查找表

```
f(KK, credibility, trap_rating) → tier ∈ {full, half, observe, skip}
```

**仓位等级语义**:
- `full` — 满仓买入(策略权重最高)
- `half` — 半仓买入(估值便宜但有瑕疵)
- `observe` — 不买入,加观察池
- `skip` — 完全跳过

**查找表草案**(待回测验证后定稿):

| KK 区间 | credibility | trap_rating | tier |
|---|---|---|---|
| ≥ 安全边际+2pct | high | low | **full** |
| ≥ 安全边际+2pct | mid | low | **half** |
| ≥ 安全边际 | high | low | **half** |
| ≥ 安全边际 | high | mid | **half** |
| ≥ 安全边际 | * | high | **observe** |
| < 安全边际 | * | * | **skip** |
| 任意 | low | * | **skip** |

> 草案逻辑:估值便宜 + 信誉好 + 无陷阱 → 满仓;只要任何一项掉档,逐级降仓;高陷阱评级直接限仓 observe。

#### L3.2 策略输出
- `ConservativeRoughStrategy` 默认 `tier ∈ {full, half}` 进入买入池
- 提供 `include_observe` flag 可放宽到 `observe`(用于研究观察)
- `Buyer` 接收 tier 做权重分配:full 权重 2 / half 权重 1

---

## 与现状的实现差异

| 层 | Roadmap 设计 | 当前实现(粗算版) | 备注 |
|---|---|---|---|
| L1 主因子 | KK(精算 + 周期修正) | **R**(粗算) | 退化原因见下 |
| L1.3 | 三维信誉评级 | ✅ **已实现** | high/mid/low,记录 factor |
| L2.1-L2.4 | 4 项 + 软评分 | 4 项**硬否决** | 命中即出局 |
| L2.5 | trap_rating 聚合 | **未实现** | 阻塞 L3 |
| L3 | 三维查表 + 4 档仓位 | **未实现**(等权满仓) | 阻塞最终选股质量 |

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
| P0 | L2 加 ROE 三年下降 disqualifier | 补齐 5 项检查 | 无 |
| ✅ | L1.3 信誉评级实现 | 三维度计算 + 聚合 high/mid/low | 2026-05-27 完成 |
| P1 | L2.5 trap_rating 聚合 | 把硬否决改为软评分 | L2 完整 5 项 |
| P2 | L3 三维查表实现 | 工具函数 `compute_position_tier(R, cred, trap)` | L1.3 + L2.5 |
| P2 | Buyer 接收 tier 做权重分配 | 改造 `MarketCapWeightedBatchBuyer` | L3 |
| P3 | KK 精算路径(可选) | 如果有办法用 LLM batch 离线打标后入库 | LLM 离线管道 |

每个 P 阶段独立 commit 并跑全量回归,符合 TDD 铁律。

---

## 相关文件

### 已实现(粗算版)
- `strategies/utils/conservative.py` — 粗算 R + 4 项 disqualifier + L1.3 信誉评级
- `strategies/examples/conservative_rough_strategy.py` — `ConservativeRoughStrategy` 类(monthly,frequency_overridable)
- `backend/tests/test_utils_conservative.py` — 18 测试(R + L2)
- `backend/tests/test_utils_conservative_credibility.py` — 23 测试(L1.3)
- `backend/tests/test_conservative_rough_strategy.py` — 7 测试(策略集成)
- `backend/services/backtest/{data_cache,market_data,context,engine}.py` — 扩 balance/cashflow/income API

### cpa 框架原文(只读参考)
- `backend/services/agent/agents/cpa/prompts/references/shared_tables.md` — R/II/Q 公式 + 税率表
- `backend/services/agent/agents/cpa/prompts/phase3_quantitative.md` — 11 步精算流程
- `backend/services/agent/agents/cpa/prompts/phase3_valuation.md` — JJ→KK 周期修正、仓位矩阵原型

### 历史决策追溯
- claude-mem 项目 key:`stock_investment`(完整路径 `/Users/11182300/PycharmProjects/stock_investment` 也存在,有早期记录)
- 关键观察记录时间:`2026-05-27T04:11:51.205Z` "Roadmap for ConservativeKKStrategy enhancements and value trap criteria"
