# Pipeline 时间关联/独立模式设计

## 目标

在 pipeline 的多策略组合中，支持相邻 screener 之间配置"时间独立"或"时间关联"模式，使得用户可以灵活控制策略之间的时间约束关系。

## 背景

当前 pipeline 中多个 screener 按顺序做级联过滤（cascading AND）：screener N+1 只看 screener N 通过的股票。但在时间维度上没有交集概念，也没有独立/关联的区分。新设计中，最终 match_dates 由所有 screener 中最细粒度的频率来决定。

用户需要两种组合模式：
- **独立（independent）**：不要求策略在同一时间点满足，只做股票集合的级联过滤
- **关联（correlated）**：要求策略在同一时间窗口内都满足

## 核心概念

### join_mode

每对相邻 screener 之间有一个 `join_mode` 属性：

- `"independent"`（默认）：级联过滤，不关心时间，与现有行为一致
- `"correlated"`：要求两者在同一个最粗周期内都通过

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

与现有行为一致：日频级联过滤。每天迭代中，前一个 screener 通过的股票传给后一个 screener。每个 screener 按自己的频率执行或使用缓存。

#### 关联模式（correlated）

以两者中最粗频率为时间窗口。在窗口内，分别累积两个 screener 通过的股票。在窗口边界处取交集：只保留窗口内两个 screener 都通过的股票。

关联模式下细频率策略只要在窗口内任意一天满足即可。例如 A(daily) 与 B(monthly) 关联，B 在 12 月通过 000001.SZ，A 只要在 12 月任意一天通过 000001.SZ 即可。

### 推演示例

策略配置：`A(daily) → 独立 → B(monthly) → 关联 → C(monthly)`

数据：000001.SZ
- A（股价低于20元）通过日期：`[2024-09-04, 2024-09-11, 2024-11-30]`
- B（成交量连续4月阳线）通过月份：`[7月, 8月, 9月, 10月]`
- C（均线发散）通过月份：`[8月, 9月, 10月]`

**第一对 A→B（独立）**：日频级联过滤。
- 09-04：A 通过 → B 9月通过 → 通过
- 09-11：A 通过 → B 9月通过 → 通过
- 11-30：A 通过 → B 11月不通过 → 过滤掉

A→B 产出：`[2024-09-04, 2024-09-11]`

**第二对 (A→B)→C（关联）**：最粗频率 monthly。
- 09-04 落在 9 月，C 9 月通过 → 匹配
- 09-11 落在 9 月，C 9 月通过 → 匹配

最终结果：`[2024-09-04, 2024-09-11]`，日粒度。

### match_dates 记录

最终 match_dates 粒度 = pipeline 中最细频率。每条 match_date 按其来源策略的频率格式记录（daily 用 `YYYY-MM-DD`，monthly 用 `YYYY-MM`）。在逐对处理的过程中，中间结果保留各自频率的日期格式，后续关联匹配时通过「属于」规则判断。

最终输出给用户的 match_dates 统一为最细频率格式。

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
2. 独立对：保持现有级联过滤行为。前一个 screener 通过的股票直接传给后一个。中间结果携带日期（按来源频率格式）。
3. 关联对：确定最粗频率 `coarse_freq`。引擎维护 `period_accumulator[pair_idx][sym]` 记录该 coarse 周期内每个 screener 是否通过。在 coarse 周期边界变化时取交集，重置 accumulator。
4. match_dates 在 pipeline 末端记录，粒度为最细频率。

#### _run_backtest（含 trader）

同样适用 join_mode 逻辑。trader 接收的股票列表是经过 join_mode 处理后的结果。

#### _run_screener_only（实时选股）

只评估最新一个 bar，不涉及历史 match_dates。join_mode 在此模式下的语义：
- 独立：与现有行为一致，级联过滤
- 关联：检查当前时间窗口内两个 screener 是否都通过

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

## 向后兼容

- `join_modes` 缺失时默认全部 `"independent"`，与现有行为一致
- 现有 match_date 格式为 `YYYY-MM-DD`（daily 频率），与新格式兼容
- 现有策略无需修改，`frequency` 默认为 `"daily"`

## 本次不做

- 引擎数据源重构（保持现有 `_precompute_periods()` 的 weekly/monthly 聚合逻辑）
- quarterly/semi-annual/yearly 频率的数据 updater 和策略实际支持
- 只预留日期格式和频率排序定义
