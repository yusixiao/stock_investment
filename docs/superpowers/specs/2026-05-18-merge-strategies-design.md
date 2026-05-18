# 5 策略合并 + 架构收敛设计

**日期**: 2026-05-18
**状态**: Draft (待 review)
**前置**: 2026-05-09-buy-sell-strategy-design.md / 2026-05-09-strategy-group-design.md / 2026-04-22-pipeline-time-correlation-design.md / 2026-04-14-chain-backtest-design.md

## 背景

项目当前包含 7 个独立策略,通过 pipeline + join_modes + StrategyGroup 三层组合机制串联。实际使用中:

1. **架构分裂**:`ScreenerStrategy / TraderStrategy / BuyStrategy / SellStrategy` 四个基类并存,Engine 因此有两套(`engine.py` + `buy_sell_engine.py`)、三条执行路径(`mode="screen"` / 选股回测 / 完整回测)、多种入参组合(`source_task_id` / `signal_table` / `join_modes`)。代码量近 700 行,语义割裂。
2. **业务概念过载**:Pipeline、StrategyGroup、链式回测、join_mode 都是"组合多个策略"的不同抽象,功能重叠且难以解释。
3. **复用难度**:跨策略复用某段逻辑(如"获取 ROE")只能通过类继承或重复实现,没有函数级复用。

本设计将 5 个相关策略合并为 1 个完整策略 `MaTangleValueStrategy`,并借此重构基类、引擎、上下文、数据库、前端,使整个回测系统收敛到**单一策略 = 单次回测**的模型。

## 决策

### D1. 单一 `Strategy` 基类

废弃 `ScreenerStrategy / TraderStrategy / BuyStrategy / SellStrategy`,改为单一 `Strategy` 类同时拥有 `screen / on_buy / on_sell` 三个钩子,默认实现:

- `screen()` → 返回全部输入 symbols(等价无筛选)
- `on_buy()` → pass
- `on_sell()` → pass(永久持有)

`frequency` / `frequency_overridable` / `settings` 整合到主类。子类按需覆盖,不强制 `NotImplementedError`。

### D1.1 频率(frequency)语义与可覆盖性

**频率定义**:`frequency` 不是"读什么数据",而是 **`screen()` 被调用的节奏**。每个策略都必须有一个 frequency,基类默认 `"daily"` 兜底。不存在"无频率"策略——任何策略都要在某根 K 线 bar 上评估。

**频率可覆盖性**:基类引入 `frequency_overridable: bool = False`(**默认 False,锁死**)。

判定规则:**只要策略中有任何一个组件对频率有语义依赖,整个策略就必须锁定频率**(`frequency_overridable = False`)。

| utils 函数 | 频率依赖 | 改频率后果 |
|---|---|---|
| `kline.detect_ma_tangle_breakout` | ✋ 强依赖 | 月线 MA 缠绕变周线 MA 缠绕,完全不同的策略 |
| `kline.is_at_history_low` | ✋ 强依赖 | "过去 N 月最低"变"过去 N 周最低" |
| `kline.has_consecutive_red_bars` | ✋ 强依赖 | "连续 4 月阳"变"连续 4 周阳" |
| `dividend.filter_by_dividend_years` | ✓ 无依赖 | 触发节奏变,结果不变 |
| `valuation.filter_by_pe_pb_product` | ✓ 无依赖 | 同上 |
| `financial.filter_by_roe` | ✓ 无依赖 | 同上 |

**应用到 5 策略合并**:
- `MaTangleValueStrategy` 用了 `detect_ma_tangle_breakout`(强依赖)→ `frequency = "monthly"`, `frequency_overridable = False`
- 假想的纯基本面策略(如未来的 `PeOver20SellStrategy` 只用 `valuation.*`)→ `frequency = "daily"`, `frequency_overridable = True`,UI 暴露下拉给用户选

**默认 False 的设计意图**:策略作者必须**主动思考**才能放开,避免无意中允许用户用错误频率跑某策略导致语义错误。

### D1.2 UI 行为(频率字段)

`StrategyInfo` API 返回的字段中包含 `frequency` 与 `frequency_overridable`。前端按下表渲染:

| `frequency_overridable` | UI 表现 |
|---|---|
| `False`(默认) | 只读展示:`评估频率: 月线 (由策略决定)`,灰色不可点 |
| `True` | 可选下拉:`评估频率: [日线 ▼]`,默认值 = `strategy.frequency`,用户可改 |

后端 `runBacktest` 入参增加可选 `frequency_override: str | None`。Engine 接收后,优先级:**用户输入 > 策略默认**。如果策略 `frequency_overridable=False` 但请求中带了 `frequency_override`,后端拒绝(400)。

### D2. 取消 Pipeline / StrategyGroup / 链式回测

一次回测 = 一个 Strategy 实例。多策略复用通过**工具函数**(代码层面)实现,不再有 pipeline / StrategyGroup / source_task_id / signal_table / join_mode 等业务概念。

### D3. Engine 单一执行路径

删 `buy_sell_engine.py`,重写 `engine.py` 为唯一入口。删除 `mode="screen"` 分支(纯选股需求由 `routers/screener.py` 直接调 `strategy.screen()`,不进 Engine)、删除 `_union_results / _intersect_results / _filter_to_finest` 等 join_mode 合并逻辑。保留按 `frequency` 周期切换的 screen 缓存(性能必需)。

主循环固定顺序:`fill_orders(T+1) → screen(若周期切换) → on_sell → on_buy → snapshot`。

### D4. utils 库结构

```
strategies/utils/
├── kline.py            # 单源:K线
├── financial.py        # 单源:财务三表+指标(不拆四表)
├── dividend.py         # 单源:分红事件
├── valuation.py        # 单源:估值(PE/PB/市值)
└── composite/
    ├── __init__.py
    └── market_cap_weighted_batch_buyer.py   # 跨源(估值+K线),含状态 → class
```

**组织规则**(两维独立):
- **位置维度**:单源 vs 跨源 → 是否进 `composite/`
- **形式维度**:无状态 vs 有状态 → 函数 vs class

跨源的无状态函数(如 `dividend_yield = 分红/股价`)也放 composite/ 但仍是函数。所以 composite/ 下函数和类都可以有。

### D5. 日志契约(决策可追溯性)

合并后单次回测产生 `N_days × N_stocks × N_conditions` 量级决策。必须做到事后给定 (symbol, date) 能精确定位被哪个 stage 选中/淘汰。

三层日志:
| 层 | 用途 | logger | 默认级别 | 输出 |
|---|---|---|---|---|
| 决策层 | per-symbol per-stage pass/reject | `backtest.decisions` | DEBUG | JSONL 文件 |
| 聚合层 | per-stage per-bar 总数 | `backtest.flow` | INFO | stdout + 文件 |
| 执行层 | 下单/平仓 | `backtest.exec` | INFO | stdout + 文件 |

`Context` 暴露 `log_pass / log_reject / log_flow` 三个 API,utils 函数和 Strategy 都通过它打日志(不直接用 logging),保证格式统一。

任务日志目录:`data/logs/backtest/<task_id>/{decisions.jsonl, flow.log, exec.log}`。`backtest_tasks` 表新增 `log_dir` 列。

提供 `enable_decision_log: bool = True` 开关,大规模批跑可关。

### D6. 数据库迁移

- `backtest_tasks` 表:清理 `source_task_id` 死列;`pipeline_info` 字段重定义为 `{strategy_class: str, params: dict}`;新增 `log_dir` 列。
- DROP `strategy_groups` 表
- DROP `group_runs` 表
- 旧任务记录保留可读(展示历史),不可重跑

### D6.1 回测范围与时间段(保留并强化)

**回测范围**:个股 vs 全市场两种模式当前后端已支持,新设计**完整保留**。

- API 入参 `symbols: list[str] | None`(沿用)+ `market: "A" | "HK" | "US"`(默认 "A",新增,见 D8)
  - `None` → 全市场:`_load_stock_data` 调 `duckdb_store.list_symbols(market)` 取代码列表(替换原 `RAW_KLINE_DIR.glob`,见 D8 Layer A)
  - `["000001.SZ"]` → 个股回测:仅加载传入列表
- 前端 `BacktestConfig.tsx` 的 `mode === 'single' / 'all'` 切换继续按现在的方式工作

**时间段**:从"可选"改为"必填"。

- API 入参 `start_date: str`(YYYY-MM-DD)、`end_date: str`(YYYY-MM-DD),**两者必填**,缺失或非法格式返回 400
- `_load_stock_data` 接收日期切片数据(由 `store.query_qfq_kline(market, symbol, start_date, end_date)` 完成,见 D8 Layer B),Engine `for idx in range(n_bars)` 自动覆盖此范围
- 校验规则:`start_date <= end_date`,且 `start_date` 不早于市场最早数据日期(可后续放宽,本期最简版)
- 前端目前已经默认填了起止日期(`startDate='2023-01-01'`, `endDate=今天`),无需 UI 改动,但增加非空提交校验

**时间段如何作用于不同 frequency 的策略**:
- 月线策略(如 `MaTangleValueStrategy`):Engine 以日线 bar 推进,但 `screen()` 仅在月切换时触发(spec 第 3 节 Engine 工作流)。因此用户给出"2020-01-01 ~ 2024-12-31"的日期范围,该策略会评估约 60 个月切换点。
- 周线策略:在每周一切换日触发 `screen()`
- 日线策略:每个交易日都触发

用户感受到的回测时长 = `end_date - start_date`,与 frequency 无关。frequency 只影响该期间内 `screen()` 被调用的次数。

### D8. 数据访问统一收敛到 DuckDB(新增,Layer A + Layer B)

**问题诊断**:本次重构暴露出数据访问层有两处架构遗留,与「单一数据源」原则冲突,**必须在本次合并中一并清理**:

| 位置 | 现状 | 问题 |
|---|---|---|
| `backend/routers/backtest.py:_load_stock_data` (~239-251 行) | `RAW_KLINE_DIR.glob("*.parquet")` 枚举全市场 | 1) 走旧路径 `data/kline/A/raw/`;2) 只支持 A 股(HK/US 拿不到);3) 绕过 DuckDB |
| `backend/services/qfq_cache.py` 全文件 | `from config import RAW_KLINE_DIR, QFQ_KLINE_DIR` 直接读旧路径 parquet,且自己从 dividend 数据现场计算复权因子 | 1) 旧路径已停止增量更新,qfq 缓存的"raw 最新日期"将永远停在某天;2) 自实现复权公式,而 `data/market/A/adjust_factor/` 已存预计算 BaoStock 因子,重复造轮子 |

**核心原则**(本次落地,需同步写入 AGENTS.md):

1. **DuckDB 是唯一业务数据源**:所有业务代码(回测、选股、K 线展示、财务/估值/分红查询)**必须**经 `services/duckdb_store.py` 访问数据,**禁止**直接 `glob` parquet 或读旧路径文件
2. **DuckDB 视图唯一来源 = `data/market/`**:`data/market/{A,HK,US}/{daily,adjust_factor,financial/*}/*.parquet`,这是唯一被业务读的物理路径
3. **旧路径仅作校验用**:`data/kline/A/raw/`、`data/kline/A/qfq/` 中已存在的 parquet **不再被业务代码读取**,只保留作为新管线输出的对照基准。新数据**不再写入**这两个目录
4. **新增数据访问能力的唯一入口**:`DuckDBStore` 类。需要新查询 → 在该类上加方法或视图;不允许业务模块绕过

#### Layer A:Router 去 glob

**改造点**:`backend/routers/backtest.py::_load_stock_data`

```python
# 之前(旧)
all_files = list(RAW_KLINE_DIR.glob("*.parquet"))
symbols = [f.stem for f in all_files]

# 之后(新)
from services.duckdb_store import get_store
store = get_store()
symbols = store.list_symbols(market="A")  # 全市场模式
# 个股模式直接用入参 symbols 列表,不查 store
```

K 线读取也从「直接读 parquet」改为 `store.query_qfq_kline(market, symbol, start, end)`(Layer B 提供),由 D6.1 定义的日期范围切片。

**多市场扩展**:API 入参增加 `market: "A" | "HK" | "US"`(默认 "A" 向后兼容),`store.list_symbols(market)` 自然支持。本次重构不强制实现 HK/US 回测全链路,但拆掉 A 股硬编码这一基础设施。

#### Layer B:qfq 计算改用 `data/market/A/adjust_factor/`(预计算因子)

**目标**:`qfq_cache.py` **彻底重写数据来源**:不再读 `data/kline/A/raw/`,也不再从 `data/dividend/A/` 推导复权因子,改为:
- raw 价格:DuckDB 视图 `v_a_daily`(底层 `data/market/A/daily/`)
- 复权因子:DuckDB 视图 `v_a_adjust_factor`(底层 `data/market/A/adjust_factor/`),BaoStock 格式已预计算

**为什么换数据源**:`data/market/A/adjust_factor/{symbol}.parquet` 已存储每个除权日的 `foreAdjustFactor / backAdjustFactor / adjustFactor`(由 BaoStockAdapter 按 BaoStock 官方算法生成),覆盖完整除权历史。直接用这份数据做 qfq 比从 dividend 现场推导更可靠:
1. **无需自己实现公式**:省掉 `(pre_close - cash) / (pre_close × (1 + bonus + transfer))` 计算 + pre_close 查找逻辑(`compute_qfq` 50+ 行可全部删除)
2. **无需处理 dividend schema 异常**:`方案进度`、`现金分红-现金分红比例` 等中文列名解析、空值处理、单位换算 (除以 10) 这些边界全部消失
3. **数据源职责分离**:dividend 数据用于"分红事件查询/选股"(连续分红年数等),adjust_factor 用于"价格复权",各司其职
4. **多市场一致性**:`adjust_factor/` 目录在 A/HK/US 三个市场都存在(已有视图 `v_a_adjust_factor / v_hk_adjust_factor / v_us_adjust_factor`),qfq 逻辑一次写完通吃三市

**adjust_factor parquet schema**(BaoStock 格式,实测 `000001.SZ` 16 行):

| 列 | 类型 | 含义 |
|---|---|---|
| `code` | str | 股票代码 |
| `dividOperateDate` | str | 除权除息日 |
| `foreAdjustFactor` | float | **前复权因子(本次重点用)** |
| `backAdjustFactor` | float | 后复权因子 |
| `adjustFactor` | float | 单次因子 |

每行对应一个除权日,因子值随时间递增(累积)。

**qfq 计算方法**(BaoStock 官方约定):

```
对 raw 数据每根 bar(date d):
  factor_d = max(foreAdjustFactor where dividOperateDate <= d)  # 该日生效的累积因子
            (没有任何除权日 ≤ d 时,factor_d = 0,价格保持 raw)
  factor_latest = 最新除权日的 foreAdjustFactor(全表 max)

  qfq_price[d] = raw_price[d] × factor_d / factor_latest
```

效果:最新交易日 `factor_d == factor_latest`,qfq = raw;历史价格被按比例下调以保证除权日前后曲线连续。

**在 DuckDB 中可纯 SQL 实现**(用 `ASOF JOIN`):

```sql
-- 一只股票的 qfq 价格(伪 SQL)
WITH latest AS (
  SELECT MAX(foreAdjustFactor) AS f_latest
  FROM v_a_adjust_factor WHERE code = ?
)
SELECT
  d.date,
  d.open  * COALESCE(af.foreAdjustFactor, 1) / latest.f_latest AS open,
  d.high  * COALESCE(af.foreAdjustFactor, 1) / latest.f_latest AS high,
  d.low   * COALESCE(af.foreAdjustFactor, 1) / latest.f_latest AS low,
  d.close * COALESCE(af.foreAdjustFactor, 1) / latest.f_latest AS close,
  d.volume, d.amount
FROM v_a_daily d
LEFT ASOF JOIN v_a_adjust_factor af
  ON af.code = d.code AND af.dividOperateDate <= d.date
CROSS JOIN latest
WHERE d.code = ? AND d.date BETWEEN ? AND ?
ORDER BY d.date
```

**架构影响**:**qfq_cache 模块整体可以删除**

既然 DuckDB 能纯 SQL 出 qfq,且 `adjust_factor` 表行数极少(每只股票 ≤ 几十行),实时计算成本几乎为零,**parquet 缓存层 + `_meta.json` 三态模型不再必要**:

- 删除 `backend/services/qfq_cache.py`(全文件 179 行)
- 删除 `data/kline/A/qfq/` 目录(包括 `_meta.json`)
- 删除 `compute_qfq` 函数及相关的 dividend 公式实现
- 在 `DuckDBStore` 上新增方法 `query_qfq_kline(market, symbol, start_date, end_date)`(执行上述 SQL)
- 所有原本调 `qfq_cache.get_qfq_kline()` 的代码改调 `store.query_qfq_kline(...)`

**与 2026-05-08 spec 的关系**:`2026-05-08-qfq-cache-refactor-design.md` **整体被 D8 Layer B superseded**。该 spec 的核心模型(raw + dividend 派生 qfq + 三态缓存)在 adjust_factor 数据已就绪的前提下不再适用。需要在该 spec 顶部加 superseded-by 注记指向本 spec。

**非目标(本期不做)**:
- 不删除 `data/kline/A/raw/` 与 `data/kline/A/qfq/` 目录的旧 parquet(留作历史对照,后续单独清理任务)
- 不迁移分红/财务/估值的 parquet 物理位置
- HK/US 市场的 qfq 查询同步可用(只要 `adjust_factor/` 目录有数据),但本期不验证回测全链路

#### D8 范围:K 线之外的数据访问

D8 改造**只覆盖 K 线 + 复权因子**。其余数据按 DuckDB 视图就绪情况分级处理:

| 数据 | DuckDB 视图 | 本期处理 |
|---|---|---|
| 财务三表 + 指标 | ✅ `v_a_income / v_a_balance / v_a_cashflow / v_a_indicator` 已注册 | `Context.get_financial()` 同步切到 `store.query_financial(...)`,Engine 不再接 `financial_data` dict 入参 |
| 分红 | ❌ 无视图 | `Context.get_dividend()` 暂保留现有 `repositories/event_repo` 路径,**标注 TODO** 后续单独 spec 加视图 |
| 估值(PE/PB/市值) | ❌ 无视图 | `Context.get_valuation()` 暂保留现有 `valuation_updater` parquet 读取,**标注 TODO** |
| 流通股本 | ❌ 无视图 | 同上,保留 `circulating_shares.py` 现状 |

**原则**:本次 D8 不阻塞在补全所有视图上,但建立「能走 DuckDB 的就必须走」规则,后续每加一个视图,对应 Context 方法立即切换,不再增加直读 parquet 的代码路径。

#### Layer A + B 实施顺序

放入 Phase 4(数据库迁移 + 后端路由简化)同期完成,因为两者都触及 `routers/backtest.py` 与数据加载链路:

1. 扩 `DuckDBStore`:新增 `query_qfq_kline(market, symbol, start, end)`(ASOF JOIN SQL,见上),单测覆盖几个有除权/无除权/早于首次除权的边界
2. 用旧 `qfq_cache.get_qfq_kline()` 与新 `store.query_qfq_kline()` 对若干股票做**全历史价格 diff**,误差应在浮点精度内(若有显著偏离说明算法理解有误,先排查)
3. 全局替换调用点:`grep -rn "from services.qfq_cache\|qfq_cache\." backend/ strategies/` 列出后逐处改为 `store.query_qfq_kline(...)`
4. 改 `routers/backtest.py::_load_stock_data`:全市场分支用 `store.list_symbols("A")`;K 线加载走 `store.query_qfq_kline("A", symbol, start, end)`
5. **跑全量回测回归测试**,与 Phase 4 前的旧实现做信号集对比 — 通过后才进入下一步
6. 删除 `backend/services/qfq_cache.py` + `data/kline/A/qfq/`(含 `_meta.json`)— 此时旧 ground truth 失效,删除前必须保证步骤 2/5 都已通过
7. 验证旧路径文件**不再被任何业务代码读取**:`grep -rn "RAW_KLINE_DIR\|QFQ_KLINE_DIR" backend/` 应只剩 `config.py`(常量定义,可后续清理)

**健康检查放置**:DuckDB 视图在 `backend/main.py` lifespan 的 `init_duckdb()` 之后立即跑:
```python
store = get_store()
assert len(store.list_symbols("A")) > 0, "v_a_daily 视图为空,data/market/A/daily/ 无数据"
assert store.query("SELECT count(*) AS c FROM v_a_adjust_factor")["c"][0] > 0, \
    "v_a_adjust_factor 视图为空,data/market/A/adjust_factor/ 无数据"
```
失败抛 RuntimeError 阻止启动,避免回测在运行时才发现数据缺失。

#### 风险与缓解

| 风险 | 缓解 |
|---|---|
| DuckDB 视图首次注册时,`data/market/A/daily/` 或 `adjust_factor/` 必须有数据,否则视图为空,所有回测失败 | 启动 `init_duckdb()` 后立即跑 `len(store.list_symbols("A")) > 0` + `store.query("SELECT count(*) FROM v_a_adjust_factor")` 健康检查,失败报错 |
| `data/market/A/daily/` 的 parquet schema 是否与 `data/kline/A/raw/` 完全一致(列名、date 格式、排序方向) | Phase 4 前先跑对照脚本 `scripts/diff_market_vs_kline.py`(本期新建),抽样 10 只股票 diff,确认一致后再切换 |
| BaoStock 的 `foreAdjustFactor` 用法理解可能有误(归一化基准、是否需 `factor_d / factor_latest`) | Phase 4 第 2 步用旧 qfq_cache 输出做 ground truth 对比,若 diff 超过浮点精度则查 BaoStock 文档/源码 校正 SQL |
| 部分股票完全无除权记录(`adjust_factor/` 中无文件或空表)| ASOF JOIN 命中失败时 `factor_d = NULL`,SQL 用 `COALESCE(factor, 1) / COALESCE(latest, 1)` 退化为 raw = qfq;单测覆盖此分支 |
| 个别股票 raw 价格本身已是复权(早期数据源不规范)| 不在本次范围,通过对照脚本发现的异常股票单独标记,不阻塞迁移 |

### D7. 合并后策略

`MaTangleValueStrategy`(月线均线缠绕价值策略)合并 5 个原策略:
1. DividendYearsScreener(连续分红年数)→ `dividend.filter_by_dividend_years`
2. PePbProductScreener(PE\*PB 区间)→ `valuation.filter_by_pe_pb_product`
3. RoeScreener(ROE 阈值)→ `financial.filter_by_roe`
4. MaTangleBreakoutScreener(月线均线缠绕突破)→ `kline.detect_ma_tangle_breakout`
5. MarketCapWeightedBuyer(市值加权 N 周定投)→ `composite.MarketCapWeightedBatchBuyer`(状态类)

筛选顺序按"数据廉价度递增、淘汰率递减"原则:分红 → PE\*PB → ROE → MA 缠绕。

`MonthlyLowScreener / MonthlyVolumeRedScreener` 的逻辑迁移到 `kline.is_at_history_low / kline.has_consecutive_red_bars`,不参与本次合并策略,但作为 utils 保留供其他策略使用。

## 详细设计

### Strategy 基类 (`backend/services/backtest/base.py` 重写)

```python
class ParamAccessor:
    """保留不动,负责参数覆盖与类型转换。"""

class Strategy:
    name: str = ""
    description: str = ""
    params: dict = {}
    frequency: str = "daily"            # screen() 调用周期 (daily/weekly/monthly)
    frequency_overridable: bool = False # 是否允许用户在 UI 改频率,默认锁死
    settings: dict = {}                 # initial_capital / commission_rate / slippage,有默认

    def __init__(self, param_overrides: dict = None):
        self.p = ParamAccessor(self.params, overrides=param_overrides)
        defaults = {
            "initial_capital": 1_000_000,
            "commission_rate": 0.0003,
            "slippage": 0.002,
        }
        self.settings = {**defaults, **self.__class__.settings}

    def screen(self, ctx: "Context", symbols: list[str]) -> list[str]:
        return symbols  # 默认全通过

    def on_buy(self, ctx: "Context") -> None:
        pass  # 默认不买

    def on_sell(self, ctx: "Context") -> None:
        pass  # 默认永久持有
```

### Engine (`backend/services/backtest/engine.py` 重写,目标 ~200 行)

```python
class BacktestEngine:
    def __init__(
        self,
        strategy: Strategy,
        stock_data: dict[str, pd.DataFrame],   # 已被 router 按 symbols + start/end 切片好
        valuation_data: dict | None = None,
        dividend_data: dict | None = None,
        financial_data: dict | None = None,
        on_progress: Callable | None = None,
        log_dir: Path | None = None,
        enable_decision_log: bool = True,
    ):
        # 注:Engine 不直接接收 symbols / start_date / end_date。
        # 这些过滤在 router._load_stock_data 完成,Engine 只对收到的数据
        # 做完整迭代(for idx in range(n_bars))。
        # 个股回测 = router 传入 symbols=["000001.SZ"]
        # 全市场回测 = router 调 store.list_symbols(market) 取代码列表
        # 时间段 = store.query_qfq_kline(market, sym, start, end) 切片,Engine 自然覆盖
        self._strategy = strategy
        self._broker = Broker(**strategy.settings)
        self._market_data = MarketData(...)  # 按 strategy.frequency 预聚合
        self._log_sink = DecisionLogSink(log_dir, enable_decision_log)

    def run(self) -> dict:
        ref_df = ...; n_bars = len(ref_df)
        target_symbols: set[str] = set()
        screener_cache: list[str] = []
        prev_period_key: str | None = None
        equity_curve, prev_closes = [], {}

        for idx in range(n_bars):
            current_bars, current_prices = self._build_bar_data(idx)
            if idx > 0:
                self._broker.fill_orders(...)

            current_date = ref_df.iloc[idx]["date"]
            ctx = Context(
                strategy=self._strategy,
                idx=idx,
                broker=self._broker,
                market_data=self._market_data,
                log_sink=self._log_sink,
            )

            # 1) screen 仅在 frequency 周期切换时跑
            pk = self._period_key(current_date, self._strategy.frequency)
            if pk != prev_period_key:
                screener_cache = self._strategy.screen(ctx, list(self._all_symbols))
                prev_period_key = pk

            # 2) 累计目标池
            today_signals = [s for s in screener_cache if s in current_bars]
            new_symbols = [s for s in today_signals if s not in target_symbols]
            target_symbols.update(new_symbols)
            ctx.set_pool(target_symbols, new_symbols)

            # 3) sell 先于 buy
            self._strategy.on_sell(ctx)
            self._strategy.on_buy(ctx)

            equity_curve.append(self._broker.portfolio.snapshot(current_date, current_prices))
            prev_closes = dict(current_prices)

        self._log_sink.flush()
        return {
            "metrics": compute_metrics(...),
            "equity_curve": equity_curve,
            "trades": self._broker.all_trades,
        }
```

### Context (`backend/services/backtest/context.py` 重写)

合并 `ScreenerContext / TraderContext` 为单一 `Context`,同时提供:
- 数据访问:`get_price / get_history / get_valuation / get_dividend / get_financial / indicator`
- 多频率:`_get_data_for_freq` 保留(按 `period` 参数)
- 持仓与下单:`get_position / get_positions / order_shares / order_value / order_target_percent / available_cash`
- 累计池:`target_symbols / new_symbols / remove_target() / set_pool()`
- 日志:`log_pass(symbol, stage, **values) / log_reject(symbol, stage, reason, **values) / log_flow(stage, **counts)`

`current_date / current_idx` 作为属性。

### utils 函数签名

#### `strategies/utils/kline.py`

```python
def detect_ma_tangle_breakout(
    ctx, symbol: str, *,
    fast: int = 5, mid: int = 10, slow: int = 20,
    tangle_threshold: float = 0.05,
    tangle_months: int = 2,
    spread_months: int = 6,
    spread_threshold: float = 0.01,
    vol_red_bars: int = 4,
    freq: str = "monthly",
) -> bool:
    """当前 bar 是否完成了一次「均线缠绕→发散→连续阳线」突破。
    内部对 symbol 写 log_pass / log_reject(stage='kline.ma_tangle')。
    """

def is_at_history_low(
    ctx, symbol: str, *, years: int = 3, range_pct: float = 20.0, freq: str = "monthly"
) -> bool:
    """当月 low 处于过去 N 年最低价的 (1+range_pct%) 范围内。
    stage='kline.history_low'
    """

def has_consecutive_red_bars(
    ctx, symbol: str, *, n: int = 4, freq: str = "monthly"
) -> bool:
    """最近 n 根 K 线全为阳线(close >= open)。
    stage='kline.consecutive_red'
    """

# 通用辅助(纯计算,不打日志)
def get_ma(ctx, symbol: str, window: int, *, freq: str = "daily") -> float | None: ...
def get_macd(ctx, symbol: str, field: str = "dif", *, freq: str = "daily") -> float | None: ...
```

#### `strategies/utils/financial.py`

```python
def filter_by_roe(ctx, symbols: list[str], *, min_roe: float = 10.0) -> list[str]:
    """ROE >= min_roe。stage='financial.roe'。
    使用财报字段 '净资产收益率'(实际数据列名)。
    """

def get_roe(ctx, symbol: str) -> float | None: ...
def get_eps(ctx, symbol: str) -> float | None: ...
def get_net_profit_growth(ctx, symbol: str) -> float | None: ...
```

#### `strategies/utils/dividend.py`

```python
def filter_by_dividend_years(
    ctx, symbols: list[str], *, min_years: int = 5
) -> list[str]:
    """累计现金分红年数 >= min_years。stage='dividend.years'"""

def count_dividend_years(ctx, symbol: str) -> int | None:
    """统计该股票历史上有几个不同的年度发生过 cash_dividend > 0"""
```

#### `strategies/utils/valuation.py`

```python
def filter_by_pe_pb_product(
    ctx, symbols: list[str], *,
    min_value: float = 0.0, max_value: float = 22.0
) -> list[str]:
    """PE(TTM) * PB ∈ [min, max]。stage='valuation.pe_pb_product'"""

def get_pe(ctx, symbol: str) -> float | None: ...
def get_pb(ctx, symbol: str) -> float | None: ...
def get_total_mv(ctx, symbol: str) -> float | None:
    """总市值(单位:元)"""
```

#### `strategies/utils/composite/market_cap_weighted_batch_buyer.py`

```python
class MarketCapWeightedBatchBuyer:
    """市值加权 N 周分批买入器。

    跨源:取 valuation.total_mv 决定权重,按 kline 周线 (open+close)/2 成交。
    状态:_buy_plans / _allocated 跨 step 调用累积,因此封装为 class 而非函数。
    """
    def __init__(self, *, buy_weeks: int = 8, lot_size: int = 100):
        self._buy_plans: dict[str, dict] = {}
        self._allocated: set[str] = set()
        self._buy_weeks = buy_weeks
        self._lot_size = lot_size

    def step(self, ctx) -> None:
        """每个 on_buy 调用一次。"""
        self._create_plans_for_new(ctx)   # log stage='batch_buyer.allocate'
        self._execute_weekly_buys(ctx)    # log stage='batch_buyer.buy'
```

### 数据流(Engine ↔ Context ↔ Strategy ↔ Buyer)

每个 bar 主循环固定数据流如下:

```
[Engine 主循环 idx]
   │
   ├─► current_bars, current_prices = build_bar_data(idx)
   ├─► broker.fill_orders(...)                          # T+1 撮合昨日订单
   │
   ├─► ctx = Context(idx, broker, market_data, log_sink)
   │
   ├─► IF 周期切换 (frequency 决定):
   │     screener_cache = strategy.screen(ctx, all_symbols)
   │
   ├─► today_signals = [s for s in screener_cache if s in current_bars]
   ├─► new_symbols   = [s for s in today_signals if s not in target_symbols]
   ├─► target_symbols.update(new_symbols)
   │
   ├─► ctx.set_pool(target_symbols, new_symbols)        # ← 关键:注入累计池
   │       └─ 设置 ctx.target_symbols / ctx.new_symbols 属性
   │       └─ 绑定 ctx.remove_target() 回调(seller 平仓时调用)
   │
   ├─► strategy.on_sell(ctx)                            # 可调 ctx.remove_target(sym)
   │
   ├─► strategy.on_buy(ctx)
   │       └─ self._buyer.step(ctx)
   │             ├─ READS  ctx.new_symbols   → 为新增股票创建买入计划
   │             ├─ READS  ctx.target_symbols → 检查股票是否仍在池中
   │             ├─ READS  ctx.available_cash → 分配本周买入金额
   │             ├─ READS  ctx.get_price(sym, period="weekly") → 取成交价
   │             ├─ CALLS  ctx.order_shares(sym, n) → 下单
   │             └─ WRITES ctx.log_pass / log_reject  (stage='batch_buyer.*')
   │
   └─► equity_curve.append(broker.portfolio.snapshot(...))
```

**Context 字段总览**(给 Strategy / Buyer / utils 函数使用):

| 字段 / 方法 | 来源 | 用途 |
|---|---|---|
| `current_date / current_idx` | Engine 注入 | 当前 bar 时间锚点 |
| `target_symbols: list[str]` | `ctx.set_pool()` 设置 | 累计目标池(已选股+尚未平仓) |
| `new_symbols: list[str]` | `ctx.set_pool()` 设置 | 本 bar 新增的目标(buyer 据此分配) |
| `remove_target(sym)` | `ctx.set_pool()` 绑定回调 | seller 调用,通知 Engine 移除累计池 |
| `available_cash` | broker.portfolio | 当前可用现金 |
| `get_price / get_history / get_valuation / get_dividend / get_financial / indicator` | market_data | 数据访问 |
| `get_position / get_positions` | broker.portfolio | 持仓查询 |
| `order_shares / order_value / order_target_percent` | broker.submit_order | 下单 |
| `log_pass / log_reject / log_flow` | log_sink | 决策日志 |

**关键不变量**:
- `new_symbols ⊆ target_symbols`(新增股票一定也在累计池中)
- `target_symbols` 是 Engine 与 ctx 共享的可变集合。`on_sell` 通过 `ctx.remove_target(sym)` 修改后,**同一 bar 内** `on_buy` 看到的 `ctx.target_symbols` 已经是更新后的视图(seller 先于 buyer,目的就是避免买入刚被卖出的股票)
- buyer 创建买入计划时基于 `ctx.new_symbols`,但执行每周买入前必须重新检查 `sym in ctx.target_symbols`(参考原 `MarketCapWeightedBuyer._execute_weekly_buys` 中 `if sym not in ctx.target_symbols: finished.append(sym)` 的处理)

### 合并策略 (`strategies/examples/ma_tangle_value_strategy.py`)

```python
class MaTangleValueStrategy(Strategy):
    name = "月线均线缠绕价值策略"
    description = (
        "基本面池(连续分红 + PE*PB 区间 + ROE 达标)与月线均线缠绕突破信号交集,"
        "命中后按市值加权 8 周分批买入,默认永久持有。"
    )
    frequency = "monthly"
    frequency_overridable = False   # 强依赖:detect_ma_tangle_breakout 必须月线

    params = {
        # 基本面池
        "min_dividend_years": {"default": 5, "type": "int", "label": "最少分红年数"},
        "pe_pb_min": {"default": 0.0, "type": "float", "label": "PE*PB 下限"},
        "pe_pb_max": {"default": 22.0, "type": "float", "label": "PE*PB 上限"},
        "min_roe": {"default": 10.0, "type": "float", "label": "最低 ROE(%)"},

        # 技术信号
        "ma_fast": {"default": 5, "type": "int"},
        "ma_mid": {"default": 10, "type": "int"},
        "ma_slow": {"default": 20, "type": "int"},
        "tangle_threshold": {"default": 0.05, "type": "float"},
        "tangle_months": {"default": 2, "type": "int"},
        "spread_months": {"default": 6, "type": "int"},
        "spread_threshold": {"default": 0.01, "type": "float"},
        "vol_red_bars": {"default": 4, "type": "int"},

        # 买入器
        "buy_weeks": {"default": 8, "type": "int", "label": "分批周数"},
    }

    settings = {
        "initial_capital": 1_000_000,
        "commission_rate": 0.0003,
        "slippage": 0.002,
    }

    def __init__(self, param_overrides=None):
        super().__init__(param_overrides)
        self._buyer = MarketCapWeightedBatchBuyer(buy_weeks=self.p.buy_weeks)

    def screen(self, ctx, symbols):
        ctx.log_flow("strategy.screen.start", input=len(symbols))

        # 顺序:数据廉价的先做,昂贵的 K 线计算后做
        pool = dividend.filter_by_dividend_years(ctx, symbols, min_years=self.p.min_dividend_years)
        pool = valuation.filter_by_pe_pb_product(
            ctx, pool, min_value=self.p.pe_pb_min, max_value=self.p.pe_pb_max
        )
        pool = financial.filter_by_roe(ctx, pool, min_roe=self.p.min_roe)
        ctx.log_flow("strategy.fundamental_pool", passed=len(pool))

        signals = []
        for sym in pool:
            if kline.detect_ma_tangle_breakout(
                ctx, sym,
                fast=self.p.ma_fast, mid=self.p.ma_mid, slow=self.p.ma_slow,
                tangle_threshold=self.p.tangle_threshold,
                tangle_months=self.p.tangle_months,
                spread_months=self.p.spread_months,
                spread_threshold=self.p.spread_threshold,
                vol_red_bars=self.p.vol_red_bars,
                freq="monthly",
            ):
                signals.append(sym)
                ctx.log_pass(sym, "strategy.screen.final")

        ctx.log_flow("strategy.screen.done", input=len(symbols), passed=len(signals))
        return signals

    def on_buy(self, ctx):
        self._buyer.step(ctx)

    # on_sell 默认 pass = 永久持有
```

### 日志样例

```
[flow]   strategy.screen.start         input=4823
[reject] dividend.years                symbol=600519 reason=below_threshold years=3 threshold=5
[pass]   dividend.years                symbol=000858 years=12 threshold=5
[flow]   dividend.years                input=4823 passed=421
[reject] valuation.pe_pb_product       symbol=000858 reason=above_max product=68.5 max=22.0
[pass]   valuation.pe_pb_product       symbol=600036 product=11.2
[flow]   valuation.pe_pb_product       input=421 passed=87
[reject] financial.roe                 symbol=601398 reason=below_threshold roe=8.4 threshold=10.0
[pass]   financial.roe                 symbol=600036 roe=14.7
[flow]   strategy.fundamental_pool     passed=43
[reject] kline.ma_tangle               symbol=600036 reason=no_tangle_in_window
[pass]   kline.ma_tangle               symbol=601318 tangle_end=2024-02 breakout=2024-04
[pass]   strategy.screen.final         symbol=601318
[flow]   strategy.screen.done          input=4823 passed=12
[flow]   batch_buyer.allocate          symbol=601318 mv=8.2e11 weight=0.34 weekly_amount=42500
[exec]                                 BUY 601318 1300 @ 35.20 (week 1/8)
```

JSONL 格式(决策层文件):
```json
{"ts":"2024-03-29","idx":1234,"freq":"monthly","stage":"financial.roe","symbol":"601398","decision":"reject","reason":"below_threshold","roe":8.4,"threshold":10.0}
```

## 影响范围

### 后端

**重写**:
- `backend/services/backtest/base.py`(只剩 `Strategy` 单基类 + `ParamAccessor`)
- `backend/services/backtest/engine.py`(单一路径,~200 行)
- `backend/services/backtest/context.py`(合并 ScreenerContext/TraderContext + 日志 API)
- `backend/services/backtest/strategy_loader.py`(适配单基类扫描)
- `backend/services/backtest/task_manager.py`(适配新 `pipeline_info` schema + `log_dir`)
- `backend/routers/backtest.py`(移除 `source_task_id` / `mode=screen` 路径,简化入参)
- `backend/services/db_schema.py`(迁移脚本)

**新增**:
- `backend/services/backtest/decision_log.py`(`DecisionLogSink` JSONL 写入器,带缓冲)
- `DuckDBStore.query_qfq_kline(market, symbol, start, end)` 方法(D8 Layer B,ASOF JOIN SQL)
- `scripts/diff_market_vs_kline.py`(D8 校对脚本:对比 `data/market/A/daily/` 与 `data/kline/A/raw/` schema + 数值)
- `strategies/utils/__init__.py`
- `strategies/utils/kline.py / financial.py / dividend.py / valuation.py`
- `strategies/utils/composite/__init__.py`
- `strategies/utils/composite/market_cap_weighted_batch_buyer.py`
- `strategies/examples/ma_tangle_value_strategy.py`

**删除**:
- `backend/services/backtest/buy_sell_engine.py`
- `backend/services/backtest/group_manager.py`
- `backend/services/backtest/engine_base.py`(合并入 engine.py)
- `backend/services/backtest/date_utils.py` 中 join_mode 相关函数(`date_belongs_to` 等若仅 join_mode 使用则删,否则保留)
- `backend/routers/strategy_group.py`
- `backend/services/qfq_cache.py`(D8 Layer B 替代:DuckDB ASOF JOIN 实时算)
- `data/kline/A/qfq/` 目录及 `_meta.json`(D8 Layer B,缓存层不再需要)
- 7 个旧 `strategies/examples/*.py`(逻辑已迁移到 utils 后删)

### 数据库

- `backtest_tasks`:DROP `source_task_id`,`pipeline_info` 改为 `{strategy_class, params}`,新增 `log_dir`,新增 `is_deleted BOOLEAN DEFAULT FALSE`(软删,日志永久保留作审计)
- DROP TABLE `strategy_groups`
- DROP TABLE `group_runs`
- 提供迁移脚本 `backend/services/migrations/2026-05-18-merge-strategies.sql`

### 前端

**实际状态**:前端从未实现 StrategyGroup 页面,且 `BacktestConfig.tsx` 当前 UI 已经是「单 strategy 选择 + 自动参数表单」形态(只是底层 API 调用还包成单元素 pipeline 数组)。改动远小于最初评估。

**调整**(均在 `frontend/src/components/backtest/BacktestConfig.tsx` + `frontend/src/api/backtestEngine.ts`):
1. `runBacktest()` 入参从 `{pipeline: [{filepath, class_name}], param_overrides: {className: {...}}}` 简化为 `{strategy_class, params}`(对应后端 API 收敛)
2. 策略下拉的副标签 `s.strategyType === 'screener' ? '选股' : '交易'` 去掉(单一 Strategy 后无此区分),改为按 `s.frequency` 显示「日/周/月」标签
3. 「K线周期」字段(行 227-238)行为变更:不再独立编辑,改为根据所选策略的 `frequency_overridable` 自动切换:`False` → 只读展示策略声明的频率;`True` → 可选下拉,默认值 = `strategy.frequency`。`runBacktest` 入参增加可选 `frequency_override`,后端校验非法覆盖时返回 400
4. `BacktestResult.tsx / BacktestHistory.tsx` 展示从 `pipeline_info` 嵌套结构改为直接显示 `strategy_class + params`(实施时核对当前实现)
5. 历史列表加上 `is_deleted` 软删过滤(默认 `is_deleted=False`),并提供「显示已删除」开关

**已知遗留问题(不在本次范围,标注供后续修)**:
- 手续费 UI 显示 `0.15`(百分比单位),后端用 `0.0003`(万三小数)— 当前传值未做单位换算,实际生效值不符预期。本次重构保留现状,以独立 issue 修复

**新增**(决策日志查询面板,**留待后续迭代**,本次仅保证后端日志写入正确):
- 未来:`src/components/backtest/DecisionLogPanel.tsx`(按 symbol + date 范围 + stage 过滤查询 decisions.jsonl)

### 测试

- 后端:`backend/tests/services/backtest/` 全面重写(原 ~80 个回测测试)
  - 删除 join_mode / chain / signal_table / strategy_group 相关
  - 新增 utils 函数级测试(每个 filter_by_* / detect_* 各一组,**Phase 1 用 mock Context** — 真实 Context 在 Phase 3 才到位)
  - 新增 `MaTangleValueStrategy` 集成测试(全链路)
  - 新增 `DecisionLogSink` 单测
  - 新增 `DuckDBStore.query_qfq_kline` 单测(D8 Layer B):有除权/无除权/早于首次除权三个边界 + 与旧 `qfq_cache` 对照 diff 测试
- 前端:删除 StrategyGroup 相关测试

## 测试策略

1. **utils 单测**:每个 `filter_by_*` 用 mock ctx + 固定数据集,验证通过/淘汰名单 + 日志条目数
2. **`MaTangleValueStrategy` 集成测**:用一组已知通过/淘汰的股票运行完整 screen,断言:
   - 最终 signals 列表正确
   - decisions.jsonl 中每个 symbol 至少有一条 pass 或 reject
   - 给定 (symbol, date) 能唯一定位到淘汰原因
3. **Engine 测**:固定单一 Strategy,验证主循环执行顺序、screen 缓存命中、target_symbols 累计、broker T+1
4. **回归测**:用旧 `MaTangleBreakoutScreener` 在某一历史时段产出的信号集,与 `MaTangleValueStrategy(min_dividend_years=0, pe_pb_max=∞, min_roe=-∞)`(等价禁用基本面)的信号集对比应一致

## 实施阶段(高层)

1. **Phase 1**:新增 utils 库 + `Strategy` 基类(向后兼容,旧基类保留)→ 跑通新单测(utils 单测用 mock Context,真实 Context 在 Phase 3 完成)
2. **Phase 2**:新增 `MaTangleValueStrategy` + 决策日志 → 集成测通过
3. **Phase 3**:重写 Engine + Context,迁移旧策略测试
4. **Phase 4**:数据库迁移 + 后端路由简化 + **D8 数据访问统一**(Layer A: router 去 glob;Layer B: 删除 qfq_cache 模块,qfq 改由 DuckDB 用 `adjust_factor` 视图实时算)
5. **Phase 5**:前端 BacktestConfig API 入参收敛 + 策略类型副标签调整 + K线周期字段移除 + 历史列表软删过滤(StrategyGroup 前端无需删除,从未存在)
6. **Phase 6**:删除 7 个旧策略 + 旧基类 + 旧引擎 + 旧路由
7. **Phase 7**:决策日志查询面板(可选,后续迭代)

每个 Phase 结束跑 `python -m pytest backend/tests/ -x -q` + `cd frontend && npx tsc --noEmit && npm test` 全绿才进入下一阶段。

## 已决议事项(2026-05-18)

1. **决策日志查询面板**:不纳入本次范围,留待后续迭代。本次只保证后端日志正确写入 `data/logs/backtest/<task_id>/`。
2. **JSONL 文件清理策略**:**永久保留作审计**。`backtest_tasks` 表新增 `is_deleted: bool` 软删字段,任务"删除"操作仅置位该字段,日志文件不动。前端列表默认过滤 `is_deleted=False`。
3. **`enable_decision_log`**:UI 不暴露,默认 True 始终开启。代码层面保留参数以便测试或大规模批跑场景关闭。
4. **`MonthlyLowScreener / MonthlyVolumeRedScreener`**:逻辑迁入 `kline.is_at_history_low / has_consecutive_red_bars`,**原策略文件直接删除**,不保留示例策略。最终 `strategies/examples/` 下仅有 `ma_tangle_value_strategy.py` 一个文件。
