# Screener + Backtest System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a unified stock screening + quantitative backtesting system with event-driven engine, strategy pipeline, and full Web UI.

**Architecture:** Python strategies loaded via importlib, event-driven backtest engine with Broker (T+1, limit-up/down, commission, slippage), pipeline model (0..N screeners → 0..1 trader), async task execution. Frontend: Vue 3 + ECharts for strategy management, screener results, backtest reports, and multi-strategy comparison.

**Tech Stack:** FastAPI, pandas, importlib, threading, Vue 3, ECharts, axios

---

## Plan Structure

The implementation is split into 4 parts with 12 tasks total:

| Part | Tasks | Description |
|------|-------|-------------|
| [Part 1](./2026-04-13-screener-backtest-part1.md) | 1-3 | Backend core: base classes, strategy loader, broker |
| [Part 2](./2026-04-13-screener-backtest-part2.md) | 4-6 | Backend engine: context, engine, analyzer |
| [Part 3](./2026-04-13-screener-backtest-part3.md) | 7-9 | Backend API + K-line adjust: routers, task manager, kline adjust param |
| [Part 4](./2026-04-13-screener-backtest-part4.md) | 10-12 | Frontend: strategy list, screener/backtest pages, result/compare pages |

## File Map

### New Files — Backend

| File | Responsibility |
|------|---------------|
| `backend/services/backtest/__init__.py` | Package init |
| `backend/services/backtest/base.py` | BaseStrategy, ScreenerStrategy, TraderStrategy, ParamAccessor |
| `backend/services/backtest/strategy_loader.py` | Scan and load .py strategy files via importlib |
| `backend/services/backtest/broker.py` | Virtual broker: order matching, T+1, limit-up/down, commission, slippage |
| `backend/services/backtest/portfolio.py` | Portfolio tracker: daily snapshots, position management |
| `backend/services/backtest/context.py` | ScreenerContext, TraderContext with indicator cache |
| `backend/services/backtest/engine.py` | BacktestEngine main loop: data preload, daily event-driven cycle |
| `backend/services/backtest/analyzer.py` | Performance metrics: return, annualized return, max drawdown, Sharpe, win rate |
| `backend/services/backtest/task_manager.py` | Async task registry: submit, poll status, get result |
| `backend/routers/backtest.py` | REST API: strategies list, run backtest, status, result |
| `backend/routers/screener.py` | REST API: run screener, get result |
| `backend/tests/test_broker.py` | Broker unit tests |
| `backend/tests/test_engine.py` | Engine integration tests |
| `backend/tests/test_analyzer.py` | Analyzer unit tests |
| `backend/tests/test_strategy_loader.py` | Strategy loader tests |
| `backend/tests/test_backtest_api.py` | Backtest API route tests |
| `backend/tests/test_screener_api.py` | Screener API route tests |

### New Files — Strategies

| File | Responsibility |
|------|---------------|
| `strategies/examples/ma_cross_screener.py` | Example: MA crossover screener |
| `strategies/examples/macd_screener.py` | Example: MACD screener |
| `strategies/examples/equal_weight_trader.py` | Example: equal-weight trader |

### New Files — Frontend

| File | Responsibility |
|------|---------------|
| `frontend/src/views/StrategyList.vue` | Strategy list page |
| `frontend/src/views/ScreenerPage.vue` | Screener pipeline builder + results |
| `frontend/src/views/BacktestPage.vue` | Backtest pipeline builder + run |
| `frontend/src/views/BacktestResult.vue` | Backtest result detail page |
| `frontend/src/views/ComparePage.vue` | Multi-strategy comparison |
| `frontend/src/components/PipelineBuilder.vue` | Pipeline assembly component |
| `frontend/src/components/ParamEditor.vue` | Strategy parameter editor |
| `frontend/src/components/EquityCurve.vue` | Equity curve chart |
| `frontend/src/components/DrawdownChart.vue` | Drawdown chart |
| `frontend/src/components/TradeTable.vue` | Trade detail table |
| `frontend/src/components/BacktestKline.vue` | K-line with buy/sell markers |
| `frontend/src/components/MetricCards.vue` | Performance metric cards |

### Modified Files

| File | Change |
|------|--------|
| `backend/config.py` | Add QFQ_KLINE_DIR, STRATEGY_DIR |
| `backend/main.py` | Register backtest + screener routers |
| `backend/routers/stock.py` | Add `adjust` query param for kline/indicators |
| `frontend/src/api/index.js` | Add backtest/screener API functions |
| `frontend/src/router/index.js` | Add new routes |
| `frontend/src/App.vue` | Add top navigation bar |
| `frontend/src/views/StockDetail.vue` | Add adjust toggle (不复权/前复权) |
