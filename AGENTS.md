# AGENTS.md

## Goal

打造个人股票投资综合平台:支持 A 股、港股、美股的行情/财务/分红/估值数据采集,K 线可视化,选股+回测引擎,持仓管理,以及面向投顾场景的 LLM Agent 对话。项目按子项目增量迭代,目前已迈过早期 MVP 阶段,进入「架构 DDD 化 + 前端全面重构 + 多市场数据层」的阶段。

## Instructions

- **沟通语言**:中文
- **技术栈**:
  - 后端 Python:FastAPI + APScheduler + DuckDB(查询层)+ pandas/parquet(存储)+ SQLite(业务库)
  - 前端 React 19 + TypeScript + Vite 7 + Tailwind v4 + zustand + react-router 7 + lightweight-charts(K 线)+ recharts(回测曲线)+ react-markdown
- **数据源**:多 adapter 架构 — `AKShareAdapter`(A 股)、`BaoStockAdapter`、`EastMoneyAdapter`(财务/估值默认)、`YFinanceAdapter`(港股/美股)。`adapters/data_source.py::create_default_data_source()` 统一装配
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
- **AKShare 在本环境会超时** — 调用 API 的代码必须用 mock 测试
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
- **测试**:550 个 case,`python -m pytest backend/tests/ -x -q`。AKShare 必须 mock(`test_adapters.py` 等)

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

- `adapters/`:base / akshare / baostock / eastmoney / yfinance + `data_source.py` 装配器
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

## Pending Designs(claude-mem 中尚未完全落地)

仍可能需要复核现状的设计:

1. **#29 QFQ 缓存重构**(2026-05-08):3 状态缓存模型已部分实现(`qfq_cache.py`),需验证 `_meta.json` 与每日增量更新链路是否完整
2. **#27 BatchBuyTrader**(2026-04-24):分 N 批买入(默认 4 个月 4 批),Broker `price_func` 机制 — 检查 `market_cap_weighted_buyer` 是否覆盖此场景或需独立策略
3. **#30 StrategyGroup 三层 UI**(2026-05-09):后端已有,前端三层页面(组列表/组详情/运行详情)是否完成需核对
4. **#32 Buy/Sell 系统**(2026-05-09):引擎已落地;策略基类拆分完成度需确认
5. ~~**APScheduler misfire_grace_time 调大**~~ ✅ 2026-05-20 完成:三个 `add_job` 都加了 `misfire_grace_time=3600`

## Relevant files / directories

```
stock_investment/
├── backend/
│   ├── main.py                         # FastAPI app, lifespan: init_db + init_duckdb + init_stock_index + scheduler
│   ├── config.py                       # 全部数据路径常量
│   ├── scheduler.py                    # 06:00 market update / 15:30 snapshot / 周日 03:00 backup
│   ├── adapters/                       # base, akshare, baostock, eastmoney, yfinance, data_source
│   ├── domain/                         # stock 领域常量
│   ├── models/                         # basic / market / financial / event Pydantic
│   ├── repositories/                   # base / basic_repo / market_repo / financial_repo / event_repo
│   ├── routers/                        # 13 个路由
│   │   ├── stock.py / stock_search.py / market_kline.py
│   │   ├── data_update.py / market_update.py
│   │   ├── backtest.py / screener.py / strategy_group.py
│   │   ├── portfolio.py
│   │   ├── valuation.py / dividend.py / financial.py
│   │   └── meta.py
│   ├── services/
│   │   ├── stock_data.py               # aggregate_kline (W-FRI / M)
│   │   ├── duckdb_store.py             # parquet 视图查询层
│   │   ├── stock_index.py              # 全市场代码索引
│   │   ├── qfq_cache.py                # 前复权缓存(派生)
│   │   ├── market_updater.py           # 多市场并行增量

│   │   ├── dividend_updater.py / financial_updater.py / valuation_updater.py
│   │   ├── circulating_shares.py / indicator_store.py / indicator.py
│   │   ├── api_utils.py / db_schema.py
│   │   ├── backtest/
│   │   │   ├── engine.py               # 主引擎,频率缓存,join_mode
│   │   │   ├── buy_sell_engine.py      # Buy/Sell 拆分版引擎
│   │   │   ├── engine_base.py          # BaseEngine + parse_screen_result
│   │   │   ├── base.py                 # ScreenerStrategy / BuyStrategy / SellStrategy
│   │   │   ├── context.py              # ScreenerContext / TraderContext + 多频率/分红/财务/估值
│   │   │   ├── broker.py               # T+1 / 涨跌停 / 佣金 / price_func
│   │   │   ├── portfolio.py            # 资产/持仓
│   │   │   ├── analyzer.py             # 指标计算
│   │   │   ├── strategy_loader.py      # importlib 扫描 + frequency
│   │   │   ├── group_manager.py        # 策略组管理
│   │   │   ├── task_manager.py         # SQLite 持久化 + 进度
│   │   │   └── date_utils.py           # format_match_date / date_belongs_to / detect_frequency
│   │   └── portfolio/
│   │       ├── db.py / manager.py
│   └── tests/                          # 550 cases
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
python -m pytest backend/tests/ -x -q     # 后端 550 tests
cd frontend && npm test                    # 前端 vitest
cd frontend && npm run test:smoke          # Playwright smoke
cd frontend && npx tsc --noEmit            # 类型检查
cd frontend && npm run lint                # ESLint
```

## Update (2026-05-18)

- 重写 AGENTS.md 以反映实际状态:前端 React 重构、后端 DDD 三层、多市场数据层、DuckDB、Buy/Sell 引擎、策略组、财务/分红/估值子系统
- 测试规模从 177 增至 550
- 旧版 AGENTS.md 严重滞后(还在 Vue + 单一 A 股),已替换
