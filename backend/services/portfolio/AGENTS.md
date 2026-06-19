# AGENTS.md — 持仓管理子系统

> 本文件聚焦**持仓管理**。跨切面铁律(DuckDB 唯一入口、`data/market/` 唯一路径、沟通语言等)见**根 `AGENTS.md`**。

## 核心规则

- **持仓估值**:用 parquet 最新收盘价(非实时 API)。
- **持仓本身不入库**:由 `trades` 在内存推导(`portfolios / trades / snapshots / stock_exclusions` 表)。
- 业务库 `data/portfolio.db`(SQLite)**跨 3 模块共享**:持仓 + 回测(`backtest_tasks`)+ 问股(`chat_sessions / chat_messages`)。**不只是持仓用**——改 schema 时注意另外两个模块(DDL 在 `services/db_schema.py` 幂等下发)。

## 关键文件

```
backend/services/portfolio/
├── db.py        # SQLite 连接 / DDL
└── manager.py   # 持仓推导 / 估值 / 快照
```

- 路由:`routers/portfolio.py`。
- 前端:PortfolioPage + 页内组件。
- scheduler 15:30 做持仓快照(snapshot)。
