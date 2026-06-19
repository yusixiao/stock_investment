# AGENTS.md — 回测 / 选股子系统

> 本文件聚焦**回测引擎 + 策略模型**。跨切面铁律(数据源、DuckDB 唯一入口、`data/market/` 唯一路径、长任务 nohup、沟通语言、双 import 风格等)见**根 `AGENTS.md`**,此处不重复。

## 回测架构

- **事件驱动**,Broker 处理 T+1、涨跌停、佣金万三+印花税千一、滑点。
- **成交价**:默认 `(open + close) / 2` 中间价。Broker 支持自定义 `price_func`(如月线 `(high+low)/2`)。
- **回测数据**:使用 `qfq/`(前复权);K 线显示支持 raw/qfq 切换。
- **年化收益率**:`(1 + total_return) ^ (1 / years) - 1`,`years = natural_days / 365.25`。
- **MACD bar**:`2 × (DIF - DEA)`(用户口径,与某些行情软件 1× 不同)。
- **A 股 volume 单位 = 股**(不是手)。
- 任务结果持久化到 SQLite `backtest_tasks` 表(`final_result` 列存完整 JSON);进度仍存内存。
- **链式回测已废弃**:旧 Signal Table / `source_task_id` 继承选股结果已从 Engine + API 移除;`backtest_tasks.source_task_id` 列与 `task_manager` 形参是历史遗留(仅持久化,无业务消费),勿据此误判功能仍在。

## 策略模型(2026-05 重构,Phase 6)

- **Pipeline + Screener/Buyer/Seller 三角拆分模型已废弃**;**StrategyGroup 整套已砍**(前端三层 UI 不要再做)。
- 当前为**单一 Strategy 类**(`strategy_base.py::Strategy` / `ScreenerStrategy`),策略实现 `screen(ctx, symbols) -> List[str]` + 可选 `on_buy(ctx, symbol)` / `on_sell(ctx, symbol)` hooks。
- 示例:`strategies/deployed/ma_tangle_value_strategy.py`、`hk_garp_strategy.py`。
- 任何看到旧文档/代码提到 BuyStrategy/SellStrategy/TraderStrategy 的,都按"已合并到单一 Strategy"理解。
- **API 兼容**:`/api/screener/run` 与 `/api/backtest/run` 仍接收 `pipeline: []` 数组,但**只取首元素**加载策略类(importlib),应用参数覆盖,执行 `screen` / 完整回测。

## 🚨 策略目录铁律(2026-06-14 迁入 backtest)

策略已从顶层 `strategies/` **整体迁入** `backend/services/backtest/strategies/`(理由:策略均为开发者自写、与回测引擎深度耦合,Phase 6.2「作者无需感知 backend」反转依赖理由已不成立)。

- `strategies/deployed/` = **已发布策略**(UI/回测 `/api/backtest/strategies` 只扫这里,经 `config.DEPLOYED_STRATEGY_DIR`)。
- `strategies/experiments/` = **在研策略**(策略研究优先写这里,**不暴露给 UI**;`.py`/`__init__.py` 入库,其余过程产物如回测结果/笔记/数据由 `.gitignore` 忽略)。
- 两者都通过 `importlib` 按文件路径加载(信任本地用户)。
- `strategies/`、`deployed/`、`experiments/` 均有 `__init__.py` 成为正规包(避免命名空间包子线程隐患)。
- 基类:`from services.backtest.strategy_base import Strategy`。原顶层 `strategies/base.py` 已合并 `ParamAccessor` → `strategy_base.py`(旧 `services/backtest/base.py` 已删)。
- **唯一未清残留** = `strategies/utils/{conservative,growth,financial,quality,...}.py` 中文字段名(待单独清理)。

## 核心组件

- **统一 Context**(`context.py`):`Context` 类**取代旧 ScreenerContext / TraderContext**,集中管理市场数据访问、broker 下单、决策日志、symbol pool 注入(每根 bar 由 Engine 注入)、因子收集(`record_factor` / `get_factors` / `reset_factors`)。轻量版 `ScreenContext` 用于 `/api/screener/run` 与 scan-radar(无 broker、可选 `log_sink`)。
- **MarketData 适配器**(`market_data.py`):BacktestEngine 数据层。预计算 numpy 缓存(daily OHLC 数组、日期数组、估值/财务表),日期索引用二分查找(O(log N))。**启动时预聚合周/月线**(`aggregate_kline`),其余频率懒加载。`get_bar_at` 比 `get_price` 快 ~9.6×。strict 模式仅在目标日期精确匹配 period 末日时返回 bar。
- **指标预计算**(`indicators.py`,Phase 6):数据加载阶段一次性计算 MA(5/10/20/30) + EMA + MACD + Volume MA + 1日收益 + 20日波动率,挂到 DataFrame 列上。Context 通过 `get_indicator(name, symbol)` O(1) 查找。MA/EMA 窗口决策:5/10/20/30。
- **BacktestEngine**(`engine.py`):统一执行流,两种模式:
  - `run()` — 完整回测:迭代窗口内每根 bar,定期调 `screen()`(按策略频率),累积 `target_symbols`,broker 撮合,触发 `on_buy/on_sell` hooks,输出 metrics/equity_curve/trades + 决策日志。
  - `run_scan()` — 雷达扫描模式:沿时间线每个频率周期跑一次 `screen()`,收集所有 hits + 因子值,服务于 `/api/backtest/scan-radar`(`/api/screener/run` 退化为只评估最后一根 bar)。
- **迭代窗口**(2026-05):构造器接收 `iter_start / iter_end` + period 数据,允许长指标 lookback 从更早日期预热,但只在窗口内产生交易/扫描结果。
- **数据缓存层**(`data_cache.py`):全市场 `MarketBundle`(symbol → DataFrame mapping + 估值/分红/财务字典),`slice_bundle()` 派生 `SlicedBundle`(可迭代,向后兼容),scheduler 市场更新后自动 invalidate + rebuild。⚠️ **daily/weekly/monthly 数据始终保留全历史**(`slice_bundle` 的 start/end 仅定迭代范围,不裁剪 daily),保证月线 MA20 等长窗口指标正确。
- **决策日志**(`DecisionLogSink`):每个回测/扫描任务产出独立日志目录,记录 screen 决策、买卖动作、因子值。雷达扫描默认开启。
- **策略雷达**(StrategyRadar):基于 `run_scan()`,前端支持 lookback、参数对话框、结果导出 Excel、多 hits 单行+hit 数列、涨跌幅按信号日累计、因子值 pill 展示。
- `aggregate_kline()`(`services/market_data/stock_data.py`)处理 W-FRI / M 聚合,被 MarketData 启动时调用。
- `date_utils.py`:`format_match_date / date_belongs_to / detect_frequency`。

## 港股通虚拟市场(HK_CONNECT,2026-06-01)

- **`HK_CONNECT` 是虚拟市场**,不是物理市场。回测/雷达的 `market` 入参除 `A/HK/US` 外新增 `HK_CONNECT`,语义 = 港股通成分股子集。
- **物理数据复用 HK**:`market_filter.py::resolve_data_market("HK_CONNECT") → "HK"`,`data_cache.get_market` 必须收到 `HK`,不能收到 `HK_CONNECT`。
- **symbols 维度过滤**:`apply_market_filter` 在 HK_CONNECT 时把 symbols 收敛为 `services.hk_connect_updater.get_latest_hk_connect_codes()` 的 `.HK` 后缀集合(601 只),无 requested 时返全集,有 requested 时返交集。
- **数据来源**:`data/market/HK/membership/hk_connect.parquet`(updater 周更),DuckDB 视图 `v_hk_connect_membership`。
- **🚨 已知偏差**:仅当前快照,**无 point-in-time 历史**;长区间回测会引入 ~2-3% look-ahead + survivorship bias。粗筛 / 资产配置可接受,严格 PIT 策略不适用。
- **前端**:`BacktestConfig.tsx` 市场下拉新增"港股通",内部 `DisplayMarket = 'A'|'HK'|'US'|'HK_CONNECT'`,`toCacheMarket()` 映射回 HK;`api/backtestCache.ts::CacheMarket` 保持 3 值不变(API 契约不动)。
- **路由覆盖**:`/api/backtest/run`、`/api/backtest/scan-radar` 已接 helper;`/api/backtest/cache/load`、`DELETE /api/backtest/cache/{market}` 先 `resolve_data_market` 再校验白名单。**`/api/screener/run` 暂未接入**(仅 A 股硬编码)。

## 现金流保守策略(粗算版)— `ConservativeRoughStrategy`

> 术语:本项目统一用**「现金流保守策略」**(英文标识符 `conservative` / `cpa_conservative`),历史代号「龟龟策略 / Turtle」已弃用。Python 符号 `MoatRatingConservative` / `map_moat_rating_conservative`。

- **不等于 cpa 精算 KK**:cpa 11 步精算(V1-V5 非经常分类 / 6.X2 隐性必要支出 / 7 会计准则 / 8 AA 三选一)需 LLM 读年报附注做定性判断,**不可机械化**。
- **本策略只做粗算 R + 4 项 Layer 2 否决**:`R = NP × 近3年支付率均值 / 市值`,门槛 5.2%(II 4.7% + 安全边际 0.5pct);否决项=金融股/商誉占比>30%/净现金转负/FCF 持续 2 年负。
- **用途**:① 给 cpa Agent 提供候选股票池(5400+ → 几十);② 作为 cpa LLM 真实精算结果的回测基线对比。
- **代码位置**:`strategies/utils/conservative.py` + `strategies/deployed/conservative_rough_strategy.py`,docstring 显式标注「粗算 / 不是 cpa 精算 KK」。

### 三层模型 Roadmap(详见 `docs/design_conservative_strategy_layers.md`)

把 cpa 11 步精算定性框架机械化拆成三层流水线 + 一个仓位矩阵:

- **L1 估值因子**:R(粗算)/ KK(精算预留)+ **L1.3 信誉评级**(5年营收 CV / 利润调整幅度 / λ warning 三维 → high/mid/low)。
- **L2 价值陷阱**:5 项 disqualifier(行业/商誉/净现金/FCF/ROE 三年下降)+ **L2.5 trap_rating** 软评分聚合(low/mid/high)。
- **L3 仓位矩阵**(2026-05-28 改 CPA 原口径):`f(R, credibility, trap_rating) → tier ∈ {full, p70, observe, skip}` 4 档(KK 0.5~1.5pct 一律 observe,无 50% 档),`full_bonus=1.5pct`。
- **L3.3 Buyer**(2026-05-28 重写):`CpaTierBatchBuyer` 抛弃市值加权,改 tier-based 单股配比(`max_per_stock_pct × TIER_PCT[tier]`,默认 full=20%/p70=14%),N 周 `order_target_percent` 等额爬坡。
- **L4 卖出**:CPA 7 条基本面止损(`phase3_valuation.md` §10.2 表),critical 清仓 / warning 减仓 50%(per-reason 去重),入场时记录 D/E、毛利率、payout 三个 baseline。
- **当前实现**:L1.R + L1.3 + L2 5 项 + L2.5 trap_rating + L3 矩阵 4 档 + `CpaTierBatchBuyer` + CPA 7 条止损全部落地 ✅。
- **KK→R 退化决策**:2026-05-27 reset,KK 精算需 LLM 读年报附注不可机械化,粗算 R 即可作 cpa Agent 候选池筛选。
- **金融股盲点**:cpa 框架 FCFF_BACK 不适用银行/保险/证券,`ConservativeRoughStrategy` 已整类排除。

## TODO

- **`ConservativeRoughStrategy` 真实回测验证**(2026-05-28 重写后):L3 矩阵改 CPA 4 档 + `CpaTierBatchBuyer` + CPA 7 条止损全部落地,需要在真实历史区间(全市场 / 至少 5 年)跑一次端到端回测,与旧"市值加权 + screen pool 白名单"版本对比超额收益。

## 关键文件

```
backend/services/backtest/
├── engine.py               # 统一引擎:run() 完整回测 + run_scan() 雷达扫描
├── strategy_base.py        # Strategy 单一类 + ParamAccessor(2026-06-14 合并自旧 base.py)
├── context.py              # Context 统一(取代旧 ScreenerContext / TraderContext)
├── market_data.py          # numpy 缓存 + 二分查找;启动预聚合周/月线
├── indicators.py           # 加载阶段一次性算 MA/EMA/MACD/Vol MA + Context O(1) 查
├── data_cache.py           # MarketBundle 全市场 + slice_bundle 派生(始终保留全历史)
├── decision_log.py         # per-task 决策日志目录
├── broker.py               # T+1 / 涨跌停 / 佣金 / price_func
├── portfolio.py            # 资产/持仓(回测内)
├── analyzer.py             # 指标计算
├── strategy_loader.py      # importlib 扫描 + frequency
├── task_manager.py         # SQLite 持久化 + 进度
├── market_filter.py        # resolve_data_market / apply_market_filter(HK_CONNECT)
├── date_utils.py           # format_match_date / date_belongs_to / detect_frequency
└── strategies/
    ├── deployed/           # 已发布策略(UI 只扫这里),现存 5 个
    ├── experiments/        # 在研策略(优先写这里,不暴露给 UI)
    └── utils/              # 因子工具:conservative/growth/financial/quality/kline/composite
```
