# opt64 策略搬运规格书：GARP深价值动量策略

> 目标读者：负责将策略搬运到 `stock_investment` 平台的 AI
> 原始代码：`~/workspace/港股回测/code/strategies/garp_opt64.py`
> 冠军记录：`~/workspace/港股回测/results/runs/CHAMPION_opt64.md`
> 平台分支：`feat/hk-eastmoney-migration`
> 编写日期：2026-10-03

---

## 一、策略一句话

**买入便宜的好公司，且它们正在被市场认可（动量启动）。**

---

## 二、业绩（2015-01-01 ~ 2026-09-30）

| 指标 | 数值 |
|---|---|
| 年化复合收益 | **32.63%** |
| 夏普比率 | 1.16 |
| 最大回撤 | -31.38% |
| 最差年度 | -6.4%（2016）|
| 涨跌比 | 13.76x |
| 去最好年后 | 25.39%（去掉2017年+112.9%）|

年度收益：2016 -6.4%、2017 +112.9%、2018 +12.5%、2019 -0.2%、2020 +38.7%、2021 +92.6%、2022 +17.1%、2023 +7.9%、2024 +19.1%、2025 +86.5%、2026 +21.9%（未完整年）

**9/11年盈利，熊市平均+7.7%**

---

## 三、选股条件（信号日全部满足）

### 3.1 估值：PE ≤ 12

```
PE = close_raw26 / (eps_adj × 1.1)
```

- `close_raw26`：信号日收盘价（Eastmoney原始价，拆股已调整到2026）
- `eps_adj`：最近可见年报的每股收益（CNY）
- `×1.1`：CNY→HKD汇率换算（固定值，近似）
- 要求：`0 < PE ≤ 12`
- **PIT说明**：未来因子在分子分母中抵消，PIT干净

### 3.2 成长：净利润5年CAGR ≥ 15%

```
CAGR = (NP_最新 / NP_5年前)^0.2 - 1 ≥ 15%
```

- 需要**6个连续年报**（年份差严格为1，共5年间隔）
- `NP_最新 > 0` 且 `NP_5年前 > 0`（剔除亏损）
- 剔除极端值：`|CAGR| > 200%` 视为数据错误，跳过
- **PIT说明**：只用 `visible_date ≤ 信号日` 的年报

### 3.3 成长：营收5年CAGR ≥ 10%

```
CAGR = (REV_最新 / REV_5年前)^0.2 - 1 ≥ 10%
```

- 同上：6个连续年报，`REV > 0`，剔除 `|CAGR| > 200%`

### 3.4 质量：ROE ≥ 10%

```
10% ≤ ROE < 1000%
```

- 下限10%：确保盈利质量
- 上限1000%：剔除极端值（数据错误）
- 同时要求 `BPS > 0`（每股净资产为正）

### 3.5 动量：6个月收益 > 20%

```
mom6 = close_adj.pct_change(126) > 20%
```

- `close_adj`：后复权价（分红+拆股已调）
- 126个交易日 ≈ 6个月
- **PIT说明**：`close_adj` 用信号日及之前数据计算，PIT干净

### 3.6 动量：1个月收益 > 0

```
mom1 = close_adj.pct_change(21) > 0
```

- 21个交易日 ≈ 1个月
- 作用：防反转（6个月强但1个月转弱的剔除）

### 3.7 趋势：收盘价 > MA90

```
MA90 = mean(P_adj(t-89)...P_adj(t))，其中 P_adj(i) = close_traded(i) × div_factor(i) / div_factor(t)
```

- `close_traded`：真实交易价（未复权）
- `div_factor`：分红因子
- **PIT关键**：MA90必须用PIT分红调整价，不能用静态复权价
  - 公式：`P_adj(历史某日) = 当日真实价 × 当日因子 / 信号日因子`
  - 这样历史价格被调整到与信号日同一口径
- 要求：`close_traded(信号日) > MA90`
- 窗口：过去90个交易日（含信号日）

### 3.8 流动性：60日均成交额 ≥ 1000万

```
turn60 = mean(close_traded × volume, 60天) ≥ 10,000,000
```

- 用**真实价**（非复权）× 成交量
- 60个交易日滚动平均
- 单位：港币

### 3.9 PEG过滤（保留但冗余）

```
PEG = PE / (净利润CAGR × 100) ≤ 1.5
```

- **注意**：在 PE≤12 + CAGR≥15% 约束下，PEG≤1.5 数学上几乎恒成立
- 原始代码保留此过滤，实测35期0筛出
- **搬运时可保留（保持逻辑一致）或注明冗余**

---

## 四、排序与组合构建

### 4.1 排序：按6个月动量降序

```python
# 对通过PEG过滤的候选，按mom6降序排序
mom_s = {t: mom6[t] for t in candidates}.sort(descending)
```

- **核心洞察**：动量强度 > 静态估值指标，强动量 = 市场共识形成

### 4.2 行业分散：每行业 ≤ 2只

```python
selected = []
count = {}
for tic in mom_s.index:  # 按动量降序遍历
    industry = ind[tic]
    if count.get(industry, 0) >= 2:
        continue
    count[industry] = count.get(industry, 0) + 1
    selected.append(tic)
    if len(selected) >= 12:
        break
```

- 行业分类：`industry_user_v1.parquet`（静态）
- **注意**：行业分类是静态的，仅用于分散约束，不影响信号逻辑

### 4.3 权重：等权

- 每只 `1/12` ≈ 8.33%
- 共12只

---

## 五、调仓规则

### 5.1 调仓日：每年4/7/10月的首个交易日

```python
def first_trading_days(dates):
    out = []
    for y in range(2015, 2027):
        for m in (4, 7, 10):
            cands = dates[(dates.year == y) & (dates.month == m)]
            if len(cands):
                out.append(cands[0])  # 当月首个交易日
    return sorted(out)
```

- **经济逻辑**：年报披露后（3月底前），4月调仓能用上最新年报
- 7月、10月：季度更新

### 5.2 执行时点：T+1

- 信号日收盘后生成信号
- **T+1日执行**（开盘价或收盘价，平台按Broker默认）
- **PIT铁律**：信号日d只允许用 `≤d` 的数据

---

## 六、成本与币种（回测用）

| 项目 | 参数 |
|---|---|
| 滑点 | 0.2% |
| 卖出税 | 0.1%（印花税）|
| 最低佣金 | 5港币 |
| 分红税 | 10% |
| 汇率 | CNY→HKD固定1.1（近似，实际1.05-1.15波动）|

---

## 七、平台搬运指南

### 7.1 目标接口

```python
# backend/services/backtest/strategy_base.py
class Strategy:
    name: str = "opt64_garp_momentum"
    description: str = "..."
    params: dict = {...}  # 参数配置化
    frequency: str = "daily"  # 或自定义调仓逻辑

    def screen(self, ctx, symbols: list[str]) -> list[str]:
        """返回选中的12只代码"""
        ...

    def on_buy(self, ctx) -> None:
        ...

    def on_sell(self, ctx) -> None:
        ...
```

### 7.2 Context可用方法

```python
ctx.get_price(symbol)              # 当前价
ctx.get_history(symbol, n)         # n日历史
ctx.get_valuation(symbol)          # 估值数据（含PE）
ctx.get_financial_annual(symbol)   # 年报财务
ctx.get_financial_annual_history(symbol, n)  # n年年报历史
ctx.get_dividend(symbol)           # 分红数据
```

### 7.3 数据映射

| 研究侧 | 平台侧 | 说明 |
|---|---|---|
| `close_raw26` | `ctx.get_price()` 或 daily表`close` | Eastmoney原始价 |
| `close_adj` | DuckDB `query_qfq_kline()` | 前复权价 |
| `close_traded` | daily表`close` | 真实交易价 |
| `div_factor` | adjust_factor表`foreAdjustFactor` | 分红因子 |
| `eps_adj` | `ctx.get_financial_annual()` | 年报EPS |
| `mom6/mom1` | 需自行计算 | 用`get_history`取126/21日 |
| `MA90` | 需自行计算 | 注意PIT分红调整公式 |
| `turn60` | 需自行计算 | `close × volume`滚动60日 |
| 行业分类 | 待确认 | 平台是否有行业数据？ |

### 7.4 参数配置化

```python
params = {
    "pe_max": 12,
    "np_cagr_min": 0.15,
    "rev_cagr_min": 0.10,
    "roe_min": 10.0,
    "roe_max": 1000.0,
    "mom6_min": 0.20,
    "mom1_min": 0.0,
    "ma_window": 90,
    "turnover_min": 10_000_000,
    "turnover_window": 60,
    "top_n": 12,
    "max_per_industry": 2,
    "rebalance_months": [4, 7, 10],
    "cny_to_hkd": 1.1,
}
```

### 7.5 关键PIT检查点

搬运时必须验证：

1. [ ] **财务可见日**：`visible_date = report_date + 90天`，只用`visible_date ≤ 信号日`的年报
2. [ ] **MA90的PIT**：`P_adj(i) = close(i) × factor(i) / factor(信号日)`，不能用静态复权价
3. [ ] **动量PIT**：`mom6/mom1`用信号日及之前数据计算
4. [ ] **T+1执行**：信号日收盘后生成，下一交易日执行
5. [ ] **CAGR连续性**：6个年报年份严格连续（差为1）

### 7.6 建议文件位置

```
backend/services/backtest/strategies/deployed/hk_garp_opt64_strategy.py
```

参考现有：`backend/services/backtest/strategies/deployed/hk_garp_strategy.py`

---

## 八、验证标准

搬运完成后，用平台回测引擎跑2015-2026，对比：

| 指标 | 目标值 | 容差 |
|---|---|---|
| CAGR | 32.63% | ±1% |
| Sharpe | 1.16 | ±0.1 |
| MDD | -31.38% | ±2% |
| 年调仓次数 | 35次 | 精确 |

**注意**：平台用前复权、研究侧用后复权，绝对收益可能有微小差异，但**收益率序列**应高度一致。

---

## 九、已知近似与取舍

1. **行业分类静态**：仅用于分散约束，不影响核心逻辑
2. **财务可见日+90天**：保守估计，实际披露可能更早
3. **汇率固定1.1**：实际1.05-1.15波动，影响PE约±5%
4. **分红税10%**：统一假设
5. **PEG冗余**：PE≤12+CAGR≥15%下恒成立，可保留或注明

---

## 十、前复权 vs 后复权：数据口径修复说明

### 10.0 为什么需要这个修复？

**问题根源**：从 yfinance 切换到 Eastmoney 时，复权因子的"生产方式"变了，必须确保新因子的语义与平台现有代码的假设一致，否则所有依赖复权价的信号（动量、MA90）都会算错。

具体有三层原因：

**（1）yfinance 与 Eastmoney 的原始数据形态不同**

- yfinance：直接提供 `Adj Close`（后复权价，开箱即用）
  - 平台老代码从 yfinance 拿 `Adj Close`，反推出 `foreAdjustFactor`
- Eastmoney：`close_raw` 出厂已处理**拆股**（调整到2026口径），但**分红未调**
  - 没有现成的复权价，必须自己从分红记录计算因子
  - 如果直接套用 yfinance 的因子反推逻辑，会重复计算拆股（因为 Eastmoney 已经调过了）

**（2）平台用前复权，研究侧用后复权——两者必须能互换验证**

- 平台（`DuckDBStore.query_qfq_kline`）用**前复权**：
  - 锚定最新交易日 = 1.0，历史价格往下调
  - 原因：实盘系统要求"最新价 = 真实市场价"，下单、风控、净值计算都基于真实价
  - 历史价调整是为了让技术指标（MA、动量）在统一口径下可比
- 研究侧用**后复权**：
  - 锚定 2026-09-30，历史价格往上调
  - 原因：研究时更关注"历史某时刻的真实购买力"，且便于与 Yahoo/雪球等外部源对比绝对价位
- **两者是等价的**：只差一个常数倍数，`pct_change()` 完全一致
  - 迁移验证时，我们用收益率序列对比（而非绝对价格），2892天中99.97%一致，证明新因子语义正确

**（3）opt64 策略强依赖复权价的正确性**

以下三个信号直接用复权价，因子错一个小数点策略就废了：

| 信号 | 依赖 | 错因子的后果 |
|---|---|---|
| 6个月动量 > 20% | `close_adj.pct_change(126)` | 动量虚高/虚低，选错股票 |
| 1个月动量 > 0 | `close_adj.pct_change(21)` | 同上 |
| 收盘价 > MA90 | PIT分红调整价 | 趋势判断反转 |

因此 `fetch_adjust_factor` 的实现必须经过收益率级别的验证，不能只看"有没有数据"。

### 10.1 口径对照表

| | 研究侧 | 平台侧 |
|---|---|---|
| 口径 | **后复权** | **前复权** |
| 锚点 | 2026-09-30 | 最新交易日 |
| 因子语义 | `div_factor`：历史价格 × 因子 = 锚点口径价 | `foreAdjustFactor`：历史价格 × 因子 = 当前口径价 |
| 因子方向 | 越早的因子越小 | 越早的因子越小（同向）|

### 10.2 关键结论

- **收益率序列一致**：两种口径只是差一个常数倍数，`pct_change()` 完全一致
- **验证数据**：00700的2892天中，收益率平均差异仅0.20bp
- **绝对价格不可比**：不要直接对比 `close_adj` vs `qfq` 的绝对值

### 10.3 Eastmoney数据的特殊性

Eastmoney的 `close_raw` **出厂已处理拆股**（调整到2026），但**分红未调**：

```
close_raw = 真实交易价 × 拆股累计因子（出厂已调）
qfq = close_raw × 分红因子 ∏(1 - D/P)
```

因此平台的 `foreAdjustFactor` **只含分红因子**，不含拆股因子。这与A股（BaoStock因子含拆股+分红）不同，搬运时注意。

### 10.4 因子计算公式

```python
# 对每次分红（除权日为ex_date）：
# 1. 找ex_date前一个交易日的收盘价 P_prev
# 2. factor_change = (P_prev - D) / P_prev，其中D为每股分红
# 3. 同日多次分红：factor_change连乘
# 4. 从后往前累乘，锚定最新=1.0：
#    factor[i] = factor[i+1] × factor_change[i+1]
```

### 10.5 已知边界问题

- **2015-05-15**（00700首次分红除权日）：ASOF JOIN边界有1天5.9%的收益率差异
- 影响：2892天中仅1天（0.03%），可接受
- 原因：因子在除权日当天生效 vs 前一日生效的边界处理差异
- **搬运时**：确保DuckDB的ASOF JOIN方向与因子语义一致（`query_qfq_kline`用backward join）

### 10.6 平台查询示例

```python
# 前复权查询（平台标准）
df = store.query_qfq_kline("00700.HK", "2024-01-01", "2024-12-31")
# 返回的close列已是前复权价，可直接用于动量/MA计算

# 验证收益率一致性
research_ret = research_close_adj.pct_change()
platform_ret = df["close"].pct_change()
assert (research_ret - platform_ret).abs().max() < 0.001
```

---

## 十一、演进历史（供理解）

```
opt23 (24.81%) → GARP + 6个月>20%强动量
opt34 (26.66%) → + 1个月>0双动量确认
opt48 (30.19%) → + 按动量排序（代替PEG排序），突破30%
opt64 (32.63%) → + PE≤12深价值，突破32%
```

两次突破都来自**经济逻辑**，非参数挖掘：
- opt48：动量强度比静态PEG更能识别赢家
- opt64：更便宜的好公司 + 动量 = 更高赔率

**用户方法论红线**：只能按指标的经济逻辑微调，绝不看数据、看曲线调参。策略必须跨年稳定，不能每年换一个。

---

## 附录：原始代码关键片段

### CAGR计算
```python
# 要求6个连续年报
sub = g[g["visible_date"] <= d].sort_values("report_date")
if len(sub) < 6: continue
seg = sub.tail(6)
years = seg["report_date"].dt.year.values
if not all(np.diff(years) == 1): continue  # 严格连续
np0, np5 = seg["net_profit"].iloc[-1], seg["net_profit"].iloc[0]
if np0 <= 0 or np5 <= 0: continue
cn = (np0 / np5) ** 0.2 - 1
if abs(cn) > 2.0: continue  # 剔除极端
```

### MA90的PIT调整
```python
# P_adj(t,d) = close_traded(t) * div_factor(t)/div_factor(d)
p_win = close_traded.loc[window, tic]      # 90天真实价
f_win = div_factor.loc[window, tic]        # 90天因子
f_d = div_factor.loc[d, tic]               # 信号日因子
p_adj = p_win * f_win / f_d                # 调整到信号日口径
ma = p_adj.mean()
if close_traded.loc[d, tic] > ma:          # 站上均线
    ...
```

### 信号日生成
```python
# 每年4/7/10月首个交易日
for y in range(2015, 2027):
    for m in (4, 7, 10):
        cands = dates[(dates.year == y) & (dates.month == m)]
        if len(cands):
            out.append(cands[0])
```
