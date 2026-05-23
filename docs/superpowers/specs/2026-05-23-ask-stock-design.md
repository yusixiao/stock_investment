# 问股(Ask Stock)后端设计

> **状态**:Spec r2(Multi-Agent Harness 修订)
> **日期**:2026-05-23(r1)/ 2026-05-23(r2 multi-agent)
> **范围**:把多个投资研究 agent(期 1 落地 `cpa_conservative`,期 2 加 `tradingagents_astock`,后续可扩展)通过统一 harness 接入本项目,以对话式 UI 产出投资分析报告。
> **替代**:`docs/design_ask_stock.md` v2(旧)。本 spec(尤其是 r2 §12-§14)为权威来源。
>
> **r2 重大变更**:从「单一 turtle pipeline」改为「multi-agent harness」。**§12-§15 是权威**,与早前章节(§2、§4.2、§5、§10)有冲突时以 r2 为准。早前章节作为历史参考保留。
>
> **r2 路由补丁**(2026-05-23 末轮决策):路由策略从三层升级为**四层 fallback**(加 LLM router 层),新增 §15 LLM Router 设计;§14 决策表加 D9-D11。期 1 单 agent only,**不做编排**(期 2 才加 OrchestratorAgent)。

---

## 1. 目的与边界

### 1.1 要解决的问题

前端 `ChatPage` 已落地(React 19 + zustand + react-markdown + 6 类 SSE 事件解析器),但后端只有占位空 stub。本 spec 设计后端 `/api/v1/agent/*` + `/api/v1/system/config/*`,把用户输入"分析比亚迪 002594"转化为完整的投资分析报告(对齐 turtle 框架的 7 phase + 11 步穿透回报率 + 估值组装)。

### 1.2 期次边界(锁定)

| 期 | 范围 | 关键交付 |
|---|---|---|
| **期 1**(本 spec 主要覆盖) | 基础设施 + Phase 1 数据包(§1-§17,DuckDB)+ Phase 3.1 CPA 量化分析(11 步)+ Phase 3.2 估值/报告组装 + system_config 后端 + auth stub + 闲聊/追问 | 用户输入"分析 002594"得到完整 markdown 报告 |
| 期 2 | `/business-analysis` 三 Agent 定性分析(搬 turtle `shared/qualitative/`,6 维度+结构化参数) | `qualitative_report.md` 注入 Phase 3 上下文 |
| 期 3 | PDF 自动下载 + PDF 附注解析(Phase 0 + Phase 2)+ 前端文件上传 UI | 支持 P2/P3/P4/P6 附注 |

**期 1 内不做**:定性分析(期 2)、PDF 处理(期 3)、文件上传 UI(期 3)、token 用量统计页、SSE 心跳。

### 1.3 关键设计约束(从代码取证锁定)

| # | 约束 | 来源 |
|---|---|---|
| C1 | **SSE 事件类型限制为 6 类**:`thinking / tool_start / tool_done / generating / done / error`。Phase 进度映射为 `tool_start/tool_done`,**禁止**新发明 `request_upload / ask / substep` 事件 | `frontend/src/stores/agentChatStore.ts:265-283` 解析器仅识别此 6 类 |
| C2 | **期 1 后端无文件上传 API**;期 3 才在前端加上传 UI | 前端无 `<input type="file">` / FormData 代码 |
| C3 | **期 1 完全跳过 auth**:后端零 auth 逻辑,`GET /auth/status` 永返 `{authEnabled: false}` | `grep -r 'auth\|Bearer\|jwt' backend/` 全 0 命中 |
| C4 | **system_config 用扁平 `{key: value}` KV 模型**,key 形如 `LLM_<NAME>_BASE_URL / _API_KEY / _MODEL / ...`,持久化到 `data/system_config.yaml`;channel 结构在服务层从 KV 重建 | `frontend/src/components/settings/LLMChannelEditor.tsx:953-1024` 用扁平键 |
| C5 | **数据包 §1-§17 schema 权威源** = `Turtle_investment_framework/scripts/tushare_modules/assembly.py:206-437`(`assemble_data_pack`)。我方用 DuckDB 还原,不引 Tushare | turtle main 分支取证 |
| C6 | **代码 normalize**:A 股 `XXXXXX.SH/SZ`、港股 `XXXXX.HK`、美股 `AAPL`(US 不带后缀,对齐 `stock_index` 现状)| `backend/services/stock_index.py` |

---

## 2. 总体架构

### 2.1 流水线全景(期 1)

```
┌────────────── 用户 ──────────────┐
│ ChatPage: "分析 002594 比亚迪"     │
└─────────────┬───────────────────┘
              │ POST /api/v1/agent/chat/stream
              ▼
┌──────────────────────────────────────────────────┐
│            Coordinator(协调器)                    │
│  • normalize 代码 → 002594.SZ                     │
│  • 创建/复用 {output_dir}                         │
│  • 路由判断:                                      │
│    ├─ 已有报告 → QA 追问模式(单次 LLM)            │
│    ├─ 提取到股票码 → 完整流水线                   │
│    └─ 否则 → 闲聊(单次 LLM)                       │
│  • 各阶段发 SSE tool_start/tool_done              │
└─────────────┬────────────────────────────────────┘
              │
   ┌──────────┼──────────┐
   ▼          ▼          ▼
┌─────────┐ ┌─────────────┐ ┌─────────────┐
│ Phase 1 │ │ Phase 3.1   │ │ Phase 3.2   │
│ 数据包  │→│ CPA 量化     │→│ 估值/报告    │
│ DuckDB  │ │ 11 步穿透    │ │ 组装        │
│ 适配器  │ │ (LLM)        │ │ (LLM)       │
└─────────┘ └─────────────┘ └─────────────┘
              │
              ▼
        最终 markdown 报告通过 SSE done.content 推回
```

期 2 在 Phase 1 与 Phase 3.1 之间插入定性分析(Agent A);期 3 在 Phase 1 之前插入 Phase 0 PDF 下载,在 Phase 1 之后插入 Phase 2 PDF 解析。本 spec 的 Coordinator 接口预留 hook 点,但期 1 不实现这两条分支。

### 2.2 模块边界(每个文件单一职责)

```
backend/
├── routers/
│   ├── agent.py              # /api/v1/agent/* 路由分发
│   ├── system_config.py      # /api/v1/system/config/* 扁平 KV CRUD
│   └── auth_stub.py          # /api/v1/auth/status(永返 disabled)
└── services/
    ├── system_config/
    │   ├── store.py          # data/system_config.yaml 读写(原子写)
    │   ├── schema.py         # Pydantic:扁平键 → 校验
    │   ├── channels.py       # KV → ChannelConfig 重建/反向写回
    │   ├── llm_client.py     # LLMClient 抽象 + 4 协议实现
    │   └── llm_test.py       # POST /system/config/test 用
    └── agent/
        ├── symbol.py         # normalize: 002594→002594.SZ; AAPL→AAPL
        ├── sse.py            # SSE 帧编码 + 6 类事件辅助函数
        ├── session_repo.py   # SQLite chat_sessions/chat_messages CRUD
        ├── coordinator.py    # 路由判断 + phase 编排 + 决策日志
        ├── parser.py         # LLM 输出解析(11 步关键字段提取)
        ├── llm_routing.py    # 按 phase 选 channel(default fallback)
        ├── workspace.py      # data/agent_runs/{code}_{name}/ 目录管理
        ├── pipeline/
        │   ├── phase1_data_pack/
        │   │   ├── builder.py           # 编排器
        │   │   ├── sections/             # §1-§17 各一文件
        │   │   │   ├── s01_basic.py
        │   │   │   ├── s02_market.py
        │   │   │   ├── s03_income.py
        │   │   │   ├── ... (16 个 section)
        │   │   │   └── s17_derived.py
        │   │   └── derived/              # 9 个派生指标计算
        │   ├── phase3_quant.py           # 调 LLM 跑 Agent B prompt
        │   └── phase3_valuation.py       # 调 LLM 跑 Agent C prompt
        └── prompts/turtle/               # 从 turtle 复制的 6 文件
            ├── phase3_quantitative.md
            ├── phase3_valuation.md
            └── references/
                ├── shared_tables.md
                ├── factor_interface.md
                ├── judgment_examples_turtle.md
                └── output_schema.md

backend/tests/agent/                       # 期 1 ≥ 30 个 test
    ├── test_symbol.py
    ├── test_sse.py
    ├── test_session_repo.py
    ├── test_workspace.py
    ├── test_phase1_sections.py
    ├── test_data_pack_builder.py
    ├── test_phase3_quant_parser.py
    ├── test_coordinator_routing.py
    ├── test_llm_client_openai.py
    ├── test_llm_client_anthropic.py
    └── test_system_config_store.py
```

### 2.3 数据/产物目录

```
data/
├── agent_runs/{code}_{name}/             # 每只股票一目录
│   ├── data_pack_market.md               # Phase 1 产出
│   ├── phase3_quantitative.md            # Phase 3.1 产出
│   ├── {name}_{code}_分析报告.md          # Phase 3.2 产出 ⇐ 最终交付
│   ├── _meta.json                        # 阶段状态/时间戳/绑定 session
│   └── _decisions.jsonl                  # 决策日志(对齐 backtest)
├── system_config.yaml                    # 扁平 KV
└── portfolio.db                          # 既有 SQLite,新增两表
```

---

## 3. 数据模型

### 3.1 SQLite 新增表(对齐 `services/db_schema.py` 既有迁移模式)

```sql
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id      TEXT PRIMARY KEY,             -- 前端 UUID
    title           TEXT NOT NULL DEFAULT '',     -- 首条消息前 60 字
    stock_code      TEXT,                         -- 002594.SZ
    output_dir      TEXT,                         -- data/agent_runs/...
    status          TEXT NOT NULL DEFAULT 'idle', -- idle/running/done/failed/cancelled
    current_phase   TEXT,                         -- phase1/phase3.1/phase3.2/qa/chitchat
    created_at      TEXT NOT NULL,
    last_active     TEXT NOT NULL,
    msg_count       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_sessions_last_active ON chat_sessions(last_active DESC);

CREATE TABLE IF NOT EXISTS chat_messages (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,                    -- user/assistant/system
    content     TEXT NOT NULL,
    context     TEXT,                             -- JSON: stock_code/record_id 等
    thinking    TEXT,                             -- JSON: progressSteps[] 数组
    artifacts   TEXT,                             -- JSON: [{name, url}]
    tokens_in   INTEGER,
    tokens_out  INTEGER,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
);
CREATE INDEX idx_messages_session ON chat_messages(session_id, created_at);
```

**Lazy session 创建**:前端在 localStorage 维护 `dsa_chat_session_id`(UUID),首次 `POST /chat/stream` 命中时若 `session_id` 不存在则插入空行(C-key 来自前端)。

### 3.2 system_config.yaml(扁平 KV)

```yaml
# 一对多 LLM channels: LLM_<NAME>_*
LLM_DEEPSEEK_PROVIDER: deepseek
LLM_DEEPSEEK_BASE_URL: https://api.deepseek.com
LLM_DEEPSEEK_API_KEY: sk-xxxxx
LLM_DEEPSEEK_MODEL: deepseek-chat
LLM_DEEPSEEK_MAX_TOKENS: "8192"
LLM_DEEPSEEK_TEMPERATURE: "0.3"
LLM_DEEPSEEK_TIMEOUT: "120"

LLM_SONNET_PROVIDER: anthropic
LLM_SONNET_BASE_URL: https://api.anthropic.com
LLM_SONNET_API_KEY: sk-ant-xxxxx
LLM_SONNET_MODEL: claude-3-5-sonnet-20241022

# 默认与路由
LLM_DEFAULT_CHANNEL: DEEPSEEK
LLM_ROUTE_PHASE3_QUANT: SONNET
LLM_ROUTE_PHASE3_VALUATION: SONNET
LLM_ROUTE_QA_FOLLOWUP: DEEPSEEK
LLM_ROUTE_CHITCHAT: DEEPSEEK
```

`channels.py` 把扁平 KV 重组成 `List[ChannelConfig]` 给业务层用,但持久化和 API 都保持扁平形态。

**API wire 约定**(对齐前端取证):
- system_config 系列:**snake_case**(请求/响应都是 `{key, value}` / `{items: [...]}`)
- auth 系列:**camelCase**(`{authEnabled: false}`)

### 3.3 `_meta.json`(每 run 状态)

```json
{
  "stock_code": "002594.SZ",
  "company": "比亚迪",
  "session_id": "uuid",
  "started_at": "2026-05-23T10:00:00Z",
  "phases": {
    "phase1_data_pack":     {"status": "done", "duration": 1.8},
    "phase3_quantitative":  {"status": "done", "duration": 380.2},
    "phase3_valuation":     {"status": "done", "duration": 210.0}
  },
  "artifacts": ["data_pack_market.md", "phase3_quantitative.md", "比亚迪_002594.SZ_分析报告.md"],
  "errors": []
}
```

---

## 4. 核心流程:`POST /chat/stream` 时序

### 4.1 请求体(沿用前端契约)

```json
{
  "message": "分析比亚迪 002594",
  "session_id": "uuid",
  "skills": [],
  "context": {"stock_code": "002594", "stock_name": "比亚迪", "record_id": null}
}
```

### 4.2 SSE 事件序列(完整流水线,期 1)

**严格只用 6 类事件**(C1)。phase 进度通过 `tool_start/tool_done` 表达,`tool` 字段填 phase 名,`display_name` 填中文短描述。

```
data: {"type":"thinking","content":"识别股票:002594.SZ 比亚迪"}

data: {"type":"tool_start","tool":"phase1_data_pack","display_name":"采集市场数据 (§1-§17)"}
data: {"type":"tool_done", "tool":"phase1_data_pack","display_name":"市场数据包","success":true,"duration":1.8}

data: {"type":"tool_start","tool":"phase3_quantitative","display_name":"CPA 量化分析(11 步穿透回报率)"}
data: {"type":"generating","content":"Step 0 数据校验..."}     // ← 可选,用于流式 LLM 中间输出
data: {"type":"generating","content":"Step 3 利润穿透..."}
data: {"type":"tool_done", "tool":"phase3_quantitative","success":true,"duration":380.2}

data: {"type":"tool_start","tool":"phase3_valuation","display_name":"估值与报告组装"}
data: {"type":"tool_done", "tool":"phase3_valuation","success":true,"duration":210.0}

data: {"type":"done","success":true,
       "content":"# 比亚迪(002594.SZ) 投资分析报告\n\n## 结论\n...(完整 markdown)",
       "artifacts":[{"name":"比亚迪_002594.SZ_分析报告.md",
                     "url":"/api/v1/agent/sessions/{sid}/artifacts/比亚迪_002594.SZ_分析报告.md"}]}
```

**Substep 表达**:Phase 3.1 内的 11 步用 `generating` 事件(自由文本流)而非新事件类型。前端 agentChatStore 已知如何累计 `generating.content`。

### 4.3 SSE 事件类型表(严格 6 类)

| type | 字段 | 用途 |
|---|---|---|
| `thinking` | `content` | 思考/路由文字 |
| `tool_start` | `tool, display_name` | Phase 开始 |
| `tool_done` | `tool, display_name?, success, duration?, message?` | Phase 完成 |
| `generating` | `content` | 流式 LLM 输出片段(累积到当前 progressStep) |
| `done` | `success, content, artifacts[]` | 终态 |
| `error` | `error, message, phase?` | 致命错误 |

### 4.4 路由判断

```python
def route_message(session, message, context):
    if session.output_dir and (Path(session.output_dir) / "_meta.json").exists():
        meta = load_meta(session.output_dir)
        if "phase3_valuation" in meta["phases"] and meta["phases"]["phase3_valuation"]["status"] == "done":
            return run_qa_followup(session, message)
    if extracted := symbol.extract(message, context):
        return run_full_pipeline(session, extracted)
    return run_chitchat(session, message)
```

### 4.5 异常路径

| 情况 | 处理 |
|---|---|
| 股票码识别失败 | 发 `thinking` + 降级到 chitchat,提示"未识别到股票码,请明确说明 6 位代码" |
| Phase 1 数据缺失(财务<5 年等)| 在 `data_pack_market.md` §13 标 warning,继续 |
| LLM 调用失败 | 重试 1 次(2s 退避);再失败发 `error` 事件,**保留**已生成的中间产物(下次断点续跑) |
| 用户 abort | 检测 `request.is_disconnected()`,中止后续 phase,`_meta.json` 标 `status=cancelled` |
| 阶段超时(§4.6) | 强制中止,`error` 推前端 |

### 4.6 阶段超时

| 阶段 | 超时 |
|---|---|
| Phase 1 数据包 | 60s |
| Phase 3.1 量化 | 10 min |
| Phase 3.2 估值 | 5 min |
| QA 追问 | 2 min |
| **总管线** | ≤ 20 min(期 1,无 PDF/定性)|

---

## 5. 组件详细设计

### 5.1 `services/agent/symbol.py`

**职责**:股票码识别 + 市场归一化。**单一接口** — 其他模块不直接 regex 解析。

```python
def extract(message: str, context: dict | None) -> StockRef | None:
    """从自然语言/context 提取股票引用,返回 None 表示无识别"""

def normalize(raw: str) -> str:
    """002594 → 002594.SZ;00700 → 00700.HK;AAPL → AAPL"""

@dataclass
class StockRef:
    code: str         # normalized
    name: str         # 中文名(从 stock_index 查)
    market: Literal["A", "HK", "US"]
```

依赖 `services/stock_index.py:get_name() / search_stocks()`(已存在)。

### 5.2 `services/agent/sse.py`

```python
def encode(event: dict) -> bytes:
    """SSE 帧:data: <json>\n\n"""

# 6 个工厂函数,签名严格对应前端字段
def thinking(content: str) -> dict: ...
def tool_start(tool: str, display_name: str) -> dict: ...
def tool_done(tool: str, success: bool, duration: float | None = None,
              message: str | None = None, display_name: str | None = None) -> dict: ...
def generating(content: str) -> dict: ...
def done(content: str, artifacts: list[dict]) -> dict: ...
def error(error_code: str, message: str, phase: str | None = None) -> dict: ...
```

**禁止**:在其他模块裸字典发 SSE,必须走这 6 个工厂。

### 5.3 `services/agent/coordinator.py`

```python
class Coordinator:
    def __init__(self, session, sse_send, decision_log):
        ...

    async def run(self, message: str, context: dict) -> None:
        """主入口,内部 route + 编排,通过 sse_send 推前端"""

    async def _run_full_pipeline(self, ref: StockRef): ...
    async def _run_qa_followup(self, message: str): ...
    async def _run_chitchat(self, message: str): ...
```

**断点续跑**:每 phase 开始前检查 `_meta.json` 中该 phase status,若 `done` 则跳过(读盘加载产物);若 `failed` 则重跑。

### 5.4 `services/agent/pipeline/phase1_data_pack/builder.py`

```python
class DataPackBuilder:
    def __init__(self, store: DuckDBStore, stock_index, indicators_cache):
        ...

    def build(self, ref: StockRef, output_dir: Path) -> Path:
        sections = [
            s01_basic.build(ref),
            s02_market.build(ref, self.store),
            s03_income.build(ref, self.store, years=5),
            # ... 共 16 个 section + 9 个 derived
        ]
        out = output_dir / "data_pack_market.md"
        out.write_text("\n\n".join(filter(None, sections)), encoding="utf-8")
        return out
```

**每个 section 是独立模块**(单一职责),签名 `build(ref, *deps) -> str | None`。返回 `None` 表示该 section 不适用(如 §3P A 股母公司报表对港股/美股返回 None)。

**期 1 内不做的 section**:§7(控股股东)/ §8(行业竞争)/ §10(ESG)/ §13.2(WebSearch warnings),这些需要 WebSearch Agent(期 2 引入)。期 1 这几节输出占位文字 `"⚠️ 数据需 Phase 1B WebSearch(期 2 实现)"`,Phase 3 prompt 已知如何降级。

### 5.5 `services/agent/pipeline/phase3_quant.py`

```python
async def run(ref: StockRef, output_dir: Path, llm_client: LLMClient,
              decision_log, sse_send) -> Path:
    """
    1. 读 data_pack_market.md
    2. 拼 prompts/turtle/phase3_quantitative.md + 数据包
    3. LLM stream 调用,累积全文
    4. parser 提取 11 步关键字段(GG, II, ROIC...)
    5. 写 phase3_quantitative.md
    """
```

`parser.py` 用正则抽取 LLM 输出末尾的结构化结果块(turtle prompt 强制包含 `<results>...</results>` 节)。

### 5.6 `services/agent/pipeline/phase3_valuation.py`

读取 `phase3_quantitative.md` + `data_pack_market.md`,跑 Agent C prompt,产出 `{name}_{code}_分析报告.md`。报告内容直接通过 SSE `done.content` 推前端。

### 5.7 `services/system_config/`

- `store.py`:原子读写 yaml(写时 `tmp + rename`),返回 `dict[str, str]`
- `schema.py`:Pydantic 校验扁平键命名规则(`LLM_<NAME>_<FIELD>`)
- `channels.py`:`reconstruct_channels(kv) -> list[ChannelConfig]` 反向 `flatten_channels(channels) -> dict`
- `llm_client.py`:抽象基类 + `OpenAICompatibleClient`(OpenAI/DeepSeek/OpenRouter 共用)+ `AnthropicClient`
- `llm_test.py`:`POST /system/config/test` 返回 `{ok: bool, model: str, latency_ms: int, error?: str}`

---

## 6. 错误处理总则

1. **每层一种异常**:`SymbolError / DataPackError / LLMError / ConfigError`,Coordinator 顶层 try/except 转 SSE `error` 事件
2. **决策日志**:每 phase 写一行到 `_decisions.jsonl`(对齐 backtest `DecisionLogSink`),包含 `{ts, phase, action, payload}`
3. **降级优先于失败**:Phase 1 单 section 失败 → 标 warning 继续;Phase 3 LLM 失败 → 重试 1 次后才中止
4. **断点续跑**:`_meta.json` 是事实来源,Coordinator 启动时按它跳过已 `done` 的 phase

---

## 7. 测试策略

### 7.1 测试层级(对齐既有 `backend/tests/` 模式)

| 层 | 范围 | 数量目标(期 1) |
|---|---|---|
| 单元 | symbol / sse / parser / channels 重组 / 各 section 独立 | ~20 |
| 集成 | DataPackBuilder 端到端(用 mock DuckDBStore)/ Coordinator routing / session_repo CRUD | ~8 |
| 契约 | SSE 帧格式与前端 `agentChatStore.processLine` 匹配(snapshot 比对) | 3 |
| LLM | OpenAI/Anthropic client mock(httpx.MockTransport)| 4 |

**禁止**:单元测试中调真实 LLM API。所有 LLM 调用必须 mock。

### 7.2 关键测试用例

- `test_symbol`:`extract("分析比亚迪 002594")` → `StockRef(code="002594.SZ", name="比亚迪", market="A")`
- `test_phase1_section_03`:给定 mock DuckDBStore 返回 5 年 income,断言生成的 markdown 与 turtle 黄金样本字节级一致(参考 `Turtle_investment_framework/tests/test_output_format.py:36-91`)
- `test_coordinator_routing`:三个分支(qa/full/chitchat)分别用 fixture session 验证
- `test_sse_contract`:每个工厂函数产出的 dict 必须含且仅含前端 `ProgressStep` 类型允许的字段

### 7.3 验证命令

```bash
python -m pytest backend/tests/agent/ -x -q     # 期 1 全部新增 test
python -m pytest backend/tests/ -x -q           # 全量 ≥ 580(原 550 + ~30 新)
```

---

## 8. 实施分期

| Phase | 范围 | 工期 |
|---|---|---|
| **A. 基础设施** | system_config + auth_stub + symbol + sse + session_repo + workspace + DB migration + agent.py 路由骨架 | 2-3 天 |
| **B. 闲聊+追问** | Coordinator chitchat/qa 分支 + LLMClient 4 协议 + `/chat/stream` 基础 SSE | 1-2 天 |
| **C. 数据包适配器** | Phase 1 §1-§6, §11-§17 共 16 section + 9 derived + builder + 黄金样本测试 | 3-4 天 |
| **D. Phase 3 量化+估值** | phase3_quant.py + parser.py + phase3_valuation.py + 6 个 turtle prompt 同步 + Coordinator full pipeline 编排 | 3-4 天 |
| **E. 集成验证** | 端到端跑通 002594/600519/00700.HK 三个标的,前端 ChatPage 联调,AGENTS.md 同步 | 1-2 天 |

**期 1 合计 10-15 天**(单人全职)。每 Phase 单独 PR。

---

## 9. 关键决策汇总

| # | 决策 | 选择 |
|---|---|---|
| 1 | LLM 协议 | OpenAI / Anthropic / OpenRouter / DeepSeek 4 协议(`OpenAICompatibleClient` 共享前 3) |
| 2 | 核心抽象 | turtle 多 Agent 流水线,Agent 间文件通信(`{output_dir}/*.md`) |
| 3 | SSE 粒度 | 严格 6 类(C1),Phase = `tool_start/tool_done`,流式中间 = `generating` |
| 4 | 历史窗口 | QA 追问 ≤ 10 条历史 + 已生成产物文件作上下文 |
| 5 | 数据存储 | SQLite 两表 + `data/agent_runs/{code}_{name}/` 文件 |
| 6 | system_config | 扁平 KV(C4),持久化 yaml,channel 在服务层重建 |
| 7 | Auth | 期 1 完全 stub,`authEnabled: false`(C3) |
| 8 | PDF | 期 1 不做(期 3 引入,Coordinator 预留 hook) |
| 9 | 定性分析 | 期 1 不做(期 2 引入,Phase 1 占位 §7/§8/§10) |
| 10 | Tushare | 不引入,DuckDB 适配器还原 §1-§17(C5) |
| 11 | 前端改动 | 期 1 = 0(C2),完全沿用现有 6 类 SSE 解析器 |
| 12 | 代码 normalize | A=`.SH/.SZ`、HK=`.HK`、US=无后缀(C6) |

---

## 10. 风险与开放问题

1. **§14 Rf 数据源**:turtle 用 yfinance ^TNX。期 1 写死常量(2.7% 中国 10Y),后续接 akshare `bond_china_yield`
2. **§16 同业可比**:本项目无行业分类元数据。期 1 降级输出"同业数据待补"占位,期 2 引入 akshare `stock_individual_info_em`
3. **A 股母公司报表 §3P/§4P**:eastmoney 是否有母表数据需在 Phase C 测试时验证。如无,该 section 输出 None(返回上层跳过)
4. **港股/美股财务 5 年完整度**:`data/market/{HK,US}/financial/` 数据完整度需在 Phase C 验证;不足则 §13 standardly warning
5. **成本估算**:一次完整分析 ≈ 50K tokens。Anthropic Sonnet ~$0.15、DeepSeek ~$0.005。建议 default routing = DeepSeek
6. **并发限制**:同 session 同时仅一条 in-flight stream(前端已 abort 旧的);跨 session 不限,依赖 LLM 上游限流

---

## 11. 附录:turtle 文件复制清单(期 1 范围)

| turtle 路径 | 目标路径 |
|---|---|
| `strategies/turtle/phase3_quantitative.md` | `backend/services/agent/prompts/turtle/phase3_quantitative.md` |
| `strategies/turtle/phase3_valuation.md` | `backend/services/agent/prompts/turtle/phase3_valuation.md` |
| `strategies/turtle/references/shared_tables.md` | `backend/services/agent/prompts/turtle/references/shared_tables.md` |
| `strategies/turtle/references/factor_interface.md` | 同上目录 |
| `strategies/turtle/references/judgment_examples_turtle.md` | 同上 |
| `strategies/turtle/references/output_schema.md` | 同上 |

复制时在文件头加 `<!-- TURTLE_SYNC_DATE: 2026-05-23 -->` 注释,后续手动 sync。

---

## 12. Multi-Agent Harness 架构(r2 — 权威)

> 本节是 r2 修订的核心,与 §2 / §4.2 / §5 / §10 中"单一 pipeline"假设冲突时以本节为准。

### 12.1 设计动机

期 1 只落地一个分析 agent(原称 turtle,r2 改名 `cpa_conservative`),但**未来必然出现多个**:`tradingagents_astock`(团队分析,搬 [TradingAgents-Astock](https://github.com/) 项目)、行业研究 agent、宏观 agent 等。
单一 pipeline 设计会导致每加一个 agent 都侵入 Coordinator + 路由 + 工作区 + SSE 事件结构。

**r2 引入 Harness Engineering 抽象**:
- **Harness 层**(agent-agnostic,可复用基础设施)
- **Agent 层**(各自治模块,实现统一 Protocol)
- 二者通过 **Manifest 注册** + **Dispatcher 调度**解耦

### 12.2 模块布局(替代 §2.2)

```
backend/services/
├── agent_harness/                    ★ 新增,所有 agent 共享
│   ├── __init__.py
│   ├── protocol.py                   # Agent / StepSpec / AgentManifest / Event 类型
│   ├── registry.py                   # 全局注册表 + discover_agents() + get(agent_id)
│   ├── dispatcher.py                 # dispatch(agent_id, ref, llm) → AsyncIterator[Event]
│   ├── routing.py                    # 三层 fallback:keyword → explicit → default
│   ├── events.py                     # 事件构造器(确保 §4.2 6 类协议合规)
│   ├── workspace.py                  # 工作区分配(原 services/agent/workspace.py 迁入)
│   ├── meta.py                       # _meta.json schema + 含 agent_id/version/prompt_hash
│   ├── observability.py              # 决策日志、阶段计时、token 计费(写 _meta.json)
│   ├── session_repo.py               # 会话存储(原 services/agent/session_repo.py 迁入)
│   ├── symbol.py                     # 代码 normalize(原 services/agent/symbol.py 迁入)
│   ├── llm/                          # LLMClient 抽象 + OpenAICompatible / Anthropic 实现
│   │   ├── base.py
│   │   ├── openai_compatible.py
│   │   └── anthropic.py
│   └── data_layer/                   ★ 共享数据查询原语,各 agent import
│       ├── __init__.py
│       ├── pricing.py                # 最新价、市值、流通股
│       ├── financial.py              # query_financial_3y / query_indicator_5y
│       ├── dividend.py               # query_dividend_history
│       ├── valuation.py              # query_pe_pb_history
│       └── industry.py               # query_industry_summary
│
├── agents/                            ★ 新增,各 agent 自治模块
│   ├── __init__.py                   # 显式 import 各 agent,触发 registry 注册
│   ├── cpa_conservative/             # 中文「保守分析」(原 turtle)
│   │   ├── __init__.py               # exports AGENT 实例
│   │   ├── manifest.py               # AgentManifest 声明
│   │   ├── agent.py                  # 实现 Agent.run() — 串 phase1→3.1→3.2
│   │   ├── data_pack.py              # 原 Phase 1 §1-§17 builder(消费 data_layer)
│   │   ├── phases.py                 # phase3_quant + phase3_valuation 执行器
│   │   ├── parser.py                 # <results> 块解析(本 agent 私有)
│   │   └── prompts/                  # 6 个 markdown(从 turtle 复制)
│   │       ├── coordinator.md
│   │       ├── phase3_quantitative.md
│   │       ├── phase3_valuation.md
│   │       └── references/
│   │           ├── shared_tables.md
│   │           ├── judgment_examples_turtle.md
│   │           └── factor_interface.md
│   ├── tradingagents_astock/         # 中文「团队分析」(期 1 仅占位)
│   │   ├── __init__.py
│   │   ├── manifest.py               # 注册 manifest
│   │   ├── agent.py                  # run() raise NotImplementedError(message)
│   │   └── README.md                 # 链接到 github 原项目 + 期 2 实施计划
│   └── chitchat/                     # 闲聊也作为 agent
│       ├── __init__.py
│       ├── manifest.py
│       └── agent.py                  # 直接 LLM stream,无 phase
│
└── system_config/                    # 不变,扁平 KV LLM 配置
    └── (新增) defaults.py            # default_agent_id 配置项
```

### 12.3 Agent Protocol(权威类型)

```python
# agent_harness/protocol.py
from __future__ import annotations
from pathlib import Path
from typing import AsyncIterator, Protocol, TypedDict, Literal

class StepSpec(TypedDict):
    id: str                      # 短 id,如 "data_pack" / "quant" / "valuation"
    label: str                   # 中文显示名,如 "拉取数据包"
    estimated_seconds: int       # 用于前端进度条预估

class AgentManifest(TypedDict):
    id: str                      # 全局唯一,如 "cpa_conservative"
    label: str                   # 中文展示,如 "保守分析"
    aliases: list[str]           # 路由关键字,如 ["保守分析", "保守", "cpa", "穿透回报率"]
    description: str             # 一句话说明(Settings/UI 用)
    version: str                 # semver,如 "1.0.0"
    steps: list[StepSpec]        # 声明步骤序列(不实际驱动执行,仅元数据)
    requires: list[str]          # 依赖能力,如 ["llm.chat", "data.duckdb.financial"]
    enabled: bool                # 期 1 占位 agent 设 False(路由器会拒绝匹配)

EventType = Literal["thinking", "tool_start", "tool_done", "generating", "done", "error"]

class Event(TypedDict, total=False):
    type: EventType
    agent_id: str                # ★ r2 新增:所有事件都含 agent_id
    agent_label: str             # ★ r2 新增:前端徽章
    step_id: str                 # ★ r2 新增:替代旧 phase 字段
    step_label: str
    step_index: int
    step_total: int
    delta: str
    message: str
    report_path: str

class HarnessContext(Protocol):
    """传给 Agent.run() 的上下文,封装 harness 提供的能力。"""
    workspace: Path
    session_id: str
    emit: callable               # async def emit(event: Event) -> None
    log_decision: callable       # async def log_decision(step_id, payload) -> None

class Agent(Protocol):
    manifest: AgentManifest
    async def run(
        self, *, ref: "StockRef", llm: "LLMClient", ctx: HarnessContext
    ) -> AsyncIterator[Event]: ...
```

### 12.4 SSE 事件 schema(替代 §4.2)

**严格遵守 C1**(6 类不变),但 payload 加 agent 维度:

```jsonc
// 1. thinking(harness 在 dispatch 前发,告知用户哪个 agent 接手)
{"type":"thinking","agent_id":"cpa_conservative","agent_label":"保守分析",
 "message":"开始分析 比亚迪(002594.SZ)"}

// 2. tool_start(每个 step 起始)
{"type":"tool_start","agent_id":"cpa_conservative","agent_label":"保守分析",
 "step_id":"data_pack","step_label":"拉取数据包","step_index":1,"step_total":3}

// 3. generating(LLM 流式 chunk)
{"type":"generating","agent_id":"cpa_conservative","step_id":"quant","delta":"..."}

// 4. tool_done
{"type":"tool_done","agent_id":"cpa_conservative","step_id":"data_pack"}

// 5. done(全流程完成)
{"type":"done","agent_id":"cpa_conservative","report_path":"比亚迪_002594.SZ_分析报告.md"}

// 6. error
{"type":"error","agent_id":"tradingagents_astock",
 "message":"团队分析 agent 计划于期 2 上线,当前不可用。请使用「保守分析」。"}
```

**前端 `agentChatStore.ts:265-283` 需小幅扩展**(向后兼容):
- `ProgressStep` 字段集追加 `agent_id`、`agent_label`、`step_id`、`step_label`、`step_index`、`step_total`
- 旧字段 `phase` 可保留作 alias(`step_id` 的别名),便于灰度

### 12.5 路由策略(替代 §4.4)

**四层 fallback,顺序固定**(r2 最终决策):

```python
# agent_harness/routing.py
async def resolve_agent(*, message: str, explicit_agent_id: str | None,
                        default_agent_id: str, llm: LLMClient,
                        emit: Callable) -> RouteDecision:
    """
    返回 RouteDecision(agent_id, reason, confidence, clarification?)。
    reason ∈ {"explicit","mention","keyword","llm","default","clarify"}。
    """
    # 1. 显式参数优先(API / UI 下拉框「分析方式」)
    if explicit_agent_id and registry.exists(explicit_agent_id):
        return RouteDecision(explicit_agent_id, "explicit", 1.0)

    # 2. @mention 解析(期 2 启用,期 1 占位:正则识别 @cpa_conservative 等)
    mentioned = parse_mention(message)
    if mentioned and registry.exists(mentioned):
        return RouteDecision(mentioned, "mention", 1.0)

    # 3. 关键字 alias 匹配(子串 ci)
    matched = registry.match_alias(message)
    if matched:
        return RouteDecision(matched, "keyword", 0.9)

    # 4. LLM router(给 LLM 列 enabled agents 的 manifest,要 JSON 输出)
    decision = await llm_router.classify(message=message, llm=llm,
                                          agents=registry.list_enabled())
    if decision.confidence >= 0.6 and registry.exists(decision.agent_id):
        return RouteDecision(decision.agent_id, "llm", decision.confidence)

    # 4b. confidence 不足 → 澄清反问(SSE thinking 事件带 quick_reply 选项)
    if decision.needs_clarification:
        return RouteDecision(
            agent_id=None, reason="clarify",
            confidence=decision.confidence,
            clarification_question=decision.clarification_question,
            quick_replies=[
                {"label": "保守分析", "agent_id": "cpa_conservative"},
                {"label": "团队分析", "agent_id": "tradingagents_astock"},
            ],
        )

    # 5. 默认 agent(从 system_config 读)
    return RouteDecision(default_agent_id, "default", 0.5)
```

**路由器同时校验 `manifest.enabled`**:若匹配到的 agent 被声明为未启用(如期 1 的 `tradingagents_astock`),则 `dispatch()` 立即发 `error` 事件并终止,**不**降级到默认 agent(避免用户混淆)。LLM router 的候选池本身就过滤为 `enabled=True`,所以不会路由到未启用 agent。

**澄清反问机制**:当 `reason == "clarify"` 时,Coordinator **不调 dispatch**,而是发一条 `thinking` 事件(payload 含 `clarification_question` + `quick_replies` 数组),前端把它渲染为消息气泡 + 快捷按钮;用户点击后前端把 `agent_id` 作为 `explicit_agent_id` 重新发请求,走第 1 层。详见 §15。

**关键字示例**(`cpa_conservative` 的 `aliases`):
```python
["保守分析", "保守", "cpa", "穿透回报率", "龟龟"]
```
**关键字示例**(`tradingagents_astock` 的 `aliases`):
```python
["团队分析", "团队", "trading agents", "tradingagents"]
```

匹配规则:**子串忽略大小写匹配**;若多 agent 同时命中,按 `manifest.id` 字典序取第一个并 log 警告。

### 12.6 工作区 + `_meta.json`(替代 §10、§3.3)

**路径**:`data/agent_runs/<session_id>/<agent_id>__<run_id>/`
- 每个 run 目录前缀 agent_id,便于同一 session 跑多 agent 时区分(例如用户先用保守分析跑了,又想团队分析对比)
- `run_id` = 时间戳 + 短随机串(原方案不变)

**`_meta.json` schema**(r2 增强):

```json
{
  "session_id": "sess-...",
  "run_id": "20260523_223010_a3f1",
  "agent_id": "cpa_conservative",
  "agent_label": "保守分析",
  "agent_version": "1.0.0",
  "prompt_hashes": {
    "phase3_quantitative.md": "sha256:abc123...",
    "phase3_valuation.md": "sha256:def456..."
  },
  "model": "deepseek-chat",
  "channel": "deepseek",
  "ref": {"symbol": "002594.SZ", "name": "比亚迪", "market": "A"},
  "started_at": "2026-05-23T22:30:10+00:00",
  "ended_at": "2026-05-23T22:34:55+00:00",
  "status": "done",
  "steps": {
    "data_pack": {"status":"done","started_at":"...","ended_at":"...","artifact":"data_pack_market.md"},
    "quant":     {"status":"done","started_at":"...","ended_at":"...","artifact":"phase3_quantitative.md","results":{"final_return_GG":11.2,"trap_risk":"低"}},
    "valuation": {"status":"done","started_at":"...","ended_at":"...","artifact":"比亚迪_002594.SZ_分析报告.md"}
  },
  "tokens": {"prompt": 12000, "completion": 5400}
}
```

`prompt_hashes` 让 Eval(期 2 引入)能验证报告复现性。

### 12.7 Coordinator → Dispatcher 重构(替代 §5.3)

旧 Coordinator 是「分意图 + 实现 pipeline」混合体,r2 拆为:

- **Coordinator(变薄)**:仅做 intent 分类(analyze / chitchat / qa_followup)。**chitchat / qa_followup 也走 dispatcher**,它们对应的 agent 是 `chitchat`(qa_followup 当作 chitchat 的一个变体处理,prompt 不同)。
- **Dispatcher**:`dispatch(agent_id, ref, llm, session_id) → AsyncIterator[Event]`。负责 workspace 分配、`_meta.json` 写入、agent 实例化、step 事件包装、错误捕获、超时。

```python
# agent_harness/dispatcher.py
async def dispatch(*, agent_id: str, ref: StockRef, llm: LLMClient,
                   session_id: str) -> AsyncIterator[Event]:
    agent = registry.get(agent_id)
    if not agent.manifest["enabled"]:
        yield events.error(agent_id=agent_id,
                           message=f"{agent.manifest['label']} agent 暂未上线")
        return

    workspace = workspace_alloc(session_id, agent_id)
    meta = init_meta(workspace, agent, ref, llm)
    ctx = HarnessContext(workspace=workspace, session_id=session_id,
                         emit=..., log_decision=...)

    yield events.thinking(agent, ref)
    try:
        async for ev in agent.run(ref=ref, llm=llm, ctx=ctx):
            # 自动注入 agent_id/agent_label(若 agent 没塞)
            ev.setdefault("agent_id", agent_id)
            ev.setdefault("agent_label", agent.manifest["label"])
            update_meta_from_event(meta, ev)
            yield ev
        finalize_meta(meta, status="done")
    except Exception as e:
        finalize_meta(meta, status="failed", error=str(e))
        yield events.error(agent_id=agent_id, message=str(e))
```

### 12.8 期 1 注册的 agents(替代 §11 + 补充)

| agent_id | label | enabled | 期 1 实现度 |
|---|---|---|---|
| `cpa_conservative` | 保守分析 | ✅ true | 完整实现(原 turtle) |
| `tradingagents_astock` | 团队分析 | ❌ false | 仅 manifest + `run()` 抛 NotImplementedError(优雅 error 事件) |
| `chitchat` | 闲聊 | ✅ true | 直接 LLM stream,无 step |

期 2 把 `tradingagents_astock.enabled = true` 并实现 `agent.py`,**零侵入** harness。

### 12.9 数据层服务化(替代 §5.4 数据来源段)

`data_layer/` 把 DuckDB 查询封装成语义化函数,**所有 agent 通过此层访问数据**,不再每个 agent 直接调 `DuckDBStore`:

```python
# agent_harness/data_layer/financial.py
def query_financial_3y(symbol: str, market: str = "A") -> dict:
    """返回最近 3 年三表 + 指标表的关键字段 dict。"""
    ...
```

`cpa_conservative.data_pack` 消费这些函数构建 §1-§17;未来 `tradingagents_astock` 可能只用其中 §3/§4/§11/§17。

### 12.10 前端影响(替代 §11 中间步骤的部分前端语义)

| 区域 | 改动 | 期次 |
|---|---|---|
| `agentChatStore.ts` ProgressStep | 字段集加 `agent_id/agent_label/step_id/step_label/step_index/step_total` | 期 1 |
| ChatPage 进度条 | 每个 step 加「[保守分析]」徽章前缀 | 期 1 |
| ChatPage 消息 bubble | 用户消息上方显示 agent 徽章(若路由 reason ∈ {"keyword","explicit"}) | 期 1 |
| Settings 页面 | 新增「默认分析方式」下拉(从 `/api/v1/agents` 动态拉) | 期 1 |
| ChatPage 输入框下方「分析方式」下拉 | 选项 = Auto(默认)+ enabled agents 列表;选定时作为 `explicit_agent_id` 提交 | 期 1 |
| ChatPage 澄清反问 UI | 当收到 `thinking` 事件含 `quick_replies` 时,渲染快捷按钮;点击后用 `explicit_agent_id` 重发 | 期 1 |
| ChatPage @mention 自动补全 | 输入 `@` 弹 agent 列表 | 期 2 |
| `/api/v1/agents` GET endpoint | 返回所有已注册 agents 的 manifest(供前端下拉) | 期 1 |

---

## 13. Agent Manifest 注册示例

```python
# backend/services/agents/cpa_conservative/manifest.py
from backend.services.agent_harness.protocol import AgentManifest

MANIFEST: AgentManifest = {
    "id": "cpa_conservative",
    "label": "保守分析",
    "aliases": ["保守分析", "保守", "cpa", "穿透回报率", "龟龟"],
    "description": "基于 CPA 视角的极端保守假设穿透回报率精算,适合长期持有决策。",
    "version": "1.0.0",
    "steps": [
        {"id": "data_pack",  "label": "拉取数据包",        "estimated_seconds": 30},
        {"id": "quant",      "label": "量化分析(穿透回报率)", "estimated_seconds": 180},
        {"id": "valuation",  "label": "估值与报告组装",     "estimated_seconds": 120},
    ],
    "requires": ["llm.chat", "data.duckdb.daily", "data.duckdb.financial",
                 "data.duckdb.dividend", "data.duckdb.valuation"],
    "enabled": True,
}
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

```python
# backend/services/agents/__init__.py
"""导入即注册。harness.registry 在模块加载时收集 MANIFEST。"""
from . import cpa_conservative, tradingagents_astock, chitchat  # noqa
```

---

## 14. 设计决策汇总(r2 锁定)

| # | 决策 | 选定 |
|---|------|------|
| D1 | Agent 选择机制 | 四层 fallback:explicit → @mention → keyword → LLM router → default(LLM router confidence<0.6 时澄清反问)|
| D2 | 默认 agent | `system_config.default_agent_id`,初始 = `cpa_conservative` |
| D3 | 期 1 是否注册 `tradingagents_astock` | ✅ 注册 manifest + `enabled=False` + NotImplemented stub |
| D4 | 前端 agent 展示 | 进度条 agent 徽章 + Settings 默认 agent 下拉 |
| D5 | 数据层归属 | `agent_harness/data_layer/`,所有 agent 共享 |
| D6 | 模块命名 | `agent_harness/` + `agents/<id>/` |
| D7 | 原 `turtle_conservative` 代号 | 改为 `cpa_conservative`,中文显示「保守分析」 |
| D8 | SSE 事件 agent 维度 | payload 加 `agent_id/agent_label/step_id/step_label/step_index/step_total`,严守 C1 6 类 |
| D9 | LLM router 模型 | 复用主 LLM channel(`system_config.default_channel`),不单独配 cheap router(避免双 channel 配置复杂度;后续可独立加 `router_channel`)|
| D10 | 澄清反问 UI 载体 | 复用 `thinking` 事件 + 扩展 payload(`clarification_question` + `quick_replies`),不发明新 SSE 类型(守 C1 6 类铁律)|
| D11 | 期 1 是否做编排 | ❌ 单 agent only。OrchestratorAgent(串/并联多 agent)推迟到期 2,期 1 单一 ref → 单一 agent run |

---

## 15. LLM Router 设计(r2 新增)

### 15.1 目的

当 explicit / @mention / keyword 三层都没命中时,用 LLM 看用户消息内容做意图分类,把含糊请求(如「帮我看看比亚迪」「这只股票怎么样」)路由到合适 agent;若 LLM 也不确定,反问用户。

### 15.2 Prompt 模板

```python
# agent_harness/llm_router.py
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
- 不要选 enabled=false 的 agent(候选池已过滤,但保险起见再校验)。
"""

ROUTER_USER_PROMPT = "用户消息:\n{message}"
```

`agents_json` 由 `registry.list_enabled()` 序列化,每个元素只含 `{id, label, description, aliases}`(不暴露 steps / requires)。

### 15.3 输出 schema 与解析

```python
# agent_harness/llm_router.py
from pydantic import BaseModel, Field

class RouterDecision(BaseModel):
    agent_id: str | None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    needs_clarification: bool
    clarification_question: str = ""

async def classify(*, message: str, llm: LLMClient,
                   agents: list[AgentManifest]) -> RouterDecision:
    """非流式调用 LLM,JSON 解析失败时降级:返回 confidence=0 + needs_clarification=True。"""
    sys_prompt = ROUTER_SYSTEM_PROMPT.format(
        agents_json=json.dumps(
            [{"id": a["id"], "label": a["label"],
              "description": a["description"], "aliases": a["aliases"]}
             for a in agents], ensure_ascii=False, indent=2),
    )
    raw = await llm.complete_json(system=sys_prompt,
                                   user=ROUTER_USER_PROMPT.format(message=message),
                                   timeout=10)
    try:
        return RouterDecision.model_validate_json(raw)
    except Exception as e:
        logger.warning("LLM router JSON 解析失败: %s; raw=%s", e, raw[:200])
        return RouterDecision(
            agent_id=None, confidence=0.0,
            reason="LLM 路由解析失败",
            needs_clarification=True,
            clarification_question="抱歉,我没听明白。你是想做保守分析(穿透回报率精算)还是团队分析(多角色辩论)?",
        )
```

### 15.4 阈值与超时

| 项 | 值 | 理由 |
|---|---|---|
| `confidence_threshold` | `0.6` | < 0.6 → 澄清;≥ 0.6 → 直接路由 |
| `timeout` | 10 秒 | router 必须快;超时降级到 default agent + log warning |
| `max_tokens` | 256 | JSON 输出短小 |
| 重试 | 0 次 | 失败立即降级澄清,不阻塞用户 |

### 15.5 澄清反问的 SSE 集成

Coordinator 收到 `RouteDecision(reason="clarify")` 后:

```python
# 不进 dispatch,直接发 thinking + done
yield events.thinking(
    agent_id=None, agent_label="路由助手",
    payload={
        "message": decision.clarification_question,
        "quick_replies": decision.quick_replies,  # [{"label","agent_id"}, ...]
    },
)
yield events.done(agent_id=None, payload={"reason": "clarify_pending"})
```

前端 `agentChatStore` 把带 `quick_replies` 的 thinking 事件渲染为消息气泡 + 按钮组;按钮 onClick 时调 `/chat/stream` 重发,带 `explicit_agent_id`。

**严守 C1**:仅复用 `thinking` / `done` 事件类型,不新增。前端契约扩展 = `ProgressStep.quick_replies?: {label,agent_id}[]`(可选字段,旧逻辑无影响)。

### 15.6 Router 跳过条件

LLM router 在以下情况**不调用**(节省 token):
- explicit_agent_id 已提供
- @mention 命中
- keyword alias 命中
- 消息长度 < 4 字符(直接走 default + log)
- 消息明显是 chitchat(由 Coordinator intent 分类先行判定;若 intent=chitchat,直接路由 `chitchat` agent,不进 router)

### 15.7 测试要点

| Case | 期望 |
|---|---|
| 「保守分析比亚迪」| keyword 命中 cpa_conservative,不调 LLM |
| 「@cpa_conservative 看下 002594」(期 2) | mention 命中 |
| 「这只股票怎么样」+ 上下文有 ref | LLM router → 高置信度选 cpa_conservative(默认偏好)|
| 「我该买还是卖」| LLM router 低置信度 → 澄清 + quick_replies |
| LLM 返回非法 JSON | 降级澄清,不抛异常 |
| LLM 超时 | 降级 default agent,log warning,不阻塞 |
| LLM router 选了 enabled=false 的 agent | registry 校验失败 → 澄清 |

详细 mock 测试用例见 plan T12.6。

---

*Spec for Ask Stock | r1 2026-05-23 | r2 multi-agent 修订 2026-05-23 | r2 LLM router 补丁 2026-05-23 | superpowers:brainstorming 产出*
