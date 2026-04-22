# Pipeline 时间关联/独立模式设计

## 目标

在 pipeline 的多策略组合中，支持相邻 screener 之间配置"时间独立"或"时间关联"模式，使得用户可以灵活控制策略之间的时间约束关系。

## 背景

当前 pipeline 中多个 screener 按顺序做级联过滤（cascading AND）：screener N+1 只看 screener N 通过的股票。但在时间维度上没有交集概念，也没有独立/关联的区分。新设计中，最终 match_dates 由所有 screener 中最细粒度的频率来决定。

用户需要两种组合模式：
- **独立（independent）**：两个 screener 各自独立对全部股票运行，结果取并集（OR）。不要求在同一时间点满足。
- **关联（correlated）**：两个 screener 各自独立对全部股票运行，结果取交集（AND）。要求在同一时间窗口内都满足。

## 核心概念

### join_mode

每对相邻 screener 之间有一个 `join_mode` 属性：

- `"independent"`（默认）：两个 screener 各自独立运行，结果取并集（OR）。不关心时间。
- `"correlated"`：两个 screener 各自独立运行，结果取交集（AND）。要求在同一个最粗周期内都通过。

配置方式：`join_modes` 数组，长度 = `len(screeners) - 1`。`join_modes[i]` 表示 `screeners[i]` 与 `screeners[i+1]` 之间的关系。

### match_date 格式

match_date 的格式携带频率语义，不同频率用不同的日期格式：

| 频率 | 格式 | 示例 |
|------|------|------|
| daily | `YYYY-MM-DD` | `2024-12-15` |
| weekly | `YYYY-Www` | `2024-W51` |
| monthly | `YYYY-MM` | `2024-12` |
| quarterly | `YYYY-Qn` | `2024-Q4` |
| semi-annual | `YYYY-Hn` | `2024-H2` |
| yearly | `YYYY` | `2024` |

quarterly/semi-annual/yearly 本次预留格式空间，不实现对应的数据和策略支持。

### 关联匹配规则

细粒度日期「属于」粗粒度日期即算匹配。例如：
- `2024-12-15`（daily）属于 `2024-12`（monthly）→ 匹配
- `2024-12-15`（daily）属于 `2024-Q4`（quarterly）→ 匹配
- `2024-12`（monthly）属于 `2024-Q4`（quarterly）→ 匹配
- `2024-12-15`（daily）不属于 `2024-11`（monthly）→ 不匹配

## 设计

### Pipeline 执行逻辑

严格按 pipeline 顺序逐对处理。每一对根据 join_mode 做不同的合并。

#### 独立模式（independent）

两个 screener 各自独立对全部股票运行（不是级联过滤），各自产出 `{symbol: [match_dates]}` 结果。最终取并集（OR）：任一 screener 通过的股票和日期都保留。

#### 关联模式（correlated）

两个 screener 各自独立对全部股票运行。以两者中最粗频率为时间窗口，取交集（AND）：只保留窗口内两个 screener 都通过的股票。

关联模式下细频率策略只要在窗口内任意一天满足即可。例如 A(daily) 与 B(monthly) 关联，B 在 12 月通过 000001.SZ，A 只要在 12 月任意一天通过 000001.SZ 即可。

### 推演示例

策略配置：`A(daily) → 独立 → B(monthly) → 关联 → C(monthly)`

数据：000001.SZ
- A（股价低于20元）通过日期：`[2024-09-04, 2024-09-11, 2024-11-30]`
- B（成交量连续4月阳线）通过月份：`[7月, 8月, 9月, 10月]`
- C（均线发散）通过月份：`[8月, 9月, 10月]`

**第一对 A→B（独立，并集）**：A 和 B 各自独立运行。
- A 产出：000001.SZ 在 `[2024-09-04, 2024-09-11, 2024-11-30]`
- B 产出：000001.SZ 在 `[2024-07, 2024-08, 2024-09, 2024-10]`
- 并集：000001.SZ 的 match_dates = `[2024-09-04, 2024-09-11, 2024-11-30, 2024-07, 2024-08, 2024-09, 2024-10]`

**第二对 (A∪B)→C（关联，交集）**：最粗频率 monthly。
前一步的每个 match_date 与 C 的月份做「属于」匹配：
- `2024-09-04` 属于 `2024-09`，C 在 9 月通过 → 保留
- `2024-09-11` 属于 `2024-09`，C 在 9 月通过 → 保留
- `2024-11-30` 属于 `2024-11`，C 在 11 月不通过 → 排除
- `2024-07` 属于 `2024-07`，C 在 7 月不通过 → 排除
- `2024-08` 属于 `2024-08`，C 在 8 月通过 → 保留（中间结果）
- `2024-09` 属于 `2024-09`，C 在 9 月通过 → 保留（中间结果）
- `2024-10` 属于 `2024-10`，C 在 10 月通过 → 保留（中间结果）

**最终输出统一为 pipeline 最细频率（daily）**：
- `2024-09-04`（daily）→ 保留
- `2024-09-11`（daily）→ 保留
- `2024-08`（monthly）→ 无法精确到 daily，丢弃
- `2024-09`（monthly）→ 无法精确到 daily，丢弃
- `2024-10`（monthly）→ 无法精确到 daily，丢弃

最终结果：000001.SZ 的 match_dates = `[2024-09-04, 2024-09-11]`

### match_dates 记录

在逐对处理的过程中，中间结果保留各自来源频率的日期格式（daily 用 `YYYY-MM-DD`，monthly 用 `YYYY-MM` 等），后续关联匹配时通过「属于」规则判断。

最终输出时，统一为 pipeline 中最细频率格式。无法精确到该频率的粗粒度日期丢弃。例如 pipeline 中有 daily 策略，则最终只保留 `YYYY-MM-DD` 格式的 match_dates，月频的 `YYYY-MM` 记录被丢弃。

### 数据结构变化

#### pipeline_info

```json
{
  "screeners": [
    {"name": "price_below_20", "frequency": "daily", "params": {}},
    {"name": "volume_4month_yang", "frequency": "monthly", "params": {}},
    {"name": "ma_diverge", "frequency": "monthly", "params": {}}
  ],
  "join_modes": ["independent", "correlated"],
  "trader": null
}
```

`join_modes` 为新增字段。缺失时默认全部为 `"independent"`（向后兼容）。

#### screened_symbols 返回结构

不变，仍为：
```json
{
  "screened_symbols": [
    {"symbol": "000001.SZ", "match_dates": ["2024-09-04", "2024-09-11"]}
  ]
}
```

### 引擎内部变化

#### _run_screener_backtest

当前逻辑：日频迭代，每个 screener 按自己的频率周期执行或缓存，级联过滤后在最后一个 screener 执行时记录 match_dates。

新增逻辑：

1. 每对相邻 screener 读取对应的 `join_mode`。
2. 每个 screener 独立对全部股票运行（不再级联过滤），各自产出 `{symbol: [match_dates]}` 中间结果。match_dates 按来源频率格式记录。
3. 独立对：两个 screener 的中间结果取并集（OR）。股票维度和日期维度都合并。
4. 关联对：确定最粗频率 `coarse_freq`。对每个股票，检查两个 screener 的 match_dates 是否落在同一个 coarse 周期内（通过 `date_belongs_to` 判断）。只保留两者在同一窗口内都通过的记录。
5. 逐对处理后的中间结果传递给下一对。最终 match_dates 保留各自来源频率格式。

#### _run_backtest（含 trader）

同样适用 join_mode 逻辑。trader 接收的股票列表是经过 join_mode 处理后的结果。

#### _run_screener_only（实时选股）

只评估最新一个 bar，不涉及历史 match_dates。join_mode 在此模式下的语义：
- 独立：两个 screener 各自独立运行，股票结果取并集
- 关联：两个 screener 各自独立运行，股票结果取交集（当前时间点都通过才保留）

### 前端变化

#### PipelineBuilder.vue

在相邻 screener 之间展示可切换的连接符：
- 默认显示「独立」标签（灰色）
- 点击切换为「关联」标签（橙色）
- 连接符显示在两个策略卡片之间

#### API 请求

`POST /api/backtest/run` 的 body 中新增 `join_modes` 字段：
```json
{
  "screeners": [...],
  "join_modes": ["independent", "correlated"],
  "trader": "...",
  "start_date": "...",
  "end_date": "..."
}
```

缺失时默认全部为 `"independent"`。

## 频率粗细排序

```
daily < weekly < monthly < quarterly < semi-annual < yearly
```

本次实际支持：daily、weekly、monthly。quarterly/semi-annual/yearly 预留格式和排序定义。

## 日期归属判断工具函数

新增 `date_belongs_to(fine_date: str, coarse_date: str) -> bool` 工具函数：

- `date_belongs_to("2024-12-15", "2024-12")` → True
- `date_belongs_to("2024-12-15", "2024-W51")` → True
- `date_belongs_to("2024-12-15", "2024-Q4")` → True
- `date_belongs_to("2024-12-15", "2024-H2")` → True
- `date_belongs_to("2024-12-15", "2024")` → True
- `date_belongs_to("2024-12", "2024-Q4")` → True
- `date_belongs_to("2024-12-15", "2024-11")` → False

通过日期字符串长度/格式自动识别频率级别。

## 日期格式化工具函数

新增 `format_match_date(date_str: str, frequency: str) -> str` 工具函数，将标准日期字符串（`YYYY-MM-DD`）转换为对应频率的 match_date 格式：

- `format_match_date("2024-12-15", "daily")` → `"2024-12-15"`
- `format_match_date("2024-12-15", "weekly")` → `"2024-W50"` 或对应 ISO 周
- `format_match_date("2024-12-15", "monthly")` → `"2024-12"`
- `format_match_date("2024-12-15", "quarterly")` → `"2024-Q4"`
- `format_match_date("2024-12-15", "semi-annual")` → `"2024-H2"`
- `format_match_date("2024-12-15", "yearly")` → `"2024"`

## match_date 格式转换责任

**引擎负责统一转换**，策略无需关心日期格式规范。

引擎在记录 match_date 时（无论来源是策略自定义的 match_date 还是引擎默认的 period_date），统一调用 `format_match_date(date, screener.frequency)` 转换为对应频率格式。

- monthly 策略返回的 `2024-09-30` → 引擎转换为 `2024-09`
- daily 策略返回的 `2024-09-04` → 引擎保持 `2024-09-04`

好处：
- 策略作者不需要知道格式约定，零修改成本
- 单一转换点，格式一致性有引擎保证
- 现有策略（MaTangleBreakoutScreener、MonthlyVolumeRedScreener）无需改动

## 向后兼容

- `join_modes` 缺失且只有一个 screener 时，行为与现有一致
- `join_modes` 缺失且有多个 screener 时，默认全部 `"independent"`（并集）。这与旧版级联过滤行为不同 — 旧版是隐式 AND 级联，新版独立模式是 OR 并集。这是有意的行为变更，因为新的 `"correlated"` 模式提供了更精确的 AND 语义。
- 现有 match_date 格式为 `YYYY-MM-DD`（daily 频率），与新格式兼容
- 现有策略无需修改，`frequency` 默认为 `"daily"`

## 本次不做

- 引擎数据源重构（保持现有 `_precompute_periods()` 的 weekly/monthly 聚合逻辑）
- quarterly/semi-annual/yearly 频率的数据 updater 和策略实际支持
- 只预留日期格式和频率排序定义
