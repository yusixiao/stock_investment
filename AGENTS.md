# AGENTS.md(根)

## Goal

打造个人股票投资综合平台:支持 A 股、港股、美股的行情/财务/分红/估值数据采集,K 线可视化,选股+回测引擎,持仓管理,以及面向投顾场景的 LLM Agent 对话。项目已迈过早期 MVP,进入「架构 DDD 化 + 前端全面重构 + 多市场数据层」阶段。

## 🚨 子模块 AGENTS.md 动态加载索引(先读这里!)

本仓库已**按子项目拆分 AGENTS.md**。本根文件只保留**跨切面铁律 + 共享内核**;各子系统的深度细节在就近的 AGENTS.md 里。**开始任一子系统的工作前,必须主动 `read` 对应文件**(它们不会全部自动进上下文):

| 你要做的事 | 必读 AGENTS.md |
|---|---|
| 回测引擎 / 策略 / 选股 / 雷达 / 港股通 / 现金流保守策略 | `backend/services/backtest/AGENTS.md` |
| 问股 / 多 agent / cpa / 定性分析 / Coordinator / Prompt | `backend/services/agent/AGENTS.md` |
| 行情/财务/分红/估值采集 / DuckDB store / adapters / updaters | `backend/services/market_data/AGENTS.md` |
| 持仓管理 / 估值 / 快照 / trades | `backend/services/portfolio/AGENTS.md` |
| 前端任何改动(组件 / K线 / 页面 / store) | `frontend/AGENTS.md` |

> 触及多个子系统时,把相关的几份都读一遍再动手。子文件与本根文件冲突时,**以本根文件的铁律为准**(铁律是全局约束),子文件负责细节。

---

## 🚨 跨切面铁律(全局,任何子系统都适用)

- **审视指令铁律**:**不要盲目遵循指令**。觉得用户指令有问题/不清晰/与既有铁律冲突时,**严格审视 → 提出疑问 → 等待澄清**,不要硬干。技术分歧直说,不附和。
- **沟通语言铁律**:**始终用中文回复**(对话、解释、状态汇报、报告正文一律中文)。代码标识符/日志保持英文照旧。
- **数据源铁律**(2026-05-24):**禁止使用 akshare**(本环境不稳定/超时,`akshare_adapter.py` 已物理删除)。所有代码用 **baostock / eastmoney / yfinance**;不要 `import akshare`,**任何"AKShare 兼容层"提议一律拒绝**。
- **唯一业务数据源 = DuckDB**(2026-05-18):所有业务代码(回测、选股、K 线、财务/估值/分红查询)**必须**经 `services/market_data/duckdb_store.py` 访问,**禁止**直接 `glob` parquet 或读旧路径。新增数据访问 API 必须先在 `DuckDBStore` 上加方法/视图。
- **唯一数据物理路径 = `data/market/`**(2026-05-21):绝对禁止读取 `data/{kline,financial,dividend,valuation,indicators}/...` 等旧路径。新增数据也必须落到 `data/market/{A,HK,US}/<category>/`,按市场分区,统一英文 schema。旧路径物理目录已归 `data/old/`(零引用,可 `rm -rf`)。
- **长任务后台执行**:任何预计超过 1 分钟的任务(回测、矩阵跑批、诊断脚本、全市场数据更新、批量迁移等)**必须** `nohup ... > log 2>&1 &` 后台执行,前台只查 PID/日志/进度。
- **MACD bar = `2 × (DIF - DEA)`**(用户口径,与某些行情软件 1× 不同)。
- **A 股 volume 单位 = 股**(不是手)。
- **代码注释**:复杂/非显然逻辑必须加注释;日志保持信息量。
- **安全**:never 暴露/log/commit secrets;敏感字段不通过 HTTP 下发真实值(三态 mask)。

## 🚨 TODO LIST 规范

右侧任务清单完全由 `todowrite` 工具驱动(不自动更新),凡涉及 ≥3 步的任务必须用它。规则:①任务开头就建清单 ②每完成一项**立即单独**标记 `completed`(不批量补) ③全程**只保留一个** `in_progress` ④无关项及时 `cancelled`。

## 🚨 项目结构铁律(2026-06-14 重订)

按"可重建性"分三类顶层目录(顶层 `cache/`、`notes/`、`exported/` 已废弃并物理删除):

- **`data/`** — 业务输入 + 派生过程缓存,**整体 gitignore**
  - `data/market/{A,HK,US}/...` — 行情/财务/分红/估值 parquet(DuckDB 视图来源,唯一业务数据源)
  - `data/meta/` — 全市场代码索引 / 流通股;`data/portfolio.db` — SQLite 业务库
  - `data/cache/` — **纯派生过程缓存**(`tavily/` 问股搜索 7天TTL、`qualitative/` 定性分析 30天TTL),可随时删自动重建。由 `config.CACHE_DIR` 统一锚定
  - `data/old/` — 废弃归档(~4.2G,零引用,可 `rm -rf`)
- **`report/`** — 用户产物 artifact(花 token 的 LLM 报告),**整体 gitignore**:`report/agent_runs/<code>_<name>/` 内分 `report/`(最终报告)+ `work/`(可复用中间产物 + `_meta.json` 状态机)、`report/exported/`(诊断/spike)
- **`logs/`** — 运行日志,可定期清理,**整体 gitignore**
- 新代码缓存写一律走 `config.CACHE_DIR`(=`data/cache`),**禁止**新起顶层 `cache/`;产物写 `report/`;**禁止**写 `data/{agent_runs,logs}` 或顶层 `notes/`、`exported/`。
- **备份真相**(2026-06-14 核实):`scripts/backup_to_baidu.py` 只 `tar.add(MARKET_DIR, arcname="market")` —— **仅备份 `data/market/`**,不碰 `data/cache`、`data/meta`、`portfolio.db`、`report/`、`logs/`。

## 技术栈 & 共享内核

- 后端 Python:FastAPI + APScheduler + DuckDB(查询层)+ pandas/parquet(存储)+ SQLite(业务库)。
- 前端:React 19 + TS + Vite 7 + Tailwind v4(详见 `frontend/AGENTS.md`)。
- **后端 DDD 三层**:`adapters/`(外部数据源)→ `repositories/`(parquet/DuckDB I/O)→ `services/`(领域服务)。`models/` 定义 Pydantic 实体,`domain/` 放领域常量。
- **共享基建**(不属于任何单一子模块):
  - `config.py` — 全部数据路径常量
  - `services/api_utils.py` — 通用工具
  - `services/db_schema.py` — SQLite DDL(回测 `backtest_tasks` + 问股 chat 表共用,故留 services 根,幂等下发)
  - `data/portfolio.db` — **跨 3 模块共享**(持仓 + 回测 + 问股 chat),改 schema 须顾及三方
  - `scheduler.py` — 06:00 market update / 15:30 snapshot / 周日 03:00 backup
- **🚨 双 import 风格刻意并存**(2026-05-19 `37b5db1` 确立,**勿擅自统一**):①生产 `from backend.xxx` 靠 `main.py` 把项目根插 `sys.path` + `backend/__init__.py`(修 ThreadPoolExecutor 子线程 `No module named backend`);②`from services.xxx`/`from config`(测试 + ~74 业务文件)靠 `pytest.ini` 的 `pythonpath = . backend`。两者均设计为可用,统一需评估子线程/调度路径风险。
- `write` 工具对超大内容会中止 —— 拆成多次小写。

## 测试

```bash
python -m pytest backend/tests/ -x -q     # 后端 1332 tests(adapter 测试用 mock)
cd frontend && npm test                    # 前端 vitest
cd frontend && npm run test:smoke          # Playwright smoke
cd frontend && npx tsc --noEmit            # 类型检查
cd frontend && npm run lint                # ESLint
```

## 顶层目录结构

```
stock_investment/
├── AGENTS.md                           # 本文件(根:铁律 + 共享内核 + 子模块索引)
├── backend/
│   ├── main.py                         # FastAPI app,lifespan: init_db + init_duckdb + init_stock_index + scheduler
│   ├── config.py / scheduler.py        # 共享:路径常量 / 定时任务
│   ├── adapters/                       # 外部数据源(base/baostock/eastmoney/yfinance/data_source/adjust_factor_audit)
│   ├── domain/ models/ repositories/   # DDL 三层:领域常量 / Pydantic / parquet·DuckDB I/O
│   ├── routers/                        # 13 个路由(均在 main.py 注册)
│   ├── services/
│   │   ├── api_utils.py / db_schema.py # 共享基建
│   │   ├── market_data/  ← AGENTS.md   # 首页·市场数据子系统
│   │   ├── backtest/     ← AGENTS.md   # 回测 / 选股子系统
│   │   ├── portfolio/    ← AGENTS.md   # 持仓管理子系统
│   │   ├── agent/        ← AGENTS.md   # 问股多 agent 平台
│   │   ├── system_config/              # 设置·LLM 渠道 / 通知配置
│   │   └── migrations/                 # 参考性 SQL 存档(实际迁移由 db_schema.py 幂等下发)
│   └── tests/                          # 1300+ cases
├── frontend/             ← AGENTS.md   # React 19 + TS + Tailwind v4(name: dsa-web)
├── data/                               # market/ meta/ cache/ portfolio.db old/(整体 gitignore)
├── report/ logs/                       # 产物 / 日志(整体 gitignore)
└── scripts/                            # backup_to_baidu.py + migrate_*/backfill_* 归档脚本
```

## 子项目里程碑(Accomplished)

- **子项目 1-3 全部完成**:数据管理+K 线 / 选股+回测 / 持仓管理。
- **多市场数据层**(2025末-2026初):adapters + models + repositories + market_updater + duckdb_store + backup + scheduler。
- **财务/分红/估值子系统**:各 updater + router + Context 取数。
- **回测引擎 Phase 6**:三角拆分模型废弃,统一单一 `Strategy` 类 + `run()/run_scan()`。
- **前端 React 重构**:Vue 3 → React 19 + TS + Tailwind v4 + zustand + react-router 7。
- **问股多 agent 平台**:Coordinator 4 层 fallback + cpa + business_analysis + 定性分析子系统。

## 🚨 历史教训汇总(防再踩)

1. **HK/US 数据源限制**:EastMoney HK 单次 ≤250 行/≤12 月须切片;yfinance 美股全量易限速须 retry+进度日志;HK/US 分红字段语义异于 A 股须显式映射。(详见 market_data 子文件)
2. **DuckDB 是唯一业务数据入口**(2026-05-18),新数据访问 API 必须先在 `DuckDBStore` 加方法,禁 `glob`/旧路径。
3. **`data/market/` 是唯一业务数据物理路径**(2026-05-21),旧目录可删,引用必须迁移。
4. **Strategy 三角模型(Screener/Buy/Sell)已死**(2026-05-19 Phase 6),已合并到单一 Strategy。
5. **StrategyGroup 整套已砍**(2026-05-19),前端三层 UI 不要再做。
6. **LLMChannelEditor 不兼容后端 SSOT**(2026-05-24),已隐藏,后续做 channel UI 必须重写。(详见 frontend 子文件)
7. **敏感字段不通过 HTTP 下发真实值**(产品级铁律),三态 mask。
8. **A 股 volume 单位 = 股**(2026-05-13 多次返工确认)。
9. **MACD bar = 2 × (DIF - DEA)**(用户口径)。
10. **长任务必须 `nohup ... &`**(回测/全市场更新/分红回填都被超时打断过多次)。
11. **claude-mem 项目 key 必须用完整绝对路径**,`stock_investment` 那个是 claude source 只有早期记录。
```
