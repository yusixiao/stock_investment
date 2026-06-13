# AGENTS.md

## Goal

打造个人股票投资综合平台:支持 A 股、港股、美股的行情/财务/分红/估值数据采集,K 线可视化,选股+回测引擎,持仓管理,以及面向投顾场景的 LLM Agent 对话。项目按子项目增量迭代,目前已迈过早期 MVP 阶段,进入「架构 DDD 化 + 前端全面重构 + 多市场数据层」的阶段。

## Instructions

- **🚨 审视指令铁律**:**不要盲目遵循指令**。如果觉得用户指令有问题、不清晰、或与既有铁律冲突,**严格审视 → 提出疑问 → 等待澄清**,不要硬干。技术分歧要直说,不要附和
- **🚨 项目结构铁律(2026-05-24)**:按"可重建性 + 备份u策略"分四类顶层目录
  - `data/` — **原始/业务数据**(parquet 行情/财务/分红/估值、`portfolio.db`),DuckDB 视图来源,**进备份**
  - `report/` — **用户产物**(LLM 生成的分析报告 = 花 token 的 artifact),`report/agent_runs/<code>_<name>/` workspace + 报告,**进备份**
  - `cache/` — **纯派生缓存**(`cache/tavily/`、`cache/qfq/` 等),可随时删,自动重建,**不备份**
  - `logs/` — **运行日志**(应用日志、调度器日志),可定期清理,**不备份**
  - 新代码**禁止**写入 `data/{agent_runs,cache,logs}`,旧路径需逐步迁移并清理
- **🚨 沟通语言铁律**:**始终用中文回复**(所有对话、解释、状态汇报、报告正文一律中文),不要用英文回话。代码标识符/日志保持英文照旧
- **🚨 TODO LIST 规范**:右侧任务清单完全由 `todowrite` 工具驱动(不会自动更新),凡涉及 ≥3 步的任务必须用它。规则:①任务开头就建清单 ②每完成一项**立即单独**标记 `completed`(不批量补) ③全程**只保留一个** `in_progress` ④无关项及时 `cancelled`
- **技术栈**:
  - 后端 Python:FastAPI + APScheduler + DuckDB(查询层)+ pandas/parquet(存储)+ SQLite(业务库)
  - 前端 React 19 + TypeScript + Vite 7 + Tailwind v4 + zustand + react-router 7 + lightweight-charts(K 线)+ recharts(回测曲线)+ react-markdown
- **数据源**:多 adapter 架构 — `BaoStockAdapter`(A 股 K 线/基础)、`EastMoneyAdapter`(财务/估值/股本默认)、`YFinanceAdapter`(港股/美股)。`adapters/data_source.py::create_default_data_source()` 统一装配
- **🚨 数据源铁律(2026-05-24)**:**禁止使用 akshare**(在本环境不稳定/经常超时),`backend/adapters/akshare_adapter.py` 已物理删除。所有新代码与现有改动必须用 **baostock / eastmoney / yfinance**;不要再 `import akshare`,**任何"AKShare 兼容层"提议一律拒绝**。旧依赖逐步迁移至 DuckDB 视图或 baostock;`scripts/migrate_financial_akshare.py` 等历史一次性迁移脚本保留供归档,不再调用
- **数据存储**:
  - **🚨 铁律(2026-05-21):所有业务数据来源**必须**是 `data/market/`,绝对禁止读取 `data/{kline,financial,dividend,valuation,indicators}/...` 等任何旧路径**。新增数据(分红、估值等当前缺失类目)也**必须落到 `data/market/{A,HK,US}/<category>/`** 下,按市场分区组织,统一英文 schema(对齐 EastMoney/YFinance 原始字段)
  - **唯一业务数据源 = DuckDB**(2026-05-18 决策):所有业务代码(回测、选股、K 线展示、财务/估值/分红查询)**必须**经 `services/duckdb_store.py` 访问数据,**禁止**直接 `glob` parquet 或读旧路径文件。新增数据访问 API 必须先在 `DuckDBStore` 上加方法/视图
  - **DuckDB 唯一来源 = `data/market/`**:`data/market/{A,HK,US}/{daily,adjust_factor,financial/{income,balance,cashflow,indicator}}/*.parquet`(DuckDB 视图 `v_a_daily / v_a_adjust_factor / v_a_income / v_a_indicator / ...` 等)。财务表统一英文 schema(`REPORT_DATE / NETPROFIT / BASIC_EPS / ROEJQ / EPSJB / BPS / ...`)
  - **旧路径完全废弃**(2026-05-21 重申):`data/kline/`、`data/financial/A/`(中文 schema)、`data/dividend/A/`、`data/valuation/A/`、`data/indicators/A/` 全部不再被任何业务代码读取。当前残留引用(`config.py` 的 `VALUATION_DIR/DIVIDEND_DIR/FINANCIAL_DIR/INDICATOR_DIR`、`data_cache._load_valuation/_load_dividend/_load_financial`、`valuation_updater/dividend_updater` 写路径、`strategies/utils/{dividend,valuation,financial}.py` 中文字段名)需要逐步清理。物理目录可手动删除
  - 复权因子:`data/market/{market}/adjust_factor/*.parquet`
  - 业务库:`data/portfolio.db`(SQLite)— portfolios / trades / snapshots / backtest_tasks
- **代码注释**:复杂/非显然逻辑必须加注释;日志保持信息量
- **MACD bar**:`2 × (DIF - DEA)`(用户明确要求)
- **🚨 策略目录铁律(2026-06-14)**:`strategies/deployed/` = **已发布策略**(UI/回测 `/api/backtest/strategies` 只扫这里,经 `config.DEPLOYED_STRATEGY_DIR`);`strategies/experiments/` = **在研策略**(策略研究优先写这里,**不暴露给 UI**)。两者都通过 `importlib` 按文件路径加载(信任本地用户)。原 `strategies/examples/` 已重命名为 `deployed/`
- **策略定义**:已发布策略放 `strategies/deployed/*.py`,在研策略放 `strategies/experiments/*.py`
- **回测架构**:事件驱动,Broker 处理 T+1、涨跌停、佣金万三+印花税千一、滑点(策略模型见下方「策略模型(Phase 6)」单一 Strategy 类)
- **成交价**:默认 `(open + close) / 2` 中间价。Broker 支持自定义 `price_func`(如月线 `(high+low)/2`)
- **回测数据**:使用 `qfq/`(前复权);K 线显示支持 raw/qfq 切换
- **年化收益率**:`(1 + total_return) ^ (1 / years) - 1`,`years = natural_days / 365.25`
- **持仓估值**:用 parquet 最新收盘价(非实时 API)。**持仓本身不入库**,由 trades 在内存推导
- **`write` 工具对超大内容会中止** — 拆成多次小写
- **前端端口**:3001(`vite.config.ts`),代理 `/api → 127.0.0.1:8000`
- **策略模型(2026-05 重构,Phase 6)**:**Pipeline + Screener/Buyer/Seller 三角拆分模型已废弃**。当前为**单一 Strategy 类**(`strategies/base.py::Strategy` / `ScreenerStrategy`),策略实现 `screen(ctx, symbols) -> List[str]` + 可选 `on_buy(ctx, symbol)` / `on_sell(ctx, symbol)` hooks。示例:`strategies/deployed/ma_tangle_value_strategy.py`、`hk_garp_strategy.py`
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
- **策略雷达**(StrategyRadar):基于 `run_scan()`,前端组件支持 lookback(1m/3m/6m/1y/...)、参数对话框(createPortal)、结果导出 Excel、多 hits 单行+hit 数列、涨跌幅按信号日累计、因子值 pill 展示
- **后端架构 DDD 三层**:`adapters/`(外部数据源)→ `repositories/`(parquet/DuckDB I/O)→ `services/`(领域服务)。`models/` 定义 Pydantic 实体,`domain/` 放领域常量
- **测试**:1332+ case,`python -m pytest backend/tests/ -x -q`。adapter 测试用 mock(`test_adapters.py` 等)
- **长任务后台执行**:任何预计运行超过 1 分钟的任务(回测、矩阵跑批、诊断脚本、全市场数据更新、批量数据迁移等)**必须**用 `nohup ... > log 2>&1 &` 后台执行,前台只查 PID/日志/进度,避免阻塞会话

## 港股通虚拟市场(HK_CONNECT,2026-06-01)

- **`HK_CONNECT` 是虚拟市场**,不是物理市场。回测/雷达的 `market` 入参除 `A/HK/US` 外新增 `HK_CONNECT`,语义 = 港股通成分股子集
- **物理数据复用 HK**:`services/backtest/market_filter.py::resolve_data_market("HK_CONNECT") → "HK"`,`data_cache.get_market` 必须收到 `HK`,不能收到 `HK_CONNECT`
- **symbols 维度过滤**:`apply_market_filter` 在 HK_CONNECT 时把 symbols 收敛为 `services.hk_connect_updater.get_latest_hk_connect_codes()` 的 `.HK` 后缀集合(601 只),无 requested 时返全集,有 requested 时返交集
- **数据来源**:`data/market/HK/membership/hk_connect.parquet`(updater 周更),DuckDB 视图 `v_hk_connect_membership`
- **🚨 已知偏差**:仅当前快照,**无 point-in-time 历史**;长区间回测会引入 ~2-3% look-ahead + survivorship bias。粗筛 / 资产配置可接受,严格 PIT 策略不适用
- **前端**:`BacktestConfig.tsx` 市场下拉新增"港股通"选项,内部 `DisplayMarket = 'A'|'HK'|'US'|'HK_CONNECT'`,缓存状态查询 `toCacheMarket()` 映射回 HK;`api/backtestCache.ts::CacheMarket` 保持 3 值不变(API 契约不动)
- **路由覆盖**:`/api/backtest/run`、`/api/backtest/scan-radar` 已接 helper;`/api/backtest/cache/load`、`DELETE /api/backtest/cache/{market}` 先 `resolve_data_market` 再校验白名单。**`/api/screener/run` 暂未接入**(仅 A 股硬编码,与回测无关)

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
- **链式回测已废弃**:旧 Signal Table / `source_task_id` 继承选股结果的功能已从 Engine + API 移除;`backtest_tasks.source_task_id` 列与 `task_manager` 形参是历史遗留(仅持久化,无业务消费),勿据此误判功能仍在
- **性能优化**:`MarketData` 启动时预聚合周/月线 + 预计算所有指标列(`indicators.py`),`get_bar_at` 用 numpy 二分查找,比 `get_price` 快 ~9.6×。Context 的 `get_indicator(name, symbol)` 直接读 DataFrame 列,O(1)
- `aggregate_kline()`(`services/stock_data.py`)处理 W-FRI / M 聚合,被 MarketData 启动时调用
- **DuckDB 查询层**(`services/duckdb_store.py`):用 `read_parquet()` 注册视图(`v_a_daily / v_hk_daily / v_us_daily / v_*_adjust_factor / v_*_{income,balance,cashflow,indicator}`),不导入数据
- **前端从 Vue 迁到 React**(2025 末):旧版备份保留在 `frontend/src_vue_backup/`
- **回测页三 Tab 结构**:策略回测(BacktestAnalysis)/ 策略雷达(StrategyRadar)/ 市场监控(MarketMonitor)
- **K 线图**(`KlineChart.tsx`,lightweight-charts v5):默认显示 150 根,价格 MA5/10/20/30/60 可切换、Volume MA5/10、MACD pane,鼠标跟随 Tooltip,左右价格刻度可配
- 后端 `backend/main.py` 启动时把项目根加入 `sys.path`,因为 `backend/` 没有 `__init__.py`
- 前端 npm name 是 `dsa-web`(早期 daily_stock_analysis 遗留)

## Accomplished

> 具体文件清单见下方「Relevant files / directories」,此处只列高层里程碑。

- **子项目 1-3 全部完成**:数据管理+K 线 / 选股+回测 / 持仓管理
- **多市场数据层**(2025 末-2026 初):`adapters/`(base/baostock/eastmoney/yfinance + data_source 装配)+ `models/`(4 Pydantic 实体)+ `repositories/`(parquet I/O)+ `market_updater`(A/HK/US 并行增量)+ `duckdb_store`(视图查询)+ `backup_to_baidu`(周备份)+ scheduler(06:00 更新/15:30 快照/周日 03:00 备份)
- **财务/分红/估值子系统**:dividend/financial/valuation updater + router,circulating_shares / indicator_store / stock_index / qfq_cache,Context `get_dividend/get_financial/get_valuation`
- **回测引擎 Phase 6**:三角拆分模型 + StrategyGroup 废弃,统一单一 `Strategy` 类 + `BacktestEngine.run()/run_scan()`;因子逻辑下沉 `strategies/utils/`
- **前端 React 重构**:Vue 3 → React 19 + TS + Tailwind v4 + zustand + react-router 7;Shell 布局 + 主题切换 + Auth;7 页(Home/Backtest/Portfolio/Chat/Settings/Login/NotFound)+ ~25 通用组件 + 3 store;vitest + Playwright smoke
- **持续增强**:数据更新带日期选择 + poll 优雅停止;任务历史表;回测详情页显示 pipeline 配置/参数/日期范围

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
│   └── tests/                          # 1332 cases
├── strategies/deployed/             # 已发布策略(UI 只扫这里),现存 5 个(2026-06-14 精简)
│   ├── hk_garp_strategy.py             # H股 GARP 冠军(frequency = "monthly")
│   ├── low_valuation_quarterly_strategy.py            # A股 低估值季度
│   ├── low_valuation_multifactor_quarterly_strategy.py # A股 低估值多因子季度
│   ├── ma_tangle_value_strategy.py     # A股 月线均线缠绕价值
│   └── conservative_rough_strategy.py  # A股 现金流保守(粗算)
├── strategies/experiments/          # 在研策略(策略研究优先写这里,不暴露给 UI)
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
python -m pytest backend/tests/ -x -q     # 后端 1332 tests
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

`backend/tests/agent/test_qualitative_d{1..6}.py` 共 ~115 用例。全量基线 **1332 passed + 1 skipped**。

### 测试策略
- AGENT_REGISTRY 单测:确保新 agent 注册后 coordinator 能路由到它
- 意图分类 mock LLM 返回值,验证 4 层 fallback 在不同条件下的分支

## TODO

- L3 LLM 意图分类器(coordinator `_classify_intent` 实现 + 4 层 fallback 测试)
- team agent 骨架(`agents/team/`,多角色协作)
- §17.8 D&A → EV/EBITDA
- Vite proxy / Nginx 长连超时验证
- **金融股盲点**:cpa 框架 FCFF_BACK 不适用银行/保险/证券(资产负债表逻辑差异大),`ConservativeRoughStrategy` 已整类排除,后续若要覆盖金融股需单独建模
- **`ConservativeRoughStrategy` 真实回测验证**(2026-05-28 重写后):L3 矩阵改 CPA 4 档 + `CpaTierBatchBuyer` + CPA 7 条止损全部落地,需要在真实历史区间(全市场 / 至少 5 年)跑一次端到端回测,与旧"市值加权 + screen pool 白名单"版本对比超额收益,验证 CPA 原口径是否真的更优

## 现金流保守策略(粗算版)定位 — `ConservativeRoughStrategy`

- **不等于 cpa 精算 KK**:cpa 11 步精算(V1-V5 非经常分类 / 6.X2 隐性必要支出 / 7 会计准则 / 8 AA 三选一)需 LLM 读年报附注做定性判断,**不可机械化**
- **本策略只做粗算 R + 4 项 Layer 2 否决**:`R = NP × 近3年支付率均值 / 市值`,门槛 5.2%(II 4.7% + 安全边际 0.5pct);否决项=金融股/商誉占比>30%/净现金转负/FCF 持续 2 年负
- **用途**:
  1. 给 cpa Agent 提供候选股票池(5400+ → 几十)
  2. 作为 cpa LLM 真实精算结果的回测基线对比
- **代码位置**:`strategies/utils/conservative.py` + `strategies/deployed/conservative_rough_strategy.py`,docstring 显式标注「粗算 / 不是 cpa 精算 KK」

### 三层模型 Roadmap(详见 `docs/design_conservative_strategy_layers.md`)

把 cpa 11 步精算定性框架机械化拆成三层流水线 + 一个仓位矩阵:

- **L1 估值因子**:R(粗算)/ KK(精算预留)+ **L1.3 信誉评级**(5年营收 CV / 利润调整幅度 / λ warning 三维 → high/mid/low)
- **L2 价值陷阱**:5 项 disqualifier(行业/商誉/净现金/FCF/ROE 三年下降)+ **L2.5 trap_rating** 软评分聚合(low/mid/high)
- **L3 仓位矩阵**(2026-05-28 改 CPA 原口径):`f(R, credibility, trap_rating) → tier ∈ {full, p70, observe, skip}` 4 档(用户口径:KK 0.5~1.5pct 一律 observe,无 50% 档),`full_bonus=1.5pct`
- **L3.3 Buyer**(2026-05-28 重写):`CpaTierBatchBuyer` 抛弃市值加权,改 tier-based 单股配比(`max_per_stock_pct × TIER_PCT[tier]`,默认 full=20%/p70=14%),N 周 `order_target_percent` 等额爬坡
- **L4 卖出**(2026-05-28 新增):CPA 7 条基本面止损(`phase3_valuation.md` §10.2 表),critical 清仓 / warning 减仓 50%(per-reason 去重),入场时记录 D/E、毛利率、payout 三个 baseline
- **当前实现**:L1.R + L1.3 + L2 5 项 + L2.5 trap_rating + L3 矩阵 4 档 + `CpaTierBatchBuyer` + CPA 7 条止损全部落地 ✅
- **KK→R 退化决策**:2026-05-27 reset `ccd7b9a`+`d02d1d8`,KK 精算需 LLM 读年报附注不可机械化,粗算 R 即可作 cpa Agent 候选池筛选

## 历史教训汇总(claude-mem 提炼)

放这里防止再踩:

1. **HK/US 数据源限制**
   - EastMoney HK 单次 ≤ 250 行 / ≤ 12 个月,长历史必须切片
   - yfinance 美股全量(~7400 只)极易触发限速,后台跑必须加 retry + 进度日志
   - HK/US 分红字段语义与 A 股不同,适配层必须显式映射
2. **DuckDB 是唯一业务数据入口**(2026-05-18 决策),新数据访问 API 必须先在 `DuckDBStore` 加方法,**禁止** `glob` parquet 或读旧路径
3. **`data/market/` 是唯一业务数据物理路径**(2026-05-21 铁律),旧 `data/{kline,financial,dividend,valuation,indicators}/` 物理目录可删,引用必须迁移
4. **Strategy 三角模型(Screener/Buy/Sell)已死**(2026-05-19 Phase 6),任何看到旧文档/代码提到 BuyStrategy/SellStrategy/TraderStrategy 的,都按"已合并到单一 Strategy"理解
5. **StrategyGroup 整套已砍**(2026-05-19),前端三层 UI 不要再做
6. **LLMChannelEditor 不兼容后端 SSOT**(2026-05-24),字段命名差太多(`_PROTOCOL` vs `_PROVIDER` / `_MODELS` 列表 vs 单值 / 强写 5 个 litellm 死字段),已隐藏不调用,后续若要做 channel UI 必须**重写**而非沿用
7. **敏感字段不通过 HTTP 下发真实值**(产品级铁律),三态 mask 语义,前端"显示密码"按钮无意义
8. **A 股 volume 单位 = 股**(2026-05-13 多次返工确认),不是手
9. **MACD bar = 2 × (DIF - DEA)**(用户口径,与某些行情软件 1× 不同)
10. **长任务必须 `nohup ... &`**(回测/全市场更新/分红回填都被超时打断过多次)
11. **claude-mem 项目 key 必须用完整绝对路径**,`stock_investment` 那个是 claude source 只有早期记录
