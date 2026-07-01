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
- 当前为**单一 Strategy 类**(`strategy_base.py::Strategy`),策略实现 `screen(ctx, symbols) -> List[str]` + 可选 `on_buy(ctx)` / `on_sell(ctx)` hooks。
- 示例:`strategies/deployed/hk_garp_strategy.py`、`strategies/deployed/lynch_slow_growers_strategy.py`(`ma_tangle_value` 已降级到 `experiments/ma_tangle_value/`)。
- 任何看到旧文档/代码提到 ScreenerStrategy/TraderStrategy/BuyStrategy/SellStrategy 的,都按"已合并到单一 Strategy"理解。
- **API 兼容**:`/api/screener/run` 与 `/api/backtest/run` 仍接收 `pipeline: []` 数组,但**只取首元素**加载策略类(importlib),应用参数覆盖,执行 `screen` / 完整回测。

## 🚨 策略目录铁律(2026-06-14 迁入 backtest;2026-07-01 增补自闭环)

策略已从顶层 `strategies/` **整体迁入** `backend/services/backtest/strategies/`(理由:策略均为开发者自写、与回测引擎深度耦合,Phase 6.2「作者无需感知 backend」反转依赖理由已不成立)。

- `strategies/deployed/` = **已发布策略**(UI/回测 `/api/backtest/strategies` 只扫这里,经 `config.DEPLOYED_STRATEGY_DIR`)。**现存 2 个**:`lynch_slow_growers_strategy.py`、`hk_garp_strategy.py`。
- `strategies/experiments/` = **在研策略**(策略研究优先写这里,**不暴露给 UI**)。**每策略一个自闭环子目录** `experiments/<strategy>/`,现存 `a_garp` / `conservative_rough` / `garp_value_first` / `growth` / `low_valuation_multifactor` / `low_valuation_quarterly` / `lvmf_c_full_t30` / `ma_tangle_value` + `lynch/`(二级,含 fast_growers / slow_growers / stalwarts / turnarounds / cyclicals 五子策略 + 共享研究报告)。
- **🚨 自闭环铁律(2026-07-01)**:一个策略的**配套资产全部放进它自己的 `experiments/<strategy>/` 子目录**,与策略代码同处、自成闭环 —— 包括:**跑批/诊断脚本(matrix / diag runner `.py`)、研究报告(`.md`)、回测结果(`.json` / `_overview.md`)、决策日志(`.jsonl`)**。目标是整目录可独立迁移 / 删除、对外零引用。**禁止**把这些散落到**项目根目录**、顶层 `scripts/`、`report/exported/` 等公共位置。
  - 范例:`experiments/lynch/lynch_turnarounds/` = `lynch_turnarounds_strategy.py` + `run_lynch_turnarounds_matrix.py` + `lynch_tr_r1.json` + `lynch_tr_r1_overview.md`,四件套同目录闭环。
  - 自闭环技术做法(见 lynch 各 matrix):脚本内 `ROOT = Path(__file__).resolve().parents[N]` 定位仓库根、`OUT_DIR = Path(__file__).resolve().parent` 让产物落回自身目录、跨策略引用走相对包 import,**不硬编码绝对路径、不依赖 CWD**。
  - **git 与物理位置解耦**:自闭环是物理组织原则(便于整体迁移/删除),与是否入库无关。**入库规则(2026-07-01 起,`.md`/`.json` 视为研究成果纳入版本管理)**:`.gitignore` 的 `experiments/**` + `!**/*.py` + `!**/*.md` + `!**/*.json` 例外 —— **`.py`(含 `__init__.py`)源码 + `.md` 研究报告/结论 + `.json` 回测结果均进 git**;`.jsonl` 决策日志 + 其他数据文件仍被忽略(可再生、噪声大、体积可膨胀)。⚠️ `.json` 入库的关键理由:`data/market/` 整体 gitignore 且随时间变动(新增 bar / 财务重述),脚本**日后重跑无法精确复现**同一数字 → `.json` 是唯一可复现的**研究时点证据**。(无论入库与否,过程产物都必须放策略子目录内,勿丢项目根)。
- **🚨 文档职责边界(2026-07-01)**:本 AGENTS.md **只写架构 / 铁律 / 目录结构**,**不写任何具体策略的业务描述**(选股逻辑 / 因子口径 / 参数 / 回测结论 —— 易过时,须就近维护)。策略详情看两处:① 策略 `.py` 模块 docstring(设计意图 / 边界 / 选股管线);② 策略目录内 markdown —— 整类策略详情见如 `experiments/lynch/林奇六类型策略研究报告.md`,单轮回测结果见如 `experiments/lynch/lynch_turnarounds/lynch_tr_r1_overview.md`。
- 两者都通过 `importlib` 按文件路径加载(信任本地用户)。
- `strategies/`、`deployed/`、`experiments/` 及各策略子目录均有 `__init__.py` 成为正规包(避免命名空间包子线程隐患)。
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

## 港股通标的池(HK_CONNECT 过滤层)

- **港股通是真实的互联互通机制**(「内地与香港股票市场交易互联互通机制」南向,含沪港通/深港通下的港股通),标的 = 联交所上市股票中受监管的**特定子集**,由两地交易所定期调入调出。
- **`HK_CONNECT` 不是独立市场,而是 HK 之上的成分过滤层(universe filter)**:回测/雷达 `market` 入参除 `A/HK/US` 外新增 `HK_CONNECT`,语义 = 仅在港股通标的子集内选股。
- **物理数据复用 HK**:`market_filter.py::resolve_data_market("HK_CONNECT") → "HK"`,`data_cache.get_market` 必须收到 `HK`,不能收到 `HK_CONNECT`。
- **symbols 维度过滤**:`apply_market_filter` 在 HK_CONNECT 时把 symbols 收敛为 `services.market_data.updaters.hk_connect_updater.get_latest_hk_connect_codes()` 的 `.HK` 后缀集合(当前快照全集,标的由两地交易所定期调入调出),无 requested 时返全集,有 requested 时返交集。
- **数据来源**:`data/market/HK/membership/hk_connect.parquet`(updater 周更),DuckDB 视图 `v_hk_connect_latest`。
- **🚨 已知偏差**:仅当前快照,**无 point-in-time 历史**;长区间回测会引入 ~2-3% look-ahead + survivorship bias。粗筛 / 资产配置可接受,严格 PIT 策略不适用。
- **前端**:`BacktestConfig.tsx` 市场下拉新增"港股通",内部 `DisplayMarket = 'A'|'HK'|'US'|'HK_CONNECT'`,`toCacheMarket()` 映射回 HK;`api/backtestCache.ts::CacheMarket` 保持 3 值不变(API 契约不动)。
- **路由覆盖**:`/api/backtest/run`、`/api/backtest/scan-radar` 已接 helper;`/api/backtest/cache/load`、`DELETE /api/backtest/cache/{market}` 先 `resolve_data_market` 再校验白名单。**`/api/screener/run` 暂未接入**(仅 A 股硬编码)。

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
    ├── deployed/           # 已发布策略(UI 只扫这里),现存 2 个:hk_garp_strategy / lynch_slow_growers_strategy
    ├── experiments/        # 在研策略,每策略一自闭环子目录(不暴露 UI);lynch/ 下再分 fast_growers/slow_growers/stalwarts/turnarounds/cyclicals 五子策略
    └── utils/              # 因子工具(15 个 .py + composite/):
        ├── conservative.py / conservative_sell.py    # 现金流保守策略专用:选股因子 / 卖出规则工具
        ├── growth.py / growth_long.py / growth_hk.py  # 成长(通用 / 年报 NOTICE_DATE PIT / 港股)
        ├── balance_long.py                            # 负债率 PIT 历史 + 去杠杆信号(NOTICE_DATE 严格)
        ├── financial / quality / dividend / valuation / yield_factor / index_timing / hk_industry / st_filter / kline .py
        └── composite/                                 # 组合买入器:cpa_tier_batch_buyer(在用)/ market_cap_weighted_batch_buyer(旧,已弃)
```
