# 子项目3：持仓管理系统设计

## 概述

为个人A股投资综合平台新增持仓管理模块，支持手动录入真实交易和从回测结果导入最终持仓，多组合独立跟踪，每日自动快照记录净值，展示持仓盈亏和收益曲线。

## 核心需求

- 支持创建多个独立组合（真实账户、回测导入等）
- 手动录入交易记录（买入/卖出）
- 从回测结果导入最终持仓为新组合
- 持仓状态从交易记录实时推算（内存计算，不持久化）
- 使用 parquet 最新收盘价估值
- 每日数据更新后自动拍快照，记录组合净值
- 风险分析暂不实现

## 数据模型（SQLite）

存储文件：`data/portfolio.db`，配置为 `config.py` 中的 `PORTFOLIO_DB`。

### portfolios 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK AUTOINCREMENT | 自增主键 |
| name | TEXT UNIQUE NOT NULL | 组合名称 |
| initial_capital | REAL NOT NULL | 初始资金 |
| source | TEXT NOT NULL | `manual` 或 `backtest` |
| created_at | TEXT NOT NULL | ISO格式创建时间 |

### trades 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK AUTOINCREMENT | 自增主键 |
| portfolio_id | INTEGER NOT NULL FK | 所属组合，引用 portfolios.id |
| symbol | TEXT NOT NULL | 股票代码（如 600519.SH） |
| direction | TEXT NOT NULL | `buy` 或 `sell` |
| price | REAL NOT NULL | 成交价格 |
| shares | INTEGER NOT NULL | 成交股数 |
| commission | REAL NOT NULL | 手续费 |
| tax | REAL NOT NULL | 印花税 |
| trade_date | TEXT NOT NULL | 成交日期 |
| created_at | TEXT NOT NULL | 录入时间 |

### snapshots 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK AUTOINCREMENT | 自增主键 |
| portfolio_id | INTEGER NOT NULL FK | 所属组合，引用 portfolios.id |
| date | TEXT NOT NULL | 日期 |
| total_value | REAL NOT NULL | 总市值（现金+持仓市值） |
| cash | REAL NOT NULL | 可用现金 |
| market_value | REAL NOT NULL | 持仓市值 |
| UNIQUE(portfolio_id, date) | | 每组合每天一条 |

### 持仓状态（内存计算）

不持久化，从交易记录实时推算：

- 持有股数 = Σ买入股数 - Σ卖出股数
- 持仓成本 = 加权平均成本（每次买入更新均价）
- 现金 = 初始资金 - Σ(买入金额+佣金) + Σ(卖出金额-佣金-印花税)

## 后端服务架构

### 新增文件

```
backend/services/portfolio/
├── __init__.py
├── db.py              # SQLite 连接管理、建表
├── manager.py         # 核心业务逻辑
```

### db.py

- SQLite 文件位置：`data/portfolio.db`
- `get_connection()` 返回连接，启用 WAL 模式和外键约束
- `init_db()` 创建3张表（幂等，IF NOT EXISTS）
- FastAPI 启动时调用 `init_db()`

### manager.py（PortfolioManager 类）

| 方法 | 说明 |
|------|------|
| `create_portfolio(name, initial_capital, source)` | 创建组合 |
| `delete_portfolio(id)` | 删除组合（级联删除交易和快照） |
| `list_portfolios()` | 列出所有组合（附带当前总市值） |
| `get_portfolio(id)` | 获取单个组合详情 |
| `add_trade(portfolio_id, symbol, direction, price, shares, trade_date, commission=None)` | 录入交易，commission 为 None 时自动按万三计算 |
| `get_trades(portfolio_id)` | 获取交易记录列表 |
| `compute_holdings(portfolio_id)` | 从交易记录推算当前持仓 |
| `compute_summary(portfolio_id)` | 计算组合概览（现金、市值、总值、总收益率） |
| `take_snapshot(portfolio_id)` | 记录今日净值快照 |
| `take_all_snapshots()` | 对所有组合拍快照（供调度器调用） |
| `get_snapshots(portfolio_id)` | 获取历史快照 |
| `import_from_backtest(task_id, name)` | 从回测结果导入最终持仓 |

### 费用计算规则

独立实现于 manager.py 中，不依赖回测 Broker 类：

- 佣金：成交金额 × 0.0003，最低5元
- 印花税：卖出时成交金额 × 0.001
- 用户可手动指定 commission 覆盖自动计算

## API 设计

新增路由 `backend/routers/portfolio.py`，前缀 `/api/portfolio`。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/` | 创建组合 |
| GET | `/` | 列出所有组合（含当前总市值） |
| GET | `/{id}` | 组合详情（含持仓、现金、总值、收益率） |
| DELETE | `/{id}` | 删除组合 |
| POST | `/{id}/trades` | 录入交易 |
| GET | `/{id}/trades` | 获取交易记录 |
| GET | `/{id}/holdings` | 获取当前持仓明细 |
| GET | `/{id}/snapshots` | 获取历史净值快照 |
| POST | `/import/{task_id}` | 从回测结果导入最终持仓 |

### 请求/响应格式

创建组合 `POST /api/portfolio/`：
```json
{"name": "真实账户", "initial_capital": 100000}
→ {"id": 1, "name": "真实账户", "initial_capital": 100000, "source": "manual", "created_at": "..."}
```

录入交易 `POST /api/portfolio/1/trades`：
```json
{"symbol": "600519.SH", "direction": "buy", "price": 1800.5, "shares": 100, "trade_date": "2026-04-10"}
→ {"id": 1, "symbol": "600519.SH", "direction": "buy", "price": 1800.5, "shares": 100, "commission": 54.02, "tax": 0, "trade_date": "2026-04-10"}
```

获取持仓 `GET /api/portfolio/1/holdings`：
```json
[{"symbol": "600519.SH", "name": "贵州茅台", "shares": 100, "avg_cost": 1800.5, "current_price": 1850.0, "market_value": 185000, "pnl": 4950, "pnl_pct": 0.0275}]
```

导入回测 `POST /api/portfolio/import/{task_id}`：
```json
{"name": "MA策略跟踪"}
→ {"id": 2, "name": "MA策略跟踪", "source": "backtest", ...}
```

导入逻辑：从回测结果中提取最终持仓（最后一个 snapshot 的 positions）和剩余现金，`initial_capital` 设为导入时的总市值（现金+持仓市值），交易记录中为每只持仓股票生成一条买入记录（以成本价和持有股数录入）。

## 前端设计

### 导航栏

在现有 `行情 | 策略 | 选股 | 回测 | 对比` 基础上增加 **持仓** 入口。

### 新增路由

| 路径 | 组件 | 说明 |
|------|------|------|
| `/portfolio` | `PortfolioList.vue` | 组合列表页 |
| `/portfolio/:id` | `PortfolioDetail.vue` | 组合详情页 |

### 新增文件

| 文件 | 说明 |
|------|------|
| `views/PortfolioList.vue` | 组合列表页 — 卡片式展示所有组合 |
| `views/PortfolioDetail.vue` | 组合详情页 — 概览/持仓/收益曲线/交易记录 |
| `components/TradeForm.vue` | 录入交易的表单弹窗 |
| `components/PortfolioEquity.vue` | 收益曲线组件 |

### 新增 API 函数（api/index.js）

`createPortfolio`, `listPortfolios`, `getPortfolio`, `deletePortfolio`, `addTrade`, `getTrades`, `getHoldings`, `getSnapshots`, `importFromBacktest`

### 组合列表页

卡片式布局，每个组合卡片显示：名称、总市值、总收益率、来源标签（手动/回测）。提供新建组合按钮和虚线占位卡片。

### 组合详情页

四个区域从上到下排列：

1. **概览卡片** — 4列：总市值、可用现金、持仓市值、总收益率
2. **持仓明细表** — 列：股票、持有、成本价、现价、市值、盈亏、收益率
3. **收益曲线** — ECharts 折线图，使用快照数据
4. **交易记录** — 列：日期、股票、方向、价格、数量、佣金、印花税。右上角"录入交易"按钮

### 回测结果页修改

`BacktestResult.vue` 新增"导入持仓"按钮，点击后弹窗输入组合名称，调用导入 API。

## 集成与调度

1. **FastAPI 启动** — `main.py` 注册 portfolio 路由，lifespan 中调用 `init_db()`
2. **APScheduler** — 每日 15:30 数据更新完成后，追加调用 `take_all_snapshots()`
3. **config.py** — 新增 `PORTFOLIO_DB = DATA_DIR / "portfolio.db"`

## 测试要求

- db.py：建表幂等性、连接配置
- manager.py：创建/删除组合、录入交易、持仓计算、费用计算、快照、回测导入
- portfolio.py 路由：API 端到端测试
- 所有测试使用内存 SQLite（`:memory:`）避免文件副作用
