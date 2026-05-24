# 问股(Ask Stock)实施计划 — 期 1

> **范围**:本计划仅覆盖**期 1**(MVP 全流程的最小骨架,含 Phase 1 数据包 + Phase 3.1 CPA 量化 + Phase 3.2 估值/报告)
> **期 2**(/business-analysis 三 agent)与**期 3**(PDF 下载/解析 + 前端上传 UI)在期 1 完成后再 make-plan 一次。
>
> **配套文档**:`docs/design_ask_stock.md`(why + what 设计)。本文档是 how(执行清单 + 验证)。
>
> **协作约定**(基于已锁定决策):
> - **SSE 协议**:复用前端现有 6 事件(`thinking / tool_start / tool_done / generating / done / error`),phase 进度映射成 `tool_start/tool_done`。**禁止发明新事件类型**。
> - **PDF/Upload**:期 1 不做。
> - **Auth**:期 1 不做。后端无 auth 依赖。
> - **system_config**:扁平 `{key, value}` 模型,对齐前端 `LLM_<NAME>_*` env-style key。Channel 结构在服务层重建供 LLM client 使用。
> - **MVP 边界**:期 1 跳过 /business-analysis 与 PDF。`data_pack_market.md` 中依赖 PDF/WebSearch 的 §7/§8/§10/§13.2 用 placeholder。

---

## Phase 0: Documentation Discovery(已完成)

**Discovery 报告**(由 3 个并行 explore subagent 取证产出,对话历史留痕):

### A. Turtle 框架可复用文件清单

| 项 | 路径 | 状态 |
|---|---|---|
| Turtle Coordinator(Phase 3 only) | `Turtle_investment_framework/strategies/turtle/coordinator.md`(337 行)| 期 1 复制 prompt 主体,删 Phase 0/1/2 分发逻辑(已委托给 /business-analysis,期 1 不实现) |
| Phase 3.1 CPA 量化(11 步) | `strategies/turtle/phase3_quantitative.md`(459 行,Step 0 校验 L36-113,Step 1-11 L115-397) | 期 1 整文件复制为 prompt |
| Phase 3.2 估值/报告 | `strategies/turtle/phase3_valuation.md`(463 行,report template L169-457) | 期 1 整文件复制 |
| Shared tables(税率/门槛/穿透公式) | `strategies/turtle/references/shared_tables.md`(99 行) | 期 1 复制 |
| Factor interface(Agent 间参数契约) | `strategies/turtle/references/factor_interface.md`(116 行) | 期 1 复制 |
| Judgment examples(G 系数/分配意愿锚点) | `strategies/turtle/references/judgment_examples_turtle.md`(42 行) | 期 1 复制 |
| **数据包 schema 权威源**(§1-§17) | `Turtle_investment_framework/scripts/tushare_modules/assembly.py::assemble_data_pack` L206-437 | **期 1 用 DuckDB 重写**,产出格式严格对齐 |
| 数据包 schema 验证测试 | `Turtle_investment_framework/tests/test_output_format.py` L36-91 | 期 1 移植为 backend test |

**§1-§17 段落清单**(见 design_ask_stock.md §9 已完整列出,此处不重复):A 股有 §1-§17,§3P/§4P 母公司表 A 股专有,§7/§8/§10/§13.2 期 1 全部 placeholder。

### B. 前端契约(后端必须满足的接口/事件 shape)

#### B.1 SSE 事件协议(`agentChatStore.ts:265-283` + `ChatPage.tsx:389-461`)

| 事件 type | 必填字段 | 选填字段 | 前端用途 |
|---|---|---|---|
| `thinking` | `type` | `step`(int)、`message` | 进度面板显示"AI 正在思考..." |
| `tool_start` | `type`,`tool` 或 `display_name` | `display_name`(优先) | 进度面板显示"xxx..." |
| `tool_done` | `type`,`tool` 或 `display_name`,`duration`(float 秒)、`success`(bool) | `display_name` | 显示"xxx 完成 (Ns)" |
| `generating` | `type` | `message` | 显示"正在生成最终分析..." |
| `done` | `type` | `success`(bool,默认 true)、`content`(markdown,最终回复) | 写入 assistant 消息 |
| `error` | `type` | `error` / `message` / `content`(取首个非空) | 抛错并显示 |

**线协议**:每行 `data: <json>\n`,`\n` 分隔。非 `data: ` 开头的行被丢弃。

#### B.2 端点契约(`api/agent.ts`,`api/systemConfig.ts`)

| URL | Method | 期 1 必须实现 | 备注 |
|---|---|---|---|
| `POST /api/v1/agent/chat/stream` | POST(SSE 响应) | ✅ | body: `{message, skills?, session_id?, context?}`;返回 SSE 流 |
| `GET /api/v1/agent/skills` | GET | ✅ | 返回 `{skills: SkillInfo[], default_skill_id}` |
| `GET /api/v1/agent/chat/sessions?limit=50` | GET | ✅ | 返回 `{sessions: ChatSessionItem[]}` |
| `GET /api/v1/agent/chat/sessions/:id` | GET | ✅ | 返回 `{messages: ChatSessionMessage[]}` |
| `DELETE /api/v1/agent/chat/sessions/:id` | DELETE | ✅ | 删除会话 |
| `POST /api/v1/agent/chat/send` | POST | ⚠️ stub | body `{content}`,期 1 返回 `{success: true}`(通知渠道转发期 1 不做) |
| `POST /api/v1/agent/chat` | POST | ⏸️ stub | 非流式,期 1 不实现 |
| `GET /api/v1/system/config` | GET | ✅ | snake_case 响应 |
| `GET /api/v1/system/config/schema` | GET | ✅ | 字段 schema |
| `PUT /api/v1/system/config` | PUT | ✅ | 含乐观锁 `config_version` |
| `GET /api/v1/system/config/setup/status` | GET | ✅ | 引导状态 |
| `POST /api/v1/system/config/validate` | POST | ✅ | |
| `GET /api/v1/system/config/export` | GET | ✅ | .env 格式 |
| `POST /api/v1/system/config/import` | POST | ✅ | |
| `POST /api/v1/system/config/llm/test-channel` | POST | ✅ | 含 capability checks |
| `POST /api/v1/system/config/llm/discover-models` | POST | ✅ | |
| `POST /api/v1/system/config/notification/test-channel` | POST | ⚠️ stub | 期 1 返回 `{success: false, message: "通知渠道期 1 未实现"}` |
| `GET/POST /api/v1/auth/*`(5 个) | — | ⏸️ stub | `/auth/status` 永返 `{authEnabled: false}`,其余 405 |

**Wire 格式**:system/config 系列**全部 snake_case**(请求 + 响应),agent 系列也是 snake_case(`session_id` / `default_skill_id` 等)。

#### B.3 Auth(已确认期 1 跳过)

后端**无 auth 中间件**。前端依靠 `withCredentials: true` 发 cookie,期 1 后端忽略。`/api/v1/auth/status` 返 `{authEnabled: false}`,前端 AuthContext 会进入 "无 auth" 模式。

### C. 后端可复用 API 清单

| 需求 | 复用现有 | 文件:行 |
|---|---|---|
| 单股日线(raw) | `DuckDBStore.query_kline(market, symbol, start, end, limit)` | `services/duckdb_store.py:275` |
| 单股日线(qfq) | `DuckDBStore.query_qfq_kline(market, symbol, start, end)` | `services/duckdb_store.py:302` |
| 单股周线(给 §11) | 调 `query_qfq_kline` 后用 `services/stock_data.py::aggregate_kline(df, 'W-FRI')` | `services/stock_data.py` |
| 财报 4 表 | `DuckDBStore.query_financial(market, fin_type, symbol, limit)` | `services/duckdb_store.py:449` |
| 估值 PE/PB | `DuckDBStore.query_valuation_bulk(market, [symbol])` | `services/duckdb_store.py:475` |
| 分红 | `DuckDBStore.query_dividend_bulk(market, [symbol])` | `services/duckdb_store.py:500` |
| 股票名称 | `services/stock_index.py::get_name(code, market)` | (subagent 报告确认) |
| 股票搜索 | `services/stock_index.py::search_stocks(query, limit)` | |
| 后台任务模式 | `BackgroundTaskRunner` + 状态轮询 | `services/api_utils.py:43` |
| SQLite migration | 新增 fn 加到 `services/db_schema.py`,在 `main.py:54 lifespan` 调用 | `services/db_schema.py` |
| Scheduler 加 job | `scheduler.add_job(...)` 加到 `start_scheduler()` | `scheduler.py:86` |
| 市场判定(部分) | `routers/market_kline.py::_resolve_market(code) -> str` | `.SH/.SZ → "A"`、`.HK → "HK"`、其他 → `"US"` |

### D. 必须新建(无现成可复用)

| 项 | 原因 |
|---|---|
| **统一 symbol normalizer** | 现状是 adapter-private(`_to_baostock_code` / `_to_yfinance_code` 等)。需要 `normalize_symbol(raw: str) -> tuple[str, str]` 返回 `(canonical_code, market)`。 |
| **SSE 流式响应模式** | 后端目前 0 SSE 实现。需要新建 `services/agent/sse.py` 工具(line-delimited JSON over `text/event-stream`)。 |
| **LLM 多协议客户端** | 需要支持 OpenAI / Anthropic / DeepSeek / OpenRouter 4 协议。可参考 `Turtle_investment_framework/scripts/data_provider/`(无 LLM 实现)— 实质是新建。 |
| **Agent pipeline 编排** | 阶段调度、文件读写约定、超时熔断、SSE 进度发射。 |
| **system_config 扁平存储 + channel 重建** | 现状无任何 system_config 后端。 |

### E. 反模式 / 禁区

1. ❌ **不要直接 `pd.read_parquet` / `glob` 读业务数据** — 必须经 `DuckDBStore`(AGENTS.md 铁律)。
2. ❌ **不要读 `data/{kline,financial,dividend,valuation,indicators}/` 旧路径** — 全废弃。
3. ❌ **不要复制 `Turtle_investment_framework/prompts/`(legacy v1)和 `*_v2.md`(experimental)文件** — 用 `strategies/turtle/` 下的现役版本。
4. ❌ **不要复制 `phase3_preflight.md`** — 已合并到 `phase3_quantitative.md` Step 0。
5. ❌ **不要在 SSE 中发明 `request_upload / ask / substep` 事件** — 前端不识别,会变成空 muted 灰条。
6. ❌ **不要假设 backend 有 auth** — 期 1 全部跳过。
7. ❌ **不要把 system_config 设计成"channels 数组对象"** — 必须扁平 `{key, value}` 对齐前端 `LLM_<NAME>_*` 模型。
8. ❌ **不要用 `BasicRepository`** — 它读非 canonical 路径 `data/basic/A/`。要用 `stock_index`。

---

## 期 1 Phase 划分总览

| Phase | 名称 | 工作量 | 阻塞下游 | 可并行 |
|---|---|---|---|---|
| A | 基础设施(SQLite schema + symbol normalizer + 目录) | 0.5 天 | B、C、D、G | — |
| B | system_config 后端(扁平 KV + 11 个 endpoint) | 2-3 天 | C(LLM client) | A 完后可与 D 并行 |
| C | LLM 多协议客户端 + channel 重建器 | 2 天 | E、F、G | B 完后 |
| D | Phase 1 数据包适配器(DuckDB → data_pack_market.md §1-§17) | 3-4 天 | E、F | A 完后,与 B 并行 |
| E | Phase 3.1 CPA 量化 agent(Step 0 + 11 步,引用 D 产物) | 1-2 天 | F、G | C+D 完后 |
| F | Phase 3.2 估值/报告 agent | 1-2 天 | G | E 完后 |
| G | SSE 路由 + 会话存储 + Coordinator 编排 | 2-3 天 | — | E+F 完后 |
| **Final** | 集成测试 + 端到端冒烟 | 1 天 | — | G 完后 |

**期 1 总工期估算**:11-16 天(关键路径 A → B → C → E → F → G)。可压缩到 8-10 天若 B/D 双线推进。

---

## Phase A: 基础设施

### A.1 What to implement

1. **新建目录结构**(空骨架,含 `__init__.py`):
   ```
   backend/services/agent/
       __init__.py
       sse.py                # SSE 工具
       symbol.py             # 代码 normalizer
       coordinator.py        # 占位
       pipeline/
           __init__.py
           phase1_data_pack.py   # 占位
           phase3_quant.py       # 占位
           phase3_valuation.py   # 占位
       prompts/              # turtle prompts 复制目录
   backend/services/system_config/
       __init__.py
       store.py              # 占位
       schema.py             # 占位
       llm_client.py         # 占位(Phase C)
   data/agent_runs/          # 输出目录,空(.gitkeep)
   ```

2. **`backend/services/agent/symbol.py`** — 统一 normalizer:

   ```python
   # 期望签名(必须包含 docstring + 单元测试覆盖)
   def normalize_symbol(raw: str) -> tuple[str, str]:
       """归一化代码 + 推断市场。

       支持输入:
         '000001'         -> ('000001.SZ', 'A')
         '600519'         -> ('600519.SH', 'A')
         '000001.SZ'      -> ('000001.SZ', 'A')
         '600519.SH'      -> ('600519.SH', 'A')
         '00700'          -> ('00700.HK', 'HK')
         '00700.HK'       -> ('00700.HK', 'HK')
         '0700.HK'        -> ('00700.HK', 'HK')   # yfinance 风格补 0
         'AAPL'           -> ('AAPL', 'US')
         'AAPL.US'        -> ('AAPL', 'US')        # US 不带后缀(对齐 stock_index)
       Returns: (canonical_code, market) where market in {'A','HK','US'}
       Raises: ValueError 当无法识别
       """
   ```

   **A 股识别规则**(沿用 `routers/market_kline.py:15` `_resolve_market` 逻辑):
   - 6 位数字 + `.SH/.SZ` 后缀 → A
   - 6 位数字无后缀 → A,前缀判断:`6` 开头 → SH,`0/3` 开头 → SZ,其他 → SZ
   - 5 位数字(可选 `.HK`)→ HK(若 4 位且 `.HK` 后缀,补前导 0)
   - 字母 → US,去掉 `.US` 后缀

3. **`backend/services/agent/sse.py`** — SSE 工具:

   ```python
   from typing import AsyncIterator, Any
   import json

   def sse_format(event: dict[str, Any]) -> str:
       """将事件 dict 序列化为 'data: <json>\n\n' 格式。

       严格遵守前端 6 事件协议(thinking/tool_start/tool_done/generating/done/error)。
       发射其他 type 会变成前端 muted 灰条 — 禁止。
       """
       return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

   async def sse_thinking(message: str, step: int | None = None) -> str: ...
   async def sse_tool_start(tool: str, display_name: str | None = None) -> str: ...
   async def sse_tool_done(tool: str, duration: float, success: bool, display_name: str | None = None) -> str: ...
   async def sse_generating(message: str = "正在生成最终分析...") -> str: ...
   async def sse_done(content: str) -> str: ...
   async def sse_error(message: str, error: str | None = None) -> str: ...
   ```

4. **SQLite schema** — 新增 `services/db_schema.py::init_agent_tables(conn)`:

   ```sql
   -- 会话表
   CREATE TABLE IF NOT EXISTS agent_chat_sessions (
       session_id TEXT PRIMARY KEY,           -- UUID,前端生成
       title TEXT NOT NULL,                   -- 取首条用户消息前 60 字
       stock_code TEXT,                       -- 解析到的 canonical code(可选)
       stock_market TEXT,                     -- 'A'/'HK'/'US'
       output_dir TEXT,                       -- 'data/agent_runs/{code}_{ts}'
       status TEXT NOT NULL DEFAULT 'idle',   -- 'idle'|'running'|'done'|'error'
       current_phase TEXT,                    -- 'phase1'/'phase3_1'/'phase3_2'/null
       message_count INTEGER NOT NULL DEFAULT 0,
       created_at TEXT NOT NULL,
       last_active TEXT NOT NULL
   );
   CREATE INDEX IF NOT EXISTS idx_agent_sessions_last_active ON agent_chat_sessions(last_active DESC);

   -- 消息表
   CREATE TABLE IF NOT EXISTS agent_chat_messages (
       id TEXT PRIMARY KEY,                   -- UUID
       session_id TEXT NOT NULL REFERENCES agent_chat_sessions(session_id) ON DELETE CASCADE,
       role TEXT NOT NULL,                    -- 'user'|'assistant'
       content TEXT NOT NULL,
       skills TEXT,                           -- JSON array,可空
       thinking_steps TEXT,                   -- JSON array of ProgressStep,可空(仅 assistant)
       created_at TEXT NOT NULL
   );
   CREATE INDEX IF NOT EXISTS idx_agent_messages_session ON agent_chat_messages(session_id, created_at);
   ```

   迁移函数挂到 `main.py:54 lifespan` 里(在 `init_db()` 之后调用):
   ```python
   # main.py lifespan
   from backend.services.db_schema import init_agent_tables
   conn = get_connection()
   init_agent_tables(conn)
   conn.close()
   ```

5. **`backend/config.py`** 新增常量:
   ```python
   AGENT_RUNS_DIR = DATA_DIR / "agent_runs"
   AGENT_RUNS_DIR.mkdir(parents=True, exist_ok=True)
   SYSTEM_CONFIG_YAML = DATA_DIR / "system_config.yaml"
   ```

### A.2 Documentation references

- 现有 SQLite migration 模式:`backend/services/db_schema.py:6 init_backtest_tables`(idempotent CREATE + 列检查 ALTER)
- 现有 lifespan 调用模式:`backend/main.py:54`
- 市场判定参考:`backend/routers/market_kline.py:15`
- 现有 adapter 私有 normalizer 参考(只看不抄):`backend/adapters/baostock_adapter.py:37-50`、`backend/adapters/yfinance_adapter.py:15-31`

### A.3 Verification checklist

- [ ] `python -m pytest backend/tests/test_agent_symbol.py -x` 通过(新建 ≥ 12 个用例覆盖所有输入形态 + 错误路径)
- [ ] `python -m pytest backend/tests/test_agent_sse.py -x` 通过(覆盖 6 个事件函数,验证输出严格 `data: {json}\n\n` 格式)
- [ ] `sqlite3 data/portfolio.db ".schema agent_chat_sessions"` 输出包含上述全部字段
- [ ] `sqlite3 data/portfolio.db ".schema agent_chat_messages"` 同上
- [ ] 重启 backend 后 `ls data/agent_runs/` 存在
- [ ] `python -c "from backend.services.agent.symbol import normalize_symbol; print(normalize_symbol('600519'))"` 输出 `('600519.SH', 'A')`
- [ ] `grep -r "request_upload\|substep\|^ask$" backend/services/agent/` 0 命中(确保未发明禁用事件)

### A.4 Anti-pattern guards

- ❌ 不要把 normalizer 放进 adapter 文件 — 必须独立模块,被多处引用
- ❌ 不要在 sse.py 中发明非 6 类事件类型
- ❌ 不要用 `pd.read_parquet` 读任何业务数据
- ❌ 不要把 SQLite 表创建放进 `routers/` — migration 函数必须在 `services/db_schema.py`
- ❌ US 代码**不带 `.US` 后缀**(对齐 `services/stock_index.py:67-72` 现状,直接 `f.stem`)— 期 1 不引入 `.US` 后缀,等期 2/3 决定

---

## Phase B: system_config 后端(扁平 KV + 11 endpoint)

### B.1 What to implement

**核心思想**:存储模型 = 扁平 `{key: str, value: str}` 列表,持久化 = `data/system_config.yaml`(简单文本,便于运维 grep/diff)。Channel 结构在**服务层**通过解析 `LLM_<NAME>_*` key 前缀重建。

#### B.1.1 持久化层 — `backend/services/system_config/store.py`

```python
class SystemConfigStore:
    """扁平 KV 配置存储,文件 = data/system_config.yaml。

    yaml 顶层结构:
        config_version: '1.0.3'  # 每次 PUT 时 +1 patch
        updated_at: '2026-05-23T12:34:56'
        items:
          - key: LLM_CHANNELS
            value: 'aihubmix,deepseek'
          - key: LLM_AIHUBMIX_PROTOCOL
            value: 'openai'
          ...
    """

    def __init__(self, yaml_path: Path = SYSTEM_CONFIG_YAML): ...

    def load(self) -> dict:  # {config_version, updated_at, items: [{key, value}]}
        ...

    def save(self, items: list[dict], expected_version: str | None) -> str:
        """乐观锁:expected_version 不匹配则 raise ConflictError。返回新 version。"""
        ...

    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...

    def export_env(self) -> str:
        """导出 .env 格式文本(KEY=VALUE 行,sensitive 字段不脱敏 — 直接导出)。"""
        ...

    def import_env(self, content: str, expected_version: str | None) -> dict:
        """解析 .env,merge 到当前 items,返回 update result。"""
        ...
```

#### B.1.2 Schema 层 — `backend/services/system_config/schema.py`

定义 18 个 LLM 相关 + N 个 notification 相关的 `SystemConfigFieldSchema`(对齐前端 `types/systemConfig.ts:39-57` 的 shape):

```python
@dataclass
class SystemConfigFieldSchema:
    key: str
    title: str
    description: str
    category: str          # 'base'|'data_source'|'ai_model'|'notification'|'system'|'agent'|'backtest'|'uncategorized'
    data_type: str         # 'string'|'integer'|'number'|'boolean'|'array'|'json'|'time'
    ui_control: str        # 'text'|'password'|'number'|'select'|'textarea'|'switch'|'time'
    is_sensitive: bool
    is_required: bool
    is_editable: bool
    default_value: str | None = None
    options: list = field(default_factory=list)
    validation: dict = field(default_factory=dict)
    display_order: int = 0
    help_key: str | None = None
    examples: list[str] = field(default_factory=list)

ALL_SCHEMAS: list[SystemConfigFieldSchema] = [
    # ── ai_model 类 ──
    SystemConfigFieldSchema(key='LLM_CHANNELS', title='已启用的 LLM 渠道', category='ai_model', data_type='array', ui_control='text', is_sensitive=False, ...),
    # 对每个静态 channel(aihubmix/deepseek/...)+ 动态 channel(用户自定义):
    #   LLM_<NAME>_PROTOCOL, _BASE_URL, _API_KEYS, _API_KEY (legacy), _MODELS, _ENABLED, _EXTRA_HEADERS
    # 但 schema 表只列泛化模板 + 静态运行时 key:
    SystemConfigFieldSchema(key='LITELLM_MODEL', title='主模型', category='ai_model', ...),
    SystemConfigFieldSchema(key='AGENT_LITELLM_MODEL', title='Agent 主模型', category='ai_model', ...),
    SystemConfigFieldSchema(key='LITELLM_FALLBACK_MODELS', title='降级模型链', ...),
    SystemConfigFieldSchema(key='VISION_MODEL', title='Vision 模型', ...),
    SystemConfigFieldSchema(key='LLM_TEMPERATURE', title='温度', ...),
    SystemConfigFieldSchema(key='LITELLM_CONFIG', title='LiteLLM 高级 yaml(可选)', ui_control='textarea', ...),
    # ── notification ── (期 1 stub,但 schema 字段要齐全以便前端渲染)
    SystemConfigFieldSchema(key='NOTIFY_CHANNELS', ...),
    # ... 13 个通知渠道的子 key
    # ── system ──
    SystemConfigFieldSchema(key='AUTH_ENABLED', default_value='false', is_editable=False, ...),  # 期 1 永远 false
]
```

**动态 channel key 处理**:`LLM_<NAME>_*` 这组 key 是**用户定义** name 的,schema 不能预知所有 NAME。Store 加载时遇到匹配 `LLM_*_PROTOCOL` 的 key 即"发现"一个 channel,生成临时 schema(category=ai_model,is_sensitive=true for `_API_KEYS/_API_KEY`)。

#### B.1.3 Validate 层 — `backend/services/system_config/validate.py`

```python
def validate_items(items: list[dict]) -> list[ConfigValidationIssue]:
    """逐 item 校验。规则:
       - LLM_CHANNELS 中列出的每个 name,必须有对应 LLM_<NAME>_PROTOCOL
       - LLM_<NAME>_PROTOCOL 必须 in {'openai','deepseek','gemini','anthropic','vertex_ai','ollama'}
       - LLM_<NAME>_BASE_URL 若 protocol=openai/deepseek 必须非空
       - LLM_TEMPERATURE 必须 0-2 浮点
       - LITELLM_MODEL 若设置,必须形如 'channel_name/model_id'
       返回 issues 列表(error/warning,带 key/code/message)。
    """
```

issue code 列举(供前端 i18n):`MISSING_REQUIRED`、`INVALID_PROTOCOL`、`INVALID_FORMAT`、`OUT_OF_RANGE`、`CHANNEL_PROTOCOL_MISSING`。

#### B.1.4 Setup status — `backend/services/system_config/setup.py`

```python
def get_setup_status() -> SetupStatusResponse:
    """检查最小可用配置是否齐全:
       checks 列表:
         - 'LLM_CHANNELS' configured (≥1 channel)
         - 至少一个 channel 有 API_KEY
         - 'LITELLM_MODEL' set
         - 'AGENT_LITELLM_MODEL' set(可继承 LITELLM_MODEL)
       is_complete = 全部 required 都 configured
       ready_for_smoke = is_complete && 至少一个 channel 通过 testLLMChannel(可选,不强求)
    """
```

#### B.1.5 LLM channel 测试 + 模型发现 — `backend/services/system_config/llm_test.py`

```python
async def test_llm_channel(req: TestLLMChannelRequest) -> TestLLMChannelResponse:
    """对 req.protocol + req.base_url + req.api_key 发一次最小请求(/v1/models 或 messages)。
    如果 capability_checks 非空,对每项再做一次专项测试(json mode / tools / vision / stream)。
    """

async def discover_llm_models(req: DiscoverLLMChannelModelsRequest) -> DiscoverLLMChannelModelsResponse:
    """根据 protocol 调用对应的 models 列表 endpoint:
       openai/deepseek/openrouter: GET {base_url}/models
       anthropic: 硬编码列表(API 不暴露)
       gemini: GET https://generativelanguage.googleapis.com/v1beta/models
    """
```

#### B.1.6 路由 — `backend/routers/system_config.py`

**11 个 endpoint**(全部 snake_case wire format):

| URL | Method | 实现要点 |
|---|---|---|
| `GET /api/v1/system/config?include_schema=true` | | 返回 `{config_version, mask_token, items, updated_at}`。mask_token 是当次响应专用 nonce,sensitive items 的 value = `<MASKED:abc123>`,前端 PUT 时若 value 仍是 `<MASKED:abc123>` 则后端跳过更新该 key |
| `GET /api/v1/system/config/schema` | | 返回 `{schema_version, categories: [{category, fields: [...]}]}` |
| `GET /api/v1/system/config/setup/status` | | |
| `GET /api/v1/system/config/export` | | 返回 `{content, config_version, updated_at}` |
| `POST /api/v1/system/config/validate` | | body `{items}`,返回 `{valid, issues}` |
| `POST /api/v1/system/config/import` | | body `{config_version, content, reload_now}` |
| `PUT /api/v1/system/config` | | body `{config_version, mask_token, reload_now, items}`。**400 + ConfigValidationError shape** if validate fail;**409 + ConfigConflict shape** if version mismatch |
| `POST /api/v1/system/config/llm/test-channel` | | |
| `POST /api/v1/system/config/llm/discover-models` | | |
| `POST /api/v1/system/config/notification/test-channel` | | **期 1 stub**:返回 `{success: false, message: "通知渠道期 1 未实现", error_code: "NOT_IMPLEMENTED", retryable: false, attempts: []}` |

**注册**:在 `backend/main.py` 的 `app.include_router(...)` 区追加 `app.include_router(system_config_router, prefix="/api/v1/system/config")`。

#### B.1.7 Auth stub 路由 — `backend/routers/auth_stub.py`

```python
# 仅 1 个 endpoint
@router.get("/api/v1/auth/status")
async def auth_status():
    return {
        "authEnabled": False,           # camelCase 对齐前端 auth.ts:13
        "loggedIn": False,
        "passwordSet": False,
        "passwordChangeable": False,
        "setupState": "no_password",
    }

# 其他 4 个 (login/logout/change-password/settings) 期 1 不暴露 — 前端在 authEnabled=false 时不调用
```

### B.2 Documentation references

- 前端契约权威源(全部已在 Phase 0 §B.2 引用):
  - `frontend/src/api/systemConfig.ts:131-237`(11 个方法签名)
  - `frontend/src/types/systemConfig.ts:1-272`(全部 type 定义)
  - `frontend/src/components/settings/LLMChannelEditor.tsx:953-1024`(channel ↔ key 映射规则)
  - `frontend/src/components/settings/NotificationTestPanel.tsx:14-28`(13 个通知渠道枚举)
- 后端注册路由模式参考:`backend/main.py:80-90`(已有 router include)
- 现有 router 结构参考:`backend/routers/portfolio.py`(CRUD 模式)

### B.3 Verification checklist

- [ ] `python -m pytest backend/tests/test_system_config_store.py -x` 通过(覆盖 load/save/get/set/import_env/export_env)
- [ ] `python -m pytest backend/tests/test_system_config_validate.py -x` 通过(每个 issue code 至少 1 个 case)
- [ ] `python -m pytest backend/tests/test_system_config_routes.py -x` 通过(11 个 endpoint 各至少 1 case,含 409 冲突 + 400 校验失败路径)
- [ ] **集成验证**:启动 backend,前端打开 SettingsPage:
  - LLM channel 列表能渲染(读现有 yaml 或空状态都不崩)
  - 添加一个 channel(name=test,protocol=openai,base_url=https://api.openai.com/v1,api_key=sk-...)→ 保存 → 刷新页面后值仍在
  - 点 "测试连接" 能调通(若 key 真实)或报清晰错误
  - sensitive 字段(API_KEYS)显示为 `<MASKED:...>`,直接保存(value 仍为 mask)→ 后端不覆盖
- [ ] `curl http://localhost:8000/api/v1/auth/status` 返回 `{"authEnabled": false, ...}`
- [ ] `curl http://localhost:8000/api/v1/system/config/notification/test-channel -X POST -d '{...}'` 返回 stub `{success: false, message: "..."}`,前端 NotificationTestPanel 能渲染该错误

### B.4 Anti-pattern guards

- ❌ **不要**把 channel 设计成嵌套对象(`{name, protocol, ...}`)— 持久化必须是扁平 KV,channel 结构是**派生视图**
- ❌ **不要**在 yaml 中存明文 `LLM_<NAME>_API_KEYS`?**实际要存** — 用户已确认无 auth,此机器是单用户;但响应给前端时必须 mask
- ❌ **不要**让 mask_token 跨请求复用 — 每次 GET 生成新 nonce
- ❌ **不要**返回 camelCase 给 system/config 系列(只有 auth 系列是 camelCase)
- ❌ **不要**为 stub 通知渠道返回 `success: true`(前端会误以为已实现)
- ❌ **不要**跳过乐观锁 — 必须 409 错误 shape `{error: "config_version_mismatch", message, currentConfigVersion}`(camelCase 内层对齐 `SystemConfigConflictResponse`,因为 frontend `systemConfig.ts:42-58` 用的是 camelCase 解析此错误)
  - **注意此处不一致!**:正常响应 snake_case,错误响应内层 camelCase(`currentConfigVersion`)。这是前端 `parseSystemConfigConflictError` 的解析逻辑,**必须严格对齐**

---

## Phase C: LLM 多协议客户端 + Channel 重建器

### C.1 What to implement

#### C.1.1 Channel 重建器 — `backend/services/system_config/channels.py`

```python
@dataclass
class LLMChannel:
    name: str               # 'aihubmix'
    protocol: str           # 'openai'|'deepseek'|'gemini'|'anthropic'|'vertex_ai'|'ollama'
    base_url: str
    api_keys: list[str]     # 多 key 轮询
    models: list[str]
    enabled: bool
    extra_headers: dict[str, str]

def list_channels(store: SystemConfigStore) -> list[LLMChannel]:
    """从扁平 KV 重建 channel 列表。
    1. 读 LLM_CHANNELS,得 names
    2. 对每个 name,读 LLM_<NAME>_PROTOCOL/_BASE_URL/_API_KEYS/_MODELS/_ENABLED/_EXTRA_HEADERS
    3. _API_KEYS 优先(逗号分隔),fallback _API_KEY(legacy 单 key)
    """

def resolve_model(model_ref: str, store: SystemConfigStore) -> tuple[LLMChannel, str]:
    """解析 'channel_name/model_id' 格式。
       例:'aihubmix/claude-3-5-sonnet-20241022' -> (channel_aihubmix, 'claude-3-5-sonnet-20241022')
    """
```

#### C.1.2 LLM 客户端抽象 — `backend/services/system_config/llm_client.py`

```python
from typing import AsyncIterator

@dataclass
class LLMMessage:
    role: str  # 'system'|'user'|'assistant'
    content: str

@dataclass
class LLMRequest:
    messages: list[LLMMessage]
    model: str               # raw model id(不含 channel 前缀)
    temperature: float = 0.7
    max_tokens: int | None = None
    stream: bool = False

@dataclass
class LLMResponse:
    content: str
    finish_reason: str
    usage: dict               # {prompt_tokens, completion_tokens, total_tokens}

class BaseLLMClient(ABC):
    @abstractmethod
    async def complete(self, req: LLMRequest) -> LLMResponse: ...
    @abstractmethod
    async def stream(self, req: LLMRequest) -> AsyncIterator[str]: ...   # yields content delta strings

class OpenAICompatibleClient(BaseLLMClient):
    """支持 OpenAI/DeepSeek/OpenRouter/Ollama(都用 OpenAI 兼容 API)。"""
    def __init__(self, channel: LLMChannel): ...
    # POST {base_url}/chat/completions

class AnthropicClient(BaseLLMClient):
    """Anthropic Messages API。"""
    def __init__(self, channel: LLMChannel): ...
    # POST {base_url}/v1/messages,header 'anthropic-version: 2023-06-01'
    # role mapping: system → top-level 'system' field;assistant/user → messages

def make_client(channel: LLMChannel) -> BaseLLMClient:
    """工厂。按 channel.protocol 路由:
       openai/deepseek/ollama -> OpenAICompatibleClient
       anthropic -> AnthropicClient
       gemini/vertex_ai -> 期 1 NotImplementedError(不在 MVP 范围)
    """
```

**多 key 轮询策略**(简单实现):每次请求随机选一个 key;若 401/429,标记该 key 失败,fallback 下一个。期 1 不做持久化失败统计。

**超时与重试**:
- 单次请求超时 = 60s
- 失败重试 3 次(指数退避 1s/2s/4s),仅对 5xx 和网络错误重试

#### C.1.3 Routing — `backend/services/agent/llm_routing.py`

```python
def get_agent_llm_client(phase: str = "default") -> tuple[BaseLLMClient, str]:
    """根据 phase 选择 channel + model。
    读取 system_config:
      AGENT_LITELLM_MODEL 优先(若设置)
      否则 fallback LITELLM_MODEL
      若都无,raise ConfigError("LLM model not configured")
    返回 (client, raw_model_id)
    """
```

期 1 所有 agent phase(phase1/phase3_1/phase3_2)共用同一 model。期 2/3 可在 yaml 加 `AGENT_PHASE_<NAME>_MODEL` 覆盖。

### C.2 Documentation references

- 测试用 mock:模仿 `backend/tests/test_adapters.py` 的 mock 模式
- httpx 异步客户端是项目已有依赖(grep `httpx` confirms);若不是则加入 `requirements.txt`
- Anthropic API doc(只读):https://docs.anthropic.com/en/api/messages — 不要 fetch,按记忆实现
- OpenAI Chat Completions:同上 — 兼容协议众所周知

### C.3 Verification checklist

- [ ] `python -m pytest backend/tests/test_llm_channels.py -x` 通过
- [ ] `python -m pytest backend/tests/test_llm_client_openai.py -x`(全部 mock httpx,验证 request body shape + response 解析)
- [ ] `python -m pytest backend/tests/test_llm_client_anthropic.py -x`(同上,关键验证 system message 提到 top level)
- [ ] **手动集成测试**(若有真实 key):写 `scripts/smoke_llm.py`,从 system_config.yaml 读默认 channel 发"你好",验证返回非空
- [ ] `gemini/vertex_ai` protocol 调用 `make_client` 时确实抛 `NotImplementedError`(不静默回退)

### C.4 Anti-pattern guards

- ❌ **不要**在 client 里硬编码 base_url — 必须从 channel 拿
- ❌ **不要**把 API key 写日志(包括 error log)— 错误消息只输出 `key_index=2 failed` 之类
- ❌ **不要**用 `requests`(同步阻塞)— 必须 `httpx.AsyncClient`
- ❌ **不要**在 agent 代码中直接 `import httpx` 或拼 base_url — 必须经 `make_client(channel)` → `client.complete()`
- ❌ **不要**让多 key 轮询变成"全部 key 都试一遍才报错" — 第二次失败立刻报错,避免被上游 ban

---

## Phase D: Phase 1 数据包适配器(DuckDB → data_pack_market.md)

### D.1 What to implement

**目标**:对给定 `(symbol, market)`,产出 markdown 文件 `{output_dir}/data_pack_market.md`,严格满足 Phase 0 §A 引用的 schema。

**架构**(新建模块):

```
backend/services/agent/pipeline/phase1_data_pack/
    __init__.py
    builder.py                # DataPackBuilder 主类
    sections/
        __init__.py
        section_basic.py      # §1
        section_market.py     # §2
        section_income.py     # §3 + §3P
        section_balance.py    # §4 + §4P
        section_cashflow.py   # §5
        section_dividend.py   # §6
        section_holders.py    # §7 (主体 placeholder + 十大股东子表)
        section_industry.py   # §8 (placeholder)
        section_segments.py   # §9
        section_mda.py        # §10 (placeholder)
        section_weekly.py     # §11
        section_indicators.py # §12
        section_risk.py       # §13.1 自动检测 + §13.2 placeholder
        section_riskfree.py   # §14
        section_repurchase.py # §15
        section_pledge.py     # §16
    derived/                  # §17 衍生指标
        __init__.py
        sec17_1_trends.py
        sec17_2_factor2.py
        sec17_3_factor3_step1.py
        sec17_4_factor3_step4.py
        sec17_5_sensitivity.py
        sec17_6_factor4.py
        sec17_7_sotp.py
        sec17_8_baseline.py
        sec17_9_sensitivity.py
    format_utils.py           # format_table / format_number / format_money(单位换算)
    warnings.py               # WarningsCollector(§13.1)
```

#### D.1.1 主类 `DataPackBuilder`

```python
class DataPackBuilder:
    def __init__(self, store: DuckDBStore, stock_index: StockIndex):
        self.store = store
        self.idx = stock_index

    def build(self, symbol: str, market: str, output_dir: Path) -> dict:
        """生成 data_pack_market.md。
        返回 {'success': True/False, 'completed': N, 'total': M, 'warnings': [...]}
        """
        # 1. header(币种 + 单位)
        # 2. 按市场决定 section 列表:
        #    A 股: §1,§2,§3,§3P,§4,§4P,§5,§6,§7,§8,§9,§10,§11,§12,§13,§14,§15,§16,§17(全部子段)
        #    HK : §1-§7(7 placeholder),§9 placeholder,§10 placeholder,§11,§12,§13,§14,§15 placeholder,§17(全部子段,HK 适配)
        #    US : 同 HK 但 §16 不适用(返回"不适用")
        # 3. 调对应 section_xxx.build(symbol, market) 拼接
        # 4. 写文件
        # 5. 返回统计
```

#### D.1.2 单位换算规则(从 Tushare assembly.py 推断)

| 市场 | 报表币种 | 显示单位 |
|---|---|---|
| A | CNY | 百万元 |
| HK | HKD | 百万港元 |
| US | USD | 百万美元 |

`format_money(value, market) -> str`:把 DuckDB 原值(单位 = 元/HKD/USD)除以 1_000_000 后保留 2 位小数。

#### D.1.3 各 section 实现要点(关键三个)

**§1 基本信息**(`section_basic.py`):
- 来源:`stock_index.get_name(symbol, market)` + `DuckDBStore.query_kline(market, symbol, limit=1)` 取最新行
- 输出字段:股票代码/名称/上市日期(从 indicator 表最早 REPORT_DATE 或 daily 表最早日期推断)/市场/币种/总股本(从 indicator 表 TOTAL_SHARE 或 circulating_shares 表)
- A 股专属:行业(SW1)— **期 1 暂留 "未知",数据源 backlog**

**§3 合并利润表**(`section_income.py`):
- 来源:`store.query_financial(market, 'income', symbol, limit=20)` — 取最近 20 期(5 年 4 季度 ≈ 5 年)
- 字段映射:DuckDB indicator 表是英文 schema(`REPORT_DATE / TOTAL_OPERATE_INCOME / OPERATE_PROFIT / TOTAL_PROFIT / NETPROFIT / PARENT_NETPROFIT / BASIC_EPS` 等)
- 输出 markdown 表格:报表日期 | 营业总收入 | 营业利润 | 利润总额 | 净利润 | 归母净利润 | 基本 EPS

**§3P 母公司利润表**(A 股专属):
- 来源:**期 1 留 placeholder**(DuckDB 当前未单独建母公司视图)— 写入"`*[§3P 数据暂未接入,期 2 补充]*`"
- 验证:仅 A 股市场输出此 section

**§17.1 财务趋势速览**(`derived/sec17_1_trends.py`):
- 取近 5 年 ROEJQ / GROSS_MARGIN / NET_MARGIN / 营收增长率 / 净利增长率
- 输出趋势表 + 文字解读"5 年 ROE 稳定在 X-Y% 区间,呈 [上升/下降/平稳] 趋势"
- 字段映射:用 `query_financial(market, 'indicator')` 的 `ROEJQ / SJL / XSMLL` 等

**§17.6 因子4·股价分位**(`derived/sec17_6_factor4.py`):
- 从 `query_qfq_kline(market, symbol)` 取最近 10 年日线
- 计算当前价在历史分位:`current_close / max(close_10y)`,`current_close / min(close_10y)`,百分位
- 输出"当前股价位于 10 年区间 X% 分位"

(其他 section 详细实现照搬 Tushare `tushare_modules/financials.py` + `derived_metrics.py` 的逻辑,字段映射 DuckDB 英文 schema → 输出中文标签)

#### D.1.4 §13.1 自动风险警示(`warnings.py`)

`WarningsCollector` 扫描以下信号:
- 商誉 / 总资产 > 30%(从 balance 表 GOODWILL)
- 应收账款增速 > 营收增速(从 balance/income 表对比)
- 经营现金流 < 净利润 ×60%(从 cashflow/income)
- 资产负债率 > 70%
- 大股东质押率 > 50%(若有 §16 数据)

每条命中输出一行 `- ⚠️ {描述}: {当前值} {历史值}`。无命中输出 `*[§13.1 未发现自动风险信号]*`。

### D.2 Documentation references

- **数据包 schema 权威源**:`Turtle_investment_framework/scripts/tushare_modules/assembly.py:206-437`(`assemble_data_pack`)
- **§17 衍生指标实现参考**:`Turtle_investment_framework/scripts/tushare_modules/derived_metrics.py`(每个 _compute_* 函数对应一个 §17.x)
- **schema 测试**:`Turtle_investment_framework/tests/test_output_format.py:36-91`(移植为 backend test)
- **DuckDB 字段对应**:`backend/services/duckdb_store.py:449-474`(query_financial 返回值为 DataFrame,列名 = parquet 列名;用 `head()` + 实际数据观察)
- **现成的 K 线聚合**:`backend/services/stock_data.py::aggregate_kline(df, period='W-FRI'|'M')`(供 §11 周线用)

### D.3 Verification checklist

- [ ] `python -m pytest backend/tests/test_phase1_data_pack_schema.py -x` 通过 — 移植自 `tests/test_output_format.py`,验证生成的 md 包含全部必须 section header
- [ ] `python -m pytest backend/tests/test_phase1_sections/test_section_income.py -x` 等(每个 section 至少 1 个 case,用 mock DuckDB)
- [ ] **集成测试**:`python scripts/smoke_data_pack.py 600519.SH`(脚本写在 scripts/ 下,调用 builder,产出文件)
  - 文件存在 ✓
  - 文件大小 > 5KB ✓
  - 用 grep 验证存在 `## 1. 基本信息` ~ `## 17.9 因子4·业绩下滑敏感性`
  - 验证币种 header 为 `*金额单位: 百万元 *`
- [ ] HK / US 各跑一例(`smoke_data_pack.py 00700.HK` / `AAPL`),验证币种 header 切换正确,不该出现的 section 不出现

### D.4 Anti-pattern guards

- ❌ **绝对不要**直接读 parquet — 全部经 `DuckDBStore` 的 `query_*` 方法
- ❌ **不要**复制 Tushare `tushare_collector.py` 的 7 个 mixin 文件 — 只参考 schema,实现层全新写
- ❌ **不要**用中文字段名(`净利润 / 营业收入` 之类作为 dict key)— DuckDB 是英文 schema(`NETPROFIT / TOTAL_OPERATE_INCOME`),内部全程英文,只在最终 markdown 输出时翻译成中文标签
- ❌ **不要**给 HK/US 强行生成 §3P/§4P/§16 — 不适用就不输出该 section,或输出"不适用"占位
- ❌ **不要**在 builder 内部触发任何 LLM 调用 — Phase 1 是纯数据组装
- ❌ **不要**把 `assemble_data_pack` 的`assemble_data_pack` 整体 copy 进来 — 它是 Tushare 专属逻辑,我们的实现是 DuckDB 改写

---

## Phase E: Phase 3.1 CPA 量化 Agent

### E.1 What to implement

#### E.1.1 Prompt 文件复制

```
backend/services/agent/prompts/turtle/
    coordinator.md             # 复制自 Turtle_investment_framework/strategies/turtle/coordinator.md
                               # 但删掉 Phase 0/1/2 调度段(L74-119 中关于 PDF/数据采集的部分)
                               # 期 1 coordinator 只负责 Phase 3.1 → 3.2 串联
    phase3_quantitative.md     # 完整复制
    phase3_valuation.md        # 完整复制(给 Phase F 用)
    references/
        shared_tables.md       # 完整复制
        factor_interface.md    # 完整复制
        judgment_examples_turtle.md
```

**复制操作**(可写 `scripts/copy_turtle_prompts.py` 一次性脚本):
```python
TURTLE_BASE = Path("/Users/11182300/PycharmProjects/Turtle_investment_framework")
TARGET = Path("backend/services/agent/prompts/turtle")
files_to_copy = [
    ("strategies/turtle/coordinator.md", "coordinator.md"),  # 后续手工删 Phase 0/1/2 段
    ("strategies/turtle/phase3_quantitative.md", "phase3_quantitative.md"),
    ("strategies/turtle/phase3_valuation.md", "phase3_valuation.md"),
    ("strategies/turtle/references/shared_tables.md", "references/shared_tables.md"),
    ("strategies/turtle/references/factor_interface.md", "references/factor_interface.md"),
    ("strategies/turtle/references/judgment_examples_turtle.md", "references/judgment_examples_turtle.md"),
]
```

#### E.1.2 Phase 3.1 Agent 实现 — `backend/services/agent/pipeline/phase3_quant.py`

```python
class Phase3QuantitativeAgent:
    """Agent B:CPA 角色,11 步穿透回报率分析。

    输入(从 output_dir 读):
      - data_pack_market.md (Phase 1 产物)
      - qualitative_report.md (期 2 产物,期 1 不存在 → agent 用 placeholder 假设处理)

    输出(写到 output_dir):
      - phase3_quantitative_report.md  (含 Step 0 校验 + 11 步分析 + 汇总参数)
      - factor_b.json                  (结构化参数,供 Phase 3.2 消费,schema 见 factor_interface.md)
    """

    def __init__(self, llm_client: BaseLLMClient, model: str, prompt_dir: Path): ...

    async def run(
        self,
        symbol: str,
        market: str,
        output_dir: Path,
        progress_callback: Callable[[dict], Awaitable[None]] | None = None,
    ) -> dict:
        """progress_callback 用于 SSE 进度上报。
           调用顺序:
             1. callback(tool_start, tool='phase3_1_load', display_name='加载数据包')
             2. 读 data_pack_market.md
             3. callback(tool_done, tool='phase3_1_load')
             4. 组装 prompt: system = phase3_quantitative.md + shared_tables.md + factor_interface.md + judgment_examples_turtle.md
                            user = data_pack_market.md 内容
             5. callback(tool_start, tool='phase3_1_llm', display_name='CPA 穿透回报率分析')
             6. 调 llm_client.stream(req) — 每收到 chunk,buffer 累积(不发到前端,Phase G 才控制流式)
             7. 解析 LLM 输出末尾的结构化参数(factor_interface.md 定义的 30 字段)
             8. 写 phase3_quantitative_report.md + factor_b.json
             9. callback(tool_done, tool='phase3_1_llm', duration=N, success=True)
           返回 {'report_path': ..., 'factor_b': {...}, 'duration': N}
        """
```

**Prompt 组装策略**:system message 由静态 reference 文件拼接(总长度 ~12K tokens),user message 是 data_pack_market.md(~10-30K tokens)。**必须用支持长 context 的模型**(claude-3.5-sonnet / gpt-4o / deepseek-v3 都满足)。

**结构化参数解析**:Agent 输出末尾必须含 `<factor_b>` ~ `</factor_b>` XML 块(在 prompt 中强制),内容为 JSON。解析器用正则 `r'<factor_b>(.*?)</factor_b>'` + `json.loads`。失败则退回 LLM 一次("请只输出 factor_b JSON,无其他文字"),仍失败则报错。

#### E.1.3 超时与重试

- LLM 单次调用超时 = 300s(穿透回报率分析需要充分思考)
- Step 0 校验失败若返回 ABORT,直接终止 Phase 3.1,标记 session.status = error

### E.2 Documentation references

- Prompt 内容权威:`strategies/turtle/phase3_quantitative.md` 全文(459 行)
- 11 步结构:Phase 0 §C 表(已列各 step 行号)
- 输出参数 schema:`strategies/turtle/references/factor_interface.md` L65-94(Agent B → Agent C 30 参数)
- 类似 LLM 调用 pattern:Phase C 已搭好的 `llm_client.stream()`

### E.3 Verification checklist

- [ ] `python -m pytest backend/tests/test_phase3_quant_parser.py -x` 通过(用 mock LLM 输出验证 factor_b JSON 解析,含成功 + 退回重问 + 最终失败 三种路径)
- [ ] **集成测试**:`python scripts/smoke_phase3_quant.py 600519.SH`(假设 data_pack_market.md 已存在)
  - 产物:`phase3_quantitative_report.md` + `factor_b.json`
  - factor_b.json 含 factor_interface.md 定义的全部 30 字段(用 `jsonschema` 校验)
  - report.md 含 11 个 `## 步骤X` header
- [ ] LLM 超时场景测试(用 mock 让 client.stream 等 400s)→ 应在 300s 时抛 TimeoutError 且 progress_callback 收到 tool_done(success=False)

### E.4 Anti-pattern guards

- ❌ **不要**复制 `strategies/turtle/phase3_preflight.md` — 已废弃合并入 quantitative.md Step 0
- ❌ **不要**让 Agent 自行调 DuckDB / 工具 — 期 1 不引入 function-calling,LLM 只读 markdown 文件
- ❌ **不要**把 LLM 输出直接当 markdown 报告写入文件而不解析 factor_b — 下游 Phase 3.2 必须有结构化参数输入
- ❌ **不要**在 Phase 3.1 处理 qualitative_report.md 缺失 — agent 应用 placeholder("定性维度暂未提供,假设 moat_rating=中等")继续运行(期 2 引入后才有真实 qualitative)
- ❌ **不要**在 prompt 里硬编码 `$TS_CODE` 变量 — 用 `{symbol}` 占位,运行时 format

---

## Phase F: Phase 3.2 估值/报告 Agent

### F.1 What to implement

#### F.1.1 Agent 实现 — `backend/services/agent/pipeline/phase3_valuation.py`

```python
class Phase3ValuationAgent:
    """Agent C:首席分析师,做买入/观察/排除决策 + 估值定价 + 组装最终报告。

    输入(从 output_dir 读):
      - data_pack_market.md
      - qualitative_report.md  (期 2 产物;期 1 缺失时用 placeholder)
      - phase3_quantitative_report.md
      - factor_b.json

    输出(写到 output_dir):
      - final_report.md              (面向用户的最终投资分析报告)
      - factor_c.json                (估值结构化参数:目标价/触发价/仓位/结论)
    """

    async def run(
        self,
        symbol: str,
        market: str,
        output_dir: Path,
        progress_callback: ...,
    ) -> dict:
        """流程:
           1. tool_start 'phase3_2_load' — 读 data_pack + factor_b + qualitative(若存在)
           2. tool_done 'phase3_2_load'
           3. tool_start 'phase3_2_llm' display_name='估值与报告'
           4. system prompt = phase3_valuation.md + shared_tables.md + factor_interface.md + judgment_examples_turtle.md
              user = 拼接 data_pack_market.md + factor_b.json + qualitative_report.md(若有)
           5. llm_client.stream(req) — 累积输出
           6. 解析 <factor_c> XML 块 → factor_c.json
           7. 报告主体写入 final_report.md
           8. tool_done
           返回 {'report_path': final_report.md, 'factor_c': {...}}
        """
```

#### F.1.2 报告模板嵌入

`phase3_valuation.md` L169-457 包含完整 `<report_template>` 块(报告骨架,含元信息 / Executive Summary / 关键假设 / 财务趋势速览 / 商业质量 / 穿透回报率 / 估值定价 / 综合结论 / 投资论点卡 / 风险提示)。

期 1 注意:**"商业质量分析"段(L240-258)依赖 qualitative_report.md**。期 1 该文件缺失,prompt 中给出明确 fallback 规则:
> "若 qualitative_report.md 不存在,在'商业质量分析'段写入 `*[期 2 补充]*`,并跳过 D1-D6 子段"

修改方式:**不改原 prompt 文件**,在系统消息后追加一段 instruction:
```
[期 1 补丁]
当前为 MVP 期 1,qualitative_report.md 不存在。
处理规则:
- "商业质量分析"段输出固定 placeholder
- "投资论点卡"中的"基本面止损条件"7 行表中,涉及定性维度的行写"待期 2 完善"
- 最终结论可信度标注为"中(缺定性维度)"
```

#### F.1.3 factor_c.json schema

(从 `factor_interface.md` L98-112 推断,含):
- `verdict`:`buy` | `observe` | `exclude`
- `position_pct`:仓位建议(0-100)
- `target_price`:估值目标价(本币)
- `trigger_buy_price`:买入触发价
- `safety_margin_pct`:安全边际百分比
- `confidence`:`high` | `medium` | `low`
- `key_risks`:`list[str]`
- `monitoring_events`:`list[str]`

### F.2 Documentation references

- Prompt:`strategies/turtle/phase3_valuation.md`(全 463 行,report template L169-457)
- 5 步估值流程:Phase 0 §D 表
- 仓位矩阵:`phase3_valuation.md:82-93`
- 双表敏感性:`phase3_valuation.md:120-142`

### F.3 Verification checklist

- [ ] `python -m pytest backend/tests/test_phase3_valuation_parser.py -x`(mock LLM,验证 factor_c JSON 解析)
- [ ] **集成测试**:`python scripts/smoke_phase3_valuation.py 600519.SH`(假设 Phase 1 + Phase 3.1 产物已存在)
  - 产物:`final_report.md` + `factor_c.json`
  - final_report.md 长度 > 3000 字符
  - 含 ASCII box(`+--`)的"综合结论"段
  - 含"投资论点卡"段(7 行止损条件表)
  - factor_c.json verdict in {buy, observe, exclude}
- [ ] qualitative 缺失场景测试:商业质量段输出 placeholder,不报错

### F.4 Anti-pattern guards

- ❌ **不要**修改 `phase3_valuation.md` 原文 — 用追加 instruction 处理期 1 patch
- ❌ **不要**让 Agent C 重新计算穿透回报率 — 必须信任 factor_b.json,只做估值与组装
- ❌ **不要**把 final_report.md 截断或加 "..." — 必须完整(LLM 输出过短时报错重试一次)
- ❌ **不要**在报告里出现 ts_code / 模型名 / API key 等技术细节 — 那些是内部信息

---

## Phase G: SSE 路由 + 会话存储 + Coordinator

### G.1 What to implement

#### G.1.1 Coordinator — `backend/services/agent/coordinator.py`

```python
class AskStockCoordinator:
    """期 1 简化 coordinator:
       Phase 1 数据包 → Phase 3.1 量化 → Phase 3.2 估值 → 完成

    SSE 进度上报粒度(总共 ~6 个 tool_start/tool_done 配对):
       1. tool_start: phase1_data_pack ("生成数据包")
       2. tool_done : phase1_data_pack
       3. tool_start: phase3_1 ("CPA 穿透回报率分析")
       4. tool_done : phase3_1
       5. tool_start: phase3_2 ("估值与报告组装")
       6. tool_done : phase3_2
       generating: ("正在汇总最终回复...")
       done: content = final_report.md 的内容
    """

    def __init__(self, store, llm_client, model, prompt_dir, output_base_dir): ...

    async def run(
        self,
        symbol_raw: str,
        session_id: str,
        sse_emit: Callable[[dict], Awaitable[None]],
    ) -> str:
        """主流程,返回最终 markdown 内容(用于 SSE done 事件)。

        步骤:
          1. normalize_symbol(symbol_raw) → (symbol, market)
          2. 创建 output_dir = data/agent_runs/{symbol}_{ts}
          3. 更新 session.stock_code/stock_market/output_dir/status='running'/current_phase='phase1'
          4. Phase 1 调用,sse_emit progress
          5. session.current_phase='phase3_1', Phase 3.1 调用
          6. session.current_phase='phase3_2', Phase 3.2 调用
          7. 读 final_report.md 内容
          8. session.status='done', current_phase=null
          9. 返回 final_report 内容
        异常:任何 Phase 失败 → session.status='error',raise CoordinatorError(含失败 phase + 原因)
        """
```

#### G.1.2 输入解析:从用户消息提取 symbol

`backend/services/agent/parser.py`:

```python
def parse_user_intent(message: str, context: dict | None) -> tuple[str, str] | None:
    """返回 (symbol, market) 或 None(无法识别)。
    解析顺序:
      1. context.stock_code 优先(前端 followup 场景已给)
      2. message 中匹配 6 位数字 → A 股
      3. message 中匹配 5 位数字 → HK
      4. message 中匹配大写字母 stock 名 (e.g. AAPL, TSLA) → US,经 stock_index 验证存在
      5. message 中含中文公司名 → stock_index.search_stocks(name) → 取首条
    """
```

#### G.1.3 SSE 路由 — `backend/routers/agent.py`

**6 个 endpoint**:

```python
@router.post("/api/v1/agent/chat/stream")
async def chat_stream(req: ChatStreamRequest):
    """
    body: {message: str, skills?: [str], session_id?: str, context?: ChatFollowUpContext}
    返回: text/event-stream
    """
    # 1. session_id = req.session_id or generate_uuid()
    # 2. upsert agent_chat_sessions 行(若不存在则 INSERT)
    # 3. INSERT user message into agent_chat_messages
    # 4. async generator:
    #    - sse_thinking("正在解析问题...")
    #    - parse_user_intent → 若失败,sse_error + done(success=False) 退出
    #    - sse_thinking(f"识别到 {symbol}({market})")
    #    - 启动 coordinator.run(),sse_emit 透传到 yield
    #    - 累积最终 content
    #    - sse_generating()
    #    - sse_done(content=final_report)
    #    - INSERT assistant message(含 thinking_steps json)
    # 5. 出错时 sse_error + sse_done(success=False)
    return StreamingResponse(generator(), media_type="text/event-stream")

@router.get("/api/v1/agent/skills")
async def list_skills():
    """期 1 返回固定列表(对齐前端 ChatPage QUICK_QUESTIONS 中提到的 skill_id):
       chan_theory / wave_theory / bull_trend / box_oscillation / emotion_cycle
       期 1 这些 skill 不影响 pipeline 行为(都跑同一个 turtle 流程),仅作 UI label。
       default_skill_id = ''(通用分析)
    """

@router.get("/api/v1/agent/chat/sessions?limit=50")
async def list_sessions(limit: int = 50):
    """SELECT * FROM agent_chat_sessions ORDER BY last_active DESC LIMIT :limit"""

@router.get("/api/v1/agent/chat/sessions/{session_id}")
async def get_session_messages(session_id: str):
    """SELECT id, role, content, created_at FROM agent_chat_messages WHERE session_id=? ORDER BY created_at"""

@router.delete("/api/v1/agent/chat/sessions/{session_id}")
async def delete_session(session_id: str):
    """CASCADE 自动删 messages"""

@router.post("/api/v1/agent/chat/send")
async def send_to_notification(req: SendChatRequest):
    """期 1 stub:返回 {success: false, message: '通知渠道转发期 1 未实现'}"""
```

#### G.1.4 Session 持久化 — `backend/services/agent/session_repo.py`

```python
class AgentSessionRepository:
    def __init__(self, conn: sqlite3.Connection): ...

    def upsert_session(self, session_id: str, title: str) -> None: ...
    def update_session_phase(self, session_id, phase: str | None, status: str | None = None): ...
    def update_session_stock(self, session_id, code: str, market: str, output_dir: str): ...
    def insert_message(self, session_id, role, content, skills=None, thinking_steps=None) -> str: ...
    def list_sessions(self, limit: int) -> list[dict]: ...
    def list_messages(self, session_id: str) -> list[dict]: ...
    def delete_session(self, session_id: str) -> None: ...
```

每个方法独立打开新 connection(对齐项目 `services/portfolio/db.py` per-request pattern)。

#### G.1.5 主入口集成

`backend/main.py` 追加:
```python
from backend.routers import agent as agent_router
from backend.routers import system_config as system_config_router
from backend.routers import auth_stub as auth_stub_router
app.include_router(agent_router.router)
app.include_router(system_config_router.router)
app.include_router(auth_stub_router.router)
```

### G.2 Documentation references

- 现有路由 include 模式:`backend/main.py:80-90`
- 现有 sqlite repo pattern:`backend/services/portfolio/manager.py`
- FastAPI StreamingResponse 文档(只读,不 fetch):标准用法
- 前端 SSE 解析逻辑(必须严格对齐):Phase 0 §B.1 表

### G.3 Verification checklist

- [ ] `python -m pytest backend/tests/test_agent_session_repo.py -x` 通过(CRUD + cascade delete)
- [ ] `python -m pytest backend/tests/test_agent_parser.py -x` 通过(覆盖 6 种输入形态 + context 优先)
- [ ] `python -m pytest backend/tests/test_agent_routes.py -x` 通过:
  - sessions list / get / delete 端点(用 fastapi TestClient)
  - chat/stream 端点(用 mock coordinator,验证 SSE 输出格式严格 `data: {json}\n\n`)
  - skills 端点
- [ ] **端到端冒烟**(需配置真实 LLM key):
  ```bash
  curl -N -X POST http://localhost:8000/api/v1/agent/chat/stream \
    -H "Content-Type: application/json" \
    -d '{"message":"分析贵州茅台 600519","session_id":"test-1"}'
  ```
  应看到一系列 `data: {...thinking...}` `data: {...tool_start...}` `data: {...tool_done...}` 最终 `data: {...done, content: "..."}`
- [ ] 前端打开 ChatPage,发送"分析 600519",观察:
  - 进度面板正常显示 6 步
  - 最终 markdown 渲染
  - 刷新页面后会话仍在,点入能看到历史消息

### G.4 Anti-pattern guards

- ❌ **不要**用同步 `for` + `yield` 拼 SSE — 必须 `async def` + `yield` + `StreamingResponse`(否则阻塞 event loop)
- ❌ **不要**在 SSE 流中漏掉 `\n\n` 结尾 — 前端按 `\n` split,缺失会导致最后事件不触发
- ❌ **不要**把 thinking_steps 整个塞进 SQLite content 字段 — 用单独 `thinking_steps` 列存 JSON
- ❌ **不要**让 chat/send 真的调通知渠道 — 期 1 是 stub
- ❌ **不要**把 LLM 异常 raise 给 FastAPI 默认 500 — 必须在 generator 内 try/except,转化为 sse_error + sse_done(success=False) 后正常关流
- ❌ **不要**在 stream 期间让 session.status 卡在 'running' — 任何退出路径(成功/失败/客户端断开)都必须更新 status
- ❌ **不要**一开始就 INSERT 完整 assistant message — 应在 done 事件发出后再 INSERT(content 此时才完整),避免半成品

---

## Final Phase: 集成验证

### Final.1 端到端验收清单

- [ ] **冷启动**:删除 `data/agent_runs/` 和 `data/system_config.yaml`,从 0 启动 backend,前端 SettingsPage 显示空 channel,可手动添加 → 保存 → 测试连接成功
- [ ] **第一次问股**:ChatPage 输入"分析贵州茅台 600519",观察:
  1. SSE 进度依次出现 6 个 tool_start/tool_done(phase1_data_pack / phase3_1 / phase3_2)
  2. 最终 markdown 渲染含元信息 / Executive Summary / 财务趋势 / 穿透回报率 / 估值 / 综合结论 / 投资论点卡 / 风险提示
  3. `data/agent_runs/600519.SH_<ts>/` 含 4 个文件:`data_pack_market.md` / `phase3_quantitative_report.md` / `factor_b.json` / `final_report.md` / `factor_c.json`
- [ ] **HK + US 各跑一例**:`00700.HK` / `AAPL` 全流程通过,币种 / 单位标签正确
- [ ] **会话历史**:刷新页面后会话列表恢复,点入历史会话能看到全部消息
- [ ] **错误路径**:
  - 输入"分析 999999"(不存在的代码)→ 应得到 sse_error + 友好提示,session.status='error'
  - 临时把 LLM API key 改成无效值 → 应在 phase3_1 阶段 tool_done(success=False),sse_error
  - 客户端中断(关浏览器)→ session.status 应更新为 'error' 或 'done'(不能卡在 'running')
- [ ] **配置乐观锁**:两个浏览器窗口同时编辑 system_config,后保存方应得到 409
- [ ] **Mask token**:刷新 SettingsPage,API_KEYS 字段值显示 `<MASKED:...>`;不修改直接保存,DB 中实际值未变

### Final.2 全量测试

```bash
python -m pytest backend/tests/ -x -q          # 应在原 550 基础上 +50~80 个新 case 全通过
cd frontend && npm test                         # 前端测试不应有回归
cd frontend && npx tsc --noEmit                 # 前端类型检查无新错误
```

### Final.3 性能基线

- Phase 1 数据包生成:**< 5 秒**(纯 DuckDB)
- Phase 3.1:**< 120 秒**(LLM 调用主导,取决于上下文长度)
- Phase 3.2:**< 90 秒**
- 端到端总时长:**< 4 分钟**(P95 < 6 分钟)

若超出,加入 backlog 优化(prompt 压缩 / 并行 phase 等)。

### Final.4 Anti-pattern grep 检查

```bash
# 必须 0 命中:
grep -rn 'request_upload\|substep' backend/services/agent/   # 不该发明新 SSE 类型
grep -rn 'data/kline\|data/financial/\|data/dividend/' backend/services/agent/  # 不该读旧路径
grep -rn 'pd.read_parquet\|\.glob.*parquet' backend/services/agent/             # 不该绕开 DuckDB
grep -rn 'tushare\|TUSHARE' backend/services/agent/                             # 不该引入 Tushare
```

### Final.5 文档更新

- [ ] 更新 `AGENTS.md` Pending Designs / Accomplished 段,标记问股期 1 完成
- [ ] 在 `docs/` 下加 `ask_stock_期1_done_summary.md` 简短记录(20 行内,含端到端跑通的代码 / 报告样例链接)
- [ ] 更新 `README.md`(若有)的功能列表

---

## 期 2 / 期 3 预告(本次不实施)

期 1 上线稳定后再 make-plan:

**期 2**:`/business-analysis` 三 agent
- 实施 `shared/qualitative/` 整套(Agent A D1+D2 / Agent B D3+D4+D5 / Summary)
- 接入 `split_data_pack.py` 切分逻辑
- coordinator 增加 Phase 2 节点,Phase 3 才能消费 qualitative_report.md
- 工期估算:5-7 天

**期 3**:PDF 下载 + 解析 + 前端上传
- Phase 0:复制 `download_report.py`,接入 cninfo / 巨潮 / 雪球 PDF 抓取
- Phase 2:复制 `pdf_preprocessor.py`,产出 pdf_sections.json
- 前端 ChatPage 加上传 UI + 后端 `/api/v1/agent/upload`
- 数据包 §10 / §13.2 用 PDF MD&A 内容填充
- 工期估算:7-10 天

---

## 附录 A:Phase 间依赖图

```
                ┌── A: 基础设施 ──┐
                │                 │
                ↓                 ↓
        ┌── B: system_config     D: 数据包(可并行)
        │                         │
        ↓                         │
        C: LLM client            │
                │                │
                └────────┬───────┘
                         ↓
                    E: Phase 3.1 量化
                         ↓
                    F: Phase 3.2 估值
                         ↓
                    G: SSE + 会话 + Coordinator
                         ↓
                      Final
```

## 附录 B:文件创建清单总览

**新建后端文件**(期 1 总计 ~35 个):
- `backend/services/agent/__init__.py`
- `backend/services/agent/sse.py`
- `backend/services/agent/symbol.py`
- `backend/services/agent/coordinator.py`
- `backend/services/agent/parser.py`
- `backend/services/agent/llm_routing.py`
- `backend/services/agent/session_repo.py`
- `backend/services/agent/pipeline/__init__.py`
- `backend/services/agent/pipeline/phase1_data_pack/builder.py` + 16 section files + 9 derived files
- `backend/services/agent/pipeline/phase3_quant.py`
- `backend/services/agent/pipeline/phase3_valuation.py`
- `backend/services/agent/prompts/turtle/*.md`(6 文件,从 turtle 复制)
- `backend/services/system_config/__init__.py`
- `backend/services/system_config/store.py`
- `backend/services/system_config/schema.py`
- `backend/services/system_config/validate.py`
- `backend/services/system_config/setup.py`
- `backend/services/system_config/channels.py`
- `backend/services/system_config/llm_client.py`
- `backend/services/system_config/llm_test.py`
- `backend/routers/agent.py`
- `backend/routers/system_config.py`
- `backend/routers/auth_stub.py`

**修改的现有文件**:
- `backend/main.py`(lifespan + include_router)
- `backend/config.py`(新增常量)
- `backend/services/db_schema.py`(`init_agent_tables`)

**新增测试文件**:`backend/tests/test_agent_*.py`(~10 文件,~60-80 个用例)

**新增脚本**:`scripts/copy_turtle_prompts.py`、`scripts/smoke_data_pack.py`、`scripts/smoke_phase3_quant.py`、`scripts/smoke_phase3_valuation.py`

---

**计划文档版本**:期 1 v1(2026-05-23)
**前置 Discovery 报告**:由 3 个并行 explore subagent 取证,留痕在对话历史
**配套设计文档**:`docs/design_ask_stock.md`(规格层)
**下一步**:用户评审本计划 → 通过后用 `do` skill 启动 Phase A 执行



