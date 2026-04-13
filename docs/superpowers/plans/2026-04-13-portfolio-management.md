# Portfolio Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a portfolio management module that supports manual trade entry, backtest import, multi-portfolio tracking, and daily net-value snapshots.

**Architecture:** SQLite-based persistence (3 tables: portfolios, trades, snapshots) with a PortfolioManager service class. Holdings computed in-memory from trade records. New FastAPI router at `/api/portfolio`, two new Vue pages (list + detail), integrated with existing scheduler for daily snapshots.

**Tech Stack:** Python 3, FastAPI, SQLite (stdlib sqlite3), Vue 3 (Composition API), ECharts, Axios

**Spec:** `docs/superpowers/specs/2026-04-13-portfolio-management-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `backend/services/portfolio/__init__.py` | Package init |
| `backend/services/portfolio/db.py` | SQLite connection, schema creation |
| `backend/services/portfolio/manager.py` | All portfolio business logic (CRUD, trades, holdings, snapshots, import) |
| `backend/routers/portfolio.py` | REST API endpoints |
| `backend/tests/test_portfolio_db.py` | DB layer tests |
| `backend/tests/test_portfolio_manager.py` | Manager logic tests |
| `backend/tests/test_portfolio_api.py` | API endpoint tests |
| `frontend/src/views/PortfolioList.vue` | Portfolio list page |
| `frontend/src/views/PortfolioDetail.vue` | Portfolio detail page |
| `frontend/src/components/TradeForm.vue` | Trade entry modal |
| `frontend/src/components/PortfolioEquity.vue` | Equity curve for portfolio snapshots |

### Modified Files
| File | Change |
|------|--------|
| `backend/config.py` | Add `PORTFOLIO_DB` path |
| `backend/main.py` | Register portfolio router, call `init_db()` in lifespan |
| `backend/scheduler.py` | Add snapshot job after daily update |
| `frontend/src/App.vue` | Add "持仓" nav link |
| `frontend/src/router/index.js` | Add 2 portfolio routes |
| `frontend/src/api/index.js` | Add 9 portfolio API functions |
| `frontend/src/views/BacktestResult.vue` | Add "导入持仓" button |

---

## Task Overview

| Task | Description | Part |
|------|-------------|------|
| 1 | Config + DB layer (db.py) | Part 1 |
| 2 | PortfolioManager — CRUD + trades + holdings | Part 1 |
| 3 | PortfolioManager — snapshots + import | Part 1 |
| 4 | Portfolio API router | Part 2 |
| 5 | Integration (main.py, scheduler.py) | Part 2 |
| 6 | Frontend API + routing + nav | Part 3 |
| 7 | PortfolioList page | Part 3 |
| 8 | PortfolioDetail page + TradeForm + PortfolioEquity | Part 3 |
| 9 | BacktestResult import button | Part 3 |

Detailed tasks are in part files:
- `docs/superpowers/plans/2026-04-13-portfolio-management-part1.md` — Tasks 1-3 (Backend service layer)
- `docs/superpowers/plans/2026-04-13-portfolio-management-part2.md` — Tasks 4-5 (Backend API + integration)
- `docs/superpowers/plans/2026-04-13-portfolio-management-part3.md` — Tasks 6-9 (Frontend)
