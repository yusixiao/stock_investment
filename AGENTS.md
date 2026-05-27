# AGENTS.md

## Goal

打造个人股票投资综合平台:支持 A 股、港股、美股的行情/财务/分红/估值数据采集,K 线可视化,选股+回测引擎,持仓管理,以及面向投顾场景的 LLM Agent 对话。项目按子项目增量迭代,目前已迈过早期 MVP 阶段,进入「架构 DDD 化 + 前端全面重构 + 多市场数据层」的阶段。

## Instructions

- **🚨 审视指令铁律**:**不要盲目遵循指令**。如果觉得用户指令有问题、不清晰、或与既有铁律冲突,**严格审视 → 提出疑问 → 等待澄清**,不要硬干。技术分歧要直说,不要附和
- **🚨 项目结构铁律(2026-05-24)**:按"可重建性 + 备份策略"分四类顶层目录
  - `data/` — **原始/业务数据**(parquet 行情/财务/分红/估值、`portfolio.db`),DuckDB 视图来源,**进备份**
  - `report/` — **用户产物**(LLM 生成的分析报告 = 花 token 的 artifact),`report/agent_runs/<code>_<name>/` workspace + 报告,**进备份**
  - `cache/` — **纯派生缓存**(`cache/tavily/`、`cache/qfq/` 等),可随时删,自动重建,**不备份**
  - `logs/` — **运行日志**(应用日志、调度器日志),可定期清理,**不备份**
  - 新代码**禁止**写入 `data/{agent_runs,cache,logs}`,旧路径需逐步迁移并清理
- **沟通语言**:中文
- **技术栈**:
  - 后端 Python:FastAPI + APScheduler + DuckDB(查询层)+ pandas/parquet(存储)+ SQLite(业务库)
  - 前端 React 19 + TypeScript + Vite 7 + Tailwind v4 + zustand + react-router 7 + lightweight-charts(K 线)+ recharts(回测曲线)+ react-markdown
- **数据源**:多 adapter 架构 — `BaoStockAdapter`(A 股 K 线/基础)、`EastMoneyAdapter`(财务/估值/股本默认)、`YFinanceAdapter`(港股/美股)。`adapters/data_source.py::create_default_data_source()` 统一装配
- **🚨 数据源铁律(2026-05-24)**:**禁止使用 akshare**(在本环境不稳定/经常超时)。所有新代码与现有改动必须用 **baostock / eastmoney / yfinance**;旧依赖 akshare 的代码逐步迁移至 DuckDB 视图(已有完整 EastMoney 财务/指标数据)或 baostock。`backend/adapters/akshare_adapter.py` 已删除;`scripts/migrate_financial_akshare.py` 等历史一次性迁移脚本保留供归档,不再调用
- **数据存储**:
  - **🚨 铁律(2026-05-21):所有业务数据来源**必须**是 `data/market/`,绝对禁止读取 `data/{kline,financial,dividend,valuation,indicators}/...` 等任何旧路径**。新增数据(分红、估值等当前缺失类目)也**必须落到 `data/market/{A,HK,US}/<category>/`** 下,按市场分区组织,统一英文 schema(对齐 EastMoney/YFinance 原始字段)
  - **唯一业务数据源 = DuckDB**(2026-05-18 决策):所有业务代码(回测、选股、K 线展示、财务/估值/分红查询)**必须**经 `services/duckdb_store.py` 访问数据,**禁止**直接 `glob` parquet 或读旧路径文件。新增数据访问 API 必须先在 `DuckDBStore` 上加方法/视图
  - **DuckDB 唯一来源 = `data/market/`**:`data/market/{A,HK,US}/{daily,adjust_factor,financial/{income,balance,cashflow,indicator}}/*.parquet`(DuckDB 视图 `v_a_daily / v_a_adjust_factor / v_a_income / v_a_indicator / ...` 等)。财务表统一英文 schema(`REPORT_DATE / NETPROFIT / BASIC_EPS / ROEJQ / EPSJB / BPS / ...`)
  - **旧路径完全废弃**(2026-05-21 重申):`data/kline/`、`data/financial/A/`(中文 schema)、`data/dividend/A/`、`data/valuation/A/`、`data/indicators/A/` 全部不再被任何业务代码读取。当前残留引用(`config.py` 的 `VALUATION_DIR/DIVIDEND_DIR/FINANCIAL_DIR/INDICATOR_DIR`、`data_cache._load_valuation/_load_dividend/_load_financial`、`valuation_updater/dividend_updater` 写路径、`strategies/utils/{dividend,valuation,financial}.py` 中文字段名)需要逐步清理。物理目录可手动删除
  - 复权因子:`data/market/{market}/adjust_factor/*.parquet`
  - 业务库:`data/portfolio.db`(SQLite)— portfolios / trades / snapshots / backtest_tasks / strategy_groups / group_runs
- **代码注释**:复杂/非显然逻辑必须加注释;日志保持信息量
- **MACD bar**:`2 × (DIF - DEA)`(用户明确要求)
- **策略定义**:本地 `strategies/examples/*.py`,通过 `importlib` 加载(信任本地用户)
- **回测架构**:事件驱动,Broker 处理 T+1、涨跌停、佣金万三+印花税千一、滑点。已从单一 `TraderStrategy` **拆分为 BuyStrategy + SellStrategy**(`buy_sell_engine.py`)
- **Pipeline 模型**:0..N ScreenerStrategy → 0..1 BuyStrategy → 0..1 SellStrategy。Pipeline 顺序由用户在 UI 中决定,**不按频率自动排序**
- **Pipeline 时间相关性**:相邻 screener 间 `join_mode = "independent"(OR 并集)| "correlated"(AND 粗周期内交集)`,`join_modes` 数组长度 = `len(screeners) - 1`,默认全部 independent(向后兼容)
- **成交价**:默认 `(open + close) / 2` 中间价。Broker 支持自定义 `price_func`(如 BatchBuyTrader 用月线 `(high+low)/2`)
- **回测数据**:使用 `qfq/`(前复权);K 线显示支持 raw/qfq 切换
- **年化收益率**:`(1 + total_return) ^ (1 / years) - 1`,`years = natural_days / 365.25`
- **持仓估值**:用 parquet 最新收盘价(非实时 API)。**持仓本身不入库**,由 trades 在内存推导
- **akshare 已禁用**(见上方数据源铁律) — 历史 mock 测试仅作迁移期保留
- **`write` 工具对超大内容会中止** — 拆成多次小写
- **前端端口**:3001(`vite.config.ts`),代理 `/api → 127.0.0.1:8000`
- **策略模型(2026-05 重构,Phase 6)**:**Pipeline + Screener/Buyer/Seller 三角拆分模型已废弃**。当前为**单一 Strategy 类**(`strategies/base.py::Strategy` / `ScreenerStrategy`),策略实现 `screen(ctx, symbols) -> List[str]` + 可选 `on_buy(ctx, symbol)` / `on_sell(ctx, symbol)` hooks。示例:`strategies/examples/ma_tangle_value_strategy.py`、`ma_close_strategy.py`
- **API 兼容**:`/api/screener/run` 与 `/api/backtest/run` 仍接收 `pipeline: []` 数组,但**只取首元素**加载策略类(importlib),应用参数覆盖,执行 `screen` / 完整回测
- **统一 Context**(`backend/services/backtest/context.py`):`Context` 类**取代旧 ScreenerContext / TraderContext**,集中管理市场数据访问、broker 下单、决策日志、symbol pool 注入(每根 bar 由 Engine 注入)、因子收集(`record_factor` / `get_factors` / `reset_factors`)。轻量版 `ScreenContext` 用于 `/api/screener/run` 与 scan-radar(无 broker、可选 `log_sink`)
- **MarketData 适配器**(`backend/services/backtest/market_data.py`):BacktestEngine 数据层。预计算 numpy 缓存(daily OHLC 数组、日期数组、估值/财务表),日期索引用二分查找(O(log N))。**启动时预聚合周/月线**(`aggregate_kline`),其余频率懒加载。`get_bar_at` 比 `get_price` 快 ~9.6×。strict 模式仅在目标日期精确匹配 period 末日时返回 bar
- **指标预计算**(`backend/services/backtest/indicators.py`,Phase 6 新增):数据加载阶段一次性计算 MA(5/10/20/30) + EMA + MACD + Volume MA + 1日收益 + 20日波动率,挂到 DataFrame 列上。Context 通过 `get_indicator(name, symbol)` O(1) 查找。MA/EMA 窗口决策:5/10/20/30(用户 2026-05 决定)
- **BacktestEngine**(`backend/services/backtest/engine.py`):统一执行流,两种模式:
  - `run()` — 完整回测:迭代窗口内每根 bar,定期调 `screen()`(按策略频率),累积 `target_symbols`,broker 撮合,触发 `on_buy/on_sell` hooks,输出 metrics/equity_curve/trades + 决策日志
  - `run_scan()` — 雷达扫描模式:沿时间线每个频率周期跑一次 `screen()`,收集所有 hits + 因子值,服务于 `/api/backtest/scan-radar`
- **迭代窗口**(2026-05):构造器接收 `iter_start / iter_end` + period 数据,允许长指标 lookback 从更早日期预热,但只在窗口内产生交易/扫描结果
- **数据缓存层**(`backend/services/backtest/data_cache.py`):全市场 `MarketBundle`(symbol → DataFrame mapping + 估值/分红/财务字典),`slice_bundle()` 派生 `SlicedBundle`(可迭代,向后兼容),scheduler 市场更新后自动 invalidate + rebuild
- **决策日志**(`DecisionLogSink`):每个回测/扫描任务产出独立日志目录,记录 screen 决策、买卖动作、因子值。雷达扫描默认开启
- **链式回测**:`POST /api/backtest/run` 接收可选 `source_task_id`,继承源任务 `screened_symbols` + 日期范围。`backtest_tasks` 表有 `source_task_id` 列
- **Signal Table 模式**:链路提供预算好的 `screened_symbols + match_dates` 时,Engine 跳过实时选股,在信号日按 hooks 执行
- **策略雷达**(StrategyRadar):基于 `run_scan()`,前端组件支持 lookback(1m/3m/6m/1y/...)、参数对话框(createPortal)、结果导出 Excel、多 hits 单行+hit 数列、涨跌幅按信号日累计、因子值 pill 展示
- **后端架构 DDD 三层**:`adapters/`(外部数据源)→ `repositories/`(parquet/DuckDB I/O)→ `services/`(领域服务)。`models/` 定义 Pydantic 实体,`domain/` 放领域常量
- **测试**:550+ case,`python -m pytest backend/tests/ -x -q`。adapter 测试用 mock(`test_adapters.py` 等)
- **长任务后台执行**:任何预计运行超过 1 分钟的任务(回测、矩阵跑批、诊断脚本、全市场数据更新、批量数据迁移等)**必须**用 `nohup ... > log 2>&1 &` 后台执行,前台只查 PID/日志/进度,避免阻塞会话

## Terminology

- **🚨 术语铁律(2026-05-26)**:本项目内部统一使用 **「现金流保守策略」**(英文标识符 `conservative` / `cpa_conservative`)指代基于穿透回报率的保守估值策略。
- **历史代号 「龟龟策略 / Turtle」 已弃用**,不要在新代码、新 prompt、新文档中出现。
- **唯一例外**:`/Users/11182300/PycharmProjects/Turtle_investment_framework` 是外部 sibling 项目的真实路径,引用该路径或描述「prompt 来源于 Turtle 框架」时保留 `Turtle` 字样,不替换。
- **Python 符号对应**:`MoatRatingConservative` / `map_moat_rating_conservative` / `_MOAT_RATING_CONSERVATIVE_MAP`。
- **Prompt 文件**:`judgment_examples_conservative.md`(原 `judgment_examples_turtle.md`)。

## Discoveries

- ~~`data/kline/A/raw/`:不复权;`data/kline/A/qfq/`:前复权~~ 已废弃,现统一走 `data/market/A/daily/` + DuckDB `query_qfq_kline` ASOF JOIN 派生
- Parquet 7 列(date 字符串、open/high/low/close/volume/amount float64),日期降序
- BacktestEngine 两种模式:
  - **`run_scan()`** — 雷达扫描:每个频率周期触发一次 `strategy.screen()`,聚合 hits + 因子值,服务 `/api/backtest/scan-radar` 与 `/api/screener/run`(后者退化为只评估最后一根 bar)
  - **`run()`** — 完整回测:窗口内逐 bar 迭代,frequency 切换时调 screen() 累积 target pool,触发 `on_buy/on_sell` hooks,输出 metrics/equity_curve/trades
- 任务结果持久化到 SQLite `backtest_tasks` 表(`final_result` 列存完整 JSON);进度仍存内存
- **性能优化**:`MarketData` 启动时预聚合周/月线 + 预计算所有指标列(`indicators.py`),`get_bar_at` 用 numpy 二分查找,比 `get_price` 快 ~9.6×。Context 的 `get_indicator(name, symbol)` 直接读 DataFrame 列,O(1)
- `aggregate_kline()`(`services/stock_data.py`)处理 W-FRI / M 聚合,被 MarketData 启动时调用
- **DuckDB 查询层**(`services/duckdb_store.py`):用 `read_parquet()` 注册视图(`v_a_daily / v_hk_daily / v_us_daily / v_*_adjust_factor / v_*_{income,balance,cashflow,indicator}`),不导入数据
- **前端从 Vue 迁到 React**(2025 末):旧版备份保留在 `frontend/src_vue_backup/`
- **回测页三 Tab 结构**:策略回测(BacktestAnalysis)/ 策略雷达(StrategyRadar)/ 市场监控(MarketMonitor)
- **K 线图**(`KlineChart.tsx`,lightweight-charts v5):默认显示 150 根,价格 MA5/10/20/30/60 可切换、Volume MA5/10、MACD pane,鼠标跟随 Tooltip,左右价格刻度可配
- 后端 `backend/main.py` 启动时把项目根加入 `sys.path`,因为 `backend/` 没有 `__init__.py`
- 前端 npm name 是 `dsa-web`(早期 daily_stock_analysis 遗留)

## Accomplished

### 子项目 1-3 全部完成(数据管理+K 线 / 选股+回测 / 持仓管理)

### 多市场数据层(2025 末-2026 初)

- `adapters/`:base / baostock / eastmoney / yfinance + `data_source.py` 装配器
- `models/`:basic / market / financial / event 四大 Pydantic 实体
- `repositories/`:base / basic_repo / market_repo / financial_repo / event_repo,封装 parquet I/O(读/写/append/排序去重)
- `services/market_updater.py`:A/HK/US 并行增量更新(K 线 + 复权因子)
- `services/duckdb_store.py`:启动注册视图,提供 SQL 查询入口
- `routers/market_update.py`、`routers/market_kline.py`:手动触发 + K 线查询(含 MA、MACD)
- `scripts/backup_to_baidu.py`:周备份 `data/market/` 到百度网盘(bypy)
- 调度器(`scheduler.py`):每日 06:00 市场更新、15:30 持仓快照、周日 03:00 备份

### 财务/分红/估值子系统

- `services/dividend_updater.py` + `routers/dividend.py`(分红派息事件)
- `services/financial_updater.py` + `routers/financial.py`(三表 + 指标)
- `services/valuation_updater.py` + `routers/valuation.py`(PE/PB)
- `services/circulating_shares.py`(流通股)
- `services/indicator_store.py`(指标缓存)
- `services/stock_index.py`(全市场代码索引,启动加载)
- `services/qfq_cache.py`(前复权缓存,raw+dividend 派生)
- 对应 ScreenerContext 扩展:`get_dividend() / get_financial() / get_valuation()`

### 回测引擎演进

- **Buy/Sell 拆分**:`BaseStrategy → ScreenerStrategy / BuyStrategy / SellStrategy`,`buy_sell_engine.py` 替代旧 TraderStrategy 路径(旧 API 兼容)
- **Pipeline 时间相关性**(`join_mode`):`engine.py` 实现 OR/AND 合并,跨频率用 `date_belongs_to()` 归属判定
- **链式回测**:`source_task_id` 完整链路 + Signal Table 模式
- **新策略**:
  - `dividend_years_screener.py`(连续分红年限)
  - `roe_screener.py`、`pe_pb_product_screener.py`(估值)
  - `monthly_low_screener.py`、`monthly_volume_red_screener.py`
  - `ma_tangle_breakout_screener.py`(月线均线缠绕突破)
  - `market_cap_weighted_buyer.py`(按市值加权买入)
- **StrategyGroup**:`group_manager.py` + `routers/strategy_group.py`,支持 archiving / deletion / execution / 分步运行

### 前端 React 重构

- **技术栈切换**:Vue 3 → React 19 + TypeScript + Tailwind v4 + zustand + react-router 7,启用 babel-plugin-react-compiler
- **Shell 布局**:`Shell.tsx` + `SidebarNav.tsx` + `ShellHeader.tsx`,主题切换(next-themes + ThemeProvider)
- **认证**:`AuthContext` + `LoginPage`,后端可配置开关(authEnabled),路由守卫支持 redirect
- **页面**:
  - `HomePage` — 行情/K 线主页,StockAutocomplete 搜索,KlineChart(MA + MACD + 体量 MA + 跟随 Tooltip)
  - `BacktestPage` — 三 Tab(BacktestAnalysis / StrategyRadar / MarketMonitor),BacktestConfig 动态生成策略参数表单,BacktestHistory 历史列表,BacktestResult 含 progress phase 显示
  - `PortfolioPage` — 持仓管理
  - `ChatPage` — LLM Agent 对话(agentChatStore + useTaskStream),支持 markdown / followup / export
  - `SettingsPage` — LLM Channel 编辑、密码、智能导入、通知测试,分类导航
  - `LoginPage` / `NotFoundPage`
- **公共组件**:Card、Button、Drawer、ConfirmDialog、Pagination、ScoreGauge、StatCard、StatusDot、Toast、Tooltip 等约 25 个
- **Stores**:agentChatStore / analysisStore / stockPoolStore
- **i18n**:`locales/settingsHelp.ts`(设置项帮助文案)
- **测试**:vitest + @testing-library/react + Playwright(smoke)

### 持续增强

- 数据更新带日期选择,前端 poll 错误优雅停止
- 任务历史表显示类型/汇总/状态/创建时间
- 回测结果详情页显示 pipeline 配置 + 实际参数 + 日期范围

## Relevant files / directories

```
stock_investment/
├── backend/
│   ├── main.py                         # FastAPI app, lifespan: init_db + init_duckdb + init_stock_index + scheduler
│   ├── config.py                       # 全部数据路径常量
│   ├── scheduler.py                    # 06:00 market update / 15:30 snapshot / 周日 03:00 backup
│   ├── adapters/                       # base, baostock, eastmoney, yfinance, data_source
│   ├── domain/                         # stock 领域常量
│   ├── models/                         # basic / market / financial / event Pydantic
│   ├── repositories/                   # base / basic_repo / market_repo / financial_repo / event_repo
│   ├── routers/                        # stock / stock_search / market_kline / data_update / market_update / backtest / screener / portfolio / valuation / dividend / financial / agent / system_config / auth_stub / meta
│   ├── services/
│   │   ├── stock_data.py               # aggregate_kline (W-FRI / M)
│   │   ├── duckdb_store.py             # parquet 视图查询层
│   │   ├── stock_index.py              # 全市场代码索引
│   │   ├── qfq_cache.py                # 前复权缓存(派生)
│   │   ├── market_updater.py           # 多市场并行增量

│   │   ├── dividend_updater.py / financial_updater.py / valuation_updater.py
│   │   ├── circulating_shares.py / indicator_store.py / indicator.py
│   │   ├── api_utils.py / db_schema.py
│   │   ├── backtest/                   # Phase 6 后单一 Strategy 模型
│   │   │   ├── engine.py               # 统一引擎:run() 完整回测 + run_scan() 雷达扫描
│   │   │   ├── base.py                 # Strategy 单一类(screen + on_buy/on_sell hooks)
│   │   │   ├── context.py              # Context 统一(取代旧 ScreenerContext / TraderContext)
│   │   │   ├── market_data.py          # numpy 缓存 + 二分查找;启动预聚合周/月线
│   │   │   ├── indicators.py           # 加载阶段一次性算 MA/EMA/MACD/Vol MA + Context O(1) 查
│   │   │   ├── data_cache.py           # MarketBundle 全市场 + slice_bundle 派生
│   │   │   ├── decision_log.py         # per-task 决策日志目录
│   │   │   ├── broker.py               # T+1 / 涨跌停 / 佣金 / price_func
│   │   │   ├── portfolio.py            # 资产/持仓
│   │   │   ├── analyzer.py             # 指标计算
│   │   │   ├── strategy_loader.py      # importlib 扫描 + frequency
│   │   │   ├── task_manager.py         # SQLite 持久化 + 进度
│   │   │   └── date_utils.py           # format_match_date / date_belongs_to / detect_frequency
│   │   └── portfolio/
│   │       ├── db.py / manager.py
│   └── tests/                          # 797 cases
├── strategies/examples/
│   ├── ma_tangle_breakout_screener.py  # frequency = "monthly"
│   ├── dividend_years_screener.py
│   ├── monthly_low_screener.py / monthly_volume_red_screener.py
│   ├── pe_pb_product_screener.py / roe_screener.py
│   └── market_cap_weighted_buyer.py
├── frontend/                           # name: dsa-web,React 19 + TS + Tailwind v4
│   ├── vite.config.ts                  # port 3001, proxy /api → :8000
│   ├── src/
│   │   ├── App.tsx                     # 路由 + AuthProvider + Shell
│   │   ├── main.tsx
│   │   ├── pages/                      # HomePage / BacktestPage / PortfolioPage / ChatPage / SettingsPage / LoginPage / NotFoundPage
│   │   ├── components/
│   │   │   ├── KlineChart.tsx          # lightweight-charts v5,MA/MACD/Volume MA/Tooltip
│   │   │   ├── backtest/               # BacktestAnalysis / Config / History / Result / StrategyRadar / MarketMonitor
│   │   │   ├── common/                 # ~25 通用 UI 组件
│   │   │   ├── layout/                 # Shell / SidebarNav / ShellHeader
│   │   │   ├── settings/               # LLMChannelEditor / NotificationTestPanel 等
│   │   │   ├── report/                 # ReportMarkdown / ReportNews 等
│   │   │   ├── tasks/ history/ dashboard/ theme/ StockAutocomplete/
│   │   ├── api/                        # backtest / portfolio / stocks / agent / auth / history / analysis / systemConfig
│   │   ├── stores/                     # agentChatStore / analysisStore / stockPoolStore (zustand)
│   │   ├── contexts/AuthContext.tsx
│   │   ├── hooks/                      # useAuth / useTaskStream / useStockSearch 等
│   │   ├── types/ utils/ locales/
│   └── src_vue_backup/                 # Vue 旧版备份
├── data/
│   ├── market/{A,HK,US}/{daily,adjust_factor}/  # 新主路径
│   ├── kline/A/{raw,qfq}/              # 旧路径(qfq 已转缓存模型)
│   ├── valuation/A/ dividend/A/ financial/A/ indicators/A/
│   ├── meta/                           # 全市场代码索引等
│   ├── portfolio.db                    # SQLite
│   └── logs/
└── scripts/                            # backup_to_baidu.py 等
```

## Testing

```bash
python -m pytest backend/tests/ -x -q     # 后端 797 tests
cd frontend && npm test                    # 前端 vitest
cd frontend && npm run test:smoke          # Playwright smoke
cd frontend && npx tsc --noEmit            # 类型检查
cd frontend && npm run lint                # ESLint
```

## 问股(Ask Stock)Phase 1 数据包构成

`DataPackBuilder` 共 19 sections,002594.SZ 端到端跑通:
- §1 基础 / §2 市值股价 / §3·§3P 利润表 / §4·§4P 资产负债 / §5 现金流 / §6 股息
- §7 股东(EastMoney F10 三表) / §8 行业 + §10 ESG(Tavily search,7 天文件缓存,无 key 优雅降级)
- §9 主营 / §11 周线 / §12 比率 / §13 warnings / §14 Rf(`RF_CHINA_10Y` 常量) / §15 行业估值 / §16 同行对比 / §17 衍生
- ⬜ §7 质押 / 高管增减持(待单独 issue);⬜ §17.8 D&A → EV/EBITDA

LLM 流水线三阶段:Phase 1 数据包 → Phase 3.1 量化(`run_phase3_quant`,穿透回报率/阈值/安全边际)→ Phase 3.2 估值(`run_phase3_valuation`,生成 `*_分析报告.md`)。Coordinator `_run_full_pipeline` 串接,统一发 `tool_start/tool_done` + `_meta.json` 状态原子写,失败带 phase 标注。SSE 6 事件:thinking / tool_start / tool_done / generating / done / error。Workspace 按 `<code>_<name>/` 隔离。

## 问股(Ask Stock)架构 — 多 Agent + 4 层 Fallback(2026-05-24 决策)

### 总体定位
问股**不是单 agent 系统**,而是**多 agent 平台**。当前已实现 **CPA 问股(cpa)**,后续将扩展 **团队分析问股(team,多角色协作/辩论)** 等更多 agent。所以目录结构、Coordinator、Prompts 都必须按 agent 维度可扩展,**禁止把单一 agent 的实现细节硬编码进顶层模块**。

### 目录结构(重构目标)
```
backend/services/agent/
├── coordinator.py              # 顶层路由:4 层 fallback(暂留 agent/ 根)
├── core/                       # 通用基础设施(跨 agent 复用)
│   ├── parser.py / sse.py / session_repo.py / workspace.py
│   ├── symbol.py / llm_routing.py
│   └── prompts_loader.py       # 原 prompts/loader.py
├── agents/                     # 每个 agent 一个子包,自包含
│   ├── __init__.py             # AGENT_REGISTRY = {"cpa": CpaAgent, "team": ...}
│   ├── cpa/                    # CPA 问股(现有)
│   │   ├── agent.py            # CpaAgent.run(ctx) → AsyncIterator[SSEEvent]
│   │   ├── pipeline/           # phase1_data_pack / phase3_quant / phase3_valuation
│   │   └── prompts/            # coordinator.md / phase3_*.md / references/
│   └── team/                   # 团队分析问股(未来)
│       ├── agent.py            # 多角色协作(分析师/风控/策略)
│       ├── pipeline/
│       └── prompts/
```

### 设计原则
1. **每个 agent 自包含** — `agents/<name>/` 包含自己的 pipeline + prompts + 解析逻辑,**不跨 agent 共享业务代码**;共享的下沉到 `core/`
2. **统一入口契约** — 每个 agent 实现 `Agent.run(ctx) -> AsyncIterator[SSEEvent]`,Coordinator 只关心这个接口
3. **AGENT_REGISTRY** — `agents/__init__.py` 维护 `name → class` 映射,Coordinator 按意图分类结果路由
4. **Prompts 跟着 agent 走** — cpa 的 prompts 在 `agents/cpa/prompts/`,team 的在 `agents/team/prompts/`,各自独立演进

### Coordinator 4 层 Fallback(规则 + LLM 意图分析混合)
**不让用户显式选 agent**,Coordinator 自动路由,顺序如下:

```
Layer 1 (规则): session.output_dir 已有完整报告 → qa_followup
              ↓ (无报告)
Layer 2 (规则): 无股票上下文 + 消息无股票码 → chitchat
              ↓ (识别到股票码)
Layer 3 (LLM): 意图分类器(轻量 LLM call)→ 选 agent
              { 个股深度分析 → cpa
                团队辩论 / 多视角对比 → team
                其他 ... → ... }
              ↓ (LLM 失败/超时/置信度低)
Layer 4 (兜底): 默认 agent = cpa (当前唯一稳定 agent)
```

- **Layer 1/2 是规则快路径**:无需 LLM,毫秒级响应
- **Layer 3 是 LLM 意图分类**:仅在识别到股票码后触发,决定派给哪个 agent
- **Layer 4 是兜底**:意图分类失败永不阻塞,降级到 cpa

### 当前实现状态(2026-05-26)
- ✅ Layer 1/2/4 已在 `coordinator.py` 实现(三分支版)
- ✅ **目录重构已完成**:`agents/cpa/{agent.py, pipeline/, prompts/}` + `core/`(session_repo / llm_routing / tavily_client / prompts_loader / symbol / sse / parser / workspace) 全部到位,旧 `pipeline/` 与 `prompts/turtle/` 已迁走
- ✅ **Layer 2.5 关键词路由**:`coordinator.py` 在识别到股票码后扫描 BA 关键词(护城河/管理层/周期性/...),命中即路由 `business_analysis` agent
- ✅ **business_analysis agent**(2026-05-26):`agents/business_analysis/` 用户入口 + `core/qualitative/` 共享 service(6 维度全部真实实现)
- ❌ Layer 3 LLM 意图分类**未实现**,识别到股票码 + 无 BA 关键词时直接走 `DEFAULT_AGENT = cpa`

## 定性分析子系统(`core/qualitative/` + business_analysis agent · 2026-05-26)

### 架构

```
backend/services/agent/
├── core/qualitative/                # 共享 service(cpa Phase 0 / business_analysis 复用)
│   ├── schema.py                    # DimensionReport / QualitativeParams(14 字段) / QualitativeReport
│   ├── runner.py                    # run_qualitative(ref, store, tavily, llm) 编排 6 维度
│   ├── cache.py                     # data/qualitative/<code>_<name>/ 30 天 TTL + REPORT_DATE 失效
│   ├── dimensions/d{1..6}.py        # 6 维度真实实现
│   └── prompts/d{1..6}.md           # LLM prompt(评级指引固化保守策略口径)
└── agents/business_analysis/        # 用户入口 agent(SSE 6 事件)
    └── agent.py                     # BusinessAnalysisAgent.run → run_qualitative + 落 qualitative_report.md
```

### 6 维度数据源

| 维度 | 数据源 | 输出参数 |
|---|---|---|
| **D1** 商业模式 | DuckDB(资产负债 + 指标视图) | `capital_intensity / collection_mode` |
| **D2** 护城河 | DuckDB(长期 ROE/毛利率)+ Tavily | `moat_type / moat_flywheel / moat_rating / competitors[]` |
| **D3** 行业周期 | DuckDB(营收/利润波动)+ Tavily | `cyclicality / cycle_position` |
| **D4** 管理层 | EastMoney emweb F10(A 股)/ yfinance(HK+US)+ Tavily | `management_rating ∈ {优秀/合格/损害价值/观察期}` |
| **D5** 经营评述 | EastMoney `RPT_F10_OP_BUSINESSANALYSIS` | `mda_credibility / mda_impact` |
| **D6** 控股结构 | DuckDB(十大股东 + 流通 + 户数)+ Tavily | `holding_structure / sotp_discount_pct` |

### 设计铁律

- **降级优先于抛异常**:任一数据源不可用 → `narrative="⚠️ ..."` + DEFAULT_PARAMS,**不阻塞**
- **30 天 TTL + REPORT_DATE 失效**:cache 命中策略,DuckDB 出现新报告期则强制刷新
- **cpa Phase 0 前置**:cpa agent 启动先调 `run_qualitative()`,失败容忍(降级,Phase 1/3.1/3.2 仍跑通)
- **价值陷阱 5 项排查**:Phase 3.2 valuation 启用 D2 护城河 / D3 周期 / D4 管理层 / D6 控股结构 5 项二元规则
- **mock_dimension_dN = dimension_dN 别名**:让 `MOCK_DIMENSION_FNS` 自动用真实实现(无需改 runner)

### 测试覆盖

`backend/tests/agent/test_qualitative_d{1..6}.py` 共 ~115 用例。基线 **926 passed + 1 skipped**。

### 测试策略
- AGENT_REGISTRY 单测:确保新 agent 注册后 coordinator 能路由到它
- 意图分类 mock LLM 返回值,验证 4 层 fallback 在不同条件下的分支

## TODO

- L3 LLM 意图分类器(coordinator `_classify_intent` 实现 + 4 层 fallback 测试)
- team agent 骨架(`agents/team/`,多角色协作)
- §17.8 D&A → EV/EBITDA
- Vite proxy / Nginx 长连超时验证
- **金融股盲点**:cpa 框架 FCFF_BACK 不适用银行/保险/证券(资产负债表逻辑差异大),`ConservativeRoughStrategy` 已整类排除,后续若要覆盖金融股需单独建模

## 现金流保守策略(粗算版)定位 — `ConservativeRoughStrategy`

- **不等于 cpa 精算 KK**:cpa 11 步精算(V1-V5 非经常分类 / 6.X2 隐性必要支出 / 7 会计准则 / 8 AA 三选一)需 LLM 读年报附注做定性判断,**不可机械化**
- **本策略只做粗算 R + 4 项 Layer 2 否决**:`R = NP × 近3年支付率均值 / 市值`,门槛 5.2%(II 4.7% + 安全边际 0.5pct);否决项=金融股/商誉占比>30%/净现金转负/FCF 持续 2 年负
- **用途**:
  1. 给 cpa Agent 提供候选股票池(5400+ → 几十)
  2. 作为 cpa LLM 真实精算结果的回测基线对比
- **代码位置**:`strategies/utils/conservative.py` + `strategies/examples/conservative_rough_strategy.py`,docstring 显式标注「粗算 / 不是 cpa 精算 KK」

### 三层模型 Roadmap(详见 `docs/design_conservative_strategy_layers.md`)

把 cpa 11 步精算定性框架机械化拆成三层流水线 + 一个仓位矩阵:

- **L1 估值因子**:R(粗算)/ KK(精算预留)+ **L1.3 信誉评级**(5年营收 CV / 利润调整幅度 / λ warning 三维 → high/mid/low)
- **L2 价值陷阱**:5 项 disqualifier(行业/商誉/净现金/FCF/ROE 三年下降)+ **L2.5 trap_rating** 软评分聚合(low/mid/high)
- **L3 仓位矩阵**:`f(KK, credibility, trap_rating) → tier ∈ {full, half, observe, skip}` 三维查找表
- **当前实现**:L1.R + L1.3 + L2 5 项硬否决 + L2.5 trap_rating 软评分(可选模式)✅(2026-05-27);**L3 仓位矩阵未做**
- **KK→R 退化决策**:2026-05-27 reset `ccd7b9a`+`d02d1d8`,KK 精算需 LLM 读年报附注不可机械化,粗算 R 即可作 cpa Agent 候选池筛选

## Project Timeline(claude-mem 摘要 · 2026-05-13 → 2026-05-26)

来自本项目 claude-mem 5500+ 条观察记录的日级提炼,只列**架构决策 / 数据踩坑 / 不可逆迁移**,日常代码改动不复述。

### 2026-05-13 — Phase 4 DDD 启动 + BaoStock K 线验证
- 建 `domain/` 层(Stock 聚合根,可选 repository 注入,默认 lazy 创建)
- 50 只样本跑 BaoStock K 线核对,**A 股 volume 单位**在新旧 parquet 间多次出现一致性问题(`002907.SZ`、`000708.SZ`、`603070.SH` 多次返工),最终统一为「股」
- AKShare → BaoStock 主迁移完成(此时还有 mock 测试残留,后期 5-21 才彻底清)

### 2026-05-14 — Vue → React 大切换 + HK 数据源踩坑
- ✅ 前端从 Vue 全量迁到 React 19(`#499`),旧 Vue 备份留 `frontend/src_vue_backup/`
- BacktestPage 重写为列表布局
- ⚠️ **EastMoney HK API 硬限制**:单次请求 >~250 行 / >12 个月范围必报错(`#242 #244 #247`),HK 长历史**只能切片拉取**
- ⚠️ AKShare `stock_hk_hist` 直连失败(`#238`),HK/US 改走 yfinance(`#231` 加依赖)

### 2026-05-15 — KlineChart 精修
- lightweight-charts v5 双侧 priceScale 切换(volume / MACD overlay 调到 left,price 留 right)
- MACD bar 计算修复(确认 `2 × (DIF - DEA)`,用户口径)
- pctChg 双负号 bug 修复
- kline API limit 参数化,前端默认拉更长窗口

### 2026-05-16 — K 线交互定型
- 默认显示 150 根 + 鼠标跟随 ruler + 持久 Tooltip(`#913`)
- 调度器 3 个 job 落地:每日 06:00 市场更新 / 15:30 持仓快照 / 周日 03:00 备份(`#910`)

### 2026-05-18 — 🚨 DuckDB 唯一来源决策日 + 策略 frequency 模型
- 🟣 **DuckDB 成为业务数据唯一来源**(`#1567 #1513`)— 旧 qfq_cache 物理路径废弃,改用 `adjust_factor` ASOF JOIN 派生
- 🟣 多市场数据层完工(A/HK/US 并行增量更新器,DuckDB 视图注册)
- 策略 `Strategy.frequency_overridable` flag 加入,UI K 线周期联动
- `MaTangleValueStrategy` 声明 `monthly` 且不可覆盖
- AGENTS.md **首次大改写**反映多市场 + DDD(`#1532`)
- merge-strategies plan 文档进库(`docs/superpowers/plans/2026-05-18-merge-strategies.md`)

### 2026-05-19 — 🚨 Phase 6 统一引擎(单日 777 条记录,最大重构)
- 🟣 **`Strategy / ScreenerStrategy / BuyStrategy / SellStrategy` 三角拆分模型废除**,合并为单一 `Strategy` 类(`screen()` + 可选 `on_buy / on_sell` hooks)
- 🟣 `BacktestEngine` 统一(legacy v1/v2 + buy_sell_engine 合并),`run()` 完整回测 / `run_scan()` 雷达扫描两条路径
- 🔴 **StrategyGroup 后端整套移除**(`#2764`),前端三层 UI 设计也同步搁置 — 之前 AGENTS.md Pending Designs #30 实际是被砍掉而非待办
- 旧引擎/上下文/策略基类的所有 import 全网清理(`#2737 #2736`)
- 链路保留 `source_task_id` 与 Signal Table 模式

### 2026-05-20 — 性能 + 元数据修复
- DuckDBStore 批量 qfq 查询(`#3349 #3350`),回测路由用批量替代单股循环
- BacktestEngine 接收 per-task `log_dir`(决策日志按任务隔离)
- `backtest_tasks.pipeline_info` 历史脏数据清理(空 pipeline 软删除,`#3303 #3305`)
- `strategy_name` 显式存表 + 前端历史列表展示

### 2026-05-21 — 🚨 数据路径铁律 + HK/US 分红回填
- 🟣 **铁律确立**:所有业务数据**只走 `data/market/`**,禁止读旧 `data/{kline,financial,dividend,valuation,indicators}/...`(commit 1: 数据架构规则)
- 🟣 strategies/utils 全英文字段切换(`commit 2`),旧中文 schema utils 弃用
- 🟣 obsolete updaters/routers 整批清(`commit 3`)
- HK 分红后台回填 + US 分红后台回填(yfinance 频繁触发限速,多次重启加 retry,共 7400+ 美股)
- ⚠️ **HK/US 分红字段语义与 A 股不一致**已识别(`#4349 #4352`),修复方案落地

### 2026-05-22 — StrategyRadar 完善 + 工具库
- 雷达扫描结果导出 Excel(`#4963`)
- StrategyRadar 参数对话框走 createPortal(避开滚动容器裁剪)
- 6m lookback 选项前后端贯通
- 雷达扫描默认开决策日志
- `strategies/utils/kline.py::filter_by_ma_close` + `MaCloseStrategy` 示例
- 指标快路径:`get_ma / macd` 工具直查 DataFrame 列(O(1))

### 2026-05-23 — Ask Stock Phase A 启动(LLM 客户端 + agent 骨架)
- `LLMClient` 抽象基类 + `OpenAICompatibleClient`(deepseek/openrouter/openai 三家)
- `services/system_config/channels.py` 自动从 KV 重建 ChannelConfig
- `routers/agent.py` SSE 骨架 + `routers/system_config.py` 注册到 main
- `auth_stub` 路由接入(本地默认关闭鉴权)
- pytest-asyncio 1.3.0 + `asyncio_mode=auto`
- 价值策略 v1+v2+v3(共 24 变体)全期跑批,**未达 10% 年化目标**(v3 P0 全期 2.96%,v2 V10 5.29% 最佳)

### 2026-05-24 — Ask Stock Phase 1 全收口 + Settings 集成
- ✅ **Phase 1 全 34 task**:DataPackBuilder + 14 真实 section + Coordinator 三阶段流水线 + SSE 6 事件 + workspace `<code>_<name>/` 隔离
- ✅ §7 股东 EastMoney F10 接入;§8/§10 Tavily search + 7 天文件缓存(无 key 优雅降级)
- ✅ AKShare 适配器**物理删除**(`backend/adapters/akshare_adapter.py`),迁移脚本归档不再调用
- ✅ Settings 9 字段 SSOT(`field_schema.py`)+ 路由重写 + LLMChannelEditor 隐藏(字段命名与后端 SSOT 不兼容,1796 行编辑器废弃)
- ✅ 敏感字段 mask 三态语义 + 删除前端"显示密码"眼睛按钮
- 测试 630 → 692 → **797**(0 回归)

### 2026-05-25 — Settings UI 收尾 + AGENTS.md 整理
- commit `2227eb1` 设置页接入 yaml 9 字段
- commit `0725cb2` 通用配置卡片标题按分类动态化
- 阅读 claude-mem 5500+ 条记录,补全本时间线段落

### 2026-05-26(今天)— 🚨 定性分析子系统 Phase 2 全收口 + 术语铁律
- 🟣 **business_analysis agent + core/qualitative/ 共享 service 全部 6 维度真实实现**(单日 6 个 commit):
  - `16d4b44` D5 经营评述(端到端样板,EastMoney `RPT_F10_OP_BUSINESSANALYSIS`)
  - `f224c96` D1 商业模式(纯 DuckDB 资产负债 + 指标视图)
  - `c4fd77c` D2 护城河(DuckDB ROE/毛利率 + Tavily)
  - `764de53` D3 行业周期(DuckDB 营收波动 + Tavily)
  - `67ff305` D4 管理层(emweb F10 / yfinance,A 股 + HK + US 全覆盖)
  - `a5c8ec1` D6 控股结构(十大股东 + Tavily,LLM 校验 sotp 0-1)
- 🟣 **D4 数据源 spike 关键发现**:emweb HK/US 返 status=-1 → 改 yfinance(`companyOfficers` + `insider_transactions`),Transaction 文本派生增减持方向
- 🟣 **术语铁律确立**(`caf6180`):「龟龟策略 → 现金流保守策略」全局重命名,Python 符号 `MoatRatingConservative` / `map_moat_rating_conservative`,prompt `judgment_examples_conservative.md`;唯一例外是 sibling 项目真实路径 `Turtle_investment_framework`
- 测试基线:797 → **926 passed + 1 skipped**(单日 +130 测试,0 回归)
- ⚠️ 仍未实现:Coordinator L3 LLM 意图分类(规则 + 关键词路由已稳定,L3 是兜底)

## 历史教训汇总(claude-mem 提炼)

放这里防止再踩:

1. **HK/US 数据源限制**
   - EastMoney HK 单次 ≤ 250 行 / ≤ 12 个月,长历史必须切片
   - yfinance 美股全量(~7400 只)极易触发限速,后台跑必须加 retry + 进度日志
   - HK/US 分红字段语义与 A 股不同,适配层必须显式映射
2. **AKShare 已彻底删除**(2026-05-24),不要再 `import akshare`,任何"AKShare 兼容层"提议都拒绝
3. **DuckDB 是唯一业务数据入口**(2026-05-18 决策),新数据访问 API 必须先在 `DuckDBStore` 加方法,**禁止** `glob` parquet 或读旧路径
4. **`data/market/` 是唯一业务数据物理路径**(2026-05-21 铁律),旧 `data/{kline,financial,dividend,valuation,indicators}/` 物理目录可删,引用必须迁移
5. **Strategy 三角模型(Screener/Buy/Sell)已死**(2026-05-19 Phase 6),任何看到旧文档/代码提到 BuyStrategy/SellStrategy/TraderStrategy 的,都按"已合并到单一 Strategy"理解
6. **StrategyGroup 整套已砍**(2026-05-19),前端三层 UI 不要再做
7. **LLMChannelEditor 不兼容后端 SSOT**(2026-05-24),字段命名差太多(`_PROTOCOL` vs `_PROVIDER` / `_MODELS` 列表 vs 单值 / 强写 5 个 litellm 死字段),已隐藏不调用,后续若要做 channel UI 必须**重写**而非沿用
8. **敏感字段不通过 HTTP 下发真实值**(产品级铁律),三态 mask 语义,前端"显示密码"按钮无意义
9. **A 股 volume 单位 = 股**(2026-05-13 多次返工确认),不是手
10. **MACD bar = 2 × (DIF - DEA)**(用户口径,与某些行情软件 1× 不同)
11. **长任务必须 `nohup ... &`**(回测/全市场更新/分红回填都被超时打断过多次)
12. **claude-mem 项目 key 必须用完整绝对路径**,`stock_investment` 那个是 claude source 只有早期记录
