# Pipeline 时间关联/独立模式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 pipeline 多策略组合中，支持相邻 screener 之间配置"时间独立(OR并集)"或"时间关联(AND交集)"模式，使得用户可以灵活控制策略之间的时间约束关系。

**Architecture:** 新增 `date_utils.py` 工具模块处理日期格式化/归属判断。重写引擎三条执行路径（`_run_screener_backtest`、`_run_screener_only`、`_run_backtest`），每个 screener 独立运行后按 `join_modes` 逐对做并集/交集。Router 传递 `join_modes`，前端 PipelineBuilder 增加独立/关联切换 UI。

**Tech Stack:** Python/FastAPI backend, Vue 3 frontend, pytest TDD

**Spec:** `docs/superpowers/specs/2026-04-22-pipeline-time-correlation-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/services/backtest/date_utils.py` | Create | `format_match_date()`, `date_belongs_to()`, `detect_frequency()`, `FREQ_ORDER` |
| `backend/tests/test_date_utils.py` | Create | date_utils 全部测试 |
| `backend/services/backtest/engine.py` | Modify | 接受 `join_modes`，重写三条执行路径，增加 DEBUG 日志 |
| `backend/tests/test_engine.py` | Modify | 增加 join_modes 相关测试 |
| `backend/routers/backtest.py` | Modify | 从请求中提取 `join_modes`，传递给引擎，写入 `pipeline_info` |
| `backend/tests/test_backtest_api.py` | Modify | 增加 join_modes API 测试 |
| `backend/tests/test_strategy_regression.py` | Modify | 更新回归测试适配新行为 |
| `frontend/src/components/PipelineBuilder.vue` | Modify | 相邻 screener 间增加独立/关联切换 UI |
| `frontend/src/views/BacktestPage.vue` | Modify | 传递 `join_modes` 到 API 请求 |

---

## Task Index

Plan 拆分为独立文件，按顺序执行：

| Task | File | Description |
|------|------|-------------|
| Task 1 | `2026-04-22-pipeline-time-correlation-task1.md` | `date_utils.py` — `format_match_date` + `date_belongs_to` + `detect_frequency` |
| Task 2 | `2026-04-22-pipeline-time-correlation-task2.md` | 重写 `_run_screener_backtest` — 独立运行 + 逐对合并 + 最终频率过滤 |
| Task 3 | `2026-04-22-pipeline-time-correlation-task3.md` | 重写 `_run_screener_only` — 独立运行 + 逐对合并(实时选股模式) |
| Task 4 | `2026-04-22-pipeline-time-correlation-task4.md` | 重写 `_run_backtest` — 独立运行 + 逐对合并 + trader 集成 |
| Task 5 | `2026-04-22-pipeline-time-correlation-task5.md` | `BacktestEngine.__init__` 接受 `join_modes` + router 传递 + pipeline_info 持久化 |
| Task 6 | `2026-04-22-pipeline-time-correlation-task6.md` | 更新现有测试（回归测试适配行为变更） |
| Task 7 | `2026-04-22-pipeline-time-correlation-task7.md` | 前端 PipelineBuilder 独立/关联切换 UI + BacktestPage 传递 join_modes |

---

## Key Design Decisions (from spec)

1. **独立(independent)** = OR 并集，**关联(correlated)** = AND 交集
2. `join_modes` 数组长度 = `len(screeners) - 1`，缺失时默认全部 `"independent"`
3. match_date 格式按频率：daily=`YYYY-MM-DD`, weekly=`YYYY-Www`, monthly=`YYYY-MM`
4. 关联匹配：以两者中最粗频率为窗口，细频率只要在窗口内任意一天满足即可
5. 最终输出统一为 pipeline 最细频率，无法精确到该频率的粗粒度日期丢弃
6. 每个 screener 独立对全部股票运行（不再级联过滤）
7. 向后兼容：`join_modes` 缺失默认 independent（与旧版级联 AND 不同，是有意变更）
8. 现有策略零修改
