# Portfolio Account Soft Delete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Portfolio 中实现安全的账户软删除，保留所有历史数据并正确隐藏/查看停用账户。

**Architecture:** 复用已有 `portfolio_accounts.is_active` 字段，在 `AccountRepository` 增加幂等状态变更，在 `AccountService` 事务内拒绝已绑定策略账户删除，并由 v1 router 暴露 DELETE endpoint。前端通过 `portfolioApi.deleteAccount` 接入确认弹窗、停用账户筛选和成功后的视图刷新。

**Tech Stack:** FastAPI、Pydantic、SQLite、React 19、TypeScript、Vitest、Testing Library。

**Spec:** `docs/superpowers/specs/2026-08-21-portfolio-account-soft-delete.md`

## Global Constraints

- 软删除只能更新 `portfolio_accounts.is_active`，禁止物理删除账户及关联业务数据。
- 已绑定策略的账户必须先解绑；删除接口返回 `409`。
- 业务数据访问继续通过现有 Portfolio repository/service/API 层，不新增旁路数据库访问。
- 前端危险操作必须使用确认弹窗，停用账户不得显示写入或删除操作。
- 所有实现先写失败测试，再写最小生产代码。

---

### Task 1: Account Soft-Delete Domain Flow

**Files:**
- Modify: `backend/services/portfolio/repository.py`
- Modify: `backend/services/portfolio/account_service.py`
- Modify: `backend/routers/portfolio_v1.py`
- Test: `backend/tests/test_portfolio_account_service.py`
- Test: `backend/tests/test_portfolio_v1_api.py`

**Interfaces:**
- `AccountRepository.soft_delete(account_id: int, updated_at: str) -> Account` updates only active account rows and returns the updated entity.
- `AccountService.soft_delete_account(account_id: int) -> Account` runs in `BEGIN IMMEDIATE`, rejects bound or already inactive accounts, and commits the state transition.
- `DELETE /api/v1/portfolio/accounts/{account_id}` returns the serialized `Account`.

- [ ] **Step 1: Write failing service tests**
  - Assert an active unbound account becomes `is_active=False` while trades and target history remain queryable.
  - Assert a bound account raises `ValueError("unbind strategy before deleting account")` and leaves strategy binding unchanged.
  - Assert a second delete raises `ValueError("account already inactive")`.

- [ ] **Step 2: Run service tests and verify failure**

  Run: `python -m pytest backend/tests/test_portfolio_account_service.py -k "soft_delete or delete_account" -q`

- [ ] **Step 3: Implement repository, service, and router**
  - Add the repository update with `WHERE id = ? AND is_active = 1`.
  - In the service, load the account including inactive rows, validate active/binding state, begin an immediate transaction, update `is_active`, and rollback on every exception.
  - Add the router endpoint and map `ValueError` through the existing `_error` mapping as `409` except missing accounts as `404`.

- [ ] **Step 4: Add API tests and verify all backend tests**
  - Test `DELETE /api/v1/portfolio/accounts/{id}` returns inactive account data.
  - Test bound account returns `409` and repeated deletion returns `409`.
  - Run: `python -m pytest backend/tests/test_portfolio_account_service.py backend/tests/test_portfolio_v1_api.py -q`

### Task 2: Frontend Account Deletion and Inactive Filter

**Files:**
- Modify: `frontend/src/api/portfolio.ts`
- Modify: `frontend/src/pages/PortfolioPage.tsx`
- Modify: `frontend/src/types/portfolio.ts` only if response typing requires it
- Test: `frontend/src/api/__tests__/portfolio.test.ts`
- Test: `frontend/src/pages/__tests__/PortfolioPage.test.tsx`

**Interfaces:**
- `portfolioApi.deleteAccount(accountId: number): Promise<PortfolioAccountItem>` calls `DELETE /api/v1/portfolio/accounts/{accountId}`.
- `PortfolioPage` owns `includeInactive` and passes it to `getAccounts(includeInactive)`.

- [ ] **Step 1: Write failing API and page tests**
  - Assert `deleteAccount(7)` calls the v1 account DELETE route.
  - Assert the page shows “删除账户” only for a selected active account with no strategy binding.
  - Assert clicking it shows confirmation, confirmation calls the API, and the page reloads accounts.
  - Assert a selected inactive account shows “已停用” and no delete/strategy write actions.

- [ ] **Step 2: Run frontend tests and verify failure**

  Run: `cd frontend && npm test -- --run src/api/__tests__/portfolio.test.ts src/pages/__tests__/PortfolioPage.test.tsx`

- [ ] **Step 3: Implement API and UI behavior**
  - Add `deleteAccount` to `portfolioApi`.
  - Add `includeInactive` state and load accounts with the flag.
  - Add the “显示停用账户” control beside the account selector.
  - Add the delete action only for the selected active account with no `strategyTaskId`; reuse `ConfirmDialog` with explicit consequence text.
  - After success, close the dialog, reload account/snapshot data, and reset `selectedAccount` to `all` if the deleted account was selected.
  - Keep inactive accounts read-only: hide unbind/delete and disable transaction/import submission for them.

- [ ] **Step 4: Verify frontend tests, typecheck, and lint**

  Run: `cd frontend && npm test -- --run src/api/__tests__/portfolio.test.ts src/pages/__tests__/PortfolioPage.test.tsx`, `cd frontend && npx tsc --noEmit`, and `cd frontend && npm run lint`.

### Task 3: Integration and Regression Verification

**Files:**
- Test only: existing backend and frontend test suites

- [ ] **Step 1: Run targeted backend and frontend tests**
- [ ] **Step 2: Run full backend suite**

  Run: `python -m pytest backend/tests/ -x -q`

- [ ] **Step 3: Run full frontend suite and static checks**

  Run: `cd frontend && npm test`, `cd frontend && npx tsc --noEmit`, and `cd frontend && npm run lint`.

- [ ] **Step 4: Manually verify the Portfolio flow**
  - Active unbound account: delete button and confirmation appear.
  - Bound account: delete button is absent; unbind remains available.
  - After deletion: account disappears from default list and appears when “显示停用账户” is enabled.
  - Historical trades and snapshot data remain visible when viewing the inactive account.
