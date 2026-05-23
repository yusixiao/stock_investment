# Ask Stock 期 1 Implementation Plan

> **修订状态**:r2(Multi-Agent Harness 重构)/ 2026-05-23
> **r2 摘要**:从单一 turtle pipeline 改为 multi-agent harness。**§Revision Log r2**(紧接本段下方)是权威增量,r1 task 与 r2 路径/命名冲突时以 r2 为准。
> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development(推荐)或 superpowers:executing-plans。

**Goal:** 实现「问股」后端期 1 — 用户在 ChatPage 输入"保守分析 002594"或"分析 002594"后,后端通过 multi-agent harness 路由到 `cpa_conservative` agent(基于 CPA 穿透回报率精算 + 极端保守假设 + Phase 1 数据包 + Phase 3.1 CPA 量化 + Phase 3.2 估值组装)产出完整 markdown 投资分析报告,通过严格 6 类 SSE 事件推回前端。期 1 同时注册 `tradingagents_astock`(团队分析,占位)与 `chitchat` agent,验证 multi-agent 扩展性。

**Architecture:** FastAPI 路由 → Coordinator 编排 → 三段流水线(DataPackBuilder / phase3_quant / phase3_valuation),Agent 间通过 `data/agent_runs/{code}_{name}/*.md` 文件通信。LLM 多协议客户端(OpenAI/Anthropic/OpenRouter/DeepSeek),system_config 用扁平 KV `LLM_<NAME>_*` 模型持久化到 yaml。前端零改动,严格沿用现有 6 类 SSE 解析器(`thinking/tool_start/tool_done/generating/done/error`)。

**Tech Stack:** Python 3.11 / FastAPI / SQLite(既有 `data/portfolio.db`)/ DuckDB(查询层,既有 `services/duckdb_store.py`)/ pydantic v2 / httpx(LLM 调用)/ pyyaml / pytest + pytest-asyncio + httpx.MockTransport

**Spec:** `docs/superpowers/specs/2026-05-23-ask-stock-design.md`(尤其是 §12-§14 multi-agent 部分)

---

## Revision Log r2(Multi-Agent Harness)

### r2-A. 全局 find-replace cheatsheet

实施 r1 task 时按以下映射替换路径/命名(若 task 中尚未出现新名称,沿用 r1):

| r1 旧 | r2 新 |
|---|---|
| `backend/services/agent/`(单数) | `backend/services/agent_harness/`(基础设施)+ `backend/services/agents/`(各 agent) |
| `backend/services/agent/symbol.py` | `backend/services/agent_harness/symbol.py` |
| `backend/services/agent/sse.py` | `backend/services/agent_harness/events.py` |
| `backend/services/agent/workspace.py` | `backend/services/agent_harness/workspace.py` |
| `backend/services/agent/session_repo.py` | `backend/services/agent_harness/session_repo.py` |
| `backend/services/agent/coordinator.py` | 拆为:`agent_harness/dispatcher.py`(通用调度)+ `agents/<id>/agent.py`(各 agent 实现)|
| `backend/services/agent/parser.py` | `backend/services/agents/cpa_conservative/parser.py` |
| `backend/services/agent/prompts/turtle/` | `backend/services/agents/cpa_conservative/prompts/` |
| `backend/services/agent/pipeline/phase1_data_pack/` | `backend/services/agents/cpa_conservative/data_pack.py` + `agents/cpa_conservative/sections/` |
| `backend/services/agent/pipeline/phase3_quant.py` | `backend/services/agents/cpa_conservative/phases.py::run_quant` |
| `backend/services/agent/pipeline/phase3_valuation.py` | `backend/services/agents/cpa_conservative/phases.py::run_valuation` |
| SSE `phase=phase1_data_pack` 等字段 | `agent_id="cpa_conservative", step_id="data_pack"`(新字段集) |
| 标识符 `turtle_conservative` | `cpa_conservative` |

DuckDB 查询若被多 agent 共用,迁入 `agent_harness/data_layer/{financial,dividend,valuation,pricing,industry}.py`。

### r2-B. 任务清单调整

| r1 Task | r2 处理 |
|---|---|
| T1-T6(SQLite/auth_stub/symbol/sse/契约/session) | 不变,按 cheatsheet 调整路径 |
| **T7 workspace** | 签名加 agent_id:`create_workspace(session_id, agent_id) -> Path`,目录格式 `<session_id>/<agent_id>__<run_id>/` |
| T8-T10(system_config) | 不变 |
| **T11**(system_config 路由) | 增加 `default_agent_id` 字段读写 |
| T12 agent 路由骨架 | 改为接 dispatcher;**拆出 T12.5(新增,见下)** |
| **T12.5(新增)** | **Agent Protocol + Registry + Routing + Events + Dispatcher + Meta** — multi-agent 基础抽象(三层 fallback:explicit/keyword/default)|
| **T12.6(新增)** | **LLM Router + 澄清反问** — 在 T12.5 三层 fallback 之上插入第 4 层 LLM 意图分类;confidence<0.6 时通过 `thinking` 事件 + `quick_replies` 反问用户 |
| T13-T16(LLM Client) | 路径改 `agent_harness/llm/` |
| T17 Coordinator chitchat | 改为「实现 chitchat agent + dispatcher 调度」(见 T31.5) |
| T18 `/chat/stream` | 改为「intent classify → routing.resolve_agent(四层 fallback,含 LLM router 与澄清分支)→ dispatcher.dispatch 或 emit clarify」 |
| T19 qa_followup | 实现为 `chitchat` agent 的 prompt 变体 |
| T20-T26(数据包) | 全部归到 `agents/cpa_conservative/`;DuckDB 查询下沉 `agent_harness/data_layer/` |
| T27 复制 prompts | 目标 `agents/cpa_conservative/prompts/` |
| T28 parser | `agents/cpa_conservative/parser.py` |
| T29-T30(quant/valuation 执行器) | 合并到 `agents/cpa_conservative/phases.py`(`run_quant` / `run_valuation`) |
| T31 Coordinator full_pipeline | 拆为:**(a)** Dispatcher 通用编排(已在 T12.5);**(b)** `cpa_conservative.agent.py::CPAConservativeAgent.run()` 串 step 序列 |
| **T31.5(新增)** | **`tradingagents_astock` 占位 + `chitchat` agent + `cpa_conservative` 注册骨架** |
| T32 e2e | 加路由测试:同消息分别用「保守分析」/「团队分析」关键字 |
| T33 烟囱 | 加一轮 `tradingagents_astock` 烟囱,验证返回 error 事件结构 |
| T34 文档 | AGENTS.md 加「问股 multi-agent 架构」段(参见 r2-D) |

工作量净增 ≈ 2 天(T12.5 ~6h、**T12.6 ~4h**、T31.5 ~2h、T7/T17/T18/T31 拆分 ~4h、前端 agent 徽章 + 分析方式下拉 + 澄清快捷按钮 ~5h、routing 测试 ~2h)。

新任务详细 5-step TDD 见本 plan 末尾「Phase F: Multi-Agent Harness 增量任务」段。

### r2-C. Spec 对齐

本 plan r2 与 spec r2 §12-§14 对齐。冲突点以 spec r2 为准。

### r2-D. AGENTS.md 同步草案(T34 用)

```markdown
## 问股 Multi-Agent 架构(2026-05-23)

- 后端 `backend/services/agent_harness/` = 通用基础设施
  `backend/services/agents/<id>/` = 各 agent 自治模块
- 期 1 注册 agents:
  - `cpa_conservative`(保守分析,enabled,基于 CPA 穿透回报率精算)
  - `tradingagents_astock`(团队分析,enabled=false,期 2 实施)
  - `chitchat`(闲聊,enabled)
- 路由:四层 fallback — 显式 agent_id(API/UI 下拉)→ @mention(期 2)→ 消息 alias 关键字 → LLM router(意图分类,confidence<0.6 反问)→ system_config.default_agent_id(初始 cpa_conservative)
- 澄清反问:LLM router 不确定时,通过 `thinking` 事件 + `quick_replies` 字段输出快捷按钮,前端点击后用 `explicit_agent_id` 重发请求(严守 SSE 6 类铁律)
- 加新 agent 三步:① 写 manifest.py ② 实现 Agent.run() ③ agents/__init__.py import 一行注册
- SSE 严格 6 类,payload 含 agent_id/agent_label/step_id/step_label/step_index/step_total
- data/agent_runs/<session_id>/<agent_id>__<run_id>/_meta.json 记录 agent_id/version/prompt_hashes/model
```

---

## File Structure

每个文件**单一职责**(对齐 spec §2.2)。Test 文件与源文件 1:1 对应(独立模块的隔离测试)。

### 新建源文件

| 路径 | 职责 |
|---|---|
| `backend/routers/agent.py` | `/api/v1/agent/*` 路由(stream / sessions CRUD / artifacts / skills) |
| `backend/routers/system_config.py` | `/api/v1/system/config/*` 扁平 KV CRUD + LLM test |
| `backend/routers/auth_stub.py` | `/api/v1/auth/status` 永返 `{authEnabled: false}` |
| `backend/services/system_config/__init__.py` | 包初始化 |
| `backend/services/system_config/store.py` | `data/system_config.yaml` 原子读写 |
| `backend/services/system_config/schema.py` | 扁平键命名规则校验(Pydantic) |
| `backend/services/system_config/channels.py` | KV ↔ `ChannelConfig` 重组/反向 |
| `backend/services/system_config/llm_client.py` | LLMClient 抽象基类 + OpenAICompatible/Anthropic 实现 |
| `backend/services/system_config/llm_test.py` | `test_channel(name)` 单次握手验活 |
| `backend/services/agent/__init__.py` | 包初始化 |
| `backend/services/agent/symbol.py` | 股票码识别 + normalize |
| `backend/services/agent/sse.py` | 6 类 SSE 帧工厂 + 编码 |
| `backend/services/agent/session_repo.py` | `chat_sessions` / `chat_messages` SQLite CRUD |
| `backend/services/agent/workspace.py` | `data/agent_runs/{code}_{name}/` 目录管理 |
| `backend/services/agent/llm_routing.py` | phase → channel 选择(default fallback) |
| `backend/services/agent/parser.py` | LLM 输出结构化字段提取(`<results>` 块解析) |
| `backend/services/agent/coordinator.py` | 路由判断 + phase 编排 + 决策日志 |
| `backend/services/agent/pipeline/__init__.py` | 包初始化 |
| `backend/services/agent/pipeline/phase1_data_pack/__init__.py` | 子包 |
| `backend/services/agent/pipeline/phase1_data_pack/builder.py` | DataPackBuilder 编排 16 sections |
| `backend/services/agent/pipeline/phase1_data_pack/sections/__init__.py` | 子包 |
| `backend/services/agent/pipeline/phase1_data_pack/sections/s01_basic.py` | §1 基础信息 |
| `backend/services/agent/pipeline/phase1_data_pack/sections/s02_market.py` | §2 市值/股价 |
| `backend/services/agent/pipeline/phase1_data_pack/sections/s03_income.py` | §3 利润表(5 年) |
| `backend/services/agent/pipeline/phase1_data_pack/sections/s03p_parent_income.py` | §3P A 股母公司利润表 |
| `backend/services/agent/pipeline/phase1_data_pack/sections/s04_balance.py` | §4 资产负债表(5 年) |
| `backend/services/agent/pipeline/phase1_data_pack/sections/s04p_parent_balance.py` | §4P A 股母公司资产负债表 |
| `backend/services/agent/pipeline/phase1_data_pack/sections/s05_cashflow.py` | §5 现金流量表(5 年) |
| `backend/services/agent/pipeline/phase1_data_pack/sections/s06_dividend.py` | §6 每股股息(5 年) |
| `backend/services/agent/pipeline/phase1_data_pack/sections/s07_holders_placeholder.py` | §7 控股股东(期 1 占位) |
| `backend/services/agent/pipeline/phase1_data_pack/sections/s08_industry_placeholder.py` | §8 行业竞争(期 1 占位) |
| `backend/services/agent/pipeline/phase1_data_pack/sections/s09_segments.py` | §9 主营拆分 |
| `backend/services/agent/pipeline/phase1_data_pack/sections/s10_esg_placeholder.py` | §10 ESG(期 1 占位) |
| `backend/services/agent/pipeline/phase1_data_pack/sections/s11_weekly_kline.py` | §11 历史价格(周线 5 年) |
| `backend/services/agent/pipeline/phase1_data_pack/sections/s12_ratios.py` | §12 关键比率 |
| `backend/services/agent/pipeline/phase1_data_pack/sections/s13_warnings.py` | §13 自检 warnings |
| `backend/services/agent/pipeline/phase1_data_pack/sections/s14_rf.py` | §14 无风险利率(常量 2.7%) |
| `backend/services/agent/pipeline/phase1_data_pack/sections/s15_industry_valuation.py` | §15 行业平均估值 |
| `backend/services/agent/pipeline/phase1_data_pack/sections/s16_peers_placeholder.py` | §16 同业可比(期 1 占位) |
| `backend/services/agent/pipeline/phase1_data_pack/sections/s17_derived.py` | §17 衍生指标(MACD/MA/分位数) |
| `backend/services/agent/pipeline/phase3_quant.py` | Phase 3.1 CPA 量化 LLM 调用 |
| `backend/services/agent/pipeline/phase3_valuation.py` | Phase 3.2 估值/报告组装 LLM 调用 |
| `backend/services/agent/prompts/turtle/phase3_quantitative.md` | 从 turtle 复制 |
| `backend/services/agent/prompts/turtle/phase3_valuation.md` | 从 turtle 复制 |
| `backend/services/agent/prompts/turtle/references/shared_tables.md` | 从 turtle 复制 |
| `backend/services/agent/prompts/turtle/references/factor_interface.md` | 从 turtle 复制 |
| `backend/services/agent/prompts/turtle/references/judgment_examples_turtle.md` | 从 turtle 复制 |
| `backend/services/agent/prompts/turtle/references/output_schema.md` | 从 turtle 复制 |

### 修改既有文件

| 路径 | 改动 |
|---|---|
| `backend/services/db_schema.py` | 增 `chat_sessions` / `chat_messages` 两表 migration |
| `backend/main.py` | lifespan 注册新路由 + 启动时确保 `data/agent_runs/`、`data/system_config.yaml` 存在 |
| `AGENTS.md` | 期 1 完成后追加 Accomplished 段 |

### 新建测试文件

| 路径 |
|---|
| `backend/tests/agent/__init__.py` |
| `backend/tests/agent/conftest.py`(共享 fixtures:tmp duckdb / mock LLM client / sample StockRef) |
| `backend/tests/agent/test_symbol.py` |
| `backend/tests/agent/test_sse.py` |
| `backend/tests/agent/test_session_repo.py` |
| `backend/tests/agent/test_workspace.py` |
| `backend/tests/agent/test_llm_routing.py` |
| `backend/tests/agent/test_parser.py` |
| `backend/tests/agent/test_coordinator_routing.py` |
| `backend/tests/agent/test_phase1_section_s01_basic.py` |
| `backend/tests/agent/test_phase1_section_s02_market.py` |
| `backend/tests/agent/test_phase1_section_s03_income.py` |
| `backend/tests/agent/test_phase1_section_s04_balance.py` |
| `backend/tests/agent/test_phase1_section_s05_cashflow.py` |
| `backend/tests/agent/test_phase1_section_s06_dividend.py` |
| `backend/tests/agent/test_phase1_section_s11_weekly.py` |
| `backend/tests/agent/test_phase1_section_s12_ratios.py` |
| `backend/tests/agent/test_phase1_section_s17_derived.py` |
| `backend/tests/agent/test_phase1_data_pack_builder.py` |
| `backend/tests/agent/test_phase3_quant_parser.py` |
| `backend/tests/agent/test_phase3_quant.py` |
| `backend/tests/agent/test_phase3_valuation.py` |
| `backend/tests/agent/test_coordinator_full_pipeline.py` |
| `backend/tests/system_config/__init__.py` |
| `backend/tests/system_config/test_store.py` |
| `backend/tests/system_config/test_schema.py` |
| `backend/tests/system_config/test_channels.py` |
| `backend/tests/system_config/test_llm_client_openai.py` |
| `backend/tests/system_config/test_llm_client_anthropic.py` |
| `backend/tests/system_config/test_routes.py` |
| `backend/tests/agent/test_routes_auth_stub.py` |
| `backend/tests/agent/test_routes_agent.py` |
| `backend/tests/agent/test_sse_contract.py`(SSE 帧 vs 前端 ProgressStep 字段一致性) |

---

## 执行约定

- **每 task 独立 commit**(message 规范见每 task Step 5)
- **TDD 严格**:Step1 先写失败测试 → Step2 验证失败 → Step3 最小实现 → Step4 验证通过 → Step5 commit
- **AKShare 必须 mock**(AGENTS.md 铁律,本环境会超时)
- **数据访问统一走 `services/duckdb_store.py`**,禁止 glob parquet(AGENTS.md 铁律)
- **所有 LLM 调用必须 mock**(用 `httpx.MockTransport`)
- 验证命令前缀使用项目根:`python -m pytest backend/tests/agent/...`

---

## Phase A — 基础设施(Tasks 1-12)

### Task 1: SQLite migration 增加 chat_sessions / chat_messages 两表

**Files:**
- Modify: `backend/services/db_schema.py`
- Test: `backend/tests/agent/test_session_repo.py`(本 task 仅写最小 schema 测试,完整 CRUD 在 Task 6)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agent/__init__.py
# 空文件

# backend/tests/agent/test_session_repo.py
import sqlite3
from pathlib import Path
from backend.services.db_schema import ensure_schema

def test_chat_sessions_table_exists(tmp_path: Path):
    db = tmp_path / "p.db"
    conn = sqlite3.connect(db)
    ensure_schema(conn)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chat_sessions'")
    assert cur.fetchone() is not None
    cur = conn.execute("PRAGMA table_info(chat_sessions)")
    cols = {row[1] for row in cur.fetchall()}
    assert {"session_id","title","stock_code","output_dir","status","current_phase",
            "created_at","last_active","msg_count"} <= cols
    conn.close()

def test_chat_messages_table_exists(tmp_path: Path):
    db = tmp_path / "p.db"
    conn = sqlite3.connect(db)
    ensure_schema(conn)
    cur = conn.execute("PRAGMA table_info(chat_messages)")
    cols = {row[1] for row in cur.fetchall()}
    assert {"id","session_id","role","content","context","thinking","artifacts",
            "tokens_in","tokens_out","created_at"} <= cols
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/agent/test_session_repo.py -x -q`
Expected: FAIL — `chat_sessions` 表不存在

- [ ] **Step 3: Write minimal implementation**

在 `backend/services/db_schema.py` 既有 `ensure_schema` 函数末尾追加(具体函数命名按现有文件惯例;若 `ensure_schema` 名不同则替换为实际名):

```python
def ensure_schema(conn):
    # ... 既有迁移 ...

    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            session_id    TEXT PRIMARY KEY,
            title         TEXT NOT NULL DEFAULT '',
            stock_code    TEXT,
            output_dir    TEXT,
            status        TEXT NOT NULL DEFAULT 'idle',
            current_phase TEXT,
            created_at    TEXT NOT NULL,
            last_active   TEXT NOT NULL,
            msg_count     INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_last_active ON chat_sessions(last_active DESC)")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id         TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role       TEXT NOT NULL,
            content    TEXT NOT NULL,
            context    TEXT,
            thinking   TEXT,
            artifacts  TEXT,
            tokens_in  INTEGER,
            tokens_out INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages(session_id, created_at)")
    conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/agent/test_session_repo.py -x -q`
Expected: PASS(2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/db_schema.py backend/tests/agent/__init__.py backend/tests/agent/test_session_repo.py
git commit -m "feat(agent): SQLite migration 增加 chat_sessions / chat_messages 两表"
```

---

### Task 2: `auth_stub` 路由(永返 authEnabled: false)

**Files:**
- Create: `backend/routers/auth_stub.py`
- Test: `backend/tests/agent/test_routes_auth_stub.py`
- Modify: `backend/main.py`(注册路由)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agent/test_routes_auth_stub.py
from fastapi.testclient import TestClient
from backend.main import app

def test_auth_status_returns_disabled():
    client = TestClient(app)
    r = client.get("/api/v1/auth/status")
    assert r.status_code == 200
    body = r.json()
    assert body == {"authEnabled": False}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/agent/test_routes_auth_stub.py -x -q`
Expected: FAIL — 404 或路由未注册

- [ ] **Step 3: Write minimal implementation**

```python
# backend/routers/auth_stub.py
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

@router.get("/status")
def status():
    return {"authEnabled": False}
```

修改 `backend/main.py`,在路由注册段加:

```python
from backend.routers import auth_stub
app.include_router(auth_stub.router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/agent/test_routes_auth_stub.py -x -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/routers/auth_stub.py backend/main.py backend/tests/agent/test_routes_auth_stub.py
git commit -m "feat(auth): /api/v1/auth/status stub 永返 authEnabled=false"
```

---

### Task 3: `services/agent/symbol.py` 股票码识别 + normalize

**Files:**
- Create: `backend/services/agent/__init__.py`(空)
- Create: `backend/services/agent/symbol.py`
- Test: `backend/tests/agent/test_symbol.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agent/test_symbol.py
from unittest.mock import MagicMock
import pytest
from backend.services.agent.symbol import normalize, extract, StockRef

class TestNormalize:
    def test_a_share_sh(self):
        assert normalize("600519") == "600519.SH"
    def test_a_share_sz(self):
        assert normalize("002594") == "002594.SZ"
    def test_a_share_creation_board(self):
        assert normalize("300750") == "300750.SZ"
    def test_a_share_star_board(self):
        assert normalize("688981") == "688981.SH"
    def test_already_suffixed_a(self):
        assert normalize("600519.SH") == "600519.SH"
    def test_hk(self):
        assert normalize("00700") == "00700.HK"
    def test_hk_short(self):
        assert normalize("700.HK") == "00700.HK"
    def test_us_no_suffix(self):
        assert normalize("AAPL") == "AAPL"
    def test_us_lowercase(self):
        assert normalize("aapl") == "AAPL"

class TestExtract:
    def test_from_context(self):
        ctx = {"stock_code": "002594", "stock_name": "比亚迪"}
        si = MagicMock(); si.get_name.return_value = "比亚迪"
        ref = extract("帮我看看", ctx, stock_index=si)
        assert ref == StockRef(code="002594.SZ", name="比亚迪", market="A")
    def test_from_message_with_code(self):
        si = MagicMock(); si.get_name.return_value = "贵州茅台"
        ref = extract("分析 600519", None, stock_index=si)
        assert ref.code == "600519.SH"
        assert ref.market == "A"
    def test_no_match_returns_none(self):
        si = MagicMock(); si.get_name.return_value = None
        assert extract("你好", None, stock_index=si) is None
    def test_us_ticker(self):
        si = MagicMock(); si.get_name.return_value = "Apple Inc"
        ref = extract("AAPL 怎么样", None, stock_index=si)
        assert ref.code == "AAPL"
        assert ref.market == "US"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/agent/test_symbol.py -x -q`
Expected: FAIL — module not found

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/agent/__init__.py
# 空
```

```python
# backend/services/agent/symbol.py
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Literal, Optional

Market = Literal["A", "HK", "US"]

@dataclass(frozen=True)
class StockRef:
    code: str
    name: str
    market: Market

_RE_A_FULL = re.compile(r"^(\d{6})\.(SH|SZ)$")
_RE_A_BARE = re.compile(r"^\d{6}$")
_RE_HK_FULL = re.compile(r"^(\d{1,5})\.HK$", re.IGNORECASE)
_RE_HK_BARE = re.compile(r"^\d{5}$")
_RE_US = re.compile(r"^[A-Za-z]{1,5}(\.US)?$")
_RE_INLINE_A = re.compile(r"\b(\d{6})\b")
_RE_INLINE_HK = re.compile(r"\b(\d{5})\b")
_RE_INLINE_US = re.compile(r"\b([A-Z]{2,5})\b")

def normalize(raw: str) -> str:
    raw = raw.strip()
    if m := _RE_A_FULL.match(raw):
        return f"{m.group(1)}.{m.group(2).upper()}"
    if _RE_A_BARE.match(raw):
        return f"{raw}.SH" if raw[0] in "6" or raw.startswith("688") else f"{raw}.SZ"
    if m := _RE_HK_FULL.match(raw):
        return f"{m.group(1).zfill(5)}.HK"
    if _RE_HK_BARE.match(raw):
        return f"{raw}.HK"
    if _RE_US.match(raw):
        return raw.upper().replace(".US", "")
    return raw

def _market_of(code: str) -> Market:
    if code.endswith((".SH", ".SZ")): return "A"
    if code.endswith(".HK"): return "HK"
    return "US"

def extract(message: str, context: Optional[dict], *, stock_index) -> Optional[StockRef]:
    """优先从 context 取,fallback 到 message regex"""
    if context and (raw := context.get("stock_code")):
        code = normalize(str(raw))
        name = context.get("stock_name") or stock_index.get_name(code) or ""
        return StockRef(code=code, name=name, market=_market_of(code))
    if not message:
        return None
    for m in _RE_INLINE_A.finditer(message):
        code = normalize(m.group(1))
        if name := stock_index.get_name(code):
            return StockRef(code=code, name=name, market="A")
    for m in _RE_INLINE_HK.finditer(message):
        code = normalize(m.group(1))
        if name := stock_index.get_name(code):
            return StockRef(code=code, name=name, market="HK")
    for m in _RE_INLINE_US.finditer(message):
        code = normalize(m.group(1))
        if name := stock_index.get_name(code):
            return StockRef(code=code, name=name, market="US")
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/agent/test_symbol.py -x -q`
Expected: PASS(13 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/__init__.py backend/services/agent/symbol.py backend/tests/agent/test_symbol.py
git commit -m "feat(agent): symbol normalize + extract(支持 A/HK/US)"
```

---

### Task 4: `services/agent/sse.py` 6 类 SSE 帧工厂

**Files:**
- Create: `backend/services/agent/sse.py`
- Test: `backend/tests/agent/test_sse.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agent/test_sse.py
import json
from backend.services.agent import sse

def test_thinking_shape():
    e = sse.thinking("识别股票")
    assert e == {"type": "thinking", "content": "识别股票"}

def test_tool_start_shape():
    e = sse.tool_start("phase1", "采集市场数据")
    assert e == {"type": "tool_start", "tool": "phase1", "display_name": "采集市场数据"}

def test_tool_done_minimal():
    e = sse.tool_done("phase1", success=True)
    assert e == {"type": "tool_done", "tool": "phase1", "success": True}

def test_tool_done_full():
    e = sse.tool_done("phase1", success=True, duration=1.8, message="ok", display_name="数据包")
    assert e["duration"] == 1.8
    assert e["message"] == "ok"
    assert e["display_name"] == "数据包"

def test_generating_shape():
    e = sse.generating("Step 0...")
    assert e == {"type": "generating", "content": "Step 0..."}

def test_done_shape():
    arts = [{"name": "report.md", "url": "/x"}]
    e = sse.done("# 报告", arts)
    assert e == {"type": "done", "success": True, "content": "# 报告", "artifacts": arts}

def test_error_shape():
    e = sse.error("LLM_TIMEOUT", "超时", phase="phase3.1")
    assert e == {"type": "error", "error": "LLM_TIMEOUT", "message": "超时", "phase": "phase3.1"}

def test_encode_frame_format():
    raw = sse.encode({"type": "thinking", "content": "x"})
    assert raw.endswith(b"\n\n")
    assert raw.startswith(b"data: ")
    body = raw[len(b"data: "):-2]
    assert json.loads(body) == {"type": "thinking", "content": "x"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/agent/test_sse.py -x -q`
Expected: FAIL — module not found

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/agent/sse.py
from __future__ import annotations
import json
from typing import Optional

def thinking(content: str) -> dict:
    return {"type": "thinking", "content": content}

def tool_start(tool: str, display_name: str) -> dict:
    return {"type": "tool_start", "tool": tool, "display_name": display_name}

def tool_done(tool: str, *, success: bool, duration: Optional[float] = None,
              message: Optional[str] = None, display_name: Optional[str] = None) -> dict:
    e: dict = {"type": "tool_done", "tool": tool, "success": success}
    if duration is not None: e["duration"] = duration
    if message is not None: e["message"] = message
    if display_name is not None: e["display_name"] = display_name
    return e

def generating(content: str) -> dict:
    return {"type": "generating", "content": content}

def done(content: str, artifacts: list[dict]) -> dict:
    return {"type": "done", "success": True, "content": content, "artifacts": artifacts}

def error(error_code: str, message: str, *, phase: Optional[str] = None) -> dict:
    e: dict = {"type": "error", "error": error_code, "message": message}
    if phase is not None: e["phase"] = phase
    return e

def encode(event: dict) -> bytes:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/agent/test_sse.py -x -q`
Expected: PASS(8 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/sse.py backend/tests/agent/test_sse.py
git commit -m "feat(agent): sse.py 严格 6 类事件工厂"
```

---

### Task 5: SSE 契约测试(对前端 ProgressStep 字段保护)

**Files:**
- Create: `backend/tests/agent/test_sse_contract.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agent/test_sse_contract.py
"""
契约测试:每个 SSE 事件 dict 的 keys 必须严格属于前端 ProgressStep 允许集合。
前端 ProgressStep 字段(frontend/src/stores/agentChatStore.ts:265-283):
  type, step?, tool?, display_name?, success?, duration?, message?, content?,
  error?, phase?, artifacts?
"""
from backend.services.agent import sse

ALLOWED = {"type","step","tool","display_name","success","duration","message",
           "content","error","phase","artifacts"}

def test_all_factories_only_use_allowed_fields():
    events = [
        sse.thinking("x"),
        sse.tool_start("p1", "数据"),
        sse.tool_done("p1", success=True, duration=1.0, message="ok", display_name="数据"),
        sse.generating("y"),
        sse.done("# r", [{"name":"r.md","url":"/x"}]),
        sse.error("E1", "msg", phase="p1"),
    ]
    for ev in events:
        unknown = set(ev.keys()) - ALLOWED
        assert not unknown, f"event {ev['type']} has unknown keys {unknown}"

def test_type_values_in_allowed_set():
    types = {sse.thinking("")["type"], sse.tool_start("","")["type"],
             sse.tool_done("",success=True)["type"], sse.generating("")["type"],
             sse.done("",[])["type"], sse.error("","")["type"]}
    assert types == {"thinking","tool_start","tool_done","generating","done","error"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/agent/test_sse_contract.py -x -q`
Expected: PASS(已有 sse.py;契约测试是冗余守护,提前发现回归)

- [ ] **Step 3: Write minimal implementation**

(无新代码;本 task 纯 guard test)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/agent/test_sse_contract.py -x -q`
Expected: PASS(2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/tests/agent/test_sse_contract.py
git commit -m "test(agent): SSE 契约 guard test(字段集白名单)"
```

---

### Task 6: `services/agent/session_repo.py` SQLite CRUD

**Files:**
- Create: `backend/services/agent/session_repo.py`
- Modify: `backend/tests/agent/test_session_repo.py`(扩展 CRUD 测试)

- [ ] **Step 1: Write the failing test**

在 `backend/tests/agent/test_session_repo.py` 末尾追加:

```python
import sqlite3
from datetime import datetime
from backend.services.agent.session_repo import SessionRepo
from backend.services.db_schema import ensure_schema

def _conn(tmp_path):
    db = tmp_path / "p.db"
    c = sqlite3.connect(db); ensure_schema(c); return c

def test_upsert_creates_session(tmp_path):
    repo = SessionRepo(_conn(tmp_path))
    repo.upsert("sid-1", title="hello")
    s = repo.get("sid-1")
    assert s is not None
    assert s["session_id"] == "sid-1"
    assert s["title"] == "hello"
    assert s["status"] == "idle"
    assert s["msg_count"] == 0

def test_upsert_idempotent(tmp_path):
    repo = SessionRepo(_conn(tmp_path))
    repo.upsert("sid-1")
    repo.upsert("sid-1")
    assert repo.get("sid-1") is not None

def test_update_status(tmp_path):
    repo = SessionRepo(_conn(tmp_path))
    repo.upsert("sid-1")
    repo.update_status("sid-1", status="running", current_phase="phase1")
    s = repo.get("sid-1")
    assert s["status"] == "running"
    assert s["current_phase"] == "phase1"

def test_append_message_increments_msg_count(tmp_path):
    repo = SessionRepo(_conn(tmp_path))
    repo.upsert("sid-1")
    repo.append_message("sid-1", role="user", content="分析比亚迪")
    repo.append_message("sid-1", role="assistant", content="好的", thinking=[{"type":"thinking","content":"x"}])
    s = repo.get("sid-1")
    assert s["msg_count"] == 2
    msgs = repo.list_messages("sid-1")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["thinking"] == [{"type":"thinking","content":"x"}]

def test_list_sessions_orders_by_last_active(tmp_path):
    repo = SessionRepo(_conn(tmp_path))
    repo.upsert("a")
    repo.upsert("b")
    repo.append_message("a", role="user", content="hi")  # bumps a's last_active
    items = repo.list_sessions(limit=10)
    assert items[0]["session_id"] == "a"

def test_delete_cascade(tmp_path):
    repo = SessionRepo(_conn(tmp_path))
    repo.upsert("sid-1")
    repo.append_message("sid-1", role="user", content="x")
    repo.delete("sid-1")
    assert repo.get("sid-1") is None
    assert repo.list_messages("sid-1") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/agent/test_session_repo.py -x -q`
Expected: FAIL — `SessionRepo` 不存在

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/agent/session_repo.py
from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

class SessionRepo:
    def __init__(self, conn):
        self.conn = conn
        self.conn.execute("PRAGMA foreign_keys = ON")

    def upsert(self, session_id: str, *, title: str = "", stock_code: Optional[str] = None,
               output_dir: Optional[str] = None) -> None:
        now = _now_iso()
        self.conn.execute("""
            INSERT INTO chat_sessions (session_id,title,stock_code,output_dir,status,
                                       current_phase,created_at,last_active,msg_count)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(session_id) DO UPDATE SET
                title       = COALESCE(NULLIF(excluded.title,''), chat_sessions.title),
                stock_code  = COALESCE(excluded.stock_code, chat_sessions.stock_code),
                output_dir  = COALESCE(excluded.output_dir, chat_sessions.output_dir),
                last_active = excluded.last_active
        """, (session_id, title, stock_code, output_dir, "idle", None, now, now, 0))
        self.conn.commit()

    def get(self, session_id: str) -> Optional[dict]:
        cur = self.conn.execute("SELECT * FROM chat_sessions WHERE session_id=?", (session_id,))
        row = cur.fetchone()
        if not row: return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))

    def update_status(self, session_id: str, *, status: Optional[str] = None,
                      current_phase: Optional[str] = None) -> None:
        sets, vals = [], []
        if status is not None: sets.append("status=?"); vals.append(status)
        if current_phase is not None: sets.append("current_phase=?"); vals.append(current_phase)
        sets.append("last_active=?"); vals.append(_now_iso())
        vals.append(session_id)
        self.conn.execute(f"UPDATE chat_sessions SET {','.join(sets)} WHERE session_id=?", vals)
        self.conn.commit()

    def append_message(self, session_id: str, *, role: str, content: str,
                       context: Optional[dict] = None, thinking: Optional[list] = None,
                       artifacts: Optional[list] = None,
                       tokens_in: Optional[int] = None, tokens_out: Optional[int] = None) -> str:
        mid = str(uuid.uuid4())
        now = _now_iso()
        self.conn.execute("""
            INSERT INTO chat_messages (id,session_id,role,content,context,thinking,artifacts,
                                       tokens_in,tokens_out,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (mid, session_id, role, content,
              json.dumps(context, ensure_ascii=False) if context else None,
              json.dumps(thinking, ensure_ascii=False) if thinking else None,
              json.dumps(artifacts, ensure_ascii=False) if artifacts else None,
              tokens_in, tokens_out, now))
        self.conn.execute("""
            UPDATE chat_sessions SET msg_count = msg_count + 1, last_active = ?
            WHERE session_id = ?
        """, (now, session_id))
        self.conn.commit()
        return mid

    def list_messages(self, session_id: str) -> list[dict]:
        cur = self.conn.execute(
            "SELECT * FROM chat_messages WHERE session_id=? ORDER BY created_at ASC", (session_id,))
        cols = [d[0] for d in cur.description]
        out = []
        for row in cur.fetchall():
            d = dict(zip(cols, row))
            for k in ("context","thinking","artifacts"):
                if d.get(k): d[k] = json.loads(d[k])
            out.append(d)
        return out

    def list_sessions(self, *, limit: int = 50, offset: int = 0) -> list[dict]:
        cur = self.conn.execute(
            "SELECT * FROM chat_sessions ORDER BY last_active DESC LIMIT ? OFFSET ?",
            (limit, offset))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def delete(self, session_id: str) -> None:
        self.conn.execute("DELETE FROM chat_messages WHERE session_id=?", (session_id,))
        self.conn.execute("DELETE FROM chat_sessions WHERE session_id=?", (session_id,))
        self.conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/agent/test_session_repo.py -x -q`
Expected: PASS(全部 8 个 test)

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/session_repo.py backend/tests/agent/test_session_repo.py
git commit -m "feat(agent): SessionRepo SQLite CRUD(upsert/get/append_message/list/delete)"
```

---

### Task 7: `services/agent/workspace.py` 目录管理

**Files:**
- Create: `backend/services/agent/workspace.py`
- Test: `backend/tests/agent/test_workspace.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agent/test_workspace.py
import json
from pathlib import Path
import pytest
from backend.services.agent.workspace import Workspace
from backend.services.agent.symbol import StockRef

@pytest.fixture
def ws(tmp_path) -> Workspace:
    return Workspace(root=tmp_path / "agent_runs")

def test_resolve_dir(ws):
    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    d = ws.resolve_dir(ref)
    assert d.name == "002594.SZ_比亚迪"
    assert d.parent == ws.root

def test_ensure_creates_dir(ws):
    ref = StockRef(code="00700.HK", name="腾讯控股", market="HK")
    d = ws.ensure(ref)
    assert d.is_dir()

def test_meta_roundtrip(ws):
    ref = StockRef(code="AAPL", name="Apple Inc", market="US")
    d = ws.ensure(ref)
    meta = {"stock_code":"AAPL","company":"Apple Inc","phases":{}}
    ws.write_meta(d, meta)
    loaded = ws.read_meta(d)
    assert loaded == meta

def test_phase_status_helpers(ws):
    ref = StockRef(code="600519.SH", name="贵州茅台", market="A")
    d = ws.ensure(ref)
    ws.mark_phase(d, "phase1_data_pack", status="done", duration=1.8)
    meta = ws.read_meta(d)
    assert meta["phases"]["phase1_data_pack"] == {"status":"done","duration":1.8}
    assert ws.phase_status(d, "phase1_data_pack") == "done"
    assert ws.phase_status(d, "phase3_quantitative") is None

def test_artifact_url_path(ws):
    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    d = ws.ensure(ref)
    p = d / "比亚迪_002594.SZ_分析报告.md"
    p.write_text("# r", encoding="utf-8")
    rel = ws.relpath_for_artifact(d, p)
    assert rel == "002594.SZ_比亚迪/比亚迪_002594.SZ_分析报告.md"

def test_sanitize_strips_unsafe_chars(ws):
    ref = StockRef(code="AAPL", name="Apple/Inc:", market="US")
    d = ws.resolve_dir(ref)
    assert "/" not in d.name and ":" not in d.name
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/agent/test_workspace.py -x -q`
Expected: FAIL — `Workspace` 不存在

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/agent/workspace.py
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Optional
from backend.services.agent.symbol import StockRef

_UNSAFE = re.compile(r"[\\/:*?\"<>|]")

class Workspace:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _safe(self, s: str) -> str:
        return _UNSAFE.sub("_", s).strip() or "_"

    def resolve_dir(self, ref: StockRef) -> Path:
        return self.root / f"{self._safe(ref.code)}_{self._safe(ref.name)}"

    def ensure(self, ref: StockRef) -> Path:
        d = self.resolve_dir(ref)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def read_meta(self, d: Path) -> dict:
        f = d / "_meta.json"
        if not f.exists(): return {}
        return json.loads(f.read_text(encoding="utf-8"))

    def write_meta(self, d: Path, meta: dict) -> None:
        tmp = d / "_meta.json.tmp"
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(d / "_meta.json")

    def mark_phase(self, d: Path, phase: str, *, status: str,
                   duration: Optional[float] = None, reason: Optional[str] = None) -> None:
        meta = self.read_meta(d)
        meta.setdefault("phases", {})
        entry = {"status": status}
        if duration is not None: entry["duration"] = duration
        if reason is not None: entry["reason"] = reason
        meta["phases"][phase] = entry
        self.write_meta(d, meta)

    def phase_status(self, d: Path, phase: str) -> Optional[str]:
        return self.read_meta(d).get("phases", {}).get(phase, {}).get("status")

    def relpath_for_artifact(self, d: Path, artifact: Path) -> str:
        return f"{d.name}/{artifact.name}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/agent/test_workspace.py -x -q`
Expected: PASS(6 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/workspace.py backend/tests/agent/test_workspace.py
git commit -m "feat(agent): Workspace 目录管理 + _meta.json 原子读写"
```

---

### Task 8: `services/system_config/store.py` yaml 原子读写

**Files:**
- Create: `backend/services/system_config/__init__.py`
- Create: `backend/services/system_config/store.py`
- Create: `backend/tests/system_config/__init__.py`
- Create: `backend/tests/system_config/test_store.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/system_config/__init__.py
# 空

# backend/tests/system_config/test_store.py
from pathlib import Path
import pytest
from backend.services.system_config.store import ConfigStore

def test_load_missing_file_returns_empty(tmp_path):
    s = ConfigStore(tmp_path / "cfg.yaml")
    assert s.load() == {}

def test_save_and_load_roundtrip(tmp_path):
    s = ConfigStore(tmp_path / "cfg.yaml")
    s.save({"LLM_DEEPSEEK_API_KEY": "sk-x", "LLM_DEFAULT_CHANNEL": "DEEPSEEK"})
    assert s.load() == {"LLM_DEEPSEEK_API_KEY": "sk-x", "LLM_DEFAULT_CHANNEL": "DEEPSEEK"}

def test_set_one(tmp_path):
    s = ConfigStore(tmp_path / "cfg.yaml")
    s.set("LLM_DEFAULT_CHANNEL", "DEEPSEEK")
    assert s.get("LLM_DEFAULT_CHANNEL") == "DEEPSEEK"

def test_delete_keys(tmp_path):
    s = ConfigStore(tmp_path / "cfg.yaml")
    s.save({"A": "1", "B": "2"})
    s.delete(["A"])
    assert s.load() == {"B": "2"}

def test_atomic_write_no_partial_file(tmp_path):
    """模拟写入中断不应留下半个文件"""
    p = tmp_path / "cfg.yaml"
    s = ConfigStore(p)
    s.save({"K": "v"})
    # 验证没有 .tmp 残留
    assert not (tmp_path / "cfg.yaml.tmp").exists()
    assert p.read_text(encoding="utf-8").strip() != ""

def test_values_coerced_to_str(tmp_path):
    s = ConfigStore(tmp_path / "cfg.yaml")
    s.save({"A": 1, "B": True, "C": "hi"})
    assert s.load() == {"A": "1", "B": "True", "C": "hi"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/system_config/test_store.py -x -q`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/system_config/__init__.py
# 空
```

```python
# backend/services/system_config/store.py
from __future__ import annotations
from pathlib import Path
from typing import Iterable
import yaml

class ConfigStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        return {str(k): str(v) for k, v in data.items()}

    def save(self, kv: dict) -> None:
        normalized = {str(k): str(v) for k, v in kv.items()}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(yaml.safe_dump(normalized, allow_unicode=True, sort_keys=True),
                       encoding="utf-8")
        tmp.replace(self.path)

    def get(self, key: str, default: str = "") -> str:
        return self.load().get(key, default)

    def set(self, key: str, value) -> None:
        kv = self.load()
        kv[key] = str(value)
        self.save(kv)

    def delete(self, keys: Iterable[str]) -> None:
        kv = self.load()
        for k in keys:
            kv.pop(k, None)
        self.save(kv)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/system_config/test_store.py -x -q`
Expected: PASS(6 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/system_config/__init__.py backend/services/system_config/store.py \
        backend/tests/system_config/__init__.py backend/tests/system_config/test_store.py
git commit -m "feat(system_config): ConfigStore yaml 原子读写"
```

---

### Task 9: `services/system_config/schema.py` 扁平键校验

**Files:**
- Create: `backend/services/system_config/schema.py`
- Create: `backend/tests/system_config/test_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/system_config/test_schema.py
import pytest
from backend.services.system_config.schema import (
    parse_llm_key, validate_kv, KEY_PATTERN_LLM, ConfigError,
)

def test_parse_llm_key_valid():
    assert parse_llm_key("LLM_DEEPSEEK_API_KEY") == ("DEEPSEEK", "API_KEY")
    assert parse_llm_key("LLM_GPT_4O_MAX_TOKENS") == ("GPT_4O", "MAX_TOKENS")

def test_parse_llm_key_invalid_returns_none():
    assert parse_llm_key("FOO") is None
    assert parse_llm_key("LLM_") is None

def test_validate_kv_accepts_known_fields():
    kv = {
        "LLM_DEEPSEEK_PROVIDER": "deepseek",
        "LLM_DEEPSEEK_BASE_URL": "https://api.deepseek.com",
        "LLM_DEEPSEEK_API_KEY": "sk-x",
        "LLM_DEEPSEEK_MODEL": "deepseek-chat",
        "LLM_DEFAULT_CHANNEL": "DEEPSEEK",
    }
    validate_kv(kv)  # no raise

def test_validate_kv_rejects_unknown_provider():
    with pytest.raises(ConfigError):
        validate_kv({"LLM_X_PROVIDER": "weird-vendor"})

def test_validate_kv_default_channel_must_exist():
    with pytest.raises(ConfigError):
        validate_kv({"LLM_DEFAULT_CHANNEL": "NONEXIST"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/system_config/test_schema.py -x -q`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/system_config/schema.py
from __future__ import annotations
import re
from typing import Optional

class ConfigError(ValueError):
    pass

KEY_PATTERN_LLM = re.compile(r"^LLM_([A-Z][A-Z0-9_]*?)_(PROVIDER|BASE_URL|API_KEY|MODEL|MAX_TOKENS|TEMPERATURE|TIMEOUT)$")
ALLOWED_PROVIDERS = {"openai", "anthropic", "openrouter", "deepseek"}
ROUTE_KEYS = {"LLM_DEFAULT_CHANNEL", "LLM_ROUTE_PHASE3_QUANT",
              "LLM_ROUTE_PHASE3_VALUATION", "LLM_ROUTE_QA_FOLLOWUP", "LLM_ROUTE_CHITCHAT"}

def parse_llm_key(key: str) -> Optional[tuple[str, str]]:
    """LLM_DEEPSEEK_API_KEY -> (DEEPSEEK, API_KEY)"""
    if not key.startswith("LLM_") or key in ROUTE_KEYS:
        return None
    m = KEY_PATTERN_LLM.match(key)
    return (m.group(1), m.group(2)) if m else None

def list_channels(kv: dict) -> set[str]:
    names: set[str] = set()
    for k in kv:
        if parsed := parse_llm_key(k):
            names.add(parsed[0])
    return names

def validate_kv(kv: dict) -> None:
    channels = list_channels(kv)
    for k, v in kv.items():
        if not k.startswith("LLM_"):
            continue
        if k in ROUTE_KEYS:
            if v and v not in channels:
                raise ConfigError(f"{k}={v} 指向的 channel 不存在;已知 channels={channels}")
            continue
        parsed = parse_llm_key(k)
        if not parsed:
            raise ConfigError(f"未知的 LLM 配置键:{k}")
        _, field = parsed
        if field == "PROVIDER" and v not in ALLOWED_PROVIDERS:
            raise ConfigError(f"{k} provider 必须是 {ALLOWED_PROVIDERS},得到 {v!r}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/system_config/test_schema.py -x -q`
Expected: PASS(5 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/system_config/schema.py backend/tests/system_config/test_schema.py
git commit -m "feat(system_config): 扁平键命名规则 + provider 白名单校验"
```

---

### Task 10: `services/system_config/channels.py` KV ↔ ChannelConfig 重组

**Files:**
- Create: `backend/services/system_config/channels.py`
- Create: `backend/tests/system_config/test_channels.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/system_config/test_channels.py
from backend.services.system_config.channels import (
    ChannelConfig, reconstruct_channels, flatten_channels, get_channel,
)

def test_reconstruct_channels_basic():
    kv = {
        "LLM_DEEPSEEK_PROVIDER": "deepseek",
        "LLM_DEEPSEEK_BASE_URL": "https://api.deepseek.com",
        "LLM_DEEPSEEK_API_KEY": "sk-x",
        "LLM_DEEPSEEK_MODEL": "deepseek-chat",
        "LLM_DEEPSEEK_MAX_TOKENS": "8192",
        "LLM_DEEPSEEK_TEMPERATURE": "0.3",
        "LLM_DEEPSEEK_TIMEOUT": "120",
    }
    chans = reconstruct_channels(kv)
    assert len(chans) == 1
    c = chans[0]
    assert c.name == "DEEPSEEK"
    assert c.provider == "deepseek"
    assert c.api_key == "sk-x"
    assert c.max_tokens == 8192
    assert c.temperature == 0.3
    assert c.timeout == 120

def test_reconstruct_multiple():
    kv = {
        "LLM_A_PROVIDER": "openai", "LLM_A_API_KEY": "k1", "LLM_A_MODEL": "gpt-4o", "LLM_A_BASE_URL": "https://x",
        "LLM_B_PROVIDER": "anthropic", "LLM_B_API_KEY": "k2", "LLM_B_MODEL": "claude", "LLM_B_BASE_URL": "https://y",
    }
    chans = reconstruct_channels(kv)
    names = {c.name for c in chans}
    assert names == {"A", "B"}

def test_flatten_roundtrip():
    c = ChannelConfig(name="X", provider="openai", base_url="https://x",
                      api_key="k", model="gpt-4", max_tokens=4096, temperature=0.5, timeout=60)
    kv = flatten_channels([c])
    chans2 = reconstruct_channels(kv)
    assert chans2[0] == c

def test_get_channel_by_name():
    kv = {"LLM_X_PROVIDER":"openai","LLM_X_API_KEY":"k","LLM_X_MODEL":"m","LLM_X_BASE_URL":"u"}
    c = get_channel(kv, "X")
    assert c.name == "X"

def test_get_channel_missing_returns_none():
    assert get_channel({}, "X") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/system_config/test_channels.py -x -q`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/system_config/channels.py
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Optional
from backend.services.system_config.schema import parse_llm_key, list_channels

@dataclass(frozen=True)
class ChannelConfig:
    name: str
    provider: str
    base_url: str
    api_key: str
    model: str
    max_tokens: int = 8192
    temperature: float = 0.3
    timeout: int = 120

_FIELD_MAP = {
    "PROVIDER": ("provider", str),
    "BASE_URL": ("base_url", str),
    "API_KEY":  ("api_key",  str),
    "MODEL":    ("model",    str),
    "MAX_TOKENS": ("max_tokens", int),
    "TEMPERATURE":("temperature",float),
    "TIMEOUT":   ("timeout", int),
}

def reconstruct_channels(kv: dict) -> list[ChannelConfig]:
    buckets: dict[str, dict] = {}
    for k, v in kv.items():
        parsed = parse_llm_key(k)
        if not parsed:
            continue
        name, field = parsed
        py_field, conv = _FIELD_MAP[field]
        try:
            buckets.setdefault(name, {})[py_field] = conv(v) if v != "" else None
        except (ValueError, TypeError):
            continue
    out = []
    for name, fields in buckets.items():
        try:
            out.append(ChannelConfig(
                name=name,
                provider=fields.get("provider", ""),
                base_url=fields.get("base_url", ""),
                api_key=fields.get("api_key", ""),
                model=fields.get("model", ""),
                max_tokens=fields.get("max_tokens") or 8192,
                temperature=fields.get("temperature") if fields.get("temperature") is not None else 0.3,
                timeout=fields.get("timeout") or 120,
            ))
        except Exception:
            continue
    return sorted(out, key=lambda c: c.name)

def flatten_channels(channels: list[ChannelConfig]) -> dict[str, str]:
    kv: dict[str, str] = {}
    for c in channels:
        kv[f"LLM_{c.name}_PROVIDER"]    = c.provider
        kv[f"LLM_{c.name}_BASE_URL"]    = c.base_url
        kv[f"LLM_{c.name}_API_KEY"]     = c.api_key
        kv[f"LLM_{c.name}_MODEL"]       = c.model
        kv[f"LLM_{c.name}_MAX_TOKENS"]  = str(c.max_tokens)
        kv[f"LLM_{c.name}_TEMPERATURE"] = str(c.temperature)
        kv[f"LLM_{c.name}_TIMEOUT"]     = str(c.timeout)
    return kv

def get_channel(kv: dict, name: str) -> Optional[ChannelConfig]:
    for c in reconstruct_channels(kv):
        if c.name == name:
            return c
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/system_config/test_channels.py -x -q`
Expected: PASS(5 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/system_config/channels.py backend/tests/system_config/test_channels.py
git commit -m "feat(system_config): KV ↔ ChannelConfig 重组(reconstruct/flatten/get)"
```

---

### Task 11: `routers/system_config.py` 扁平 KV CRUD

**Files:**
- Create: `backend/routers/system_config.py`
- Create: `backend/tests/system_config/test_routes.py`
- Modify: `backend/main.py`(注册路由 + lifespan 准备 yaml 路径)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/system_config/test_routes.py
from fastapi.testclient import TestClient
import importlib

def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("DSA_CONFIG_PATH", str(tmp_path / "cfg.yaml"))
    import backend.main as m
    importlib.reload(m)
    return TestClient(m.app)

def test_get_returns_empty_initially(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/system/config")
    assert r.status_code == 200
    assert r.json() == {"items": []}

def test_put_then_get(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.put("/api/v1/system/config", json={"items": [
        {"key":"LLM_DEEPSEEK_PROVIDER","value":"deepseek"},
        {"key":"LLM_DEEPSEEK_API_KEY","value":"sk-x"},
        {"key":"LLM_DEEPSEEK_MODEL","value":"deepseek-chat"},
        {"key":"LLM_DEEPSEEK_BASE_URL","value":"https://api.deepseek.com"},
        {"key":"LLM_DEFAULT_CHANNEL","value":"DEEPSEEK"},
    ]})
    assert r.status_code == 200
    r = c.get("/api/v1/system/config")
    items = {it["key"]: it["value"] for it in r.json()["items"]}
    assert items["LLM_DEEPSEEK_API_KEY"] == "sk-x"
    assert items["LLM_DEFAULT_CHANNEL"] == "DEEPSEEK"

def test_put_rejects_invalid_default_channel(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.put("/api/v1/system/config", json={"items":[
        {"key":"LLM_DEFAULT_CHANNEL","value":"NONEXIST"}
    ]})
    assert r.status_code == 400
    assert "channel" in r.json()["detail"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/system_config/test_routes.py -x -q`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# backend/routers/system_config.py
from __future__ import annotations
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.services.system_config.store import ConfigStore
from backend.services.system_config.schema import validate_kv, ConfigError

router = APIRouter(prefix="/api/v1/system/config", tags=["system_config"])

def _store() -> ConfigStore:
    p = os.environ.get("DSA_CONFIG_PATH", "data/system_config.yaml")
    return ConfigStore(Path(p))

class Item(BaseModel):
    key: str
    value: str

class ItemList(BaseModel):
    items: list[Item]

@router.get("", response_model=ItemList)
def get_all():
    kv = _store().load()
    return {"items": [{"key": k, "value": v} for k, v in sorted(kv.items())]}

@router.put("", response_model=ItemList)
def put_all(payload: ItemList):
    new_kv = {it.key: it.value for it in payload.items}
    try:
        validate_kv(new_kv)
    except ConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _store().save(new_kv)
    return {"items": [{"key": k, "value": v} for k, v in sorted(new_kv.items())]}

@router.delete("/{key}")
def delete_one(key: str):
    s = _store()
    s.delete([key])
    return {"ok": True}
```

修改 `backend/main.py` 注册段加:

```python
from backend.routers import system_config
app.include_router(system_config.router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/system_config/test_routes.py -x -q`
Expected: PASS(3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/routers/system_config.py backend/main.py backend/tests/system_config/test_routes.py
git commit -m "feat(system_config): /api/v1/system/config GET/PUT/DELETE 扁平 KV CRUD"
```

---

### Task 12: `routers/agent.py` 路由骨架(skills + sessions CRUD,无 stream)

**Files:**
- Create: `backend/routers/agent.py`
- Create: `backend/tests/agent/test_routes_agent.py`
- Modify: `backend/main.py`(注册)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agent/test_routes_agent.py
from fastapi.testclient import TestClient
import importlib, os

def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("DSA_PORTFOLIO_DB", str(tmp_path / "p.db"))
    import backend.main as m
    importlib.reload(m)
    return TestClient(m.app)

def test_skills_returns_empty_array(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/agent/skills")
    assert r.status_code == 200
    assert r.json() == {"skills": []}

def test_sessions_empty_initially(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/agent/sessions")
    assert r.status_code == 200
    assert r.json() == {"items": []}

def test_session_upsert_via_get(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/agent/sessions/sid-1")
    assert r.status_code == 200
    assert r.json()["session_id"] == "sid-1"
    r = c.get("/api/v1/agent/sessions/sid-1/messages")
    assert r.status_code == 200
    assert r.json() == {"items": []}

def test_session_delete(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.get("/api/v1/agent/sessions/sid-1")
    r = c.delete("/api/v1/agent/sessions/sid-1")
    assert r.status_code == 200
    r = c.get("/api/v1/agent/sessions")
    assert r.json() == {"items": []}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/agent/test_routes_agent.py -x -q`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# backend/routers/agent.py
from __future__ import annotations
import os
import sqlite3
from fastapi import APIRouter, Depends
from backend.services.agent.session_repo import SessionRepo
from backend.services.db_schema import ensure_schema

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])

def _conn():
    p = os.environ.get("DSA_PORTFOLIO_DB", "data/portfolio.db")
    c = sqlite3.connect(p, check_same_thread=False)
    ensure_schema(c)
    return c

def _repo() -> SessionRepo:
    return SessionRepo(_conn())

@router.get("/skills")
def get_skills():
    return {"skills": []}  # 期 1 无技能,留前端兼容

@router.get("/sessions")
def list_sessions(limit: int = 50):
    return {"items": _repo().list_sessions(limit=limit)}

@router.get("/sessions/{sid}")
def get_session(sid: str):
    repo = _repo()
    repo.upsert(sid)  # lazy create
    return repo.get(sid)

@router.delete("/sessions/{sid}")
def delete_session(sid: str):
    _repo().delete(sid)
    return {"ok": True}

@router.get("/sessions/{sid}/messages")
def list_messages(sid: str):
    return {"items": _repo().list_messages(sid)}
```

修改 `backend/main.py` 加:

```python
from backend.routers import agent as agent_router
app.include_router(agent_router.router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/agent/test_routes_agent.py -x -q`
Expected: PASS(4 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/routers/agent.py backend/main.py backend/tests/agent/test_routes_agent.py
git commit -m "feat(agent): /api/v1/agent/* 路由骨架(skills + sessions CRUD)"
```

---

## Phase B — LLM 客户端 + 闲聊/追问 + /chat/stream(Tasks 13-19)

### Task 13: `LLMClient` 抽象基类

**Files:**
- Modify: `backend/services/system_config/llm_client.py`(本 task 创建抽象基类与异常)
- Test:(本 task 仅创建文件骨架,真正测试在 Task 14/15)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/system_config/test_llm_client_openai.py(本 task 先建占位测试)
from backend.services.system_config.llm_client import LLMClient, LLMError, Message

def test_message_dataclass():
    m = Message(role="user", content="hi")
    assert m.role == "user"
    assert m.content == "hi"

def test_llm_error_is_exception():
    assert issubclass(LLMError, Exception)

def test_client_is_abstract():
    import inspect
    assert inspect.isabstract(LLMClient)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/system_config/test_llm_client_openai.py -x -q`
Expected: FAIL — 模块不存在

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/system_config/llm_client.py
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Optional

class LLMError(Exception):
    """统一的 LLM 调用异常(网络/4xx/5xx/超时/解析失败)"""
    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message

@dataclass(frozen=True)
class Message:
    role: str   # "user" | "assistant" | "system"
    content: str

@dataclass
class CompletionResult:
    text: str
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None

class LLMClient(ABC):
    @abstractmethod
    async def complete(self, messages: list[Message], *, max_tokens: int | None = None,
                       temperature: float | None = None, timeout: float | None = None) -> CompletionResult: ...

    @abstractmethod
    async def stream(self, messages: list[Message], *, max_tokens: int | None = None,
                     temperature: float | None = None, timeout: float | None = None) -> AsyncIterator[str]: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/system_config/test_llm_client_openai.py -x -q`
Expected: PASS(3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/system_config/llm_client.py backend/tests/system_config/test_llm_client_openai.py
git commit -m "feat(system_config): LLMClient 抽象基类 + Message/LLMError"
```

---

### Task 14: `OpenAICompatibleClient`(OpenAI/DeepSeek/OpenRouter 共用)

**Files:**
- Modify: `backend/services/system_config/llm_client.py`
- Modify: `backend/tests/system_config/test_llm_client_openai.py`

- [ ] **Step 1: Write the failing test**

在 `backend/tests/system_config/test_llm_client_openai.py` 末尾追加:

```python
import json
import pytest
import httpx
from backend.services.system_config.channels import ChannelConfig
from backend.services.system_config.llm_client import (
    OpenAICompatibleClient, Message, LLMError,
)

def _ch(provider="openai") -> ChannelConfig:
    return ChannelConfig(name="X", provider=provider, base_url="https://api.x.com/v1",
                         api_key="sk-test", model="gpt-4o-mini",
                         max_tokens=1024, temperature=0.3, timeout=30)

@pytest.mark.asyncio
async def test_complete_returns_text():
    body = {
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 1}
    }
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=body))
    client = OpenAICompatibleClient(_ch(), transport=transport)
    r = await client.complete([Message("user", "hi")])
    assert r.text == "hello"
    assert r.tokens_in == 5
    assert r.tokens_out == 1

@pytest.mark.asyncio
async def test_complete_4xx_raises_llm_error():
    transport = httpx.MockTransport(lambda req: httpx.Response(401, json={"error": "bad key"}))
    client = OpenAICompatibleClient(_ch(), transport=transport)
    with pytest.raises(LLMError) as ei:
        await client.complete([Message("user", "hi")])
    assert "401" in str(ei.value) or ei.value.code == "HTTP_401"

@pytest.mark.asyncio
async def test_stream_yields_deltas():
    chunks = [
        b'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n',
        b'data: [DONE]\n\n',
    ]
    async def handler(req):
        return httpx.Response(200, content=b"".join(chunks),
                              headers={"content-type": "text/event-stream"})
    transport = httpx.MockTransport(handler)
    client = OpenAICompatibleClient(_ch(), transport=transport)
    out = []
    async for piece in client.stream([Message("user", "hi")]):
        out.append(piece)
    assert "".join(out) == "hello"

@pytest.mark.asyncio
async def test_request_includes_authorization_header():
    captured = {}
    def handler(req):
        captured["auth"] = req.headers.get("authorization")
        captured["model"] = json.loads(req.content)["model"]
        return httpx.Response(200, json={"choices":[{"message":{"content":""}}],"usage":{}})
    client = OpenAICompatibleClient(_ch(), transport=httpx.MockTransport(handler))
    await client.complete([Message("user", "hi")])
    assert captured["auth"] == "Bearer sk-test"
    assert captured["model"] == "gpt-4o-mini"
```

确保安装 `pytest-asyncio`(若 `requirements.txt` 未含,顺手追加 `pytest-asyncio>=0.23`)。`backend/tests/conftest.py` 或本测试文件需配 `pytest_plugins = ["pytest_asyncio"]` 或在 pytest.ini 添加 `asyncio_mode = auto`。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/system_config/test_llm_client_openai.py -x -q`
Expected: FAIL — `OpenAICompatibleClient` 不存在

- [ ] **Step 3: Write minimal implementation**

在 `backend/services/system_config/llm_client.py` 追加:

```python
import json
from typing import AsyncIterator, Optional
import httpx
from backend.services.system_config.channels import ChannelConfig

class OpenAICompatibleClient(LLMClient):
    """覆盖 OpenAI / DeepSeek / OpenRouter(POST /chat/completions)"""
    def __init__(self, ch: ChannelConfig, *, transport: Optional[httpx.AsyncBaseTransport] = None):
        self.ch = ch
        self._transport = transport

    def _payload(self, messages: list[Message], max_tokens, temperature, stream: bool) -> dict:
        return {
            "model": self.ch.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_tokens or self.ch.max_tokens,
            "temperature": temperature if temperature is not None else self.ch.temperature,
            "stream": stream,
        }

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.ch.api_key}", "Content-Type": "application/json"}

    async def complete(self, messages, *, max_tokens=None, temperature=None, timeout=None) -> CompletionResult:
        url = self.ch.base_url.rstrip("/") + "/chat/completions"
        async with httpx.AsyncClient(transport=self._transport,
                                     timeout=timeout or self.ch.timeout) as cli:
            try:
                r = await cli.post(url, headers=self._headers(),
                                   json=self._payload(messages, max_tokens, temperature, stream=False))
            except httpx.HTTPError as e:
                raise LLMError("NETWORK", str(e))
        if r.status_code >= 400:
            raise LLMError(f"HTTP_{r.status_code}", r.text[:500])
        try:
            data = r.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
            return CompletionResult(text=text, tokens_in=usage.get("prompt_tokens"),
                                    tokens_out=usage.get("completion_tokens"))
        except (KeyError, ValueError) as e:
            raise LLMError("PARSE", f"unexpected response: {e}")

    async def stream(self, messages, *, max_tokens=None, temperature=None, timeout=None) -> AsyncIterator[str]:
        url = self.ch.base_url.rstrip("/") + "/chat/completions"
        async with httpx.AsyncClient(transport=self._transport,
                                     timeout=timeout or self.ch.timeout) as cli:
            async with cli.stream("POST", url, headers=self._headers(),
                                   json=self._payload(messages, max_tokens, temperature, stream=True)) as r:
                if r.status_code >= 400:
                    body = await r.aread()
                    raise LLMError(f"HTTP_{r.status_code}", body.decode("utf-8", "ignore")[:500])
                async for line in r.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        return
                    try:
                        evt = json.loads(payload)
                        delta = evt["choices"][0].get("delta", {}).get("content")
                        if delta:
                            yield delta
                    except (KeyError, ValueError):
                        continue
```

如需配 `asyncio_mode = auto`,在 `pytest.ini` 或 `pyproject.toml` 增加。若项目已有 conftest 注入,直接用。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/system_config/test_llm_client_openai.py -x -q`
Expected: PASS(7 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/system_config/llm_client.py backend/tests/system_config/test_llm_client_openai.py
git commit -m "feat(llm): OpenAICompatibleClient(OpenAI/DeepSeek/OpenRouter 共用)"
```

---

### Task 15: `AnthropicClient`(messages API)

**Files:**
- Modify: `backend/services/system_config/llm_client.py`
- Create: `backend/tests/system_config/test_llm_client_anthropic.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/system_config/test_llm_client_anthropic.py
import json
import pytest
import httpx
from backend.services.system_config.channels import ChannelConfig
from backend.services.system_config.llm_client import (
    AnthropicClient, Message, LLMError,
)

def _ch() -> ChannelConfig:
    return ChannelConfig(name="S", provider="anthropic",
                         base_url="https://api.anthropic.com",
                         api_key="sk-ant-x", model="claude-3-5-sonnet-20241022",
                         max_tokens=1024, temperature=0.3, timeout=30)

@pytest.mark.asyncio
async def test_complete_basic():
    body = {
        "content": [{"type": "text", "text": "hello"}],
        "usage": {"input_tokens": 5, "output_tokens": 1},
    }
    captured = {}
    def handler(req):
        captured["x_api_key"] = req.headers.get("x-api-key")
        captured["anthropic_version"] = req.headers.get("anthropic-version")
        captured["body"] = json.loads(req.content)
        return httpx.Response(200, json=body)
    client = AnthropicClient(_ch(), transport=httpx.MockTransport(handler))
    r = await client.complete([Message("user", "hi")])
    assert r.text == "hello"
    assert r.tokens_in == 5 and r.tokens_out == 1
    assert captured["x_api_key"] == "sk-ant-x"
    assert captured["anthropic_version"]
    assert captured["body"]["model"] == "claude-3-5-sonnet-20241022"

@pytest.mark.asyncio
async def test_system_message_extracted():
    captured = {}
    def handler(req):
        captured["body"] = json.loads(req.content)
        return httpx.Response(200, json={"content":[{"type":"text","text":"ok"}],"usage":{}})
    client = AnthropicClient(_ch(), transport=httpx.MockTransport(handler))
    await client.complete([Message("system", "be brief"), Message("user", "hi")])
    assert captured["body"]["system"] == "be brief"
    assert captured["body"]["messages"] == [{"role":"user","content":"hi"}]

@pytest.mark.asyncio
async def test_stream_yields_text_deltas():
    chunks = [
        b'event: content_block_delta\n',
        b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"hel"}}\n\n',
        b'event: content_block_delta\n',
        b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"lo"}}\n\n',
        b'event: message_stop\ndata: {"type":"message_stop"}\n\n',
    ]
    def handler(req):
        return httpx.Response(200, content=b"".join(chunks),
                              headers={"content-type":"text/event-stream"})
    client = AnthropicClient(_ch(), transport=httpx.MockTransport(handler))
    out = []
    async for piece in client.stream([Message("user","hi")]):
        out.append(piece)
    assert "".join(out) == "hello"

@pytest.mark.asyncio
async def test_4xx_raises():
    client = AnthropicClient(_ch(), transport=httpx.MockTransport(
        lambda r: httpx.Response(401, json={"error":"bad key"})))
    with pytest.raises(LLMError):
        await client.complete([Message("user","hi")])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/system_config/test_llm_client_anthropic.py -x -q`
Expected: FAIL — `AnthropicClient` 不存在

- [ ] **Step 3: Write minimal implementation**

在 `backend/services/system_config/llm_client.py` 追加:

```python
class AnthropicClient(LLMClient):
    ANTHROPIC_VERSION = "2023-06-01"

    def __init__(self, ch: ChannelConfig, *, transport: Optional[httpx.AsyncBaseTransport] = None):
        self.ch = ch
        self._transport = transport

    def _split_system(self, messages: list[Message]) -> tuple[Optional[str], list[dict]]:
        system, msgs = None, []
        for m in messages:
            if m.role == "system":
                system = (system + "\n" if system else "") + m.content
            else:
                msgs.append({"role": m.role, "content": m.content})
        return system, msgs

    def _headers(self) -> dict:
        return {
            "x-api-key": self.ch.api_key,
            "anthropic-version": self.ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }

    def _payload(self, messages, max_tokens, temperature, stream: bool) -> dict:
        system, msgs = self._split_system(messages)
        body = {
            "model": self.ch.model,
            "messages": msgs,
            "max_tokens": max_tokens or self.ch.max_tokens,
            "temperature": temperature if temperature is not None else self.ch.temperature,
            "stream": stream,
        }
        if system:
            body["system"] = system
        return body

    async def complete(self, messages, *, max_tokens=None, temperature=None, timeout=None) -> CompletionResult:
        url = self.ch.base_url.rstrip("/") + "/v1/messages"
        async with httpx.AsyncClient(transport=self._transport,
                                     timeout=timeout or self.ch.timeout) as cli:
            try:
                r = await cli.post(url, headers=self._headers(),
                                   json=self._payload(messages, max_tokens, temperature, False))
            except httpx.HTTPError as e:
                raise LLMError("NETWORK", str(e))
        if r.status_code >= 400:
            raise LLMError(f"HTTP_{r.status_code}", r.text[:500])
        try:
            data = r.json()
            text = "".join(blk["text"] for blk in data["content"] if blk.get("type") == "text")
            usage = data.get("usage") or {}
            return CompletionResult(text=text, tokens_in=usage.get("input_tokens"),
                                    tokens_out=usage.get("output_tokens"))
        except (KeyError, ValueError) as e:
            raise LLMError("PARSE", str(e))

    async def stream(self, messages, *, max_tokens=None, temperature=None, timeout=None) -> AsyncIterator[str]:
        url = self.ch.base_url.rstrip("/") + "/v1/messages"
        async with httpx.AsyncClient(transport=self._transport,
                                     timeout=timeout or self.ch.timeout) as cli:
            async with cli.stream("POST", url, headers=self._headers(),
                                   json=self._payload(messages, max_tokens, temperature, True)) as r:
                if r.status_code >= 400:
                    body = await r.aread()
                    raise LLMError(f"HTTP_{r.status_code}", body.decode("utf-8","ignore")[:500])
                async for line in r.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    payload = line[6:].strip()
                    try:
                        evt = json.loads(payload)
                    except ValueError:
                        continue
                    if evt.get("type") == "content_block_delta":
                        delta = evt.get("delta", {})
                        if delta.get("type") == "text_delta":
                            yield delta.get("text", "")
```

`build_client(ch: ChannelConfig) -> LLMClient` 工厂函数追加:

```python
def build_client(ch: ChannelConfig, *, transport: Optional[httpx.AsyncBaseTransport] = None) -> LLMClient:
    if ch.provider in ("openai", "deepseek", "openrouter"):
        return OpenAICompatibleClient(ch, transport=transport)
    if ch.provider == "anthropic":
        return AnthropicClient(ch, transport=transport)
    raise LLMError("CONFIG", f"unknown provider: {ch.provider}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/system_config/test_llm_client_anthropic.py -x -q`
Expected: PASS(4 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/system_config/llm_client.py backend/tests/system_config/test_llm_client_anthropic.py
git commit -m "feat(llm): AnthropicClient + build_client 工厂"
```

---

### Task 16: `services/agent/llm_routing.py` phase → channel 选择

**Files:**
- Create: `backend/services/agent/llm_routing.py`
- Create: `backend/tests/agent/test_llm_routing.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agent/test_llm_routing.py
import pytest
from backend.services.agent.llm_routing import resolve_channel_name, RoutingError

def test_phase_specific_route():
    kv = {"LLM_DEFAULT_CHANNEL":"DEEPSEEK", "LLM_ROUTE_PHASE3_QUANT":"SONNET"}
    assert resolve_channel_name(kv, "phase3_quantitative") == "SONNET"

def test_falls_back_to_default():
    kv = {"LLM_DEFAULT_CHANNEL":"DEEPSEEK"}
    assert resolve_channel_name(kv, "chitchat") == "DEEPSEEK"

def test_no_default_raises():
    with pytest.raises(RoutingError):
        resolve_channel_name({}, "chitchat")

def test_known_phases_have_route_keys():
    """phase 名 → ROUTE key 映射保证存在"""
    kv = {
        "LLM_DEFAULT_CHANNEL":"D",
        "LLM_ROUTE_PHASE3_QUANT":"S",
        "LLM_ROUTE_PHASE3_VALUATION":"S",
        "LLM_ROUTE_QA_FOLLOWUP":"D",
        "LLM_ROUTE_CHITCHAT":"D",
    }
    for ph in ["phase3_quantitative","phase3_valuation","qa_followup","chitchat"]:
        assert resolve_channel_name(kv, ph) in {"S","D"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/agent/test_llm_routing.py -x -q`
Expected: FAIL — module 不存在

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/agent/llm_routing.py
from __future__ import annotations

class RoutingError(ValueError):
    pass

PHASE_TO_ROUTE_KEY = {
    "phase3_quantitative": "LLM_ROUTE_PHASE3_QUANT",
    "phase3_valuation":    "LLM_ROUTE_PHASE3_VALUATION",
    "qa_followup":         "LLM_ROUTE_QA_FOLLOWUP",
    "chitchat":            "LLM_ROUTE_CHITCHAT",
}

def resolve_channel_name(kv: dict, phase: str) -> str:
    route_key = PHASE_TO_ROUTE_KEY.get(phase)
    if route_key and (val := kv.get(route_key)):
        return val
    if val := kv.get("LLM_DEFAULT_CHANNEL"):
        return val
    raise RoutingError(f"无法为 phase={phase!r} 选择 channel:LLM_DEFAULT_CHANNEL 未配置")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/agent/test_llm_routing.py -x -q`
Expected: PASS(4 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/llm_routing.py backend/tests/agent/test_llm_routing.py
git commit -m "feat(agent): llm_routing.resolve_channel_name(phase → channel)"
```

---

### Task 17: Coordinator `chitchat` 分支(单次 LLM 调用)

**Files:**
- Create: `backend/services/agent/coordinator.py`
- Create: `backend/tests/agent/test_coordinator_routing.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agent/test_coordinator_routing.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.services.agent.coordinator import Coordinator
from backend.services.agent.symbol import StockRef
from backend.services.system_config.llm_client import CompletionResult

@pytest.mark.asyncio
async def test_chitchat_emits_thinking_then_done(tmp_path):
    sent = []
    async def sse_send(ev): sent.append(ev)

    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(return_value=CompletionResult(text="你好!", tokens_in=3, tokens_out=2))

    repo = MagicMock()
    repo.get.return_value = {"session_id":"s1","output_dir":None,"status":"idle"}

    workspace = MagicMock()
    si = MagicMock(); si.get_name.return_value = None  # 无股票码识别

    coord = Coordinator(
        sse_send=sse_send, repo=repo, workspace=workspace,
        stock_index=si, llm_factory=lambda phase: fake_llm,
    )
    await coord.run(session_id="s1", message="你好", context=None)

    types = [e["type"] for e in sent]
    assert types[0] == "thinking"
    assert types[-1] == "done"
    assert sent[-1]["content"] == "你好!"
    fake_llm.complete.assert_awaited_once()

@pytest.mark.asyncio
async def test_chitchat_llm_error_emits_error_event(tmp_path):
    from backend.services.system_config.llm_client import LLMError
    sent = []
    async def sse_send(ev): sent.append(ev)

    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(side_effect=LLMError("HTTP_401","bad key"))

    repo = MagicMock()
    repo.get.return_value = {"session_id":"s1","output_dir":None,"status":"idle"}
    si = MagicMock(); si.get_name.return_value = None

    coord = Coordinator(sse_send=sse_send, repo=repo, workspace=MagicMock(),
                        stock_index=si, llm_factory=lambda p: fake_llm)
    await coord.run(session_id="s1", message="你好", context=None)
    types = [e["type"] for e in sent]
    assert "error" in types
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/agent/test_coordinator_routing.py -x -q`
Expected: FAIL — `Coordinator` 不存在

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/agent/coordinator.py
from __future__ import annotations
from pathlib import Path
from typing import Awaitable, Callable, Optional
from backend.services.agent import sse
from backend.services.agent.symbol import extract, StockRef
from backend.services.system_config.llm_client import LLMClient, Message, LLMError

SseSend = Callable[[dict], Awaitable[None]]

class Coordinator:
    """期 1 三分支:full_pipeline / qa_followup / chitchat"""

    def __init__(self, *, sse_send: SseSend, repo, workspace, stock_index,
                 llm_factory: Callable[[str], LLMClient]):
        self.sse_send = sse_send
        self.repo = repo
        self.workspace = workspace
        self.stock_index = stock_index
        self.llm_factory = llm_factory

    async def run(self, *, session_id: str, message: str, context: Optional[dict]) -> None:
        try:
            # 路由判断
            session = self.repo.get(session_id) or {}
            output_dir = session.get("output_dir")
            if output_dir and self._has_completed_report(Path(output_dir)):
                return await self._run_qa_followup(session_id, message, Path(output_dir))
            if ref := extract(message, context, stock_index=self.stock_index):
                return await self._run_full_pipeline(session_id, ref)
            return await self._run_chitchat(session_id, message)
        except LLMError as e:
            await self.sse_send(sse.error(e.code, e.message))
        except Exception as e:
            await self.sse_send(sse.error("INTERNAL", str(e)))

    def _has_completed_report(self, d: Path) -> bool:
        meta = self.workspace.read_meta(d)
        return meta.get("phases", {}).get("phase3_valuation", {}).get("status") == "done"

    async def _run_chitchat(self, session_id: str, message: str) -> None:
        await self.sse_send(sse.thinking("闲聊模式..."))
        client = self.llm_factory("chitchat")
        result = await client.complete([
            Message("system", "你是一名简洁友好的中文 AI 助手,回答问题并保持中立。"),
            Message("user", message),
        ])
        self.repo.append_message(session_id, role="assistant", content=result.text,
                                 tokens_in=result.tokens_in, tokens_out=result.tokens_out)
        await self.sse_send(sse.done(result.text, artifacts=[]))

    async def _run_qa_followup(self, session_id: str, message: str, output_dir: Path) -> None:
        # Task 23 实现细节
        raise NotImplementedError

    async def _run_full_pipeline(self, session_id: str, ref: StockRef) -> None:
        # Task 24 实现细节
        raise NotImplementedError
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/agent/test_coordinator_routing.py -x -q`
Expected: PASS(2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/coordinator.py backend/tests/agent/test_coordinator_routing.py
git commit -m "feat(agent): Coordinator chitchat 分支 + 路由判断 + 异常→error 事件"
```

---

### Task 18: `POST /chat/stream` SSE endpoint(接 Coordinator)

**Files:**
- Modify: `backend/routers/agent.py`
- Modify: `backend/tests/agent/test_routes_agent.py`

- [ ] **Step 1: Write the failing test**

在 `backend/tests/agent/test_routes_agent.py` 末尾追加:

```python
import json
from unittest.mock import patch, AsyncMock, MagicMock
from backend.services.system_config.llm_client import CompletionResult

def test_chat_stream_chitchat(tmp_path, monkeypatch):
    monkeypatch.setenv("DSA_PORTFOLIO_DB", str(tmp_path / "p.db"))
    monkeypatch.setenv("DSA_CONFIG_PATH", str(tmp_path / "cfg.yaml"))
    monkeypatch.setenv("DSA_AGENT_RUNS", str(tmp_path / "runs"))
    # 提前写一个有效 config
    import yaml
    (tmp_path / "cfg.yaml").write_text(yaml.safe_dump({
        "LLM_X_PROVIDER":"openai","LLM_X_BASE_URL":"https://x","LLM_X_API_KEY":"k",
        "LLM_X_MODEL":"m","LLM_DEFAULT_CHANNEL":"X",
    }), encoding="utf-8")
    import importlib, backend.main as m
    importlib.reload(m)
    from fastapi.testclient import TestClient

    fake = MagicMock()
    fake.complete = AsyncMock(return_value=CompletionResult(text="你好!", tokens_in=3, tokens_out=2))
    with patch("backend.routers.agent.build_client_for_phase", return_value=fake):
        c = TestClient(m.app)
        with c.stream("POST", "/api/v1/agent/chat/stream", json={
            "message":"你好","session_id":"s1","skills":[],"context":None
        }) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            events = []
            for line in r.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
    types = [e["type"] for e in events]
    assert types[0] == "thinking"
    assert types[-1] == "done"
    assert events[-1]["content"] == "你好!"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/agent/test_routes_agent.py -x -q`
Expected: FAIL — `/chat/stream` 路由不存在

- [ ] **Step 3: Write minimal implementation**

在 `backend/routers/agent.py` 追加:

```python
import asyncio
import os
from pathlib import Path
from fastapi import Body
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from backend.services.agent import sse
from backend.services.agent.coordinator import Coordinator
from backend.services.agent.workspace import Workspace
from backend.services.agent.llm_routing import resolve_channel_name
from backend.services.system_config.store import ConfigStore
from backend.services.system_config.channels import get_channel
from backend.services.system_config.llm_client import build_client
from backend.services.stock_index import get_stock_index  # 既有单例访问

class ChatStreamRequest(BaseModel):
    message: str
    session_id: str
    skills: list[str] = []
    context: dict | None = None

def _config_kv() -> dict:
    return ConfigStore(Path(os.environ.get("DSA_CONFIG_PATH","data/system_config.yaml"))).load()

def build_client_for_phase(phase: str):
    kv = _config_kv()
    name = resolve_channel_name(kv, phase)
    ch = get_channel(kv, name)
    if not ch:
        raise RuntimeError(f"channel {name} not configured")
    return build_client(ch)

def _workspace() -> Workspace:
    return Workspace(Path(os.environ.get("DSA_AGENT_RUNS","data/agent_runs")))

@router.post("/chat/stream")
async def chat_stream(payload: ChatStreamRequest = Body(...)):
    queue: asyncio.Queue = asyncio.Queue()

    async def sse_send(event: dict):
        await queue.put(sse.encode(event))

    repo = _repo()
    repo.upsert(payload.session_id)
    repo.append_message(payload.session_id, role="user", content=payload.message,
                        context=payload.context)

    coord = Coordinator(
        sse_send=sse_send, repo=repo, workspace=_workspace(),
        stock_index=get_stock_index(),
        llm_factory=build_client_for_phase,
    )

    async def runner():
        try:
            await coord.run(session_id=payload.session_id,
                            message=payload.message, context=payload.context)
        finally:
            await queue.put(None)  # sentinel

    async def gen():
        task = asyncio.create_task(runner())
        try:
            while True:
                chunk = await queue.get()
                if chunk is None: break
                yield chunk
        finally:
            task.cancel()

    return StreamingResponse(gen(), media_type="text/event-stream")
```

注:`get_stock_index()` 是 `services/stock_index.py` 已存在的访问方式;若实际函数名不同(如 `get_index()` / `_INDEX` 模块级变量)请按实际改。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/agent/test_routes_agent.py -x -q`
Expected: PASS(全部)

- [ ] **Step 5: Commit**

```bash
git add backend/routers/agent.py backend/tests/agent/test_routes_agent.py
git commit -m "feat(agent): POST /chat/stream SSE endpoint(chitchat 路径打通)"
```

---

### Task 19: Coordinator `qa_followup` 分支(已有报告时单次 LLM 答疑)

**Files:**
- Modify: `backend/services/agent/coordinator.py`
- Modify: `backend/tests/agent/test_coordinator_routing.py`

- [ ] **Step 1: Write the failing test**

在 `backend/tests/agent/test_coordinator_routing.py` 末尾追加:

```python
@pytest.mark.asyncio
async def test_qa_followup_uses_existing_report(tmp_path):
    sent = []
    async def sse_send(ev): sent.append(ev)

    output_dir = tmp_path / "002594.SZ_比亚迪"
    output_dir.mkdir()
    (output_dir / "比亚迪_002594.SZ_分析报告.md").write_text("# 报告\n\nROIC=15%", encoding="utf-8")

    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(return_value=CompletionResult(text="第 5 段...", tokens_in=10, tokens_out=4))

    repo = MagicMock()
    repo.get.return_value = {"session_id":"s1","output_dir":str(output_dir),"status":"done"}
    repo.list_messages.return_value = []

    workspace = MagicMock()
    workspace.read_meta.return_value = {"phases": {"phase3_valuation":{"status":"done"}}}

    coord = Coordinator(sse_send=sse_send, repo=repo, workspace=workspace,
                        stock_index=MagicMock(), llm_factory=lambda p: fake_llm)
    await coord.run(session_id="s1", message="第 5 段那个 G 系数怎么算的?", context=None)

    types = [e["type"] for e in sent]
    assert types[0] == "thinking"
    assert types[-1] == "done"
    # 校验 prompt 含报告内容
    sent_msgs = fake_llm.complete.call_args[0][0]
    assert any("ROIC=15%" in m.content for m in sent_msgs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/agent/test_coordinator_routing.py::test_qa_followup_uses_existing_report -x -q`
Expected: FAIL — `_run_qa_followup` 还是 `NotImplementedError`

- [ ] **Step 3: Write minimal implementation**

替换 coordinator 中 `_run_qa_followup`:

```python
async def _run_qa_followup(self, session_id: str, message: str, output_dir: Path) -> None:
    await self.sse_send(sse.thinking("加载已有分析报告作上下文..."))
    # 读取报告(取 output_dir 下唯一的 *_分析报告.md)
    reports = list(output_dir.glob("*_分析报告.md"))
    report_text = reports[0].read_text(encoding="utf-8") if reports else ""
    # 取最近 10 条历史
    history = (self.repo.list_messages(session_id) or [])[-10:]
    msgs = [
        Message("system",
                "你是一名投资研究助理,基于以下投资分析报告回答用户的追问。"
                "请在报告范围内引用,避免编造数据。\n\n<<报告>>\n" + report_text + "\n<<报告结束>>"),
    ]
    for h in history:
        if h["role"] in ("user", "assistant"):
            msgs.append(Message(h["role"], h["content"]))
    msgs.append(Message("user", message))

    client = self.llm_factory("qa_followup")
    result = await client.complete(msgs)
    self.repo.append_message(session_id, role="assistant", content=result.text,
                             tokens_in=result.tokens_in, tokens_out=result.tokens_out)
    await self.sse_send(sse.done(result.text, artifacts=[]))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/agent/test_coordinator_routing.py -x -q`
Expected: PASS(3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/coordinator.py backend/tests/agent/test_coordinator_routing.py
git commit -m "feat(agent): Coordinator qa_followup 分支(已有报告时答疑)"
```

---

## Phase C — 数据包适配器(Tasks 20-26)

**前置阅读**:实施本 phase 前必须阅读 turtle 黄金参照:
- `Turtle_investment_framework/scripts/tushare_modules/assembly.py:206-437`(§1-§17 schema 权威)
- `Turtle_investment_framework/tests/test_output_format.py:36-91`(测试契约)
- 本项目 `backend/services/duckdb_store.py`(查询入口)

**统一约定**:
- 数值统一**百万元**(原始单位元 ÷ 1e6),用 `f"{v/1e6:,.2f}"` 格式
- 缺失数据写 `—`(em dash),不写 `null` / `N/A`
- 每个 section 返回 `str | None`;`None` 表示该 section 在当前市场不适用(由 builder 过滤)

### Task 20: DataPackBuilder 骨架 + 占位 sections(§7/§8/§10/§14/§16)

**Files:**
- Create: `backend/services/agent/pipeline/__init__.py`
- Create: `backend/services/agent/pipeline/phase1_data_pack/__init__.py`
- Create: `backend/services/agent/pipeline/phase1_data_pack/sections/__init__.py`
- Create: `backend/services/agent/pipeline/phase1_data_pack/sections/s07_holders_placeholder.py`
- Create: `backend/services/agent/pipeline/phase1_data_pack/sections/s08_industry_placeholder.py`
- Create: `backend/services/agent/pipeline/phase1_data_pack/sections/s10_esg_placeholder.py`
- Create: `backend/services/agent/pipeline/phase1_data_pack/sections/s14_rf.py`
- Create: `backend/services/agent/pipeline/phase1_data_pack/sections/s16_peers_placeholder.py`
- Create: `backend/services/agent/pipeline/phase1_data_pack/builder.py`
- Create: `backend/tests/agent/test_phase1_data_pack_builder.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agent/test_phase1_data_pack_builder.py
from pathlib import Path
from unittest.mock import MagicMock
from backend.services.agent.symbol import StockRef
from backend.services.agent.pipeline.phase1_data_pack.builder import DataPackBuilder

def test_builder_produces_file_with_placeholders(tmp_path):
    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    store = MagicMock()
    store.query_qfq_kline.return_value = []
    store.query_financial.return_value = {}
    builder = DataPackBuilder(store=store, stock_index=MagicMock(),
                              indicators=MagicMock(), include=("s07","s08","s10","s14","s16"))
    out = builder.build(ref, tmp_path)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "## §7" in text and "WebSearch(期 2)" in text
    assert "## §8" in text
    assert "## §10" in text
    assert "## §14 无风险利率" in text and "2.70" in text  # Rf 常量
    assert "## §16" in text

def test_section_returning_none_is_skipped(tmp_path):
    ref = StockRef(code="AAPL", name="Apple", market="US")
    builder = DataPackBuilder(store=MagicMock(), stock_index=MagicMock(),
                              indicators=MagicMock(), include=("s07","s14"))
    out = builder.build(ref, tmp_path)
    assert "§7" in out.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/agent/test_phase1_data_pack_builder.py -x -q`
Expected: FAIL — module 不存在

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/agent/pipeline/__init__.py
# 空

# backend/services/agent/pipeline/phase1_data_pack/__init__.py
# 空

# backend/services/agent/pipeline/phase1_data_pack/sections/__init__.py
# 空
```

```python
# sections/s07_holders_placeholder.py
def build(ref, **kw) -> str:
    return ("## §7 控股股东与管理层\n\n"
            "⚠️ 数据需 Phase 1B WebSearch(期 2 实现)\n")

# sections/s08_industry_placeholder.py
def build(ref, **kw) -> str:
    return ("## §8 行业竞争与监管\n\n"
            "⚠️ 数据需 Phase 1B WebSearch(期 2 实现)\n")

# sections/s10_esg_placeholder.py
def build(ref, **kw) -> str:
    return ("## §10 ESG 与争议事件\n\n"
            "⚠️ 数据需 Phase 1B WebSearch(期 2 实现)\n")

# sections/s14_rf.py
RF_CHINA_10Y = 0.027  # 2026Q2,后续接 akshare bond_china_yield
def build(ref, **kw) -> str:
    return (f"## §14 无风险利率 Rf\n\n"
            f"- 中国 10 年期国债收益率:**{RF_CHINA_10Y*100:.2f}%**(常量,2026Q2 快照)\n")

# sections/s16_peers_placeholder.py
def build(ref, **kw) -> str:
    return ("## §16 同业可比公司\n\n"
            "⚠️ 行业分类元数据缺失(期 2 引入 akshare stock_individual_info_em)\n")
```

```python
# backend/services/agent/pipeline/phase1_data_pack/builder.py
from __future__ import annotations
from pathlib import Path
from typing import Iterable, Optional
from backend.services.agent.symbol import StockRef
from backend.services.agent.pipeline.phase1_data_pack.sections import (
    s07_holders_placeholder, s08_industry_placeholder, s10_esg_placeholder,
    s14_rf, s16_peers_placeholder,
)

# 注册表 — 后续 task 持续追加
SECTION_REGISTRY = {
    "s07": s07_holders_placeholder.build,
    "s08": s08_industry_placeholder.build,
    "s10": s10_esg_placeholder.build,
    "s14": s14_rf.build,
    "s16": s16_peers_placeholder.build,
}

DEFAULT_INCLUDE = (
    "s01","s02","s03","s03p","s04","s04p","s05","s06","s07","s08","s09",
    "s10","s11","s12","s13","s14","s15","s16","s17",
)

class DataPackBuilder:
    def __init__(self, *, store, stock_index, indicators,
                 include: Iterable[str] = DEFAULT_INCLUDE):
        self.store = store
        self.stock_index = stock_index
        self.indicators = indicators
        self.include = tuple(include)

    def build(self, ref: StockRef, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        parts: list[str] = [f"# 数据包 — {ref.name}({ref.code})\n"]
        deps = dict(store=self.store, stock_index=self.stock_index, indicators=self.indicators)
        for key in self.include:
            fn = SECTION_REGISTRY.get(key)
            if fn is None:
                continue
            chunk = fn(ref, **deps)
            if chunk is None:
                continue
            parts.append(chunk)
        out = output_dir / "data_pack_market.md"
        out.write_text("\n\n".join(parts), encoding="utf-8")
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/agent/test_phase1_data_pack_builder.py -x -q`
Expected: PASS(2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/pipeline/ backend/tests/agent/test_phase1_data_pack_builder.py
git commit -m "feat(phase1): DataPackBuilder 骨架 + 占位 sections(§7/§8/§10/§14/§16)"
```

---

### Task 21: §1 基础信息 + §2 市值/股价

**Files:**
- Create: `backend/services/agent/pipeline/phase1_data_pack/sections/s01_basic.py`
- Create: `backend/services/agent/pipeline/phase1_data_pack/sections/s02_market.py`
- Modify: `backend/services/agent/pipeline/phase1_data_pack/builder.py`(注册新 section)
- Create: `backend/tests/agent/test_phase1_section_s01_basic.py`
- Create: `backend/tests/agent/test_phase1_section_s02_market.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agent/test_phase1_section_s01_basic.py
from unittest.mock import MagicMock
from backend.services.agent.symbol import StockRef
from backend.services.agent.pipeline.phase1_data_pack.sections import s01_basic

def test_a_share_section1():
    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    si = MagicMock(); si.get_industry.return_value = "汽车整车"
    out = s01_basic.build(ref, store=MagicMock(), stock_index=si, indicators=MagicMock())
    assert "## §1 基础信息" in out
    assert "002594.SZ" in out and "比亚迪" in out
    assert "CNY" in out  # A 股币种
    assert "A 股" in out

def test_hk_share_currency():
    ref = StockRef(code="00700.HK", name="腾讯控股", market="HK")
    out = s01_basic.build(ref, store=MagicMock(), stock_index=MagicMock(),
                          indicators=MagicMock())
    assert "HKD" in out

def test_us_currency():
    ref = StockRef(code="AAPL", name="Apple Inc", market="US")
    out = s01_basic.build(ref, store=MagicMock(), stock_index=MagicMock(),
                          indicators=MagicMock())
    assert "USD" in out
```

```python
# backend/tests/agent/test_phase1_section_s02_market.py
from unittest.mock import MagicMock
from backend.services.agent.symbol import StockRef
from backend.services.agent.pipeline.phase1_data_pack.sections import s02_market

def test_section_2_emits_price_and_market_cap():
    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    store = MagicMock()
    store.query_qfq_kline.return_value = [
        {"date":"2026-05-22","close":268.50,"open":265.0,"high":270.0,"low":264.0,"volume":1.2e8,"amount":3.2e10}
    ]
    store.query_circulating_shares.return_value = 2.91e9
    out = s02_market.build(ref, store=store, stock_index=MagicMock(), indicators=MagicMock())
    assert "## §2 市值/股价" in out
    assert "268.50" in out
    assert "2026-05-22" in out
    # 市值 = 268.50 × 2.91e9 = 7.81e11 = 781,335 百万元
    assert "781,335" in out or "781335" in out

def test_section_2_no_data_emits_warning():
    ref = StockRef(code="999999.SZ", name="未知", market="A")
    store = MagicMock(); store.query_qfq_kline.return_value = []
    out = s02_market.build(ref, store=store, stock_index=MagicMock(), indicators=MagicMock())
    assert "—" in out or "数据缺失" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/agent/test_phase1_section_s01_basic.py backend/tests/agent/test_phase1_section_s02_market.py -x -q`
Expected: FAIL — module 不存在

- [ ] **Step 3: Write minimal implementation**

```python
# sections/s01_basic.py
from __future__ import annotations

_CURRENCY = {"A": "CNY", "HK": "HKD", "US": "USD"}
_MARKET_LABEL = {"A": "A 股", "HK": "港股", "US": "美股"}

def build(ref, *, store, stock_index, indicators) -> str:
    industry = "—"
    try:
        industry = stock_index.get_industry(ref.code) or "—"
    except (AttributeError, Exception):
        pass
    lines = [
        "## §1 基础信息",
        "",
        f"- 股票代码:**{ref.code}**",
        f"- 公司名称:{ref.name}",
        f"- 上市结构:{_MARKET_LABEL[ref.market]}",
        f"- 报表币种:{_CURRENCY[ref.market]}",
        f"- 所属行业:{industry}",
    ]
    return "\n".join(lines) + "\n"
```

```python
# sections/s02_market.py
from __future__ import annotations

def _fmt_million(v: float) -> str:
    return f"{v/1e6:,.0f}"

def build(ref, *, store, stock_index, indicators) -> str:
    rows = store.query_qfq_kline(ref.code, limit=1, order="desc") or []
    if not rows:
        return "## §2 市值/股价\n\n- 当前价:—(数据缺失)\n"
    last = rows[0]
    price = float(last["close"])
    date = last["date"]

    shares = None
    try:
        shares = float(store.query_circulating_shares(ref.code) or 0) or None
    except (AttributeError, Exception):
        pass
    market_cap = price * shares if shares else None

    lines = [
        "## §2 市值/股价",
        "",
        f"- 最新收盘价:**{price:.2f}**({date})",
        f"- 流通股本(股):{shares:,.0f}" if shares else "- 流通股本:—",
        f"- 流通市值(百万元):{_fmt_million(market_cap)}" if market_cap else "- 流通市值:—",
    ]
    return "\n".join(lines) + "\n"
```

修改 builder 注册表:

```python
# 在 builder.py 顶部 imports 增加
from backend.services.agent.pipeline.phase1_data_pack.sections import s01_basic, s02_market
# SECTION_REGISTRY 字典追加:
SECTION_REGISTRY.update({"s01": s01_basic.build, "s02": s02_market.build})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/agent/test_phase1_section_s01_basic.py backend/tests/agent/test_phase1_section_s02_market.py -x -q`
Expected: PASS(5 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/pipeline/phase1_data_pack/sections/s01_basic.py \
        backend/services/agent/pipeline/phase1_data_pack/sections/s02_market.py \
        backend/services/agent/pipeline/phase1_data_pack/builder.py \
        backend/tests/agent/test_phase1_section_s01_basic.py \
        backend/tests/agent/test_phase1_section_s02_market.py
git commit -m "feat(phase1): §1 基础信息 + §2 市值/股价"
```

---

### Task 22: §3 利润表 + §4 资产负债表 + §5 现金流(5 年三表)

**Files:**
- Create: `backend/services/agent/pipeline/phase1_data_pack/sections/s03_income.py`
- Create: `backend/services/agent/pipeline/phase1_data_pack/sections/s04_balance.py`
- Create: `backend/services/agent/pipeline/phase1_data_pack/sections/s05_cashflow.py`
- Create: `backend/services/agent/pipeline/phase1_data_pack/sections/_table.py`(共享 markdown 表格生成器)
- Modify: `backend/services/agent/pipeline/phase1_data_pack/builder.py`
- Create: `backend/tests/agent/test_phase1_section_s03_income.py`
- Create: `backend/tests/agent/test_phase1_section_s04_balance.py`
- Create: `backend/tests/agent/test_phase1_section_s05_cashflow.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agent/test_phase1_section_s03_income.py
from unittest.mock import MagicMock
from backend.services.agent.symbol import StockRef
from backend.services.agent.pipeline.phase1_data_pack.sections import s03_income

def _store(rows):
    s = MagicMock()
    s.query_financial.return_value = rows
    return s

def test_section_3_basic():
    rows = [
        {"REPORT_DATE":"2025-12-31","TOTAL_OPERATE_INCOME":7.7e11,"OPERATE_COST":6.2e11,
         "GROSS_PROFIT":1.5e11,"OPERATE_PROFIT":3.0e10,"NETPROFIT":3.5e10,
         "PARENT_NETPROFIT":3.4e10,"DEDUCT_PARENT_NETPROFIT":3.0e10,"BASIC_EPS":11.7},
        {"REPORT_DATE":"2024-12-31","TOTAL_OPERATE_INCOME":6.0e11,"OPERATE_COST":4.9e11,
         "GROSS_PROFIT":1.1e11,"OPERATE_PROFIT":2.5e10,"NETPROFIT":3.0e10,
         "PARENT_NETPROFIT":2.9e10,"DEDUCT_PARENT_NETPROFIT":2.7e10,"BASIC_EPS":10.0},
    ]
    out = s03_income.build(StockRef("002594.SZ","比亚迪","A"),
                           store=_store(rows), stock_index=MagicMock(), indicators=MagicMock())
    assert "## §3 利润表" in out
    assert "2025-12-31" in out and "2024-12-31" in out
    assert "770,000" in out  # 7.7e11/1e6
    assert "扣非归母净利润" in out

def test_section_3_empty_emits_warning():
    out = s03_income.build(StockRef("X","x","A"),
                           store=_store([]), stock_index=MagicMock(), indicators=MagicMock())
    assert "数据缺失" in out or "—" in out
```

```python
# backend/tests/agent/test_phase1_section_s04_balance.py
from unittest.mock import MagicMock
from backend.services.agent.symbol import StockRef
from backend.services.agent.pipeline.phase1_data_pack.sections import s04_balance

def test_section_4_basic():
    rows = [{
        "REPORT_DATE":"2025-12-31","TOTAL_ASSETS":8.0e11,"TOTAL_LIABILITIES":5.5e11,
        "TOTAL_EQUITY":2.5e11,"TOTAL_CURRENT_ASSETS":3.0e11,"TOTAL_CURRENT_LIAB":3.0e11,
        "MONETARY_FUND":6.0e10,"INVENTORIES":4.0e10,"FIXED_ASSETS":1.5e11,
        "INTANGIBLE_ASSETS":2.0e10,"GOODWILL":5.0e9,"BPS":85.5,
    }]
    s = MagicMock(); s.query_financial.return_value = rows
    out = s04_balance.build(StockRef("002594.SZ","比亚迪","A"),
                            store=s, stock_index=MagicMock(), indicators=MagicMock())
    assert "## §4 资产负债表" in out
    assert "总资产" in out and "总负债" in out and "股东权益" in out
    assert "800,000" in out  # 8e11/1e6
```

```python
# backend/tests/agent/test_phase1_section_s05_cashflow.py
from unittest.mock import MagicMock
from backend.services.agent.symbol import StockRef
from backend.services.agent.pipeline.phase1_data_pack.sections import s05_cashflow

def test_section_5_basic():
    rows = [{
        "REPORT_DATE":"2025-12-31","NETCASH_OPERATE":8.0e10,"NETCASH_INVEST":-7.0e10,
        "NETCASH_FINANCE":-1.0e10,"END_CASH":7.0e10,"DEPRECIATION_FA":3.0e10,
        "CONSTRUCT_LONG_ASSET":5.0e10,
    }]
    s = MagicMock(); s.query_financial.return_value = rows
    out = s05_cashflow.build(StockRef("002594.SZ","比亚迪","A"),
                             store=s, stock_index=MagicMock(), indicators=MagicMock())
    assert "## §5 现金流量表" in out
    assert "经营性现金流" in out
    assert "80,000" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/agent/test_phase1_section_s03_income.py backend/tests/agent/test_phase1_section_s04_balance.py backend/tests/agent/test_phase1_section_s05_cashflow.py -x -q`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# sections/_table.py
from __future__ import annotations

def md_table(headers: list[str], rows: list[list[str]]) -> str:
    """生成 markdown 表格"""
    if not rows:
        return ""
    h = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join([h, sep, *body])

def fmt_million(v) -> str:
    if v is None: return "—"
    try:
        return f"{float(v)/1e6:,.0f}"
    except (TypeError, ValueError):
        return "—"

def fmt_num(v, digits=2) -> str:
    if v is None: return "—"
    try:
        return f"{float(v):,.{digits}f}"
    except (TypeError, ValueError):
        return "—"
```

```python
# sections/s03_income.py
from __future__ import annotations
from backend.services.agent.pipeline.phase1_data_pack.sections._table import md_table, fmt_million, fmt_num

INCOME_FIELDS = [
    ("TOTAL_OPERATE_INCOME", "营业总收入"),
    ("OPERATE_COST",         "营业成本"),
    ("GROSS_PROFIT",         "毛利"),
    ("OPERATE_PROFIT",       "营业利润"),
    ("NETPROFIT",            "净利润"),
    ("PARENT_NETPROFIT",     "归母净利润"),
    ("DEDUCT_PARENT_NETPROFIT","扣非归母净利润"),
]

def build(ref, *, store, stock_index, indicators) -> str:
    rows = store.query_financial(ref.code, table="income", years=5) or []
    if not rows:
        return "## §3 利润表(近 5 年)\n\n数据缺失\n"
    rows = sorted(rows, key=lambda r: r["REPORT_DATE"], reverse=True)[:5]
    headers = ["指标(百万元)"] + [r["REPORT_DATE"] for r in rows]
    table_rows = []
    for key, label in INCOME_FIELDS:
        table_rows.append([label] + [fmt_million(r.get(key)) for r in rows])
    # EPS 单独一行(元/股)
    table_rows.append(["每股收益(元/股)"] + [fmt_num(r.get("BASIC_EPS"), 2) for r in rows])
    return ("## §3 利润表(近 5 年)\n\n"
            + md_table(headers, table_rows) + "\n")
```

```python
# sections/s04_balance.py
from __future__ import annotations
from backend.services.agent.pipeline.phase1_data_pack.sections._table import md_table, fmt_million, fmt_num

BALANCE_FIELDS = [
    ("TOTAL_ASSETS",       "总资产"),
    ("TOTAL_LIABILITIES",  "总负债"),
    ("TOTAL_EQUITY",       "股东权益"),
    ("TOTAL_CURRENT_ASSETS","流动资产"),
    ("TOTAL_CURRENT_LIAB", "流动负债"),
    ("MONETARY_FUND",      "货币资金"),
    ("INVENTORIES",        "存货"),
    ("FIXED_ASSETS",       "固定资产"),
    ("INTANGIBLE_ASSETS",  "无形资产"),
    ("GOODWILL",           "商誉"),
]

def build(ref, *, store, stock_index, indicators) -> str:
    rows = store.query_financial(ref.code, table="balance", years=5) or []
    if not rows:
        return "## §4 资产负债表(近 5 年)\n\n数据缺失\n"
    rows = sorted(rows, key=lambda r: r["REPORT_DATE"], reverse=True)[:5]
    headers = ["指标(百万元)"] + [r["REPORT_DATE"] for r in rows]
    table_rows = []
    for key, label in BALANCE_FIELDS:
        table_rows.append([label] + [fmt_million(r.get(key)) for r in rows])
    table_rows.append(["每股净资产(元/股)"] + [fmt_num(r.get("BPS"), 2) for r in rows])
    return ("## §4 资产负债表(近 5 年)\n\n"
            + md_table(headers, table_rows) + "\n")
```

```python
# sections/s05_cashflow.py
from __future__ import annotations
from backend.services.agent.pipeline.phase1_data_pack.sections._table import md_table, fmt_million

CASHFLOW_FIELDS = [
    ("NETCASH_OPERATE",     "经营性现金流"),
    ("NETCASH_INVEST",      "投资性现金流"),
    ("NETCASH_FINANCE",     "筹资性现金流"),
    ("END_CASH",            "期末现金及等价物"),
    ("DEPRECIATION_FA",     "固定资产折旧"),
    ("CONSTRUCT_LONG_ASSET","构建长期资产支出(资本支出)"),
]

def build(ref, *, store, stock_index, indicators) -> str:
    rows = store.query_financial(ref.code, table="cashflow", years=5) or []
    if not rows:
        return "## §5 现金流量表(近 5 年)\n\n数据缺失\n"
    rows = sorted(rows, key=lambda r: r["REPORT_DATE"], reverse=True)[:5]
    headers = ["指标(百万元)"] + [r["REPORT_DATE"] for r in rows]
    table_rows = [[label] + [fmt_million(r.get(key)) for r in rows] for key, label in CASHFLOW_FIELDS]
    return ("## §5 现金流量表(近 5 年)\n\n"
            + md_table(headers, table_rows) + "\n")
```

修改 builder 注册:

```python
from backend.services.agent.pipeline.phase1_data_pack.sections import s03_income, s04_balance, s05_cashflow
SECTION_REGISTRY.update({
    "s03": s03_income.build, "s04": s04_balance.build, "s05": s05_cashflow.build,
})
```

**注意:`store.query_financial(code, table=..., years=...)` 是新接口**。验证 `services/duckdb_store.py` 是否已有等价方法;若无,本 task 顺手追加(读取 `v_a_income / v_a_balance / v_a_cashflow / v_hk_*` / `v_us_*`,`ORDER BY REPORT_DATE DESC LIMIT years`)。如该方法已存在但签名不同,**优先适配既有签名**(更新 section 调用)而非更改 store 公共 API。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/agent/test_phase1_section_s03_income.py backend/tests/agent/test_phase1_section_s04_balance.py backend/tests/agent/test_phase1_section_s05_cashflow.py -x -q`
Expected: PASS(5 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/pipeline/phase1_data_pack/sections/_table.py \
        backend/services/agent/pipeline/phase1_data_pack/sections/s03_income.py \
        backend/services/agent/pipeline/phase1_data_pack/sections/s04_balance.py \
        backend/services/agent/pipeline/phase1_data_pack/sections/s05_cashflow.py \
        backend/services/agent/pipeline/phase1_data_pack/builder.py \
        backend/services/duckdb_store.py \
        backend/tests/agent/test_phase1_section_s03_income.py \
        backend/tests/agent/test_phase1_section_s04_balance.py \
        backend/tests/agent/test_phase1_section_s05_cashflow.py
git commit -m "feat(phase1): §3/§4/§5 5 年三表(英文 schema 对齐 EastMoney)"
```

---

### Task 23: §3P + §4P A 股母公司报表(港股/美股返回 None)

**Files:**
- Create: `backend/services/agent/pipeline/phase1_data_pack/sections/s03p_parent_income.py`
- Create: `backend/services/agent/pipeline/phase1_data_pack/sections/s04p_parent_balance.py`
- Modify: `backend/services/agent/pipeline/phase1_data_pack/builder.py`
- Modify: `backend/tests/agent/test_phase1_section_s03_income.py`(增 §3P 测试)
- Modify: `backend/tests/agent/test_phase1_section_s04_balance.py`(增 §4P 测试)

- [ ] **Step 1: Write the failing test**

在 `test_phase1_section_s03_income.py` 末尾追加:

```python
from backend.services.agent.pipeline.phase1_data_pack.sections import s03p_parent_income

def test_s03p_returns_none_for_hk():
    ref = StockRef("00700.HK","腾讯","HK")
    assert s03p_parent_income.build(ref, store=MagicMock(), stock_index=MagicMock(),
                                    indicators=MagicMock()) is None

def test_s03p_returns_none_for_us():
    ref = StockRef("AAPL","Apple","US")
    assert s03p_parent_income.build(ref, store=MagicMock(), stock_index=MagicMock(),
                                    indicators=MagicMock()) is None

def test_s03p_a_share_returns_table():
    rows = [{"REPORT_DATE":"2025-12-31","TOTAL_OPERATE_INCOME":1.0e10,
             "PARENT_NETPROFIT":2.0e9,"NETPROFIT":2.0e9}]
    s = MagicMock(); s.query_financial.return_value = rows
    out = s03p_parent_income.build(StockRef("002594.SZ","比亚迪","A"),
                                   store=s, stock_index=MagicMock(), indicators=MagicMock())
    assert out is not None
    assert "§3P 母公司利润表" in out

def test_s03p_a_share_no_parent_data_returns_warning():
    s = MagicMock(); s.query_financial.return_value = []
    out = s03p_parent_income.build(StockRef("002594.SZ","比亚迪","A"),
                                   store=s, stock_index=MagicMock(), indicators=MagicMock())
    assert "母公司数据缺失" in out
```

在 `test_phase1_section_s04_balance.py` 末尾追加:

```python
from backend.services.agent.pipeline.phase1_data_pack.sections import s04p_parent_balance

def test_s04p_returns_none_for_hk():
    ref = StockRef("00700.HK","腾讯","HK")
    assert s04p_parent_balance.build(ref, store=MagicMock(), stock_index=MagicMock(),
                                     indicators=MagicMock()) is None

def test_s04p_returns_none_for_us():
    ref = StockRef("AAPL","Apple","US")
    assert s04p_parent_balance.build(ref, store=MagicMock(), stock_index=MagicMock(),
                                     indicators=MagicMock()) is None

def test_s04p_a_share_returns_table():
    rows = [
        {"REPORT_DATE":"2025-12-31","TOTAL_ASSETS":3.5e11,"TOTAL_LIABILITIES":2.4e11,
         "TOTAL_EQUITY":1.1e11,"MONETARY_FUND":4.0e10,"LONG_EQUITY_INVEST":8.0e10},
        {"REPORT_DATE":"2024-12-31","TOTAL_ASSETS":3.0e11,"TOTAL_LIABILITIES":2.1e11,
         "TOTAL_EQUITY":9.0e10,"MONETARY_FUND":3.5e10,"LONG_EQUITY_INVEST":7.0e10},
    ]
    s = MagicMock(); s.query_financial.return_value = rows
    out = s04p_parent_balance.build(StockRef("002594.SZ","比亚迪","A"),
                                    store=s, stock_index=MagicMock(), indicators=MagicMock())
    assert out is not None
    assert "§4P 母公司资产负债表" in out
    # 验证关键科目均渲染
    assert "总资产" in out and "总负债" in out and "股东权益" in out
    assert "对子公司长投" in out  # 母公司表特有

def test_s04p_a_share_no_parent_data_returns_warning():
    s = MagicMock(); s.query_financial.return_value = []
    out = s04p_parent_balance.build(StockRef("002594.SZ","比亚迪","A"),
                                    store=s, stock_index=MagicMock(), indicators=MagicMock())
    assert out is not None
    assert "母公司数据缺失" in out

def test_s04p_a_share_truncates_to_5_years():
    """6 行数据时应只取最近 5 年(按 REPORT_DATE 降序)。"""
    rows = [
        {"REPORT_DATE": f"{y}-12-31","TOTAL_ASSETS":1e11,"TOTAL_LIABILITIES":5e10,
         "TOTAL_EQUITY":5e10,"MONETARY_FUND":1e10,"LONG_EQUITY_INVEST":1e10}
        for y in [2025, 2024, 2023, 2022, 2021, 2020]
    ]
    s = MagicMock(); s.query_financial.return_value = rows
    out = s04p_parent_balance.build(StockRef("002594.SZ","比亚迪","A"),
                                    store=s, stock_index=MagicMock(), indicators=MagicMock())
    assert "2025-12-31" in out and "2021-12-31" in out
    assert "2020-12-31" not in out  # 第 6 年应被截掉
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/agent/test_phase1_section_s03_income.py backend/tests/agent/test_phase1_section_s04_balance.py -x -q`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# sections/s03p_parent_income.py
from __future__ import annotations
from typing import Optional
from backend.services.agent.pipeline.phase1_data_pack.sections._table import md_table, fmt_million

PARENT_INCOME_FIELDS = [
    ("TOTAL_OPERATE_INCOME","营业总收入(母公司)"),
    ("OPERATE_PROFIT",      "营业利润(母公司)"),
    ("NETPROFIT",           "净利润(母公司)"),
    ("PARENT_NETPROFIT",    "母公司净利润"),
]

def build(ref, *, store, stock_index, indicators) -> Optional[str]:
    if ref.market != "A":
        return None
    rows = store.query_financial(ref.code, table="income_parent", years=5) or []
    if not rows:
        return "## §3P 母公司利润表(近 5 年)\n\n母公司数据缺失(eastmoney 未提供母表)\n"
    rows = sorted(rows, key=lambda r: r["REPORT_DATE"], reverse=True)[:5]
    headers = ["指标(百万元)"] + [r["REPORT_DATE"] for r in rows]
    table_rows = [[label] + [fmt_million(r.get(key)) for r in rows]
                  for key, label in PARENT_INCOME_FIELDS]
    return ("## §3P 母公司利润表(近 5 年)\n\n"
            + md_table(headers, table_rows) + "\n")
```

```python
# sections/s04p_parent_balance.py
from __future__ import annotations
from typing import Optional
from backend.services.agent.pipeline.phase1_data_pack.sections._table import md_table, fmt_million

PARENT_BALANCE_FIELDS = [
    ("TOTAL_ASSETS",      "总资产(母公司)"),
    ("TOTAL_LIABILITIES", "总负债(母公司)"),
    ("TOTAL_EQUITY",      "股东权益(母公司)"),
    ("MONETARY_FUND",     "货币资金(母公司)"),
    ("LONG_EQUITY_INVEST","对子公司长投(母公司)"),
]

def build(ref, *, store, stock_index, indicators) -> Optional[str]:
    if ref.market != "A":
        return None
    rows = store.query_financial(ref.code, table="balance_parent", years=5) or []
    if not rows:
        return "## §4P 母公司资产负债表(近 5 年)\n\n母公司数据缺失\n"
    rows = sorted(rows, key=lambda r: r["REPORT_DATE"], reverse=True)[:5]
    headers = ["指标(百万元)"] + [r["REPORT_DATE"] for r in rows]
    table_rows = [[label] + [fmt_million(r.get(key)) for r in rows]
                  for key, label in PARENT_BALANCE_FIELDS]
    return ("## §4P 母公司资产负债表(近 5 年)\n\n"
            + md_table(headers, table_rows) + "\n")
```

builder 注册:

```python
from backend.services.agent.pipeline.phase1_data_pack.sections import s03p_parent_income, s04p_parent_balance
SECTION_REGISTRY.update({"s03p": s03p_parent_income.build, "s04p": s04p_parent_balance.build})
```

`duckdb_store.query_financial` 需支持 `table="income_parent" / "balance_parent"`(分别映射到 `v_a_income_parent / v_a_balance_parent` 视图)。**若数据层尚无母表,本 task 在 store 层加视图注册**(通过 `register_view("v_a_income_parent", "data/market/A/financial/income_parent/*.parquet")`,若 parquet 不存在该视图也不存在,query 应返回 `[]` 而非抛错)。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/agent/test_phase1_section_s03_income.py backend/tests/agent/test_phase1_section_s04_balance.py -x -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/pipeline/phase1_data_pack/sections/s03p_parent_income.py \
        backend/services/agent/pipeline/phase1_data_pack/sections/s04p_parent_balance.py \
        backend/services/agent/pipeline/phase1_data_pack/builder.py \
        backend/services/duckdb_store.py \
        backend/tests/agent/test_phase1_section_s03_income.py \
        backend/tests/agent/test_phase1_section_s04_balance.py
git commit -m "feat(phase1): §3P/§4P A 股母公司报表(港股/美股返 None)"
```

---

### Task 24: §6 股息 + §11 周线 + §15 行业估值

**Files:**
- Create: `backend/services/agent/pipeline/phase1_data_pack/sections/s06_dividend.py`
- Create: `backend/services/agent/pipeline/phase1_data_pack/sections/s11_weekly_kline.py`
- Create: `backend/services/agent/pipeline/phase1_data_pack/sections/s15_industry_valuation.py`
- Modify: `backend/services/agent/pipeline/phase1_data_pack/builder.py`
- Create: 3 个对应 test 文件

- [ ] **Step 1: Write the failing test**

```python
# test_phase1_section_s06_dividend.py
from unittest.mock import MagicMock
from backend.services.agent.symbol import StockRef
from backend.services.agent.pipeline.phase1_data_pack.sections import s06_dividend

def test_section_6_dps_5_years():
    s = MagicMock()
    s.query_dividend_bulk.return_value = [
        {"year":"2025","dps":2.05},{"year":"2024","dps":1.10},
        {"year":"2023","dps":0.49},{"year":"2022","dps":0.11},{"year":"2021","dps":0.0},
    ]
    out = s06_dividend.build(StockRef("002594.SZ","比亚迪","A"),
                             store=s, stock_index=MagicMock(), indicators=MagicMock())
    assert "## §6" in out
    assert "2.05" in out and "0.49" in out
```

```python
# test_phase1_section_s11_weekly.py
from unittest.mock import MagicMock
from backend.services.agent.symbol import StockRef
from backend.services.agent.pipeline.phase1_data_pack.sections import s11_weekly_kline

def test_section_11_basic():
    rows = [{"date":f"2026-{m:02d}-01","close":100+m,"high":105+m,"low":95+m,"volume":1e6} for m in range(1,6)]
    s = MagicMock(); s.query_qfq_kline.return_value = rows
    out = s11_weekly_kline.build(StockRef("002594.SZ","比亚迪","A"),
                                 store=s, stock_index=MagicMock(), indicators=MagicMock())
    assert "## §11 历史价格" in out
    # 表只展示头/尾各几行 + 摘要(min/max/return)
    assert "近 5 年" in out or "周线" in out
    assert "100" in out or "105" in out
```

```python
# test_phase1_section_s15_industry_valuation.py
from unittest.mock import MagicMock
from backend.services.agent.symbol import StockRef
from backend.services.agent.pipeline.phase1_data_pack.sections import s15_industry_valuation

def test_section_15_industry_median():
    s = MagicMock()
    s.query_industry_valuation_summary.return_value = {"industry":"汽车整车","pe_median":25.3,"pb_median":3.1,"sample_size":42}
    out = s15_industry_valuation.build(StockRef("002594.SZ","比亚迪","A"),
                                       store=s, stock_index=MagicMock(), indicators=MagicMock())
    assert "## §15 行业平均估值" in out
    assert "25.3" in out and "3.1" in out

def test_section_15_no_industry_data():
    s = MagicMock(); s.query_industry_valuation_summary.return_value = None
    out = s15_industry_valuation.build(StockRef("X","x","A"),
                                       store=s, stock_index=MagicMock(), indicators=MagicMock())
    assert "—" in out or "数据缺失" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/agent/test_phase1_section_s06_dividend.py backend/tests/agent/test_phase1_section_s11_weekly.py backend/tests/agent/test_phase1_section_s15_industry_valuation.py -x -q`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# sections/s06_dividend.py
from __future__ import annotations
from backend.services.agent.pipeline.phase1_data_pack.sections._table import md_table, fmt_num

def build(ref, *, store, stock_index, indicators) -> str:
    rows = store.query_dividend_bulk(ref.code, years=5) or []
    if not rows:
        return "## §6 每股股息(近 5 年)\n\n数据缺失\n"
    rows = sorted(rows, key=lambda r: r["year"], reverse=True)[:5]
    return ("## §6 每股股息(近 5 年)\n\n"
            + md_table(["年度","DPS(元/股)"],
                       [[r["year"], fmt_num(r.get("dps"), 2)] for r in rows]) + "\n")
```

```python
# sections/s11_weekly_kline.py
from __future__ import annotations
from backend.services.agent.pipeline.phase1_data_pack.sections._table import md_table, fmt_num

def build(ref, *, store, stock_index, indicators) -> str:
    rows = store.query_qfq_kline(ref.code, freq="W", years=5) or []
    if not rows:
        return "## §11 历史价格(近 5 年周线)\n\n数据缺失\n"
    closes = [float(r["close"]) for r in rows]
    high_all = max(float(r["high"]) for r in rows)
    low_all  = min(float(r["low"])  for r in rows)
    ret = (closes[-1] / closes[0] - 1) * 100 if closes[0] else 0
    summary = (f"- 区间最高:{high_all:,.2f}  最低:{low_all:,.2f}\n"
               f"- 期初/期末收盘:{closes[0]:,.2f} → {closes[-1]:,.2f}\n"
               f"- 区间涨跌幅:**{ret:+.1f}%**\n")
    sample = rows[:3] + (rows[-3:] if len(rows) > 6 else [])
    table = md_table(["日期","收盘"],
                     [[r["date"], fmt_num(r["close"], 2)] for r in sample])
    return ("## §11 历史价格(近 5 年周线)\n\n" + summary + "\n" + table + "\n")
```

```python
# sections/s15_industry_valuation.py
from __future__ import annotations
from backend.services.agent.pipeline.phase1_data_pack.sections._table import fmt_num

def build(ref, *, store, stock_index, indicators) -> str:
    summary = None
    try:
        summary = store.query_industry_valuation_summary(ref.code)
    except (AttributeError, Exception):
        pass
    if not summary:
        return "## §15 行业平均估值\n\n—(行业数据缺失)\n"
    return ("## §15 行业平均估值\n\n"
            f"- 行业:{summary.get('industry','—')}\n"
            f"- 行业 PE 中位数:{fmt_num(summary.get('pe_median'),1)}\n"
            f"- 行业 PB 中位数:{fmt_num(summary.get('pb_median'),1)}\n"
            f"- 样本数:{summary.get('sample_size','—')}\n")
```

注:`query_qfq_kline(freq="W")`、`query_dividend_bulk`、`query_industry_valuation_summary` 是新方法。如 `duckdb_store.py` 缺,本 task 顺手实现:
- `query_qfq_kline(freq="W")`:基于 `v_*_daily` ASOF JOIN `v_*_adjust_factor` 后用 W-FRI 重采样(可复用 `services/stock_data.py:aggregate_kline`)
- `query_dividend_bulk(code, years)`:`SELECT year, SUM(dps) FROM v_a_dividend WHERE code=? GROUP BY year ORDER BY year DESC LIMIT ?`(港股/美股暂返空)
- `query_industry_valuation_summary(code)`:期 1 占位返回 `None`(stock_index 暂无行业字段)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/agent/test_phase1_section_s06_dividend.py backend/tests/agent/test_phase1_section_s11_weekly.py backend/tests/agent/test_phase1_section_s15_industry_valuation.py -x -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/pipeline/phase1_data_pack/sections/s06_dividend.py \
        backend/services/agent/pipeline/phase1_data_pack/sections/s11_weekly_kline.py \
        backend/services/agent/pipeline/phase1_data_pack/sections/s15_industry_valuation.py \
        backend/services/agent/pipeline/phase1_data_pack/builder.py \
        backend/services/duckdb_store.py \
        backend/tests/agent/test_phase1_section_s06_dividend.py \
        backend/tests/agent/test_phase1_section_s11_weekly.py \
        backend/tests/agent/test_phase1_section_s15_industry_valuation.py
git commit -m "feat(phase1): §6/§11/§15 股息+周线+行业估值"
```

---

### Task 25: §9 主营拆分 + §12 关键比率 + §13 自检 warnings + §17 衍生指标

**Files:**
- Create: 4 个 sections 文件
- Modify: builder.py
- Create: 4 个测试文件(`test_phase1_section_s09_segments.py` / `test_phase1_section_s12_ratios.py` / `test_phase1_section_s13_warnings.py` / `test_phase1_section_s17_derived.py`,均详写)

- [ ] **Step 1: Write the failing test**

```python
# test_phase1_section_s12_ratios.py
from unittest.mock import MagicMock
from backend.services.agent.symbol import StockRef
from backend.services.agent.pipeline.phase1_data_pack.sections import s12_ratios

def test_section_12_ratios_basic():
    rows = [
        {"REPORT_DATE":"2025-12-31","ROEJQ":15.3,"ROAJQ":7.5,"GROSSPROFIT_MARGIN":19.5,
         "NETPROFIT_MARGIN":4.5,"DEBT_ASSET_RATIO":68.7,"CURRENT_RATIO":1.05},
        {"REPORT_DATE":"2024-12-31","ROEJQ":24.5,"ROAJQ":8.5,"GROSSPROFIT_MARGIN":18.3,
         "NETPROFIT_MARGIN":5.0,"DEBT_ASSET_RATIO":71.2,"CURRENT_RATIO":0.98},
    ]
    s = MagicMock(); s.query_financial.return_value = rows
    out = s12_ratios.build(StockRef("002594.SZ","比亚迪","A"),
                           store=s, stock_index=MagicMock(), indicators=MagicMock())
    assert "## §12 关键比率" in out
    assert "ROE" in out and "15.30" in out
    assert "毛利率" in out

# test_phase1_section_s17_derived.py
from unittest.mock import MagicMock
from backend.services.agent.symbol import StockRef
from backend.services.agent.pipeline.phase1_data_pack.sections import s17_derived

def test_section_17_macd_ma():
    ind = MagicMock()
    ind.get_indicator_snapshot.return_value = {
        "MA5":268.0, "MA10":265.0, "MA20":260.5, "MA60":255.0,
        "MACD_DIF":0.5, "MACD_DEA":0.2, "MACD_BAR":0.6,
        "PE_PCT_5Y":0.42, "PB_PCT_5Y":0.38,
    }
    out = s17_derived.build(StockRef("002594.SZ","比亚迪","A"),
                            store=MagicMock(), stock_index=MagicMock(), indicators=ind)
    assert "## §17 衍生指标" in out
    assert "MA5" in out and "268.00" in out
    assert "MACD" in out
    assert "PE 历史分位" in out and "42" in out
```

```python
# test_phase1_section_s09_segments.py
from unittest.mock import MagicMock
from backend.services.agent.symbol import StockRef
from backend.services.agent.pipeline.phase1_data_pack.sections import s09_segments


def test_section_09_segments_with_data():
    segs = [
        {"segment": "汽车及相关产品", "revenue_pct": 78.5, "gross_margin": 22.3},
        {"segment": "手机部件、组装及其他", "revenue_pct": 18.2, "gross_margin": 8.6},
        {"segment": "二次充电电池", "revenue_pct": 3.3, "gross_margin": 16.5},
    ]
    s = MagicMock()
    s.query_business_segments.return_value = segs
    out = s09_segments.build(StockRef("002594.SZ", "比亚迪", "A"),
                              store=s, stock_index=MagicMock(), indicators=MagicMock())
    assert "## §9 主营拆分" in out
    assert "汽车及相关产品" in out
    assert "78.5" in out
    assert "22.3" in out
    # md 表头包含三列
    assert "营收占比" in out and "毛利率" in out


def test_section_09_segments_empty_returns_placeholder():
    s = MagicMock()
    s.query_business_segments.return_value = []
    out = s09_segments.build(StockRef("002594.SZ", "比亚迪", "A"),
                              store=s, stock_index=MagicMock(), indicators=MagicMock())
    assert "## §9 主营拆分" in out
    assert "暂未接入" in out


def test_section_09_segments_store_lacks_method_no_crash():
    """store.query_business_segments 不存在时降级为占位文案。"""
    class _NoMethodStore: pass
    out = s09_segments.build(StockRef("002594.SZ", "比亚迪", "A"),
                              store=_NoMethodStore(),
                              stock_index=MagicMock(), indicators=MagicMock())
    assert "## §9 主营拆分" in out
    assert "暂未接入" in out


def test_section_09_segments_store_raises_no_crash():
    """store 抛异常时降级,不阻塞数据包构建。"""
    s = MagicMock()
    s.query_business_segments.side_effect = RuntimeError("duckdb error")
    out = s09_segments.build(StockRef("002594.SZ", "比亚迪", "A"),
                              store=s, stock_index=MagicMock(), indicators=MagicMock())
    assert "## §9 主营拆分" in out


# test_phase1_section_s13_warnings.py
from unittest.mock import MagicMock
from backend.services.agent.symbol import StockRef
from backend.services.agent.pipeline.phase1_data_pack.sections import s13_warnings


def test_section_13_no_warnings_when_healthy():
    rows = [{"REPORT_DATE": "2025-12-31", "DEBT_ASSET_RATIO": 55.0,
             "GOODWILL": 1e8, "TOTAL_EQUITY": 1e11}]
    s = MagicMock(); s.query_financial.return_value = rows
    out = s13_warnings.build(StockRef("002594.SZ", "比亚迪", "A"),
                              store=s, stock_index=MagicMock(), indicators=MagicMock())
    assert "## §13 数据自检 Warnings" in out
    assert "无显著异常" in out


def test_section_13_high_leverage_warning():
    rows = [{"REPORT_DATE": "2025-12-31", "DEBT_ASSET_RATIO": 85.0,
             "GOODWILL": 0, "TOTAL_EQUITY": 1e10}]
    s = MagicMock(); s.query_financial.return_value = rows
    out = s13_warnings.build(StockRef("002594.SZ", "比亚迪", "A"),
                              store=s, stock_index=MagicMock(), indicators=MagicMock())
    assert "资产负债率 > 80%" in out
    assert "高杠杆" in out


def test_section_13_goodwill_impairment_warning():
    rows = [{"REPORT_DATE": "2025-12-31", "DEBT_ASSET_RATIO": 50.0,
             "GOODWILL": 5e10, "TOTAL_EQUITY": 1e11}]  # GOODWILL/EQUITY = 50% > 30%
    s = MagicMock(); s.query_financial.return_value = rows
    out = s13_warnings.build(StockRef("002594.SZ", "比亚迪", "A"),
                              store=s, stock_index=MagicMock(), indicators=MagicMock())
    assert "商誉" in out
    assert "减值风险" in out


def test_section_13_both_warnings_listed():
    rows = [{"REPORT_DATE": "2025-12-31", "DEBT_ASSET_RATIO": 90.0,
             "GOODWILL": 8e10, "TOTAL_EQUITY": 1e11}]
    s = MagicMock(); s.query_financial.return_value = rows
    out = s13_warnings.build(StockRef("002594.SZ", "比亚迪", "A"),
                              store=s, stock_index=MagicMock(), indicators=MagicMock())
    assert "高杠杆" in out
    assert "减值风险" in out
    # 两条 warning 都应渲染为列表项
    assert out.count("⚠️") >= 2


def test_section_13_no_data_no_crash():
    s = MagicMock(); s.query_financial.return_value = []
    out = s13_warnings.build(StockRef("002594.SZ", "比亚迪", "A"),
                              store=s, stock_index=MagicMock(), indicators=MagicMock())
    assert "## §13 数据自检 Warnings" in out
    # 空数据无法判断,应输出 "无显著异常" 或类似占位
    assert "无显著异常" in out


def test_section_13_store_raises_no_crash():
    s = MagicMock()
    s.query_financial.side_effect = RuntimeError("store error")
    out = s13_warnings.build(StockRef("002594.SZ", "比亚迪", "A"),
                              store=s, stock_index=MagicMock(), indicators=MagicMock())
    assert "## §13 数据自检 Warnings" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/agent/test_phase1_section_s09_segments.py backend/tests/agent/test_phase1_section_s12_ratios.py backend/tests/agent/test_phase1_section_s13_warnings.py backend/tests/agent/test_phase1_section_s17_derived.py -x -q`
Expected: FAIL(4 个 section 模块均不存在)

- [ ] **Step 3: Write minimal implementation**

```python
# sections/s09_segments.py
from typing import Optional
def build(ref, *, store, stock_index, indicators) -> Optional[str]:
    segs = []
    try:
        segs = store.query_business_segments(ref.code) or []
    except (AttributeError, Exception):
        pass
    if not segs:
        return "## §9 主营拆分\n\n—(eastmoney 主营拆分暂未接入)\n"
    from backend.services.agent.pipeline.phase1_data_pack.sections._table import md_table, fmt_num
    rows = [[s.get("segment","—"), fmt_num(s.get("revenue_pct"), 1) + "%",
             fmt_num(s.get("gross_margin"), 1) + "%"] for s in segs]
    return "## §9 主营拆分\n\n" + md_table(["业务","营收占比","毛利率"], rows) + "\n"

# sections/s12_ratios.py
from backend.services.agent.pipeline.phase1_data_pack.sections._table import md_table, fmt_num
RATIO_FIELDS = [
    ("ROEJQ","ROE(%)"),("ROAJQ","ROA(%)"),
    ("GROSSPROFIT_MARGIN","毛利率(%)"),("NETPROFIT_MARGIN","净利率(%)"),
    ("DEBT_ASSET_RATIO","资产负债率(%)"),("CURRENT_RATIO","流动比率"),
]
def build(ref, *, store, stock_index, indicators):
    rows = store.query_financial(ref.code, table="indicator", years=5) or []
    if not rows:
        return "## §12 关键比率(近 5 年)\n\n数据缺失\n"
    rows = sorted(rows, key=lambda r: r["REPORT_DATE"], reverse=True)[:5]
    headers = ["指标"] + [r["REPORT_DATE"] for r in rows]
    table_rows = [[label] + [fmt_num(r.get(key), 2) for r in rows]
                  for key, label in RATIO_FIELDS]
    return "## §12 关键比率(近 5 年)\n\n" + md_table(headers, table_rows) + "\n"

# sections/s13_warnings.py
def build(ref, *, store, stock_index, indicators) -> str:
    warnings = []
    try:
        last = (store.query_financial(ref.code, table="balance", years=1) or [{}])[0]
        if (last.get("DEBT_ASSET_RATIO") or 0) > 80:
            warnings.append("⚠️ 资产负债率 > 80%(高杠杆)")
        if (last.get("GOODWILL") or 0) > (last.get("TOTAL_EQUITY") or 1) * 0.3:
            warnings.append("⚠️ 商誉 > 股东权益 30%(减值风险)")
    except Exception:
        pass
    if not warnings:
        return "## §13 数据自检 Warnings\n\n无显著异常\n"
    return "## §13 数据自检 Warnings\n\n" + "\n".join(f"- {w}" for w in warnings) + "\n"

# sections/s17_derived.py
def build(ref, *, store, stock_index, indicators) -> str:
    snap = {}
    try:
        snap = indicators.get_indicator_snapshot(ref.code) or {}
    except (AttributeError, Exception):
        pass
    def f(k, d=2):
        v = snap.get(k)
        return "—" if v is None else (f"{v:,.{d}f}" if isinstance(v,(int,float)) else str(v))
    pe_pct = snap.get("PE_PCT_5Y"); pb_pct = snap.get("PB_PCT_5Y")
    return ("## §17 衍生指标(技术 + 估值分位)\n\n"
            f"- MA5/MA10/MA20/MA60:{f('MA5')} / {f('MA10')} / {f('MA20')} / {f('MA60')}\n"
            f"- MACD(DIF/DEA/BAR):{f('MACD_DIF')} / {f('MACD_DEA')} / {f('MACD_BAR')}\n"
            f"- PE 历史分位(5 年):{int(pe_pct*100)}%\n" if pe_pct is not None else
            "- PE 历史分位(5 年):—\n"
            f"- PB 历史分位(5 年):{int(pb_pct*100)}%\n" if pb_pct is not None else
            "- PB 历史分位(5 年):—\n")
```

注:`indicators.get_indicator_snapshot(code)` 是新接口。本 task 在 `backend/services/indicator_store.py` 或新建 `backend/services/agent/indicator_snapshot.py` 提供该方法,内部读 `services/backtest/indicators.py` 已预计算的 MA/EMA/MACD 数组取最新值,以及 `services/duckdb_store.py` 估值分位查询。最简实现可以是 raw computation on demand。

builder 注册:

```python
from backend.services.agent.pipeline.phase1_data_pack.sections import s09_segments, s12_ratios, s13_warnings, s17_derived
SECTION_REGISTRY.update({
    "s09": s09_segments.build, "s12": s12_ratios.build,
    "s13": s13_warnings.build, "s17": s17_derived.build,
})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/agent/ -x -q -k "phase1_section"`
Expected: PASS(全部)

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/pipeline/phase1_data_pack/sections/s09_segments.py \
        backend/services/agent/pipeline/phase1_data_pack/sections/s12_ratios.py \
        backend/services/agent/pipeline/phase1_data_pack/sections/s13_warnings.py \
        backend/services/agent/pipeline/phase1_data_pack/sections/s17_derived.py \
        backend/services/agent/pipeline/phase1_data_pack/builder.py \
        backend/tests/agent/test_phase1_section_s09_segments.py \
        backend/tests/agent/test_phase1_section_s12_ratios.py \
        backend/tests/agent/test_phase1_section_s13_warnings.py \
        backend/tests/agent/test_phase1_section_s17_derived.py
git commit -m "feat(phase1): §9/§12/§13/§17 主营+比率+warnings+衍生"
```

---

### Task 26: DataPackBuilder 端到端集成测试(全 19 sections)

**Files:**
- Modify: `backend/tests/agent/test_phase1_data_pack_builder.py`

- [ ] **Step 1: Write the failing test**

在文件末尾追加:

```python
def test_full_pipeline_a_share_002594(tmp_path):
    """端到端:用 mock store/indicators 跑完所有 sections,断言段落数 + 关键内容"""
    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    store = MagicMock()
    # K 线
    store.query_qfq_kline.side_effect = lambda code, **kw: (
        [{"date":"2026-05-22","close":268.5,"open":265,"high":270,"low":264,"volume":1.2e8,"amount":3.2e10}]
        if "limit" in kw else
        [{"date":f"2026-{m:02d}-01","close":250+m,"high":260+m,"low":240+m,"volume":1e6} for m in range(1,5)]
    )
    store.query_circulating_shares.return_value = 2.91e9
    store.query_financial.side_effect = lambda code, table, years: {
        "income":[{"REPORT_DATE":"2025-12-31","TOTAL_OPERATE_INCOME":7.7e11,"OPERATE_COST":6.2e11,
                   "GROSS_PROFIT":1.5e11,"OPERATE_PROFIT":3.0e10,"NETPROFIT":3.5e10,
                   "PARENT_NETPROFIT":3.4e10,"DEDUCT_PARENT_NETPROFIT":3.0e10,"BASIC_EPS":11.7}],
        "income_parent":[{"REPORT_DATE":"2025-12-31","TOTAL_OPERATE_INCOME":1e10,"NETPROFIT":2e9,
                          "PARENT_NETPROFIT":2e9}],
        "balance":[{"REPORT_DATE":"2025-12-31","TOTAL_ASSETS":8e11,"TOTAL_LIABILITIES":5.5e11,
                    "TOTAL_EQUITY":2.5e11,"DEBT_ASSET_RATIO":68.7,"GOODWILL":5e9,"BPS":85.5}],
        "balance_parent":[{"REPORT_DATE":"2025-12-31","TOTAL_ASSETS":1e11,"TOTAL_EQUITY":3e10}],
        "cashflow":[{"REPORT_DATE":"2025-12-31","NETCASH_OPERATE":8e10,"NETCASH_INVEST":-7e10,
                     "NETCASH_FINANCE":-1e10,"END_CASH":7e10,"DEPRECIATION_FA":3e10,
                     "CONSTRUCT_LONG_ASSET":5e10}],
        "indicator":[{"REPORT_DATE":"2025-12-31","ROEJQ":15.3,"ROAJQ":7.5,
                      "GROSSPROFIT_MARGIN":19.5,"NETPROFIT_MARGIN":4.5,
                      "DEBT_ASSET_RATIO":68.7,"CURRENT_RATIO":1.05}],
    }.get(table, [])
    store.query_dividend_bulk.return_value = [{"year":"2025","dps":2.05},{"year":"2024","dps":1.10}]
    store.query_industry_valuation_summary.return_value = {"industry":"汽车整车","pe_median":25.3,"pb_median":3.1,"sample_size":42}
    store.query_business_segments.return_value = [{"segment":"汽车","revenue_pct":78.5,"gross_margin":21.0}]

    indicators = MagicMock()
    indicators.get_indicator_snapshot.return_value = {
        "MA5":268.0,"MA10":265.0,"MA20":260.5,"MA60":255.0,
        "MACD_DIF":0.5,"MACD_DEA":0.2,"MACD_BAR":0.6,
        "PE_PCT_5Y":0.42,"PB_PCT_5Y":0.38,
    }

    si = MagicMock(); si.get_industry.return_value = "汽车整车"

    builder = DataPackBuilder(store=store, stock_index=si, indicators=indicators)
    out = builder.build(ref, tmp_path)
    text = out.read_text(encoding="utf-8")

    # 19 个 §x 段落都应出现(s07/s08/s10/s16 是占位)
    for sec in ["§1","§2","§3","§3P","§4","§4P","§5","§6","§7","§8","§9",
                "§10","§11","§12","§13","§14","§15","§16","§17"]:
        assert sec in text, f"missing {sec}"
    # 全文 ≥ 1500 chars
    assert len(text) > 1500
```

- [ ] **Step 2: Run test to verify it fails / verify currently passes**

Run: `python -m pytest backend/tests/agent/test_phase1_data_pack_builder.py::test_full_pipeline_a_share_002594 -x -q`
Expected: PASS(若 Task 20-25 实现正确;若失败则按错误信息修补 builder/sections)

- [ ] **Step 3: Write minimal implementation**

(若 Step 2 已通过,跳过;否则修复缺失 section 注册或 mock 不匹配)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/agent/ -x -q`
Expected: PASS(全部 agent test)

- [ ] **Step 5: Commit**

```bash
git add backend/tests/agent/test_phase1_data_pack_builder.py
git commit -m "test(phase1): DataPackBuilder 端到端 19 sections 集成测试"
```

---

## Phase D: LLM 流水线编排(Tasks 27-32)

> 本阶段把 Phase 1 数据包接到 turtle Phase 3 的两段 LLM 调用上,产出最终 `{name}_{code}_分析报告.md`。
> Turtle 框架位置:**`/Users/11182300/PycharmProjects/Turtle_investment_framework`**(sibling 项目,只读)。
> 所有 prompt 文件必须**复制**到本项目 `backend/services/agent/prompts/turtle/`,运行时不依赖外部目录。

---

### Task 27: 复制 turtle prompt 文件 + 加载器

**目的**:把 turtle Phase 3 的 6 个 markdown prompt 文件纳入本项目,供 Coordinator 在 runtime 渲染。复制而非 symlink,保证可独立部署。

- [ ] **Step 1: 写测试 `backend/tests/agent/test_prompts_loader.py`**

```python
# backend/tests/agent/test_prompts_loader.py
"""验证 turtle prompts 已复制到位且 loader 能渲染变量。"""
from pathlib import Path
from backend.services.agent.prompts import loader

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "backend" / "services" / "agent" / "prompts" / "turtle"


def test_six_prompt_files_exist():
    expected = [
        "coordinator.md",
        "phase3_quantitative.md",
        "phase3_valuation.md",
        "references/shared_tables.md",
        "references/judgment_examples_turtle.md",
        "references/factor_interface.md",
    ]
    for rel in expected:
        path = PROMPTS_DIR / rel
        assert path.exists(), f"missing {rel}"
        assert path.stat().st_size > 500, f"{rel} suspiciously small"


def test_load_phase3_quant_renders_output_dir():
    text = loader.load("phase3_quantitative.md", output_dir="/tmp/run_xyz")
    # turtle 原文里有 {output_dir} 占位,渲染后应被替换
    assert "{output_dir}" not in text
    assert "/tmp/run_xyz" in text


def test_load_references_relative_path():
    """phase3_quantitative.md 引用 references/shared_tables.md,loader 应能展开 include。"""
    text = loader.load("phase3_quantitative.md", output_dir="/tmp/x", expand_includes=True)
    # shared_tables 里有 "穿透回报率" 关键字
    assert "穿透回报率" in text
```

- [ ] **Step 2: 验证测试失败**

`python -m pytest backend/tests/agent/test_prompts_loader.py -x -q`
预期:`FileNotFoundError`(prompts 目录不存在)。

- [ ] **Step 3: 复制 prompts + 实现 loader**

```bash
mkdir -p backend/services/agent/prompts/turtle/references
cp /Users/11182300/PycharmProjects/Turtle_investment_framework/strategies/turtle/coordinator.md backend/services/agent/prompts/turtle/
cp /Users/11182300/PycharmProjects/Turtle_investment_framework/strategies/turtle/phase3_quantitative.md backend/services/agent/prompts/turtle/
cp /Users/11182300/PycharmProjects/Turtle_investment_framework/strategies/turtle/phase3_valuation.md backend/services/agent/prompts/turtle/
cp /Users/11182300/PycharmProjects/Turtle_investment_framework/strategies/turtle/references/shared_tables.md backend/services/agent/prompts/turtle/references/
cp /Users/11182300/PycharmProjects/Turtle_investment_framework/strategies/turtle/references/judgment_examples_turtle.md backend/services/agent/prompts/turtle/references/
cp /Users/11182300/PycharmProjects/Turtle_investment_framework/strategies/turtle/references/factor_interface.md backend/services/agent/prompts/turtle/references/
```

```python
# backend/services/agent/prompts/__init__.py
"""空 init,占位让 prompts 成为包。"""
```

```python
# backend/services/agent/prompts/loader.py
"""Turtle prompts 加载器。

支持 {var} 占位替换和 include 展开。期 1 仅支持 phase3_quantitative.md /
phase3_valuation.md 直接 include references/* 的场景。
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any

PROMPTS_DIR = Path(__file__).resolve().parent / "turtle"


def _read(rel: str) -> str:
    path = PROMPTS_DIR / rel
    if not path.exists():
        raise FileNotFoundError(f"prompt not found: {rel}")
    return path.read_text(encoding="utf-8")


_INCLUDE_RE = re.compile(r"`references/([\w_]+\.md)`")


def load(name: str, *, expand_includes: bool = False, **vars: Any) -> str:
    """读取 prompt 并替换 {key} 占位。

    Args:
        name: prompt 相对路径(如 "phase3_quantitative.md")
        expand_includes: True 时把所有 `references/xxx.md` 反引用替换为
                         "<ref name=xxx>...</ref>" 块,供 LLM 一次读全
        **vars: 占位变量,如 output_dir="/tmp/run_xyz"
    """
    text = _read(name)
    for key, val in vars.items():
        text = text.replace("{" + key + "}", str(val))
    if expand_includes:
        seen: set[str] = set()
        for m in _INCLUDE_RE.finditer(text):
            ref = m.group(1)
            if ref in seen:
                continue
            seen.add(ref)
            try:
                ref_text = _read(f"references/{ref}")
            except FileNotFoundError:
                continue
            text += f"\n\n<!-- expanded: references/{ref} -->\n<ref name={ref}>\n{ref_text}\n</ref>\n"
    return text
```

- [ ] **Step 4: 验证测试通过**

`python -m pytest backend/tests/agent/test_prompts_loader.py -x -q`
预期:3 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/prompts/ backend/tests/agent/test_prompts_loader.py
git commit -m "feat(prompts): 复制 turtle Phase 3 prompts 并实现 loader"
```

---

### Task 28: phase3_quant 输出解析器(parser.py)

**目的**:从 LLM 生成的 `phase3_quantitative.md` 中提取关键数值字段(GG/II/KK/ROIC/owner_earnings/I/R)供 phase3_valuation 阶段拼 prompt + Executive Summary 表格回填。Turtle 原版用 `<results>` XML 标签包裹关键字段;本期延续此约定。

- [ ] **Step 1: 写测试 `backend/tests/agent/test_parser.py`**

```python
# backend/tests/agent/test_parser.py
from backend.services.agent.parser import parse_phase3_quant_results

SAMPLE = """
# Phase 3 定量分析报告

## Step 11 最终输出

<results>
owner_earnings_I=4523.5
gross_return_R=12.3
threshold_II=10.5
final_return_GG=11.2
margin_KK=0.7
roic_avg=15.6
payout_ratio_M=35.0
g_capex_coef=0.85
trap_risk=低
extrapolation_confidence=中
</results>
"""


def test_parse_complete_results_block():
    out = parse_phase3_quant_results(SAMPLE)
    assert out["owner_earnings_I"] == 4523.5
    assert out["final_return_GG"] == 11.2
    assert out["trap_risk"] == "低"
    assert out["extrapolation_confidence"] == "中"


def test_parse_missing_block_returns_empty():
    out = parse_phase3_quant_results("# 报告\n\n无 results 块")
    assert out == {}


def test_parse_partial_fields_tolerated():
    text = "<results>\nfinal_return_GG=8.5\nthreshold_II=10.0\n</results>"
    out = parse_phase3_quant_results(text)
    assert out["final_return_GG"] == 8.5
    assert out["threshold_II"] == 10.0
    assert "owner_earnings_I" not in out


def test_parse_handles_pct_suffix():
    """LLM 偶尔会带 % 或单位后缀,parser 必须容错。"""
    text = "<results>\nfinal_return_GG=11.2%\nowner_earnings_I=4,523.5 百万\n</results>"
    out = parse_phase3_quant_results(text)
    assert out["final_return_GG"] == 11.2
    assert out["owner_earnings_I"] == 4523.5
```

- [ ] **Step 2: 验证测试失败**

`python -m pytest backend/tests/agent/test_parser.py -x -q`
预期:ImportError。

- [ ] **Step 3: 实现 `backend/services/agent/parser.py`**

```python
# backend/services/agent/parser.py
"""Phase 3 量化报告解析器。

LLM 输出的报告末尾约定带 <results>...</results> 块,key=value 一行一对。
本模块负责把这些键值对解析为 dict,数值自动转 float,字符串保留。
"""
from __future__ import annotations
import re
from typing import Any

_BLOCK_RE = re.compile(r"<results>(.*?)</results>", re.DOTALL | re.IGNORECASE)
_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$")
_NUMERIC_CLEAN_RE = re.compile(r"[,%\s]")
# 中文单位关键字(出现则丢弃后半段,只保留前面的数字)
_UNIT_TAIL_RE = re.compile(r"(百万|万元|亿元|元|股|倍|次)$")


def _coerce(val: str) -> Any:
    raw = val.strip()
    # 试着解析为数字:剥离 , % 空白 + 中文单位
    cleaned = _UNIT_TAIL_RE.sub("", raw).strip()
    cleaned = _NUMERIC_CLEAN_RE.sub("", cleaned)
    try:
        if "." in cleaned:
            return float(cleaned)
        return float(int(cleaned))
    except (ValueError, TypeError):
        return raw  # 非数字,保留原字符串(如 trap_risk=低)


def parse_phase3_quant_results(text: str) -> dict[str, Any]:
    """从 phase3_quantitative.md 提取 <results> 块。

    Returns:
        dict: 提取到的字段,数字字段转 float,字符串字段保留原值。
              若无 <results> 块则返回 {}。
    """
    m = _BLOCK_RE.search(text)
    if not m:
        return {}
    out: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        lm = _LINE_RE.match(line)
        if not lm:
            continue
        key, val = lm.group(1), lm.group(2)
        out[key] = _coerce(val)
    return out
```

- [ ] **Step 4: 验证测试通过**

`python -m pytest backend/tests/agent/test_parser.py -x -q`
预期:4 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/parser.py backend/tests/agent/test_parser.py
git commit -m "feat(agent): phase3 量化输出 <results> 块解析器"
```

---

### Task 29: phase3_quant 阶段执行器

**目的**:封装 Phase 3.1 一次完整执行 — 读 `data_pack_market.md` → 拼 prompt → 调 LLM(stream)→ 写 `phase3_quantitative.md` → 解析 `<results>`。返回 `(report_path, parsed_results)`。

- [ ] **Step 1: 写测试 `backend/tests/agent/test_phase3_quant.py`**

```python
# backend/tests/agent/test_phase3_quant.py
import asyncio
from pathlib import Path
import pytest
from backend.services.agent.pipeline.phase3_quant import run_phase3_quant


class _FakeStreamLLM:
    """Fake LLM:把固定字符串按 chunk 流回。"""
    def __init__(self, full_text: str, chunks: int = 4):
        self.full_text = full_text
        self.chunks = chunks
        self.last_prompt: str | None = None

    async def stream(self, prompt: str, **kwargs):
        self.last_prompt = prompt
        size = max(1, len(self.full_text) // self.chunks)
        for i in range(0, len(self.full_text), size):
            yield self.full_text[i : i + size]


REPORT = """# Phase 3 定量分析

## Step 11 输出

<results>
owner_earnings_I=4523.5
final_return_GG=11.2
threshold_II=10.5
margin_KK=0.7
trap_risk=低
extrapolation_confidence=中
</results>
"""


def test_run_phase3_quant_writes_report_and_parses(tmp_path):
    # 准备 data pack
    (tmp_path / "data_pack_market.md").write_text("# §1 ...\n## §3 ...\n", encoding="utf-8")
    llm = _FakeStreamLLM(REPORT)
    chunks_received: list[str] = []

    async def on_chunk(s: str):
        chunks_received.append(s)

    out_path, parsed = asyncio.run(
        run_phase3_quant(workspace=tmp_path, llm=llm, on_chunk=on_chunk)
    )
    assert out_path == tmp_path / "phase3_quantitative.md"
    assert out_path.read_text(encoding="utf-8") == REPORT
    assert parsed["final_return_GG"] == 11.2
    assert parsed["trap_risk"] == "低"
    # 流式回调收到 ≥ 2 chunk
    assert len(chunks_received) >= 2
    # prompt 包含 data_pack 内容引用
    assert "§1" in llm.last_prompt or "data_pack_market" in llm.last_prompt


def test_run_phase3_quant_missing_pack_raises(tmp_path):
    llm = _FakeStreamLLM(REPORT)
    with pytest.raises(FileNotFoundError):
        asyncio.run(run_phase3_quant(workspace=tmp_path, llm=llm, on_chunk=None))
```

- [ ] **Step 2: 验证测试失败**

`python -m pytest backend/tests/agent/test_phase3_quant.py -x -q`
预期:ImportError。

- [ ] **Step 3: 实现 `backend/services/agent/pipeline/phase3_quant.py`**

```python
# backend/services/agent/pipeline/phase3_quant.py
"""Phase 3.1 — CPA 量化(穿透回报率精算)阶段编排。

流程:
1. 读 workspace/data_pack_market.md(必有)+ data_pack_report.md(可选)
2. 加载 turtle phase3_quantitative.md prompt 并展开 references include
3. 把 data pack 注入 prompt 末尾
4. LLM stream 调用,边产生边写入 phase3_quantitative.md
5. 完成后解析 <results> 块,返回 (path, dict)
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Callable, Awaitable, Protocol

from backend.services.agent.prompts import loader
from backend.services.agent.parser import parse_phase3_quant_results


class StreamLLM(Protocol):
    async def stream(self, prompt: str, **kwargs) -> Any: ...


OnChunk = Callable[[str], Awaitable[None]] | None


async def run_phase3_quant(
    *,
    workspace: Path,
    llm: StreamLLM,
    on_chunk: OnChunk = None,
) -> tuple[Path, dict[str, Any]]:
    """执行 Phase 3.1。

    Args:
        workspace: 本次运行目录(已存在 data_pack_market.md)
        llm: 实现 stream(prompt) -> AsyncIterator[str] 的客户端
        on_chunk: 每收到一段文本时的异步回调(用于 SSE 转发)

    Returns:
        (report_path, parsed_results_dict)
    """
    pack_path = workspace / "data_pack_market.md"
    if not pack_path.exists():
        raise FileNotFoundError(f"data_pack_market.md 不存在于 {workspace}")
    pack_text = pack_path.read_text(encoding="utf-8")

    # 可选的 PDF 解析包(期 1 通常没有)
    extra = ""
    report_pack = workspace / "data_pack_report.md"
    if report_pack.exists():
        extra += "\n\n<data_pack_report>\n" + report_pack.read_text(encoding="utf-8") + "\n</data_pack_report>"

    instr = loader.load(
        "phase3_quantitative.md",
        expand_includes=True,
        output_dir=str(workspace),
    )

    prompt = (
        instr
        + "\n\n---\n\n## 输入数据包\n\n"
        + "<data_pack_market>\n"
        + pack_text
        + "\n</data_pack_market>"
        + extra
        + "\n\n请按上述 Step 0~11 顺序输出完整报告,末尾必须含 <results>...</results> 块。"
    )

    out_path = workspace / "phase3_quantitative.md"
    parts: list[str] = []
    with out_path.open("w", encoding="utf-8") as f:
        async for chunk in llm.stream(prompt):
            if not chunk:
                continue
            f.write(chunk)
            f.flush()
            parts.append(chunk)
            if on_chunk is not None:
                await on_chunk(chunk)

    full_text = "".join(parts)
    parsed = parse_phase3_quant_results(full_text)
    return out_path, parsed
```

- [ ] **Step 4: 验证测试通过**

`python -m pytest backend/tests/agent/test_phase3_quant.py -x -q`
预期:2 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/pipeline/phase3_quant.py backend/tests/agent/test_phase3_quant.py
git commit -m "feat(pipeline): Phase 3.1 量化阶段执行器"
```

---

### Task 30: phase3_valuation 阶段执行器

**目的**:Phase 3.2 — 读 `phase3_quantitative.md` + `data_pack_market.md` + `_quant_results.json`(parser 输出),拼 prompt → LLM stream → 写 `{name}_{code}_分析报告.md`(最终用户可见报告)。

- [ ] **Step 1: 写测试 `backend/tests/agent/test_phase3_valuation.py`**

```python
# backend/tests/agent/test_phase3_valuation.py
import asyncio
from pathlib import Path
from backend.services.agent.pipeline.phase3_valuation import run_phase3_valuation


class _FakeStreamLLM:
    def __init__(self, text: str):
        self.text = text
        self.last_prompt: str | None = None

    async def stream(self, prompt: str, **kwargs):
        self.last_prompt = prompt
        for i in range(0, len(self.text), 200):
            yield self.text[i : i + 200]


FINAL_REPORT = """# 龟龟投资策略 · 分析报告:比亚迪(002594.SZ)

## Executive Summary
**仓位建议**:观察

| 指标 | 值 |
|---|---|
| Owner Earnings | 4,523.5 百万 |
| 精算穿透回报率 | 11.2% |
"""


def test_run_phase3_valuation_writes_named_report(tmp_path):
    (tmp_path / "data_pack_market.md").write_text("# §1\n基本信息: 比亚迪 002594.SZ\n", encoding="utf-8")
    (tmp_path / "phase3_quantitative.md").write_text("# 量化\n<results>\nfinal_return_GG=11.2\n</results>\n", encoding="utf-8")

    llm = _FakeStreamLLM(FINAL_REPORT)
    chunks: list[str] = []

    async def on_chunk(s):
        chunks.append(s)

    out_path = asyncio.run(
        run_phase3_valuation(
            workspace=tmp_path,
            llm=llm,
            company_name="比亚迪",
            symbol="002594.SZ",
            quant_results={"final_return_GG": 11.2, "trap_risk": "低"},
            on_chunk=on_chunk,
        )
    )
    assert out_path.name == "比亚迪_002594.SZ_分析报告.md"
    assert out_path.read_text(encoding="utf-8") == FINAL_REPORT
    assert len(chunks) >= 1
    # prompt 应包含 quant 报告 + data pack
    assert "final_return_GG=11.2" in llm.last_prompt
    assert "比亚迪" in llm.last_prompt
```

- [ ] **Step 2: 验证测试失败**

`python -m pytest backend/tests/agent/test_phase3_valuation.py -x -q`
预期:ImportError。

- [ ] **Step 3: 实现 `backend/services/agent/pipeline/phase3_valuation.py`**

```python
# backend/services/agent/pipeline/phase3_valuation.py
"""Phase 3.2 — 估值 + 报告组装。

读取 quant 阶段产物 + 原始 data pack,生成对用户可见的最终 markdown 报告。
文件名格式:`{name}_{code}_分析报告.md`(turtle 原约定)。
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

from backend.services.agent.prompts import loader


class StreamLLM(Protocol):
    async def stream(self, prompt: str, **kwargs) -> Any: ...


OnChunk = Callable[[str], Awaitable[None]] | None


def _safe_filename(s: str) -> str:
    """剥离文件名非法字符。"""
    bad = '<>:"/\\|?*'
    return "".join("_" if c in bad else c for c in s).strip() or "report"


async def run_phase3_valuation(
    *,
    workspace: Path,
    llm: StreamLLM,
    company_name: str,
    symbol: str,
    quant_results: dict[str, Any],
    on_chunk: OnChunk = None,
) -> Path:
    """执行 Phase 3.2,返回最终报告路径。"""
    pack_path = workspace / "data_pack_market.md"
    quant_path = workspace / "phase3_quantitative.md"
    if not pack_path.exists():
        raise FileNotFoundError(f"data_pack_market.md 不存在于 {workspace}")
    if not quant_path.exists():
        raise FileNotFoundError(f"phase3_quantitative.md 不存在于 {workspace}")

    # 持久化 parser 结果(便于 debug / 后续重用)
    (workspace / "_quant_results.json").write_text(
        json.dumps(quant_results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    instr = loader.load(
        "phase3_valuation.md",
        expand_includes=True,
        output_dir=str(workspace),
    )

    pack_text = pack_path.read_text(encoding="utf-8")
    quant_text = quant_path.read_text(encoding="utf-8")
    quant_json = json.dumps(quant_results, ensure_ascii=False, indent=2)

    prompt = (
        instr
        + f"\n\n---\n\n## 公司信息\n- 公司名:{company_name}\n- 股票代码:{symbol}\n"
        + "\n\n## Phase 3.1 量化报告(完整)\n<phase3_quantitative>\n"
        + quant_text
        + "\n</phase3_quantitative>"
        + "\n\n## Phase 3.1 解析后关键参数\n```json\n"
        + quant_json
        + "\n```"
        + "\n\n## 原始数据包\n<data_pack_market>\n"
        + pack_text
        + "\n</data_pack_market>"
        + "\n\n请严格按 phase3_valuation.md 中 <report_template> 输出完整 markdown 报告。"
    )

    fname = f"{_safe_filename(company_name)}_{_safe_filename(symbol)}_分析报告.md"
    out_path = workspace / fname
    with out_path.open("w", encoding="utf-8") as f:
        async for chunk in llm.stream(prompt):
            if not chunk:
                continue
            f.write(chunk)
            f.flush()
            if on_chunk is not None:
                await on_chunk(chunk)
    return out_path
```

- [ ] **Step 4: 验证测试通过**

`python -m pytest backend/tests/agent/test_phase3_valuation.py -x -q`
预期:1 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/pipeline/phase3_valuation.py backend/tests/agent/test_phase3_valuation.py
git commit -m "feat(pipeline): Phase 3.2 估值与报告组装阶段执行器"
```

---

### Task 31: Coordinator 完整流水线编排 + SSE 事件序列

**目的**:把 Phase 1 → 3.1 → 3.2 串起来,通过 `_meta.json` 记录阶段状态(running/done/failed),支持断点续跑(若 `phase3_quantitative.md` 已完整则跳过重跑),并按 §4.2 SSE 协议产出 `thinking → tool_start(phase=...) → generating → tool_done → ... → done`。

- [ ] **Step 1: 写测试 `backend/tests/agent/test_coordinator_full_pipeline.py`**

```python
# backend/tests/agent/test_coordinator_full_pipeline.py
"""完整流水线集成测试 — mock 三段产物(数据包 / quant / valuation)。"""
import asyncio
import json
from pathlib import Path
from unittest.mock import patch
import pytest

from backend.services.agent.coordinator import Coordinator


class _FakeLLM:
    """每次 stream 返回 `_queue` 头部的字符串。"""
    def __init__(self, queue: list[str]):
        self._queue = list(queue)
        self.calls: list[str] = []

    async def stream(self, prompt: str, **kwargs):
        self.calls.append(prompt)
        text = self._queue.pop(0) if self._queue else ""
        for i in range(0, len(text), 256):
            yield text[i : i + 256]


QUANT_REPORT = """# 量化
<results>
owner_earnings_I=4523.5
final_return_GG=11.2
threshold_II=10.5
margin_KK=0.7
trap_risk=低
extrapolation_confidence=中
</results>
"""

VAL_REPORT = "# 龟龟投资策略 · 分析报告:比亚迪(002594.SZ)\n\n## Executive Summary\n**仓位建议**:观察\n"


@pytest.mark.asyncio
async def test_full_pipeline_emits_canonical_sse_sequence(tmp_path):
    """断言 SSE 事件序列符合 §4.2:thinking → tool_start(phase1) → tool_done →
    tool_start(phase3.1) → generating × N → tool_done → tool_start(phase3.2) →
    generating × N → tool_done → done。"""

    # 把 workspace 根重定向到 tmp
    with patch("backend.services.agent.workspace.WORKSPACE_ROOT", tmp_path):
        # 让 Phase 1 builder 写出最小 data pack
        async def fake_phase1(*, ref, workspace, on_progress=None):
            (workspace / "data_pack_market.md").write_text("# §1 比亚迪 002594.SZ\n", encoding="utf-8")
            if on_progress:
                await on_progress("§1 done")
            return workspace / "data_pack_market.md"

        llm = _FakeLLM([QUANT_REPORT, VAL_REPORT])

        coord = Coordinator(llm=llm)
        events: list[dict] = []
        async for ev in coord.run_full_pipeline(
            session_id="sess-1",
            user_message="比亚迪",
            phase1_runner=fake_phase1,
        ):
            events.append(ev)

    types = [e["type"] for e in events]
    # 至少包含这些类型
    assert "thinking" in types
    assert types.count("tool_start") >= 3
    assert types.count("tool_done") >= 3
    assert types.count("generating") >= 2  # phase3.1 + phase3.2 stream chunks
    assert types[-1] == "done"
    # tool_start 的 phase 字段覆盖三阶段
    phases = [e.get("phase") for e in events if e["type"] == "tool_start"]
    assert "phase1_data_pack" in phases
    assert "phase3_quant" in phases
    assert "phase3_valuation" in phases


@pytest.mark.asyncio
async def test_full_pipeline_writes_meta_json(tmp_path):
    with patch("backend.services.agent.workspace.WORKSPACE_ROOT", tmp_path):
        async def fake_phase1(*, ref, workspace, on_progress=None):
            (workspace / "data_pack_market.md").write_text("# §1\n", encoding="utf-8")
            return workspace / "data_pack_market.md"

        llm = _FakeLLM([QUANT_REPORT, VAL_REPORT])
        coord = Coordinator(llm=llm)
        async for _ in coord.run_full_pipeline(
            session_id="sess-meta", user_message="002594", phase1_runner=fake_phase1
        ):
            pass

    # workspace 下应有 _meta.json
    runs = list(tmp_path.glob("*/_meta.json"))
    assert len(runs) == 1
    meta = json.loads(runs[0].read_text(encoding="utf-8"))
    assert meta["status"] == "done"
    assert meta["phases"]["phase1_data_pack"]["status"] == "done"
    assert meta["phases"]["phase3_quant"]["status"] == "done"
    assert meta["phases"]["phase3_valuation"]["status"] == "done"
```

- [ ] **Step 2: 验证测试失败**

`python -m pytest backend/tests/agent/test_coordinator_full_pipeline.py -x -q`
预期:`AttributeError: 'Coordinator' object has no attribute 'run_full_pipeline'`(Coordinator 在 Task 17 已建骨架,只有 chitchat/qa_followup 分支)。

- [ ] **Step 3: 在 Coordinator 添加 `run_full_pipeline` 方法**

`backend/services/agent/coordinator.py` 末尾追加:

```python
# coordinator.py 在 class Coordinator 内追加(其余方法保留)
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable

from backend.services.agent.workspace import create_workspace
from backend.services.agent.symbol import resolve as resolve_symbol
from backend.services.agent.pipeline.phase3_quant import run_phase3_quant
from backend.services.agent.pipeline.phase3_valuation import run_phase3_valuation


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_meta(workspace: Path, meta: dict) -> None:
    (workspace / "_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# class Coordinator 内新增:
async def run_full_pipeline(
    self,
    *,
    session_id: str,
    user_message: str,
    phase1_runner: Callable[..., Awaitable[Path]] | None = None,
) -> AsyncIterator[dict]:
    """执行 Phase 1 → 3.1 → 3.2 完整链路。

    Args:
        phase1_runner: 可注入的 Phase 1 构建函数(测试用);默认调
                       backend.services.agent.pipeline.phase1_data_pack.builder.build。
    Yields:
        SSE 事件 dict(符合 §4.2 6 类协议)
    """
    # 0. 解析公司
    ref = resolve_symbol(user_message)
    workspace = create_workspace(session_id=session_id)
    meta: dict[str, Any] = {
        "session_id": session_id,
        "symbol": ref.symbol,
        "company_name": ref.name,
        "started_at": _utcnow(),
        "status": "running",
        "phases": {},
    }
    _write_meta(workspace, meta)

    yield {"type": "thinking", "message": f"开始分析 {ref.name}({ref.symbol})"}

    # ---- Phase 1 ----
    yield {"type": "tool_start", "phase": "phase1_data_pack", "label": "拉取数据包"}
    meta["phases"]["phase1_data_pack"] = {"status": "running", "started_at": _utcnow()}
    _write_meta(workspace, meta)
    try:
        if phase1_runner is None:
            from backend.services.agent.pipeline.phase1_data_pack.builder import build as _build
            async def phase1_runner(*, ref, workspace, on_progress=None):  # type: ignore
                return _build(ref, workspace)
        await phase1_runner(ref=ref, workspace=workspace)
        meta["phases"]["phase1_data_pack"].update({"status": "done", "ended_at": _utcnow()})
        _write_meta(workspace, meta)
        yield {"type": "tool_done", "phase": "phase1_data_pack"}
    except Exception as e:
        meta["phases"]["phase1_data_pack"].update({"status": "failed", "error": str(e)})
        meta["status"] = "failed"
        _write_meta(workspace, meta)
        yield {"type": "error", "message": f"Phase 1 失败:{e}"}
        return

    # ---- Phase 3.1 ----
    yield {"type": "tool_start", "phase": "phase3_quant", "label": "量化分析(穿透回报率)"}
    meta["phases"]["phase3_quant"] = {"status": "running", "started_at": _utcnow()}
    _write_meta(workspace, meta)

    chunk_buffer: list[dict] = []
    async def _quant_chunk(s: str):
        chunk_buffer.append({"type": "generating", "phase": "phase3_quant", "delta": s})

    try:
        _, parsed = await run_phase3_quant(
            workspace=workspace, llm=self.llm, on_chunk=_quant_chunk
        )
    except Exception as e:
        meta["phases"]["phase3_quant"].update({"status": "failed", "error": str(e)})
        meta["status"] = "failed"
        _write_meta(workspace, meta)
        yield {"type": "error", "message": f"Phase 3.1 失败:{e}"}
        return

    for ev in chunk_buffer:
        yield ev
    meta["phases"]["phase3_quant"].update({
        "status": "done", "ended_at": _utcnow(), "results": parsed
    })
    _write_meta(workspace, meta)
    yield {"type": "tool_done", "phase": "phase3_quant"}

    # ---- Phase 3.2 ----
    yield {"type": "tool_start", "phase": "phase3_valuation", "label": "估值与报告组装"}
    meta["phases"]["phase3_valuation"] = {"status": "running", "started_at": _utcnow()}
    _write_meta(workspace, meta)

    val_buffer: list[dict] = []
    async def _val_chunk(s: str):
        val_buffer.append({"type": "generating", "phase": "phase3_valuation", "delta": s})

    try:
        report_path = await run_phase3_valuation(
            workspace=workspace,
            llm=self.llm,
            company_name=ref.name or ref.symbol,
            symbol=ref.symbol,
            quant_results=parsed,
            on_chunk=_val_chunk,
        )
    except Exception as e:
        meta["phases"]["phase3_valuation"].update({"status": "failed", "error": str(e)})
        meta["status"] = "failed"
        _write_meta(workspace, meta)
        yield {"type": "error", "message": f"Phase 3.2 失败:{e}"}
        return

    for ev in val_buffer:
        yield ev
    meta["phases"]["phase3_valuation"].update({
        "status": "done", "ended_at": _utcnow(), "report": report_path.name
    })
    meta["status"] = "done"
    meta["ended_at"] = _utcnow()
    _write_meta(workspace, meta)

    yield {"type": "tool_done", "phase": "phase3_valuation"}
    yield {"type": "done", "report_path": str(report_path)}
```

并在 `backend/services/agent/workspace.py` 顶部确保 `WORKSPACE_ROOT` 是模块级可 patch 的变量(Task 7 已实现;若不是需补)。

- [ ] **Step 4: 验证测试通过**

`python -m pytest backend/tests/agent/test_coordinator_full_pipeline.py -x -q`
预期:2 PASS。然后跑全量:`python -m pytest backend/tests/agent/ -x -q` 应全绿。

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/coordinator.py backend/tests/agent/test_coordinator_full_pipeline.py
git commit -m "feat(coordinator): 完整流水线编排 + _meta.json 状态机 + SSE 事件序列"
```

---

### Task 32: `/chat/stream` 路由接入完整流水线 + 端到端 SSE 集成测试

**目的**:把 `/api/v1/agent/chat/stream`(Task 18 已建骨架,只支持 chitchat/qa_followup)接到 `run_full_pipeline`,根据 Coordinator 的 intent 分类决定走哪条分支。E2E 测试用 FastAPI TestClient + mock LLM 验证完整 SSE 流。

- [ ] **Step 1: 写测试 `backend/tests/agent/test_chat_stream_e2e.py`**

```python
# backend/tests/agent/test_chat_stream_e2e.py
"""端到端 SSE:POST /api/v1/agent/chat/stream → 完整事件流。"""
import json
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from backend.main import app


QUANT = """# 量化\n<results>\nfinal_return_GG=11.2\nthreshold_II=10.0\ntrap_risk=低\n</results>\n"""
VAL = "# 报告:比亚迪(002594.SZ)\n## Executive Summary\n仓位建议:观察\n"


class _FakeLLM:
    def __init__(self, queue):
        self._q = list(queue)

    async def stream(self, prompt, **kwargs):
        text = self._q.pop(0) if self._q else ""
        for i in range(0, len(text), 200):
            yield text[i : i + 200]


def _parse_sse(body: str) -> list[dict]:
    out = []
    for block in body.strip().split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


def test_chat_stream_full_pipeline_e2e(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.services.agent.workspace.WORKSPACE_ROOT", tmp_path
    )

    async def fake_phase1(*, ref, workspace, on_progress=None):
        (workspace / "data_pack_market.md").write_text("# §1 比亚迪\n", encoding="utf-8")
        return workspace / "data_pack_market.md"

    fake_llm = _FakeLLM([QUANT, VAL])

    with patch("backend.routers.agent._build_llm", return_value=fake_llm), \
         patch("backend.routers.agent._build_phase1_runner", return_value=fake_phase1):
        client = TestClient(app)
        resp = client.post(
            "/api/v1/agent/chat/stream",
            json={"session_id": "e2e-1", "message": "分析比亚迪 002594"},
        )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    types = [e["type"] for e in events]
    assert "thinking" in types
    assert types.count("tool_start") >= 3
    assert types[-1] == "done"


def test_chat_stream_chitchat_branch(monkeypatch):
    """非分析意图走 chitchat,只产 generating + done。"""
    class _Echo:
        async def stream(self, prompt, **kwargs):
            for c in "你好,我是问股助手。":
                yield c

    with patch("backend.routers.agent._build_llm", return_value=_Echo()):
        client = TestClient(app)
        resp = client.post(
            "/api/v1/agent/chat/stream",
            json={"session_id": "chit-1", "message": "你好"},
        )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    types = [e["type"] for e in events]
    assert "tool_start" not in types  # 闲聊不走 phase
    assert "generating" in types
    assert types[-1] == "done"
```

- [ ] **Step 2: 验证测试失败**

`python -m pytest backend/tests/agent/test_chat_stream_e2e.py -x -q`
预期:失败(`/chat/stream` 未接 full pipeline,或 `_build_llm` / `_build_phase1_runner` 不存在)。

- [ ] **Step 3: 修改 `backend/routers/agent.py` 接入 full pipeline**

```python
# backend/routers/agent.py 关键改动(保留 Task 19 已写的 router 结构)
from typing import Any
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
import json

from backend.services.agent.coordinator import Coordinator
from backend.services.agent.llm_routing import build_llm_for_session
from backend.services.agent.session_repo import get_or_create_session

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


def _build_llm(session_id: str):
    """工厂:可被测试 patch。"""
    return build_llm_for_session(session_id)


def _build_phase1_runner():
    """工厂:返回真正的 Phase 1 builder 入口(测试可 patch 为 fake)。"""
    from backend.services.agent.pipeline.phase1_data_pack.builder import build as _build
    async def _runner(*, ref, workspace, on_progress=None):
        return _build(ref, workspace)
    return _runner


def _sse(payload: dict) -> bytes:
    return ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8")


@router.post("/chat/stream")
async def chat_stream(req: Request):
    body = await req.json()
    session_id: str = body["session_id"]
    message: str = body["message"]
    get_or_create_session(session_id)

    llm = _build_llm(session_id)
    coord = Coordinator(llm=llm)

    async def _gen():
        intent = coord.classify_intent(message)  # Task 17 已实现:分析 / 闲聊 / 追问
        if intent == "analyze":
            phase1_runner = _build_phase1_runner()
            async for ev in coord.run_full_pipeline(
                session_id=session_id,
                user_message=message,
                phase1_runner=phase1_runner,
            ):
                yield _sse(ev)
        elif intent == "qa_followup":
            async for ev in coord.run_qa_followup(session_id=session_id, message=message):
                yield _sse(ev)
        else:  # chitchat
            async for ev in coord.run_chitchat(session_id=session_id, message=message):
                yield _sse(ev)

    return StreamingResponse(_gen(), media_type="text/event-stream")
```

- [ ] **Step 4: 验证测试通过**

```bash
python -m pytest backend/tests/agent/test_chat_stream_e2e.py -x -q
python -m pytest backend/tests/ -x -q   # 全量回归
```
预期:e2e 2 PASS,全量绿(原 550 + agent 新增 ~30)。

- [ ] **Step 5: Commit**

```bash
git add backend/routers/agent.py backend/tests/agent/test_chat_stream_e2e.py
git commit -m "feat(agent): /chat/stream 接入完整流水线,端到端 SSE 集成测试"
```

---

## Phase E: 验证与文档同步(Tasks 33-34)

---

### Task 33: 真实 LLM 烟囱 + 前端联调

**目的**:用真实 channel(DeepSeek/Anthropic)对 3 个代表股(A/HK/US)各跑一次完整链路,前端 ChatPage 联调验证 SSE 渲染、Markdown 报告显示、错误恢复。

- [ ] **Step 1: 写烟囱脚本 `scripts/smoke_ask_stock.py`**

```python
# scripts/smoke_ask_stock.py
"""问股 E2E 烟囱:对 3 个代表股各跑一次完整流水线,把结果落到 exported/。

usage:
    python scripts/smoke_ask_stock.py [--channel deepseek] [--symbols 002594,600519,00700]
"""
from __future__ import annotations
import argparse
import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime

# 项目根入 sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.services.agent.coordinator import Coordinator  # noqa
from backend.services.agent.llm_routing import build_llm_for_channel  # noqa


async def _run_one(symbol: str, channel: str, out_dir: Path) -> dict:
    llm = build_llm_for_channel(channel)
    coord = Coordinator(llm=llm)
    log_path = out_dir / f"smoke_{symbol.replace('.', '_')}_events.jsonl"
    types: list[str] = []
    error: str | None = None
    with log_path.open("w", encoding="utf-8") as logf:
        async for ev in coord.run_full_pipeline(
            session_id=f"smoke-{symbol}",
            user_message=f"分析 {symbol}",
            phase1_runner=None,  # 用真 builder
        ):
            logf.write(json.dumps(ev, ensure_ascii=False) + "\n")
            types.append(ev["type"])
            if ev["type"] == "error":
                error = ev.get("message")
    return {"symbol": symbol, "events": len(types), "type_counts": {t: types.count(t) for t in set(types)}, "error": error}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="deepseek")
    ap.add_argument("--symbols", default="002594.SZ,600519.SH,00700.HK")
    args = ap.parse_args()

    out_dir = ROOT / "exported" / f"smoke_ask_stock_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for sym in args.symbols.split(","):
        print(f"\n=== {sym} ===")
        r = await _run_one(sym.strip(), args.channel, out_dir)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        results.append(r)

    summary = out_dir / "summary.json"
    summary.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ Summary: {summary}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: 后台执行烟囱(AGENTS.md Line 50 — 超 1 分钟必须 nohup)**

```bash
mkdir -p data/logs/smoke
nohup python scripts/smoke_ask_stock.py --channel deepseek \
    > data/logs/smoke/smoke_$(date +%Y%m%d_%H%M%S).log 2>&1 &
echo $!  # 记录 PID
# 监控:tail -f data/logs/smoke/smoke_*.log
```

预期:每个 symbol 跑 ~3-5 分钟,最终 `exported/smoke_ask_stock_*/summary.json` 显示
- 每股 `error: null`
- `type_counts.tool_start >= 3`、`tool_done >= 3`、`done == 1`、`generating > 50`(stream chunks)
- workspace 下 `{name}_{symbol}_分析报告.md` 含 Executive Summary 表 + 数值

- [ ] **Step 3: 前端联调(手工 + 截图)**

```bash
# 后端
nohup python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 \
    > data/logs/backend_smoke.log 2>&1 &

# 前端
cd frontend && nohup npm run dev > /tmp/fe_smoke.log 2>&1 &
```

打开 http://localhost:3001/chat ,发送「分析 002594」,核对:
- (a) 进度条按 Phase 1 → Phase 3.1 → Phase 3.2 推进,phase 标签显示「拉取数据包」「量化分析」「估值与报告组装」
- (b) Markdown 报告在生成阶段流式增量渲染,完成后表格、列表正确显示
- (c) 切换 channel(Settings → LLM Channel)后再次提问,可以走另一个 LLM
- (d) 闲聊「你好」时无 tool_start,只有 generating

把截图与 SSE 日志归档到 `exported/smoke_ask_stock_<ts>/frontend_screens/`。

- [ ] **Step 4: 跑前后端测试套确认无回归**

```bash
python -m pytest backend/tests/ -x -q                # 全后端
cd frontend && npx tsc --noEmit && npm test          # 前端 ts + vitest
cd frontend && npm run test:smoke                    # Playwright smoke
```
预期:全绿。

- [ ] **Step 5: Commit**

```bash
git add scripts/smoke_ask_stock.py
git commit -m "test(smoke): 问股 E2E 烟囱脚本(3 股票真实 LLM 联调)"
```

---

### Task 34: AGENTS.md 同步 + 期 1 收尾

**目的**:把问股期 1 落地结果写回 AGENTS.md(Discoveries / Accomplished / Relevant files),并归档 spec/plan 文档,删除已废弃的旧设计稿。

- [ ] **Step 1: 检视(无独立测试,改文档)**

通读 AGENTS.md,定位需要更新的段落:
- `Goal` 段:在最后追加「**问股(Ask Stock)期 1 已上线**:对话式投资分析,基于 turtle Phase 3 框架」
- `Instructions` 段:追加「**问股 SSE 协议**:严格 6 类(`thinking/tool_start/tool_done/generating/done/error`),不得新增类型」
- `Discoveries` 段:追加问股相关的关键代码位置(coordinator/builder/parser/loader)
- `Accomplished` 段:新增「### 问股期 1(2026-05-23)」小节,列出 Tasks 1-33 总结
- `Relevant files / directories` 段:加入 `backend/services/agent/`、`backend/routers/agent.py`、`backend/services/system_config/`、`data/agent_runs/`、`data/system_config.yaml`

- [ ] **Step 2: 编辑 AGENTS.md**

按上述清单逐段 `edit`(每段一次,避免大段重写)。同时:
- 删除 `docs/design_ask_stock.md`(803 行旧版,已被 spec 替代)
- 删除 `docs/plan_ask_stock.md`(1289 行旧版,已被本 plan 替代)

```bash
git rm docs/design_ask_stock.md docs/plan_ask_stock.md
```

- [ ] **Step 3: 跑 lint/typecheck 把关**

```bash
python -m pytest backend/tests/ -x -q
cd frontend && npx tsc --noEmit && npm run lint
```
预期:全绿。

- [ ] **Step 4: 验证 AGENTS.md 自洽**

抽查 AGENTS.md 中提到的所有路径都真实存在(简单 grep + ls 即可),Discoveries 中提到的代码行号点开能找到对应实体。

- [ ] **Step 5: Commit + 期 1 收尾**

```bash
git add AGENTS.md docs/superpowers/specs/2026-05-23-ask-stock-design.md docs/superpowers/plans/2026-05-23-ask-stock-phase-1.md
git rm docs/design_ask_stock.md docs/plan_ask_stock.md
git commit -m "docs(ask-stock): 期 1 收尾 — 同步 AGENTS.md,归档新版 spec/plan,删除旧稿"
```

至此问股期 1 全部完成。期 2(`/business-analysis` 三 Agent 定性)与期 3(PDF 自动下载 + 前端上传 UI)按既定边界另行规划。

---

## 计划自检(Self-Review)

> 实施前的最终检查,对照 spec §1-§15(r2)和 skill 规范。**r2 修订**:扩展覆盖 §12-§15(multi-agent harness + LLM router)与 Phase F(T12.5/T12.6/T31.5)。

### 1. Spec 覆盖度

| Spec 节 | 对应 Tasks | 验证 |
|---|---|---|
| §1 目标与范围 | T20-32 全链路 + T12.5/T31.5 | 期 1 范围明确,multi-agent 抽象就位 |
| §2 SSE 协议(C1) | T18, T31, T32, **T12.5**, **T12.6** | 严格 6 类;agent_id/agent_label/step_* 维度;clarify 复用 thinking 事件 |
| §3 system_config(C4) | T9-T11 | 扁平 KV + yaml 持久化 + channels.py 重组 + `default_agent_id` 字段 |
| §4 数据包 §1-§17(C5) | T20-T26 | 19 sections 全覆盖,集成测试断言 |
| §5 Phase 3.1 11 步(CPA) | T27-T29 → 合并 `agents/cpa_conservative/phases.py::run_quant` | turtle prompt 复制 + parser + 执行器 |
| §6 Phase 3.2 报告组装 | T30 → `phases.py::run_valuation` | `{name}_{code}_分析报告.md` |
| §7 闲聊/追问 | T17(改为 chitchat agent)+ T31.5 | dispatcher 调度 chitchat agent |
| §8 auth stub(C3) | T2 | `/auth/status` 永返 false |
| §9 symbol normalize(C6) | T3 | A/HK/US 三市场 |
| §10 workspace + 断点续跑 | **T7(签名加 agent_id)**, T31, **T12.5** | `<session_id>/<agent_id>__<run_id>/_meta.json` 含 agent_id/version/prompt_hashes |
| §11 测试 + 烟囱 | T33 | 3 股票真实 LLM + tradingagents_astock 错误烟囱 |
| **§12 Multi-Agent Harness** | **T12.5, T31.5** | Protocol/Registry/Routing/Events/Dispatcher/Meta + 三 agent 注册 |
| **§13 Agent Manifest 注册** | **T31.5** | cpa/trading/chitchat 三 manifest |
| **§14 D1-D11 决策汇总** | T12.5(D1-D8)+ **T12.6**(D1 升级 + D9-D10)+ T31.5(D3) | 决策点逐一落地 |
| **§15 LLM Router 设计** | **T12.6** | classify + RouterDecision + 阈值 + 澄清反问 + 跳过条件 |

✅ 全覆盖(§1-§15)。

### 2. Placeholder 扫描

- [x] **r2/Phase F 部分**:T12.5/T12.6/T31.5 三任务每 Step 3 完整代码,无「略」「类似」「参考 Task N」;每测试有具体 assert
- [x] **r2 路由 pseudocode**:T18 修订段 `/chat/stream` 用完整可执行 async 代码(含 clarify 分支)
- [x] **r2 §15 LLM router**:Prompt 模板 + Pydantic schema + fallback 逻辑全量给出

✅ **r1 placeholder 缺口已补齐(2026-05-23 r2 修订)**:

| 位置 | 内容 | 状态 |
|---|---|---|
| T23 Step 1 | `test_phase1_section_s04_balance.py` §4P 母公司资产负债表测试 | ✅ 补全 5 个测试(HK/US 返 None / A 股表渲染 / 数据缺失 warning / 5 年截断) |
| T25 Step 1 | `test_phase1_section_s09_segments.py` §9 主营拆分测试 | ✅ 补全 4 个测试(有数据/空数据/store 缺方法/store 抛异常) |
| T25 Step 1 | `test_phase1_section_s13_warnings.py` §13 自检 warnings 测试 | ✅ 补全 6 个测试(健康/高杠杆/商誉减值/双 warning/无数据/store 异常) |

合计补齐 15 个测试用例,r1+r2 全文不再有 `略 / 类似 / 参考上面模式` 这类 placeholder 标记。

### 3. 类型一致性

- [x] **r1 链**:`StockRef`(T3)→ `WorkspaceCtx`(T7,加 agent_id)→ `build_data_pack(ref, workspace)`(T20)→ `CPAConservativeAgent.run(ref, llm, ctx)`(T31)签名串通
- [x] **r2 Agent Protocol**:`AgentManifest` TypedDict + `Agent.run(*, ref, llm, ctx) -> AsyncIterator[Event]` 在 T12.5 定义,T31.5 三 agent 全部遵循
- [x] **LLM 流式**:`LLMClient.stream(prompt, **kw) -> AsyncIterator[str]` 跨 T13-15、T29-30、T31 一致
- [x] **r2 LLM 非流式**:`LLMClient.complete_json(*, system, user, timeout=10) -> str` 在 T12.6 base 加抽象签名;T14/T15 实施期补具体实现(T14/T15 修订要点见 r2 cheatsheet)
- [x] **r2 路由签名**:`routing.resolve_agent(*, message, explicit_agent_id, default_agent_id, llm) -> RouteDecision` 在 T12.6 升级为 async,T18 修订段 caller 加 await
- [x] **r2 RouterDecision vs RouteDecision** 区分:`llm_router.RouterDecision`(LLM 输出原始结构)≠ `routing.RouteDecision`(路由层最终决定,含 quick_replies)。两者在 T12.6 测试中分别覆盖
- [x] **SSE 事件字段**:`type/agent_id/agent_label/step_id/step_label/step_index/step_total/delta/message/report_path/quick_replies/clarification_question?` 与 `frontend/src/stores/agentChatStore.ts:265-283` 对齐;`quick_replies` 为期 1 新增可选字段(前端任务在 r2-D 已列入)

### 4. 时间预估(r2 更新)

| Phase | Tasks | 预估 |
|---|---|---|
| A 基础设施 | 12 | 3-4 天 |
| **F-1 Harness 核心** | **T12.5** | **0.75 天(~6h)** |
| **F-2 LLM Router** | **T12.6** | **0.5 天(~4h)** |
| B LLM + 闲聊/追问 | 7(含 T14/T15 加 complete_json) | 2 天 |
| **F-3 Agent 注册** | **T31.5** | **0.25 天(~2h)** |
| C 数据包 | 7(目录改 `agents/cpa_conservative/`)| 3 天 |
| D LLM 流水线 | 6(改写 T29-T31 落地到 phases.py + agent.py)| 2 天 |
| E 验证 + 文档 | 2(含 multi-agent 烟囱 + AGENTS.md 同步)| 1 天 |
| 前端集成 | 含「分析方式」下拉 + 进度条徽章 + 澄清快捷按钮 | 0.5 天(穿插在 T18/T32) |
| **合计** | **37**(34 r1 + T12.5/T12.6/T31.5)| **13-14 天** |

---

## Execution Handoff

计划 r2 已完成(spec 1052 行 / plan 6468 行,37 tasks,13-14 天)。请选择执行方式:

1. **Subagent-Driven Execution(推荐)** — 每个 Task fresh subagent,主会话只负责审阅 commit。**强烈推荐用于本 plan**(37 tasks 上下文极重,r2 引入 multi-agent 抽象后类型链路更复杂)。流程:
   - 主会话 dispatch task → subagent 读 spec 相关章节 + plan 该 task 完整段落 → 完成 5 step + 提 commit → 返回 diff
   - 主会话审阅 diff → next task
   - 失败时主会话决策(继续/调整 plan/求助)
   - **特别提示**:T23/T25 dispatch 时,prompt 显式要求「Step 1 补齐 §4/§9/§13 测试,不可写"略"」(参见自检 §2 已知缺口)
   - **顺序约束**:Phase F 优先 — T12.5 → T31.5 → T12.6 → r1 T1-T34 按依赖顺序;具体见 Phase F 头部说明

2. **Inline Execution** — 当前会话连续跑,每 task 后 checkpoint。**不推荐**:本 plan 6468 行,主会话 context 撑不到 Phase C 就会被压缩

3. **Hybrid** — 主会话跑 Phase A 短任务(T1-T6,基础设施小步)+ Phase F(T12.5/T12.6 类型抽象需主会话掌控),Phase C/D 重活切 subagent。**适合想保持架构掌控感的场景**

启动入口:
- 1/3 → `superpowers:subagent-driven-development` skill
- 2 → `superpowers:executing-plans` skill(主会话 inline)

请告知选择。

---

## Phase F: Multi-Agent Harness 增量任务(r2 新增)

> 本 Phase 是 r2 修订引入的新任务。**实施顺序**:T12.5 在 r1 T12 之前/之后均可,但**必须早于** r1 T17(Coordinator chitchat)、T20(数据包)、T31(full pipeline);T31.5 必须在 T12.5 之后、r1 T20 之前(因为 T20 起的工作要落入 `agents/cpa_conservative/` 目录,需要 agent 注册骨架先就位)。

**推荐插入位置**:在 r1 T11 完成后插入 T12.5,然后 T31.5,然后回到 r1 T12 起继续。

---

### Task 12.5: Agent Harness 核心 — Protocol + Registry + Routing + Events + Dispatcher + Meta

**目的**:建立 multi-agent harness 的全部基础抽象。本任务是后续所有 agent 工作的硬前置依赖。

- [ ] **Step 1: 写测试 `backend/tests/agent_harness/test_protocol_and_registry.py`**

```python
# backend/tests/agent_harness/test_protocol_and_registry.py
"""Agent registry + routing 单元测试。"""
import pytest
from backend.services.agent_harness import registry, routing
from backend.services.agent_harness.protocol import AgentManifest


@pytest.fixture(autouse=True)
def _clean_registry():
    registry._clear()
    yield
    registry._clear()


def _mk(id_: str, aliases: list[str], enabled: bool = True) -> AgentManifest:
    return {
        "id": id_, "label": id_.upper(), "aliases": aliases,
        "description": "test", "version": "1.0.0", "steps": [],
        "requires": [], "enabled": enabled,
    }


def test_register_and_get():
    m = _mk("cpa_conservative", ["保守分析", "保守"])
    registry.register(m, agent_factory=lambda: object())
    assert registry.exists("cpa_conservative")
    assert registry.get_manifest("cpa_conservative")["label"] == "CPA_CONSERVATIVE"


def test_list_only_enabled_filter():
    registry.register(_mk("a", ["A"]), lambda: None)
    registry.register(_mk("b", ["B"], enabled=False), lambda: None)
    assert {m["id"] for m in registry.list_manifests()} == {"a", "b"}
    assert {m["id"] for m in registry.list_manifests(only_enabled=True)} == {"a"}


def test_routing_keyword_match():
    registry.register(_mk("cpa_conservative", ["保守分析", "保守"]), lambda: None)
    registry.register(_mk("tradingagents_astock", ["团队分析", "团队"]), lambda: None)
    aid, reason = routing.resolve_agent(
        message="请用保守分析帮我看一下 002594", explicit_agent_id=None,
        default_agent_id="cpa_conservative",
    )
    assert (aid, reason) == ("cpa_conservative", "keyword")
    aid, reason = routing.resolve_agent(
        message="团队分析 600519", explicit_agent_id=None,
        default_agent_id="cpa_conservative",
    )
    assert (aid, reason) == ("tradingagents_astock", "keyword")


def test_routing_explicit_overrides_keyword():
    registry.register(_mk("cpa_conservative", ["保守"]), lambda: None)
    registry.register(_mk("tradingagents_astock", ["团队"]), lambda: None)
    aid, reason = routing.resolve_agent(
        message="保守分析 002594",
        explicit_agent_id="tradingagents_astock",
        default_agent_id="cpa_conservative",
    )
    assert (aid, reason) == ("tradingagents_astock", "explicit")


def test_routing_default_when_no_match():
    registry.register(_mk("cpa_conservative", ["保守"]), lambda: None)
    aid, reason = routing.resolve_agent(
        message="002594 怎么样", explicit_agent_id=None,
        default_agent_id="cpa_conservative",
    )
    assert (aid, reason) == ("cpa_conservative", "default")


def test_routing_disabled_agent_match_still_returned():
    """禁用 agent 仍可被关键字命中,由 dispatcher 在 dispatch 时拒绝。"""
    registry.register(_mk("tradingagents_astock", ["团队分析"], enabled=False), lambda: None)
    registry.register(_mk("cpa_conservative", ["保守"]), lambda: None)
    aid, _ = routing.resolve_agent(
        message="团队分析 002594", explicit_agent_id=None,
        default_agent_id="cpa_conservative",
    )
    assert aid == "tradingagents_astock"
```

也写 dispatcher 测试 `backend/tests/agent_harness/test_dispatcher.py`:

```python
# backend/tests/agent_harness/test_dispatcher.py
import asyncio
import json
import pytest
from backend.services.agent_harness import dispatcher, registry
from backend.services.agent_harness import events as E


@pytest.fixture(autouse=True)
def _clean():
    registry._clear()
    yield
    registry._clear()


class _Ref:
    symbol, name, market = "002594.SZ", "比亚迪", "A"


class _LLM:
    model, channel = "test-model", "test-ch"
    async def stream(self, prompt, **kw):
        yield "ok"


def _collect(aiter):
    async def _go():
        out = []
        async for ev in aiter: out.append(ev)
        return out
    return asyncio.run(_go())


def test_dispatch_unknown_agent(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.services.agent_harness.workspace.WORKSPACE_ROOT", tmp_path)
    out = _collect(dispatcher.dispatch(
        agent_id="ghost", ref=_Ref(), llm=_LLM(), session_id="s1"))
    assert len(out) == 1 and out[0]["type"] == "error"
    assert "未知" in out[0]["message"]


def test_dispatch_disabled_agent(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.services.agent_harness.workspace.WORKSPACE_ROOT", tmp_path)
    registry.register({
        "id": "team", "label": "团队分析", "aliases": [],
        "description": "", "version": "0", "steps": [], "requires": [], "enabled": False,
    }, lambda: object())
    out = _collect(dispatcher.dispatch(
        agent_id="team", ref=_Ref(), llm=_LLM(), session_id="s2"))
    assert out[0]["type"] == "error" and "暂未上线" in out[0]["message"]


def test_dispatch_runs_agent_and_writes_meta(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.services.agent_harness.workspace.WORKSPACE_ROOT", tmp_path)

    class _A:
        manifest = {
            "id": "demo", "label": "Demo", "aliases": [], "description": "",
            "version": "1.0.0", "steps": [{"id": "s1", "label": "Step1", "estimated_seconds": 1}],
            "requires": [], "enabled": True,
        }
        async def run(self, *, ref, llm, ctx):
            yield E.tool_start(agent_id="demo", agent_label="Demo",
                               step_id="s1", step_label="Step1", step_index=1, step_total=1)
            yield E.generating(agent_id="demo", step_id="s1", delta="hello")
            yield E.tool_done(agent_id="demo", step_id="s1")
            yield E.done(agent_id="demo")

    registry.register(_A.manifest, lambda: _A())
    out = _collect(dispatcher.dispatch(
        agent_id="demo", ref=_Ref(), llm=_LLM(), session_id="s3"))
    types = [e["type"] for e in out]
    assert types == ["thinking", "tool_start", "generating", "tool_done", "done"]
    # 所有事件都注入了 agent_id
    assert all(e["agent_id"] == "demo" for e in out)
    # _meta.json 已写
    runs = list(tmp_path.glob("s3/demo__*/_meta.json"))
    assert len(runs) == 1
    meta = json.loads(runs[0].read_text(encoding="utf-8"))
    assert meta["status"] == "done"
    assert meta["agent_id"] == "demo"
    assert meta["steps"]["s1"]["status"] == "done"
```

- [ ] **Step 2: 验证测试失败**

```bash
mkdir -p backend/tests/agent_harness && touch backend/tests/agent_harness/__init__.py
python -m pytest backend/tests/agent_harness/ -x -q
```
预期:ModuleNotFoundError(`agent_harness` 不存在)。

- [ ] **Step 3: 实现 harness 全部基础模块**

逐个创建以下文件(完整实现见前面 spec §12.3-§12.7 + Revision Log):

```
backend/services/agent_harness/__init__.py
backend/services/agent_harness/protocol.py
backend/services/agent_harness/registry.py
backend/services/agent_harness/routing.py
backend/services/agent_harness/events.py
backend/services/agent_harness/workspace.py
backend/services/agent_harness/meta.py
backend/services/agent_harness/dispatcher.py
```

**完整代码清单**(直接拷贝):

```python
# backend/services/agent_harness/__init__.py
"""问股 Multi-Agent Harness 包。"""
```

```python
# backend/services/agent_harness/protocol.py
from __future__ import annotations
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable, Literal, Protocol, TypedDict


class StepSpec(TypedDict):
    id: str
    label: str
    estimated_seconds: int


class AgentManifest(TypedDict):
    id: str
    label: str
    aliases: list[str]
    description: str
    version: str
    steps: list[StepSpec]
    requires: list[str]
    enabled: bool


EventType = Literal["thinking", "tool_start", "tool_done", "generating", "done", "error"]


class Event(TypedDict, total=False):
    type: EventType
    agent_id: str
    agent_label: str
    step_id: str
    step_label: str
    step_index: int
    step_total: int
    delta: str
    message: str
    report_path: str


class HarnessContext(Protocol):
    workspace: Path
    session_id: str
    emit: Callable[[Event], Awaitable[None]]
    log_decision: Callable[[str, dict], Awaitable[None]]


class Agent(Protocol):
    manifest: AgentManifest
    async def run(self, *, ref, llm, ctx: HarnessContext) -> AsyncIterator[Event]: ...
```

```python
# backend/services/agent_harness/registry.py
from __future__ import annotations
from typing import Any, Callable
from .protocol import AgentManifest

_ENTRIES: dict[str, dict[str, Any]] = {}


def register(manifest: AgentManifest, agent_factory: Callable[[], Any]) -> None:
    aid = manifest["id"]
    if aid in _ENTRIES:
        raise ValueError(f"agent {aid} already registered")
    _ENTRIES[aid] = {"manifest": manifest, "factory": agent_factory}


def exists(agent_id: str) -> bool:
    return agent_id in _ENTRIES


def get_manifest(agent_id: str) -> AgentManifest:
    if agent_id not in _ENTRIES:
        raise KeyError(f"unknown agent: {agent_id}")
    return _ENTRIES[agent_id]["manifest"]


def get_agent(agent_id: str):
    if agent_id not in _ENTRIES:
        raise KeyError(f"unknown agent: {agent_id}")
    return _ENTRIES[agent_id]["factory"]()


def list_manifests(*, only_enabled: bool = False) -> list[AgentManifest]:
    out = [e["manifest"] for e in _ENTRIES.values()]
    if only_enabled:
        out = [m for m in out if m.get("enabled", True)]
    return sorted(out, key=lambda m: m["id"])


def _clear() -> None:
    """test only"""
    _ENTRIES.clear()
```

```python
# backend/services/agent_harness/routing.py
from __future__ import annotations
from . import registry


def resolve_agent(*, message: str, explicit_agent_id: str | None,
                  default_agent_id: str) -> tuple[str, str]:
    if explicit_agent_id and registry.exists(explicit_agent_id):
        return explicit_agent_id, "explicit"

    msg_lower = message.lower()
    candidates: list[str] = []
    for m in registry.list_manifests():
        for alias in m.get("aliases", []):
            if alias and alias.lower() in msg_lower:
                candidates.append(m["id"])
                break
    if candidates:
        candidates.sort()
        return candidates[0], "keyword"

    if not registry.exists(default_agent_id):
        raise RuntimeError(f"default agent '{default_agent_id}' not registered")
    return default_agent_id, "default"
```

```python
# backend/services/agent_harness/events.py
from .protocol import Event


def thinking(*, agent_id: str, agent_label: str, message: str) -> Event:
    return {"type": "thinking", "agent_id": agent_id, "agent_label": agent_label, "message": message}


def tool_start(*, agent_id: str, agent_label: str, step_id: str,
               step_label: str, step_index: int, step_total: int) -> Event:
    return {"type": "tool_start", "agent_id": agent_id, "agent_label": agent_label,
            "step_id": step_id, "step_label": step_label,
            "step_index": step_index, "step_total": step_total}


def tool_done(*, agent_id: str, step_id: str) -> Event:
    return {"type": "tool_done", "agent_id": agent_id, "step_id": step_id}


def generating(*, agent_id: str, step_id: str, delta: str) -> Event:
    return {"type": "generating", "agent_id": agent_id, "step_id": step_id, "delta": delta}


def done(*, agent_id: str, report_path: str | None = None) -> Event:
    out: Event = {"type": "done", "agent_id": agent_id}
    if report_path:
        out["report_path"] = report_path
    return out


def error(*, agent_id: str, message: str) -> Event:
    return {"type": "error", "agent_id": agent_id, "message": message}
```

```python
# backend/services/agent_harness/workspace.py
from __future__ import annotations
from pathlib import Path
from datetime import datetime
import secrets

WORKSPACE_ROOT = Path("data/agent_runs")


def create_workspace(*, session_id: str, agent_id: str) -> Path:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(2)
    path = WORKSPACE_ROOT / session_id / f"{agent_id}__{run_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path
```

```python
# backend/services/agent_harness/meta.py
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from .protocol import AgentManifest, Event


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write(workspace: Path, meta: dict) -> None:
    (workspace / "_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def init_meta(*, workspace: Path, manifest: AgentManifest, ref, llm) -> dict:
    meta = {
        "session_id": workspace.parent.name,
        "run_id": workspace.name,
        "agent_id": manifest["id"],
        "agent_label": manifest["label"],
        "agent_version": manifest["version"],
        "model": getattr(llm, "model", None),
        "channel": getattr(llm, "channel", None),
        "ref": {
            "symbol": getattr(ref, "symbol", None),
            "name": getattr(ref, "name", None),
            "market": getattr(ref, "market", None),
        },
        "started_at": _now(),
        "status": "running",
        "steps": {},
    }
    _write(workspace, meta)
    return meta


def update_meta_from_event(workspace: Path, meta: dict, ev: Event) -> None:
    sid = ev.get("step_id")
    t = ev["type"]
    if t == "tool_start" and sid:
        meta["steps"][sid] = {"status": "running", "started_at": _now(),
                              "label": ev.get("step_label", sid)}
    elif t == "tool_done" and sid:
        meta["steps"].setdefault(sid, {})
        meta["steps"][sid].update({"status": "done", "ended_at": _now()})
    elif t == "error" and sid:
        meta["steps"].setdefault(sid, {})
        meta["steps"][sid].update({"status": "failed", "error": ev.get("message")})
    _write(workspace, meta)


def finalize_meta(workspace: Path, meta: dict, *, status: str, error: str | None = None) -> None:
    meta["status"] = status
    meta["ended_at"] = _now()
    if error:
        meta["error"] = error
    _write(workspace, meta)
```

```python
# backend/services/agent_harness/dispatcher.py
from __future__ import annotations
from typing import AsyncIterator
from . import registry, events
from .protocol import Event
from .workspace import create_workspace
from .meta import init_meta, finalize_meta, update_meta_from_event


async def dispatch(*, agent_id: str, ref, llm, session_id: str) -> AsyncIterator[Event]:
    if not registry.exists(agent_id):
        yield events.error(agent_id=agent_id, message=f"未知 agent: {agent_id}")
        return
    manifest = registry.get_manifest(agent_id)
    if not manifest.get("enabled", True):
        yield events.error(
            agent_id=agent_id,
            message=f"{manifest['label']} agent 暂未上线,请使用其他分析方式。",
        )
        return

    agent = registry.get_agent(agent_id)
    workspace = create_workspace(session_id=session_id, agent_id=agent_id)
    meta = init_meta(workspace=workspace, manifest=manifest, ref=ref, llm=llm)

    class _Ctx:
        def __init__(self):
            self.workspace = workspace
            self.session_id = session_id
        async def emit(self, ev: Event) -> None: pass
        async def log_decision(self, step_id: str, payload: dict) -> None: pass

    ctx = _Ctx()

    yield events.thinking(
        agent_id=agent_id, agent_label=manifest["label"],
        message=f"开始分析 {getattr(ref, 'name', '') or getattr(ref, 'symbol', '')}",
    )
    try:
        async for ev in agent.run(ref=ref, llm=llm, ctx=ctx):
            ev.setdefault("agent_id", agent_id)
            ev.setdefault("agent_label", manifest["label"])
            update_meta_from_event(workspace, meta, ev)
            yield ev
        finalize_meta(workspace, meta, status="done")
    except NotImplementedError as e:
        finalize_meta(workspace, meta, status="failed", error=str(e))
        yield events.error(agent_id=agent_id, message=str(e))
    except Exception as e:
        finalize_meta(workspace, meta, status="failed", error=str(e))
        yield events.error(agent_id=agent_id, message=f"{manifest['label']} 执行失败:{e}")
```

- [ ] **Step 4: 验证测试通过**

`python -m pytest backend/tests/agent_harness/ -x -q`
预期:9 PASS(6 registry/routing + 3 dispatcher)。

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent_harness/ backend/tests/agent_harness/
git commit -m "feat(harness): Agent Protocol + Registry + Routing + Dispatcher + Meta(multi-agent 核心)"
```

---

### Task 12.6: LLM Router + 澄清反问(routing 第 4 层 fallback)

**目的**:在 T12.5 三层 fallback(explicit / keyword / default)之上插入 LLM 意图分类层 — 当含糊请求(「这只股票怎么样」)既无 explicit 也无 keyword 时,由 LLM 看消息内容选 agent;若 LLM confidence < 0.6,通过 `thinking` 事件 + `quick_replies` 反问用户(严守 SSE 6 类铁律)。

**前置**:T12.5 已完成(`agent_harness/{protocol,registry,routing,events,dispatcher}.py` 就绪,`registry.list_enabled()` 与 `registry.exists()` 可用,`events.thinking()` / `events.done()` 工厂函数可用)。

**改动文件**:
- 新增 `backend/services/agent_harness/llm_router.py`(LLM 意图分类器)
- 修改 `backend/services/agent_harness/routing.py`(同步函数升级为 async,加第 4 层)
- 修改 `backend/services/agent_harness/events.py`(`thinking` 工厂支持 payload kwarg)
- 新增 `backend/tests/agent_harness/test_llm_router.py`
- 新增 `backend/tests/agent_harness/test_routing_clarify.py`

- [ ] **Step 1: 写失败测试 `backend/tests/agent_harness/test_llm_router.py`**

```python
# backend/tests/agent_harness/test_llm_router.py
import asyncio
import json
import pytest
from backend.services.agent_harness import llm_router, registry
import backend.services.agents  # 触发注册(依赖 T31.5 已完成;若未完成,可在 conftest 手动 register)


class _StubLLM:
    """可编程 LLM:complete_json 返回预设 raw 字符串。"""
    def __init__(self, raw: str, *, raise_exc: Exception | None = None,
                 sleep: float = 0.0):
        self.raw = raw
        self.raise_exc = raise_exc
        self.sleep = sleep
        self.calls = []

    async def complete_json(self, *, system: str, user: str, timeout: float = 10):
        self.calls.append({"system": system, "user": user, "timeout": timeout})
        if self.sleep:
            await asyncio.sleep(self.sleep)
        if self.raise_exc:
            raise self.raise_exc
        return self.raw


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) \
        if asyncio.get_event_loop().is_running() is False else asyncio.run(coro)


def test_high_confidence_returns_decision():
    raw = json.dumps({
        "agent_id": "cpa_conservative", "confidence": 0.9,
        "reason": "用户问长期持有,适合保守分析",
        "needs_clarification": False, "clarification_question": "",
    })
    llm = _StubLLM(raw)
    agents = registry.list_enabled()
    decision = asyncio.run(llm_router.classify(
        message="这只股票适合长期持有吗", llm=llm, agents=agents))
    assert decision.agent_id == "cpa_conservative"
    assert decision.confidence == pytest.approx(0.9)
    assert decision.needs_clarification is False
    # 验证 prompt 包含候选 agents
    assert "cpa_conservative" in llm.calls[0]["system"]
    assert "保守分析" in llm.calls[0]["system"]


def test_low_confidence_triggers_clarification():
    raw = json.dumps({
        "agent_id": None, "confidence": 0.4,
        "reason": "请求模糊", "needs_clarification": True,
        "clarification_question": "你是想做保守分析还是团队分析?",
    })
    decision = asyncio.run(llm_router.classify(
        message="我该买还是卖", llm=_StubLLM(raw),
        agents=registry.list_enabled()))
    assert decision.needs_clarification is True
    assert "保守分析" in decision.clarification_question


def test_invalid_json_falls_back_to_clarification():
    decision = asyncio.run(llm_router.classify(
        message="??", llm=_StubLLM("not a json {bad"),
        agents=registry.list_enabled()))
    assert decision.needs_clarification is True
    assert decision.confidence == 0.0
    assert "保守分析" in decision.clarification_question


def test_llm_exception_falls_back_to_clarification():
    decision = asyncio.run(llm_router.classify(
        message="hi", llm=_StubLLM("", raise_exc=RuntimeError("network")),
        agents=registry.list_enabled()))
    assert decision.needs_clarification is True
    assert decision.confidence == 0.0


def test_timeout_falls_back_to_clarification():
    decision = asyncio.run(llm_router.classify(
        message="hi",
        llm=_StubLLM("", raise_exc=asyncio.TimeoutError()),
        agents=registry.list_enabled()))
    assert decision.needs_clarification is True


def test_disabled_agent_in_response_is_rejected():
    """LLM 即使错选 enabled=false 的 agent,routing 层也要拦截。"""
    raw = json.dumps({
        "agent_id": "tradingagents_astock", "confidence": 0.95,
        "reason": "想要团队", "needs_clarification": False,
        "clarification_question": "",
    })
    decision = asyncio.run(llm_router.classify(
        message="团队", llm=_StubLLM(raw),
        agents=registry.list_enabled()))
    # classify 直接返回 LLM 决定;由 routing.resolve_agent 在 exists 校验时拒绝
    # 这里测试 classify 层不主动拒(让上层逻辑判断 enabled)
    assert decision.agent_id == "tradingagents_astock"
```

```python
# backend/tests/agent_harness/test_routing_clarify.py
import asyncio
import json
import pytest
from backend.services.agent_harness import routing
import backend.services.agents  # noqa


class _StubLLM:
    def __init__(self, raw):
        self.raw = raw
    async def complete_json(self, *, system, user, timeout=10):
        return self.raw


def _run(coro): return asyncio.run(coro)


def test_explicit_short_circuits_llm():
    """显式 agent_id 提供时,根本不调 LLM。"""
    llm = _StubLLM("should-not-be-called")
    decision = _run(routing.resolve_agent(
        message="任意消息", explicit_agent_id="cpa_conservative",
        default_agent_id="cpa_conservative", llm=llm))
    assert decision.reason == "explicit"
    assert decision.agent_id == "cpa_conservative"


def test_keyword_short_circuits_llm():
    decision = _run(routing.resolve_agent(
        message="保守分析这只票", explicit_agent_id=None,
        default_agent_id="cpa_conservative", llm=_StubLLM("never")))
    assert decision.reason == "keyword"
    assert decision.agent_id == "cpa_conservative"


def test_llm_router_high_confidence_used():
    raw = json.dumps({"agent_id": "cpa_conservative", "confidence": 0.85,
                      "reason": "x", "needs_clarification": False,
                      "clarification_question": ""})
    decision = _run(routing.resolve_agent(
        message="这只股票怎么样", explicit_agent_id=None,
        default_agent_id="cpa_conservative", llm=_StubLLM(raw)))
    assert decision.reason == "llm"
    assert decision.confidence >= 0.6


def test_llm_router_low_confidence_returns_clarify():
    raw = json.dumps({"agent_id": None, "confidence": 0.3,
                      "reason": "模糊", "needs_clarification": True,
                      "clarification_question": "你是想做保守分析还是团队分析?"})
    decision = _run(routing.resolve_agent(
        message="帮帮我", explicit_agent_id=None,
        default_agent_id="cpa_conservative", llm=_StubLLM(raw)))
    assert decision.reason == "clarify"
    assert decision.agent_id is None
    assert decision.clarification_question
    assert decision.quick_replies
    assert any(r["agent_id"] == "cpa_conservative" for r in decision.quick_replies)


def test_llm_picks_disabled_agent_falls_back_to_clarify():
    raw = json.dumps({"agent_id": "tradingagents_astock", "confidence": 0.9,
                      "reason": "x", "needs_clarification": False,
                      "clarification_question": ""})
    decision = _run(routing.resolve_agent(
        message="团队", explicit_agent_id=None,
        default_agent_id="cpa_conservative", llm=_StubLLM(raw)))
    # disabled agent 即使高 confidence,也应降级到 clarify(让用户重选)
    assert decision.reason == "clarify"


def test_message_too_short_skips_llm_returns_default():
    """消息 < 4 字符直接走 default,不调 LLM。"""
    decision = _run(routing.resolve_agent(
        message="嗯", explicit_agent_id=None,
        default_agent_id="cpa_conservative", llm=_StubLLM("never")))
    assert decision.reason == "default"
```

- [ ] **Step 2: 验证测试失败**

```bash
python -m pytest backend/tests/agent_harness/test_llm_router.py \
                  backend/tests/agent_harness/test_routing_clarify.py -x -q
```
预期:`ModuleNotFoundError: backend.services.agent_harness.llm_router` 或 `RouteDecision missing fields`(routing.py 旧签名同步函数)。

- [ ] **Step 3: 实现 `agent_harness/llm_router.py` + 升级 `routing.py`**

```python
# backend/services/agent_harness/llm_router.py
from __future__ import annotations
import asyncio
import json
import logging
from typing import Any
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

ROUTER_SYSTEM_PROMPT = """你是一个意图路由器。根据用户消息,从下面的 agents 中选择最合适的一个。

可选 agents:
{agents_json}

每个 agent 的 description 与 aliases 是判断依据。

输出严格 JSON,无任何额外文字:
{{
  "agent_id": "<agent_id 或 null 表示无法判断>",
  "confidence": <0.0-1.0 的浮点数>,
  "reason": "<一句话说明为什么选这个 agent>",
  "needs_clarification": <true/false>,
  "clarification_question": "<若 needs_clarification=true,反问用户的话;否则空串>"
}}

规则:
- confidence < 0.6 时,设 needs_clarification=true 并写一句反问。
- 反问要列出可选项(用 agents 的 label),例如「你是想做保守分析还是团队分析?」
- 不要选 enabled=false 的 agent(候选池已过滤)。
"""

ROUTER_USER_PROMPT = "用户消息:\n{message}"

DEFAULT_CLARIFICATION = "抱歉,我没听明白。你是想做保守分析(穿透回报率精算)还是团队分析(多角色辩论)?"
ROUTER_TIMEOUT_SEC = 10.0


class RouterDecision(BaseModel):
    agent_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    needs_clarification: bool
    clarification_question: str = ""


def _build_system_prompt(agents: list[dict]) -> str:
    payload = [
        {"id": a["id"], "label": a["label"],
         "description": a["description"], "aliases": a["aliases"]}
        for a in agents
    ]
    return ROUTER_SYSTEM_PROMPT.format(
        agents_json=json.dumps(payload, ensure_ascii=False, indent=2))


def _fallback(reason: str) -> RouterDecision:
    return RouterDecision(
        agent_id=None, confidence=0.0,
        reason=reason, needs_clarification=True,
        clarification_question=DEFAULT_CLARIFICATION,
    )


async def classify(*, message: str, llm: Any,
                   agents: list[dict]) -> RouterDecision:
    """非流式 LLM 调用,JSON 输出 → RouterDecision。失败时降级澄清。"""
    if not agents:
        return _fallback("无可用 agent")
    system = _build_system_prompt(agents)
    user = ROUTER_USER_PROMPT.format(message=message)
    try:
        raw = await asyncio.wait_for(
            llm.complete_json(system=system, user=user,
                              timeout=ROUTER_TIMEOUT_SEC),
            timeout=ROUTER_TIMEOUT_SEC + 1.0,
        )
    except asyncio.TimeoutError:
        logger.warning("LLM router timeout (>%.1fs); fallback to clarify",
                       ROUTER_TIMEOUT_SEC)
        return _fallback("LLM 路由超时")
    except Exception as e:
        logger.warning("LLM router exception: %s; fallback to clarify", e)
        return _fallback("LLM 路由异常")

    try:
        return RouterDecision.model_validate_json(raw)
    except ValidationError as e:
        logger.warning("LLM router JSON 解析失败: %s; raw=%s",
                       e, str(raw)[:200])
        return _fallback("LLM 路由解析失败")
```

```python
# backend/services/agent_harness/routing.py(r2 升级:async + 4 层 fallback)
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from . import registry, llm_router

CONFIDENCE_THRESHOLD = 0.6
MIN_MESSAGE_LEN_FOR_LLM = 4

DEFAULT_QUICK_REPLIES = [
    {"label": "保守分析", "agent_id": "cpa_conservative"},
    {"label": "团队分析", "agent_id": "tradingagents_astock"},
]


@dataclass
class RouteDecision:
    agent_id: str | None
    reason: str  # explicit / mention / keyword / llm / clarify / default
    confidence: float = 1.0
    clarification_question: str = ""
    quick_replies: list[dict] = field(default_factory=list)


def _parse_mention(message: str) -> str | None:
    """期 1 占位:简单解析 @<agent_id>;期 2 替换为 NLP 抽取。"""
    import re
    m = re.search(r"@([a-zA-Z_][\w-]*)", message)
    return m.group(1) if m else None


async def resolve_agent(*, message: str, explicit_agent_id: str | None,
                        default_agent_id: str, llm: Any) -> RouteDecision:
    # 1. explicit
    if explicit_agent_id and registry.exists(explicit_agent_id):
        return RouteDecision(explicit_agent_id, "explicit", 1.0)

    # 2. @mention(期 1 简易实现,期 2 强化)
    mention = _parse_mention(message)
    if mention and registry.exists(mention):
        return RouteDecision(mention, "mention", 1.0)

    # 3. keyword alias
    matched = registry.match_alias(message)
    if matched:
        return RouteDecision(matched, "keyword", 0.9)

    # 短消息直接 default,不浪费 token
    if len(message.strip()) < MIN_MESSAGE_LEN_FOR_LLM:
        return RouteDecision(default_agent_id, "default", 0.5)

    # 4. LLM router
    enabled = registry.list_enabled()
    decision = await llm_router.classify(
        message=message, llm=llm, agents=enabled)

    # disabled agent 拒绝(LLM 误选时)
    chosen_ok = (decision.agent_id is not None
                 and registry.exists(decision.agent_id)
                 and any(a["id"] == decision.agent_id for a in enabled))

    if (not decision.needs_clarification and chosen_ok
            and decision.confidence >= CONFIDENCE_THRESHOLD):
        return RouteDecision(decision.agent_id, "llm",
                              decision.confidence)

    # 4b. 澄清反问
    question = (decision.clarification_question
                or "抱歉,我没听明白。你是想做保守分析还是团队分析?")
    return RouteDecision(
        agent_id=None, reason="clarify",
        confidence=decision.confidence,
        clarification_question=question,
        quick_replies=list(DEFAULT_QUICK_REPLIES),
    )
```

**`events.thinking` 扩展**(若 T12.5 实现未支持 payload kwarg,加之):

```python
# backend/services/agent_harness/events.py 关键片段(确认或新增)
def thinking(*, agent_id: str | None = None,
             agent_label: str | None = None,
             payload: dict | None = None) -> dict:
    ev = {"type": "thinking"}
    if agent_id is not None: ev["agent_id"] = agent_id
    if agent_label is not None: ev["agent_label"] = agent_label
    if payload:
        # quick_replies / message 等附加字段直接展开到顶层 payload
        ev.update(payload)
    return ev
```

**`LLMClient` 接口扩展(`agent_harness/llm/base.py`)**:

```python
# 在 LLMClient 抽象类加非流式 JSON 完成方法(T13 已定义流式 stream;此方法需新增)
async def complete_json(self, *, system: str, user: str,
                        timeout: float = 10) -> str:
    """非流式调用,要求 LLM 输出严格 JSON 字符串。子类实现。"""
    raise NotImplementedError
```

OpenAICompatible / Anthropic 子类的具体实现在 T14/T15 已就绪流式方法,**T12.6 仅在 base 加抽象签名**;T14/T15 修订时各加 `complete_json` 实现(用 `response_format={"type":"json_object"}` 或 system 指令)。**临时**:T12.6 实施期 LLMClient 子类未实现 complete_json 时,测试用 `_StubLLM` 覆盖即可,生产 router 调用会触发 NotImplementedError → fallback 到 clarify(降级路径正确)。

- [ ] **Step 4: 验证测试通过**

```bash
python -m pytest backend/tests/agent_harness/test_llm_router.py \
                  backend/tests/agent_harness/test_routing_clarify.py -x -q
# 同时跑全量 harness 回归(routing.py 签名变 async,确保 T12.5 测试同步加 await)
python -m pytest backend/tests/agent_harness/ -x -q
```
预期:11 个新测试 PASS;若 T12.5 测试因 routing 函数签名变更失败,同步把 T12.5 测试中的 `routing.resolve_agent(...)` 调用改为 `asyncio.run(routing.resolve_agent(..., llm=_StubLLM("")))`(传哑 LLM,因 explicit/keyword 路径不调它)。

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent_harness/llm_router.py \
        backend/services/agent_harness/routing.py \
        backend/services/agent_harness/events.py \
        backend/services/agent_harness/llm/base.py \
        backend/tests/agent_harness/test_llm_router.py \
        backend/tests/agent_harness/test_routing_clarify.py
git commit -m "feat(harness): LLM router + 澄清反问(routing 第 4 层 fallback)"
```

> **后续依赖**:r1 T18 修订(见末尾「r1 Task 17/18 修订」段)的 `/chat/stream` 已经把 routing 调用换为 async + clarify 分支;r1 T14/T15 实现 `complete_json` 时,生产 LLM router 才完全可用。

---

### Task 31.5: 注册三个 agent 占位骨架(`cpa_conservative` / `tradingagents_astock` / `chitchat`)

**目的**:让 r1 T20 起的 cpa_conservative 实现工作能落入正确目录,同时验证 disabled agent 路由分支正常返回错误,实现可用的 chitchat agent。

- [ ] **Step 1: 写测试 `backend/tests/agents/test_agent_registration.py`**

```python
# backend/tests/agents/test_agent_registration.py
import asyncio
import pytest
from backend.services.agent_harness import dispatcher, registry
import backend.services.agents  # 触发注册


def _collect(aiter):
    async def _go():
        out = []
        async for ev in aiter: out.append(ev)
        return out
    return asyncio.run(_go())


class _Ref:
    symbol, name, market = "002594.SZ", "比亚迪", "A"


class _LLM:
    model, channel = "test", "test"
    async def stream(self, prompt, **kw):
        for c in "你好,问股助手在线。":
            yield c


def test_three_agents_registered_in_phase1():
    ids = {m["id"] for m in registry.list_manifests()}
    assert {"cpa_conservative", "tradingagents_astock", "chitchat"} <= ids
    enabled = {m["id"] for m in registry.list_manifests(only_enabled=True)}
    assert "cpa_conservative" in enabled
    assert "chitchat" in enabled
    assert "tradingagents_astock" not in enabled


def test_tradingagents_astock_returns_graceful_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.services.agent_harness.workspace.WORKSPACE_ROOT", tmp_path)
    out = _collect(dispatcher.dispatch(
        agent_id="tradingagents_astock", ref=_Ref(), llm=_LLM(), session_id="s-team"))
    types = [e["type"] for e in out]
    assert types == ["error"]
    assert "团队分析" in out[0]["message"]
    assert "暂未上线" in out[0]["message"]


def test_chitchat_agent_streams(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.services.agent_harness.workspace.WORKSPACE_ROOT", tmp_path)
    out = _collect(dispatcher.dispatch(
        agent_id="chitchat", ref=_Ref(), llm=_LLM(), session_id="s-chit"))
    types = [e["type"] for e in out]
    assert types[0] == "thinking"
    assert "generating" in types
    assert types[-1] == "done"
    assert "tool_start" not in types  # 闲聊无 step


def test_cpa_conservative_manifest_exposes_three_steps():
    """期 1 实施前的占位 agent 注册必须正确声明 step 序列。"""
    m = registry.get_manifest("cpa_conservative")
    step_ids = [s["id"] for s in m["steps"]]
    assert step_ids == ["data_pack", "quant", "valuation"]
    assert m["label"] == "保守分析"
    assert "保守分析" in m["aliases"]
```

- [ ] **Step 2: 验证测试失败**

```bash
mkdir -p backend/tests/agents && touch backend/tests/agents/__init__.py
python -m pytest backend/tests/agents/ -x -q
```
预期:ModuleNotFoundError(`backend.services.agents` 不存在)。

- [ ] **Step 3: 创建三个 agent 目录 + 注册**

完整代码清单:

```python
# backend/services/agents/__init__.py
"""导入即触发各 agent 向 registry 注册。"""
from . import cpa_conservative  # noqa: F401
from . import tradingagents_astock  # noqa: F401
from . import chitchat  # noqa: F401
```

**cpa_conservative**(占位骨架,r1 T20-T31 在此目录内填实):

```python
# backend/services/agents/cpa_conservative/__init__.py
from .manifest import MANIFEST
from backend.services.agent_harness import registry


class _Placeholder:
    """T20-T31 实施前的占位。实施时替换为真 CPAConservativeAgent。"""
    manifest = MANIFEST
    async def run(self, *, ref, llm, ctx):
        raise NotImplementedError("cpa_conservative agent 待 r1 T20-T31 实施完成")
        yield  # async generator marker


registry.register(MANIFEST, agent_factory=_Placeholder)
```

```python
# backend/services/agents/cpa_conservative/manifest.py
MANIFEST = {
    "id": "cpa_conservative",
    "label": "保守分析",
    "aliases": ["保守分析", "保守", "cpa", "穿透回报率", "龟龟"],
    "description": "基于 CPA 视角的极端保守假设穿透回报率精算,适合长期持有决策。",
    "version": "1.0.0",
    "steps": [
        {"id": "data_pack", "label": "拉取数据包",        "estimated_seconds": 30},
        {"id": "quant",     "label": "量化分析(穿透回报率)", "estimated_seconds": 180},
        {"id": "valuation", "label": "估值与报告组装",     "estimated_seconds": 120},
    ],
    "requires": [
        "llm.chat", "data.duckdb.daily", "data.duckdb.financial",
        "data.duckdb.dividend", "data.duckdb.valuation",
    ],
    "enabled": True,
}
```

**tradingagents_astock**:

```python
# backend/services/agents/tradingagents_astock/__init__.py
from .manifest import MANIFEST
from backend.services.agent_harness import registry


class _TradingAgent:
    manifest = MANIFEST
    async def run(self, *, ref, llm, ctx):
        # 永远走 dispatcher 的 enabled=False 短路;此处仅防御
        raise NotImplementedError(
            "团队分析 agent 计划于期 2 上线,基于 TradingAgents-Astock 多角色辩论框架。"
        )
        yield


registry.register(MANIFEST, agent_factory=_TradingAgent)
```

```python
# backend/services/agents/tradingagents_astock/manifest.py
MANIFEST = {
    "id": "tradingagents_astock",
    "label": "团队分析",
    "aliases": ["团队分析", "团队", "trading agents", "tradingagents"],
    "description": "[期 2 上线] 模拟分析师团队多角色辩论决策,适合事件驱动型机会判断。",
    "version": "0.0.0",
    "steps": [],
    "requires": ["llm.chat"],
    "enabled": False,
}
```

```markdown
<!-- backend/services/agents/tradingagents_astock/README.md -->
# tradingagents_astock(团队分析)

期 2 实施。原型参考:[TradingAgents-Astock](https://github.com/) 多角色辩论框架。

## 期 2 工作清单(占位)
- [ ] 搬运角色 prompts(看多/看空/风控等)
- [ ] 实现辩论循环 + 决议机制
- [ ] 接入 `agent_harness.data_layer` 取行情/财务/事件数据
- [ ] 实现 `agent.py::TeamAgent.run()`,改 manifest.enabled = True
```

**chitchat**:

```python
# backend/services/agents/chitchat/__init__.py
from .manifest import MANIFEST
from .agent import ChitchatAgent
from backend.services.agent_harness import registry

registry.register(MANIFEST, agent_factory=ChitchatAgent)
```

```python
# backend/services/agents/chitchat/manifest.py
MANIFEST = {
    "id": "chitchat",
    "label": "闲聊",
    "aliases": [],  # 不通过关键字路由,Coordinator intent classifier 显式选
    "description": "通用对话与帮助,不走分析流水线。",
    "version": "1.0.0",
    "steps": [],
    "requires": ["llm.chat"],
    "enabled": True,
}
```

```python
# backend/services/agents/chitchat/agent.py
from __future__ import annotations
from .manifest import MANIFEST
from backend.services.agent_harness import events


class ChitchatAgent:
    manifest = MANIFEST

    async def run(self, *, ref, llm, ctx):
        user_msg = getattr(ctx, "user_message", "你好")
        prompt = (
            "你是问股(Ask Stock)助手。回答简洁、有帮助。\n"
            f"用户:{user_msg}\n助手:"
        )
        async for chunk in llm.stream(prompt):
            if not chunk:
                continue
            yield events.generating(agent_id=MANIFEST["id"], step_id="chat", delta=chunk)
        yield events.done(agent_id=MANIFEST["id"])
```

**让 main.py 启动时触发注册**:

```python
# backend/main.py 的 lifespan 中(注释 + 一行 import):
# 触发 agent 注册(导入即注册到 agent_harness.registry)
import backend.services.agents  # noqa: F401
```

- [ ] **Step 4: 验证测试通过**

```bash
python -m pytest backend/tests/agents/ backend/tests/agent_harness/ -x -q
```
预期:13 PASS(9 harness + 4 agents)。

- [ ] **Step 5: Commit**

```bash
git add backend/services/agents/ backend/tests/agents/ backend/main.py
git commit -m "feat(agents): 注册 cpa_conservative(占位)+ tradingagents_astock(disabled)+ chitchat"
```

---

### r1 Task 7 修订(workspace 加 agent_id)

如 r1 T7 仍未实施,**直接采用** Task 12.5 Step 3 中的 `agent_harness/workspace.py` 实现(签名为 `create_workspace(*, session_id, agent_id)`),跳过 r1 T7 原版。

如 r1 T7 已实施(单参数),则在 T12.5 Step 3 实施前用一次 edit 把 `create_workspace` 签名改掉,所有 caller(若已存在)同步加 `agent_id` 参数。

---

### r1 Task 17/18 修订(Coordinator + /chat/stream 接 dispatcher)

r1 T17 原本实现 Coordinator chitchat 分支。r2 改为:

- **Coordinator 只做 intent classify**:`classify_intent(message) -> "analyze" | "chitchat" | "qa_followup"`
- 三种 intent 都走 dispatcher:
  - `analyze` → `routing.resolve_agent` → `dispatcher.dispatch(agent_id, ref, ...)`
  - `chitchat` → 显式 `dispatcher.dispatch(agent_id="chitchat", ref=None, ...)`(`ref` 可传 None,workspace 仍按 chitchat 创建)
  - `qa_followup` → `dispatcher.dispatch(agent_id="chitchat", ...)`,但通过 `ctx.user_message` 注入"基于上次报告回答..."的 prompt 前缀

r1 T18 `/chat/stream` 路由代码改为(**r2 路由补丁:四层 fallback + 澄清反问**):

```python
# backend/routers/agent.py 关键 handler
from backend.services.agent_harness import routing, dispatcher, events
from backend.services.agent_harness.symbol import resolve as resolve_symbol
from backend.services.system_config.store import get_config


@router.post("/chat/stream")
async def chat_stream(req: Request):
    body = await req.json()
    session_id = body["session_id"]
    message = body["message"]
    explicit_agent_id = body.get("agent_id")  # 可选,UI「分析方式」下拉传

    cfg = get_config()
    default_agent_id = cfg.get("default_agent_id", "cpa_conservative")

    intent = classify_intent(message)  # analyze / chitchat / qa_followup

    async def _gen():
        llm = _build_llm(session_id)

        if intent == "analyze":
            # 四层 fallback:explicit → @mention → keyword → LLM router → default
            decision = await routing.resolve_agent(
                message=message,
                explicit_agent_id=explicit_agent_id,
                default_agent_id=default_agent_id,
                llm=llm,
            )

            # 澄清分支:LLM router confidence < 0.6 → 不进 dispatch,反问用户
            if decision.reason == "clarify":
                yield _sse(events.thinking(
                    agent_id=None, agent_label="路由助手",
                    payload={
                        "message": decision.clarification_question,
                        "quick_replies": decision.quick_replies,
                    },
                ))
                yield _sse(events.done(agent_id=None,
                                        payload={"reason": "clarify_pending"}))
                return

            ref = resolve_symbol(message)
            async for ev in dispatcher.dispatch(
                agent_id=decision.agent_id, ref=ref, llm=llm,
                session_id=session_id):
                yield _sse(ev)
        else:  # chitchat / qa_followup 都走 chitchat agent
            # 注入 user_message 到 ctx(通过自定义 Ref hack,期 2 改为 ctx 字段)
            async for ev in dispatcher.dispatch(
                agent_id="chitchat", ref=_NoRef(message=message),
                llm=llm, session_id=session_id):
                yield _sse(ev)

    return StreamingResponse(_gen(), media_type="text/event-stream")
```

> 注:`resolve_agent` 在 r2 升级为 **async** 函数(因 LLM router 内部要 await)。T12.5 Step 3 实现的同步版本在 T12.6 Step 3 改为 async,所有 caller 同步加 await。

**`_NoRef` 小工具**:把 `user_message` 携带到 ctx 让 ChitchatAgent 读取:

```python
# 临时数据结构,不对外暴露
class _NoRef:
    def __init__(self, message: str):
        self.symbol = None
        self.name = None
        self.market = None
        self.user_message = message  # ChitchatAgent 通过 getattr 读取(已在其代码中处理)
```

> ⚠️ **设计权衡**:把 `user_message` 挂在 ref 上略 hacky,但避免改动 Agent Protocol 签名。期 2 若多 agent 都需要消息上下文,可以扩展 `HarnessContext.user_message` 字段。

---

### r1 Task 31 修订(实现 cpa_conservative.agent.py)

r1 T31 原写「Coordinator.run_full_pipeline」,r2 改为「实现 `CPAConservativeAgent.run()`」,内容大体相同(串 phase1 → phase3.1 → phase3.2),但:

- 用 `events.tool_start/tool_done/generating/done` 构造器,**不要**手写 dict
- 通过 `ctx.workspace` 而非自分配
- step_id 直接用 manifest 中声明的 `data_pack/quant/valuation`,确保前端 step 推进与 manifest steps 序列一致

替换 r1 T31 Step 3 的实现为:

```python
# backend/services/agents/cpa_conservative/agent.py
from __future__ import annotations
from typing import AsyncIterator
from .manifest import MANIFEST
from .data_pack import build_data_pack  # r1 T20-T26 实现
from .phases import run_quant, run_valuation  # r1 T29-T30 合并实现
from backend.services.agent_harness import events
from backend.services.agent_harness.protocol import Event


class CPAConservativeAgent:
    manifest = MANIFEST

    async def run(self, *, ref, llm, ctx) -> AsyncIterator[Event]:
        steps = MANIFEST["steps"]
        total = len(steps)

        # ---- Step 1: data_pack ----
        yield events.tool_start(
            agent_id=MANIFEST["id"], agent_label=MANIFEST["label"],
            step_id="data_pack", step_label=steps[0]["label"],
            step_index=1, step_total=total,
        )
        try:
            build_data_pack(ref=ref, workspace=ctx.workspace)
        except Exception as e:
            yield events.error(agent_id=MANIFEST["id"], message=f"数据包构建失败:{e}")
            return
        yield events.tool_done(agent_id=MANIFEST["id"], step_id="data_pack")

        # ---- Step 2: quant ----
        yield events.tool_start(
            agent_id=MANIFEST["id"], agent_label=MANIFEST["label"],
            step_id="quant", step_label=steps[1]["label"],
            step_index=2, step_total=total,
        )

        async def _q_chunk(s: str):
            pass  # 占位,实际通过下面的 wrapper

        chunks_q: list[Event] = []
        async def _on_chunk_q(s: str):
            chunks_q.append(events.generating(
                agent_id=MANIFEST["id"], step_id="quant", delta=s))

        try:
            _, parsed = await run_quant(
                workspace=ctx.workspace, llm=llm, on_chunk=_on_chunk_q)
        except Exception as e:
            yield events.error(agent_id=MANIFEST["id"], message=f"量化失败:{e}")
            return
        for ev in chunks_q:
            yield ev
        yield events.tool_done(agent_id=MANIFEST["id"], step_id="quant")

        # ---- Step 3: valuation ----
        yield events.tool_start(
            agent_id=MANIFEST["id"], agent_label=MANIFEST["label"],
            step_id="valuation", step_label=steps[2]["label"],
            step_index=3, step_total=total,
        )
        chunks_v: list[Event] = []
        async def _on_chunk_v(s: str):
            chunks_v.append(events.generating(
                agent_id=MANIFEST["id"], step_id="valuation", delta=s))

        try:
            report_path = await run_valuation(
                workspace=ctx.workspace, llm=llm,
                company_name=ref.name or ref.symbol, symbol=ref.symbol,
                quant_results=parsed, on_chunk=_on_chunk_v)
        except Exception as e:
            yield events.error(agent_id=MANIFEST["id"], message=f"估值失败:{e}")
            return
        for ev in chunks_v:
            yield ev
        yield events.tool_done(agent_id=MANIFEST["id"], step_id="valuation")
        yield events.done(agent_id=MANIFEST["id"], report_path=str(report_path))
```

并修改 `cpa_conservative/__init__.py`:把 `_Placeholder` 替换为 `CPAConservativeAgent`(在 r1 T20-T31 全部实施完成后)。

---

### r1 Task 32 增量(多 agent 路由 E2E)

在 r1 T32 e2e 测试基础上,**追加**:

```python
# backend/tests/agent/test_chat_stream_e2e.py 追加

def test_chat_stream_routes_to_team_keyword(tmp_path, monkeypatch):
    """关键字「团队分析」路由到 disabled agent,返回 error 事件且 agent_id 正确。"""
    monkeypatch.setattr(
        "backend.services.agent_harness.workspace.WORKSPACE_ROOT", tmp_path)
    with patch("backend.routers.agent._build_llm", return_value=_FakeLLM([])):
        client = TestClient(app)
        resp = client.post(
            "/api/v1/agent/chat/stream",
            json={"session_id": "team-1", "message": "团队分析 002594"},
        )
    events = _parse_sse(resp.text)
    types = [e["type"] for e in events]
    assert types[-1] == "error"
    assert events[-1]["agent_id"] == "tradingagents_astock"
    assert "暂未上线" in events[-1]["message"]


def test_chat_stream_routes_to_cpa_keyword(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.services.agent_harness.workspace.WORKSPACE_ROOT", tmp_path)
    # 用与 test_chat_stream_full_pipeline_e2e 相同的 fake_phase1/fake_llm 设置
    # 但消息为「保守分析 002594」
    # 断言所有 tool_start.agent_id == "cpa_conservative"
    ...


def test_chat_stream_explicit_agent_id_overrides_keyword(tmp_path, monkeypatch):
    """body 显式 agent_id 覆盖关键字。"""
    monkeypatch.setattr(
        "backend.services.agent_harness.workspace.WORKSPACE_ROOT", tmp_path)
    with patch("backend.routers.agent._build_llm", return_value=_FakeLLM([])):
        client = TestClient(app)
        resp = client.post(
            "/api/v1/agent/chat/stream",
            json={
                "session_id": "explicit-1",
                "message": "保守分析 002594",  # keyword 命中 cpa
                "agent_id": "tradingagents_astock",  # 但显式参数胜出
            },
        )
    events = _parse_sse(resp.text)
    assert events[-1]["agent_id"] == "tradingagents_astock"
    assert events[-1]["type"] == "error"
```

---

### r1 Task 33 增量(多 agent 烟囱)

`scripts/smoke_ask_stock.py` 加一段:

```python
async def _smoke_team_disabled():
    """验证团队分析 agent 当前返回优雅错误。"""
    llm = build_llm_for_channel("deepseek")
    from backend.services.agent_harness import dispatcher
    types = []
    async for ev in dispatcher.dispatch(
        agent_id="tradingagents_astock", ref=_DummyRef("002594.SZ", "比亚迪", "A"),
        llm=llm, session_id="smoke-team",
    ):
        types.append(ev["type"])
    assert types == ["error"], f"expected single error, got {types}"
    print("✅ tradingagents_astock 优雅 error 验证通过")
```

并在 `main()` 末尾调用 `await _smoke_team_disabled()`。

---

### r1 Task 34 增量(AGENTS.md multi-agent 段)

如 r2-D 所示,在 AGENTS.md 的「Goal」之后插入「## 问股 Multi-Agent 架构」段。

---

### Phase F 总结

| 新任务 | 工作量 | 前置 | 后续依赖 |
|---|---|---|---|
| T12.5 | ~6h | r1 T1-T11 | r1 T17/T18/T20+ 全部依赖此 |
| T31.5 | ~2h | T12.5 | r1 T20+ 期望 cpa_conservative 目录已就位 |
| r1 T7 修订 | ~1h | — | T12.5 |
| r1 T17/T18 修订 | ~3h | T12.5 + T31.5 | r1 T19+ |
| r1 T31 修订 | ~2h | r1 T20-T30 全部完成 | r1 T32 |
| r1 T32/T33/T34 增量 | ~3h | 各自前置 | — |

**Phase F 总工作量**:~17h ≈ 2 工作日(吸收在原 11-12 天预算内)。

