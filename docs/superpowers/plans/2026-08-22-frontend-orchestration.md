# Frontend Monitor And History Orchestration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan task-by-task.

**Goal:** Reduce cross-domain orchestration in `MarketMonitor` and `BacktestHistory` without changing visual behavior, routes, API contracts, or user-visible semantics.

**Architecture:** Keep both components as presentation modules. Extract monitor loading/actions into hooks, task schema/result interpretation into a typed history adapter, and Portfolio account binding into a dedicated hook. Do not add backend endpoints in this phase.

**Tech Stack:** React 19, TypeScript, Vitest, existing API modules and hooks conventions.

## Global Constraints

- Preserve existing API calls, routes, payloads, and user-visible Chinese copy.
- Preserve React 19 + TypeScript + Vite patterns and existing Tailwind visual language.
- Do not add a backend endpoint or change backend schemas.
- Keep old/new `pipeline_info` compatibility and monitor/radar routing behavior.
- Portfolio account binding remains functionally identical, including empty-account checks.
- Do not commit or push as part of implementation.

---

### Task 1: Extract Monitor Center Data And Actions

**Files:**
- Create: `frontend/src/components/backtest/useMonitorCenter.ts`
- Create: `frontend/src/components/backtest/useMonitorActions.ts`
- Modify: `frontend/src/components/backtest/MarketMonitor.tsx`
- Test: `frontend/src/components/backtest/__tests__/MarketMonitor.test.tsx`

**Interfaces:**
- `useMonitorCenter()` owns strategy/stock/catalog loading, refresh, collections, loading and error state.
- `useMonitorActions({ onStrategyChanged, onStockChanged })` owns create/run/pause/resume/delete operations and action state.
- `MarketMonitor` keeps form fields and rendering only, consuming typed hook state/actions.

- [ ] Write one failing hook/component test proving initial loading calls the three existing list endpoints and keeps strategy and stock errors independent.
- [ ] Run the focused Vitest test and confirm it fails because the hooks do not exist.
- [ ] Implement the hooks by moving existing request bodies without changing API calls or error copy.
- [ ] Replace component-local loading/action functions with hook calls; keep JSX and class names unchanged.
- [ ] Run `cd frontend && npm test -- src/components/backtest/__tests__/MarketMonitor.test.tsx` and existing monitor tests.

### Task 2: Extract History Task Adapter

**Files:**
- Create: `frontend/src/components/backtest/historyTaskAdapter.ts`
- Modify: `frontend/src/components/backtest/BacktestHistory.tsx`
- Test: `frontend/src/components/backtest/__tests__/historyTaskAdapter.test.ts`
- Test: `frontend/src/components/backtest/__tests__/BacktestHistory.test.tsx`

**Interfaces:**
- `extractStrategyName(item) -> string`.
- `isMonitorTask(item) -> boolean`.
- `extractMarketLabel(item) -> string`.
- `extractParams(item) -> Record<string, unknown> | null`.
- `buildBacktestTask(item, detail) -> BacktestTask` preserving radar/full conversion and date precedence.

- [ ] Write failing adapter tests for flat and legacy nested `pipeline_info`, monitor detection, full payload mapping, radar payload mapping, and result date-range precedence.
- [ ] Run the focused test and confirm it fails because the adapter module does not exist.
- [ ] Move pure parsing/conversion logic into the adapter with explicit types and no React imports.
- [ ] Make `BacktestHistory` call `buildBacktestTask()` and retain only list state, sorting, loading, and rendering.
- [ ] Run adapter and History tests, including monitor badge and radar detail navigation regressions.

### Task 3: Extract Strategy Account Binding

**Files:**
- Create: `frontend/src/components/backtest/useStrategyAccountBinding.ts`
- Modify: `frontend/src/components/backtest/BacktestHistory.tsx`
- Test: `frontend/src/components/backtest/__tests__/useStrategyAccountBinding.test.ts`
- Test: `frontend/src/components/backtest/__tests__/BacktestHistory.test.tsx`

**Interfaces:**
- `useStrategyAccountBinding({ refresh })` returns `bindingId`, `bindingError`, `clearBindingError`, and `bindTask(item)`.
- It preserves the existing candidate filter, snapshot position check, bind-or-create behavior, error parsing, and refresh call.

- [ ] Write failing hook tests for eligible empty account binding, account creation fallback, and API error state.
- [ ] Run the focused test and confirm it fails because the hook does not exist.
- [ ] Move the current `handleBind` logic into the hook without changing Portfolio API calls.
- [ ] Remove Portfolio imports and binding workflow from `BacktestHistory`; render hook state and invoke `bindTask`.
- [ ] Run the hook and History tests.

### Task 4: Frontend Verification And Review

**Files:**
- Modify only files required by review findings.
- Test: `frontend/src/components/backtest/__tests__/*.test.tsx`, `frontend/src/components/backtest/__tests__/*.test.ts`

- [ ] Run `cd frontend && npm test`.
- [ ] Run `cd frontend && npx tsc --noEmit`.
- [ ] Run `cd frontend && npm run lint`.
- [ ] Run `git diff --check` and inspect that no API/route/visual contract changed.
- [ ] Review the final diff for request races, stale closures, and duplicated compatibility logic.
