# 数据管理 + K 线可视化 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 A 股数据管理与 K 线可视化 Web 平台，支持每日增量更新和交互式图表

**Architecture:** FastAPI 后端提供 REST API，读写 parquet 文件；Vue 3 + ECharts 前端渲染 K 线图表和技术指标；APScheduler 驱动定时数据更新

**Tech Stack:** Python 3.10+, FastAPI, Pandas, AKShare, APScheduler, Vue 3, ECharts

**Spec:** `docs/superpowers/specs/2026-04-13-data-management-visualization-design.md`

---

## File Structure

```
stock_investment/
├── backend/
│   ├── main.py                  # FastAPI app entry, mount routers, start scheduler
│   ├── config.py                # paths, scheduler time, retry config
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── stock.py             # GET /api/stocks, /api/stocks/{symbol}/kline, /indicators
│   │   └── data_update.py       # POST /api/data/update, GET status/logs
│   ├── services/
│   │   ├── __init__.py
│   │   ├── data_updater.py      # spot API fetch, retry, incremental write
│   │   ├── stock_data.py        # parquet read, stock list, search
│   │   └── indicator.py         # MA, MACD(DIF/DEA), KDJ, BOLL calculation
│   ├── scheduler.py             # APScheduler setup
│   ├── requirements.txt
│   └── tests/
│       ├── __init__.py
│       ├── test_data_updater.py
│       ├── test_stock_data.py
│       ├── test_indicator.py
│       └── test_api.py
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── App.vue
│       ├── main.js
│       ├── router/index.js
│       ├── api/index.js          # axios wrapper
│       ├── views/
│       │   ├── StockList.vue
│       │   └── StockDetail.vue
│       └── components/
│           ├── KlineChart.vue
│           ├── UpdateStatus.vue
│           └── SearchBar.vue
├── data/
│   ├── kline/A/raw/             # existing parquet files
│   └── logs/                    # update logs
└── docs/
```

---

## Task Overview

| Task | Description | Details |
|------|-------------|---------|
| 1 | Project scaffolding + config | See plan part 1 |
| 2 | stock_data service (parquet read) | See plan part 1 |
| 3 | data_updater service (incremental update) | See plan part 2 |
| 4 | indicator service (MA/MACD/KDJ/BOLL) | See plan part 2 |
| 5 | FastAPI routers + scheduler | See plan part 3 |
| 6 | Frontend scaffolding + stock list page | See plan part 3 |
| 7 | K line chart + indicator toggle | See plan part 4 |
| 8 | Update status UI + integration | See plan part 4 |

Detailed steps in:
- `2026-04-13-plan-part1.md` (Task 1-2)
- `2026-04-13-plan-part2.md` (Task 3-4)
- `2026-04-13-plan-part3.md` (Task 5-6)
- `2026-04-13-plan-part4.md` (Task 7-8)
