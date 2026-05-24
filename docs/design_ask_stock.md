# 问股(Ask Stock)后端设计文档 — v2

> 状态:**v2 草案**(2026-05-23,基于 turtle 框架重写)
> 范围:把 [Turtle Investment Framework](https://github.com/yusixiao/Turtle_investment_framework) 的多 Agent 投资研究流水线,接入到本项目的 `/api/v1/agent/*` 后端,以**对话式 UI** 交付完整投资分析报告。

---

## 0. v1 → v2 关键变更

| 项 | v1(已废弃) | v2(本文) |
|---|---|---|
| 核心抽象 | 5 个分析视角技能 prompt | **多 Agent 投资研究流水线**(turtle) |
| 后端形态 | 单次 LLM 调用 | **Coordinator 调度多个 sub-agent**,Agent 间文件通信 |
| 数据层 | 临时拉数据塞 prompt | DuckDB → 适配器导出 turtle 风格 `data_pack_market.md`(§1-§17) |
| 输出 | markdown 对话回复 | **完整投资分析报告**(`{公司}_{代码}_分析报告.md`)|
| 流式粒度 | (未决) | **只发 `step` + `substep`**,不发 delta |
| LLM 协议 | 仅 OpenAI | **OpenAI / Anthropic / OpenRouter / DeepSeek 多协议** |
| PDF 处理 | 不支持 | **支持**:在 chat 中提示用户上传 |
| 定性分析 | 不实现 | **一并实现**(搬 turtle `shared/qualitative/`)|
| 前端 | (未决) | **不重做**,仅小幅扩展(新增 `request_upload` step 事件)|

---

## 1. 总体架构

### 1.1 流水线全景

```
┌──────────────────────────── 用户 ────────────────────────────┐
│  ChatPage 输入: "分析 002594 比亚迪"                          │
└──────────────────────────────┬──────────────────────────────┘
                               │ POST /api/v1/agent/chat/stream
                               ▼
┌─────────────────────────────────────────────────────────────┐
│              Coordinator(协调器 Agent)                       │
│  • normalize 代码 → 002594.SZ                                │
│  • AskUserQuestion(持股渠道?需要 PDF?)                       │
│  • 创建 {output_dir} = data/agent_runs/002594.SZ_比亚迪/    │
│  • 检查前置:qualitative_report.md / data_pack_market.md      │
│  • 调度 Phase 0 → 1 → 2 → 3.1 → 3.2                          │
│  • 每阶段完成发 SSE step 给前端                              │
└──────────────────────────────┬──────────────────────────────┘
                               │
       ┌───────────────────────┼────────────────────────┐
       ▼                       ▼                        ▼
┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ Phase 0      │    │ Phase 1A         │    │ Phase 1B         │
│ PDF 下载     │    │ 数据采集脚本     │    │ WebSearch Agent   │
│ (可选)       │    │ duckdb_exporter  │    │ (财经记者,LLM)    │
│              │    │ → data_pack_     │    │ → §7 §8 §10 §13   │
│              │    │   market.md      │    │   追加到 data_pack│
└──────────────┘    └──────────────────┘    └──────────────────┘
                               │
                               ▼
                    ┌──────────────────┐
                    │ Phase 2          │
                    │ PDF 附注解析     │
                    │ pdf_preprocessor │
                    │ → data_pack_     │
                    │   report.md      │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────────┐
                    │ /business-analysis    │
                    │ qualitative_assessment│
                    │ Agent A(LLM,定性)    │
                    │ → qualitative_       │
                    │   report.md          │
                    └────────┬─────────────┘
                             │
                             ▼
              ┌──────────────────────────┐
              │ Phase 3.1 Agent B        │
              │ (CPA 量化分析师, LLM)    │
              │ Step 0 数据校验+口径锚定 │
              │ Steps 1-11 穿透回报率    │
              │ → phase3_quantitative.md │
              └────────┬─────────────────┘
                       │
                       ▼
              ┌────────────────────────────┐
              │ Phase 3.2 Agent C          │
              │ (首席分析师, LLM)          │
              │ 估值定价 + 报告组装        │
              │ → {company}_{code}_       │
              │     分析报告.md            │
              └────────┬───────────────────┘
                       │
                       ▼
              ┌────────────────────────────┐
              │ Coordinator 交付:         │
              │ 把 分析报告.md 内容        │
              │ 作为 done.content 通过 SSE │
              │ 推回前端                   │
              └────────────────────────────┘
```

### 1.2 后续追问(轻量问答模式)

完整分析报告生成后,用户在**同 session** 内继续追问("第 5 段那个 G 系数怎么算的?"):

- Coordinator 检测到 `{output_dir}` 已存在且分析报告完成
- 不再启动流水线,改走**轻量问答模式**:
  - 把已有的 `qualitative_report.md` + `phase3_quantitative.md` + `分析报告.md` 摘要作为上下文
  - 加上历史对话(最近 10 条)
  - 调一次 LLM 直接回答
- 仍发 `step` 进度(`type=step, message="加载分析报告作上下文..."`),但只有 1-2 个

---

## 2. 模块拆分

### 2.1 后端代码组织

```
backend/
├── routers/
│   ├── agent.py                       # /api/v1/agent/*
│   ├── system_config.py               # /api/v1/system/config/*
│   └── upload.py                      # /api/v1/upload/pdf(PDF 上传)
├── services/
│   ├── system_config/                 # ⭐ 新增
│   │   ├── __init__.py
│   │   ├── store.py                   # 读写 data/system_config.yaml
│   │   ├── schema.py                  # Pydantic 模型(LLMChannel 等)
│   │   ├── llm_client.py              # 多协议 LLM 客户端(见 §5)
│   │   └── notification.py            # 通知 channel(占位)
│   └── agent/                         # ⭐ 新增
│       ├── __init__.py
│       ├── session_store.py           # SQLite 会话/消息 CRUD
│       ├── pipeline/                  # turtle 流水线执行引擎
│       │   ├── __init__.py
│       │   ├── coordinator.py         # 总调度,SSE step 编排
│       │   ├── phase0_pdf_download.py # 调 yfinance/akshare 找年报 URL
│       │   ├── phase1_data_pack.py    # ⭐ DuckDB → data_pack_market.md
│       │   ├── phase1b_websearch.py   # WebSearch sub-agent(LLM)
│       │   ├── phase2_pdf_parse.py    # 复用 turtle/scripts/pdf_preprocessor.py
│       │   ├── phase3_quantitative.py # 调 LLM 跑 Agent B prompt
│       │   ├── phase3_valuation.py    # 调 LLM 跑 Agent C prompt
│       │   └── qualitative.py         # 跑 Agent A 定性分析
│       ├── stock_resolver.py          # 002594 → 002594.SZ 比亚迪
│       ├── prompts/                   # ⭐ 从 turtle 同步进来
│       │   ├── coordinator.md
│       │   ├── phase1b_websearch.md
│       │   ├── phase3_quantitative.md
│       │   ├── phase3_valuation.md
│       │   ├── qualitative_assessment.md
│       │   └── references/
│       │       ├── shared_tables.md
│       │       ├── factor_interface.md
│       │       ├── judgment_examples_turtle.md
│       │       ├── output_schema.md          # 定性 6 维度参数 schema
│       │       ├── market_rules_hk.md        # 港股规则
│       │       └── market_rules_us.md        # 美股规则
│       └── workspace.py               # {output_dir} 路径管理
└── tests/agent/
    ├── test_session_store.py
    ├── test_stock_resolver.py
    ├── test_phase1_data_pack.py
    ├── test_coordinator.py
    └── test_llm_client.py
```

### 2.2 数据/产物目录

```
data/
├── agent_runs/                        # ⭐ 每只股票一个目录(对齐 turtle output/)
│   └── {code}_{company}/              # 如 002594.SZ_比亚迪
│       ├── data_pack_market.md        # Phase 1 产出
│       ├── data_pack_report.md        # Phase 2 产出(可选)
│       ├── qualitative_report.md      # /business-analysis 产出
│       ├── phase3_quantitative.md     # Agent B 产出
│       ├── 比亚迪_002594.SZ_分析报告.md  # Agent C 产出 ⇐ 最终交付
│       └── _meta.json                 # 任务状态/时间戳/绑定的 session_id
├── uploads/                           # ⭐ 用户上传的 PDF
│   └── {session_id}/{filename}.pdf
├── system_config.yaml                 # ⭐ LLM channel + 系统配置
└── portfolio.db                       # 既有 SQLite,新增 chat_sessions/chat_messages
```

---

## 3. 数据模型

### 3.1 SQLite 新增表

```sql
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id      TEXT PRIMARY KEY,             -- 前端 UUID
    title           TEXT NOT NULL DEFAULT '',     -- 首条消息前 60 字
    stock_code      TEXT,                         -- 绑定的股票代码(分析任务才有)
    output_dir      TEXT,                         -- data/agent_runs/{code}_{company}/
    status          TEXT NOT NULL DEFAULT 'idle', -- idle/running/done/failed
    current_phase   TEXT,                         -- phase0/phase1/phase2/qualitative/phase3.1/phase3.2/qa
    created_at      TEXT NOT NULL,
    last_active     TEXT NOT NULL,
    msg_count       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_sessions_last_active ON chat_sessions(last_active DESC);

CREATE TABLE IF NOT EXISTS chat_messages (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,        -- 'user' | 'assistant' | 'system'
    content     TEXT NOT NULL,
    context     TEXT,                 -- JSON: 用户消息时的 stock_code/record_id 等
    thinking    TEXT,                 -- JSON: progress steps 数组
    artifacts   TEXT,                 -- JSON: 产出物路径 ['{output_dir}/分析报告.md']
    tokens_in   INTEGER,
    tokens_out  INTEGER,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
);
CREATE INDEX idx_messages_session ON chat_messages(session_id, created_at);
```

### 3.2 system_config.yaml schema

```yaml
llm:
  default_channel_id: deepseek_default
  channels:
    - id: openai_4o
      provider: openai            # openai | anthropic | openrouter | deepseek
      base_url: https://api.openai.com/v1
      api_key: sk-xxxxx
      model: gpt-4o-mini
      max_tokens: 8192
      temperature: 0.3
      timeout: 120
    - id: anthropic_sonnet
      provider: anthropic
      base_url: https://api.anthropic.com
      api_key: sk-ant-xxxxx
      model: claude-3-5-sonnet-20241022
      max_tokens: 8192
      temperature: 0.3
    - id: deepseek_default
      provider: deepseek
      base_url: https://api.deepseek.com
      api_key: sk-xxxxx
      model: deepseek-chat
    - id: openrouter
      provider: openrouter
      base_url: https://openrouter.ai/api/v1
      api_key: sk-or-xxxxx
      model: anthropic/claude-3.5-sonnet

# 各 phase 可单独指定 channel(否则用 default)
agent_channel_routing:
  qualitative: anthropic_sonnet      # 定性分析用 Sonnet(强推理)
  phase1b_websearch: openai_4o       # WebSearch 整理用 GPT-4o
  phase3_quantitative: anthropic_sonnet
  phase3_valuation: anthropic_sonnet
  qa_followup: deepseek_default      # 追问轻量场景用 DeepSeek(便宜)

websearch:
  provider: tavily                   # tavily | bing | google
  api_key: tvly-xxxxx

notification:
  channels: []                       # 占位
```

### 3.3 `_meta.json`(每 run 状态文件)

```json
{
  "stock_code": "002594.SZ",
  "company": "比亚迪",
  "session_id": "uuid",
  "started_at": "2026-05-23T10:00:00Z",
  "phases": {
    "phase0_pdf_download": {"status": "skipped", "reason": "用户选择跳过"},
    "phase1_data_pack": {"status": "done", "duration": 12.3},
    "phase1b_websearch": {"status": "done", "duration": 45.1},
    "phase2_pdf_parse": {"status": "skipped"},
    "qualitative": {"status": "done", "duration": 120.5},
    "phase3_quantitative": {"status": "done", "duration": 380.2},
    "phase3_valuation": {"status": "done", "duration": 210.0}
  },
  "artifacts": [
    "data_pack_market.md",
    "qualitative_report.md",
    "phase3_quantitative.md",
    "比亚迪_002594.SZ_分析报告.md"
  ],
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
  "skills": [],                      // ⚠️ v2 中无技能概念,前端传也忽略
  "context": {                       // 来自其他页面的跳转
    "stock_code": "002594",
    "stock_name": "比亚迪",
    "record_id": null
  }
}
```

### 4.2 SSE 事件序列(分析流程)

```
data: {"type":"step","phase":"resolve","message":"识别股票:002594.SZ 比亚迪"}

data: {"type":"step","phase":"phase0","message":"询问是否上传年报 PDF..."}
data: {"type":"request_upload","accept":".pdf","prompt":"上传年报 PDF(可跳过)","optional":true}

  ↓ (前端弹上传/跳过按钮;用户点击后通过 POST /upload/pdf 或 /chat/skip-upload 回传,
     后端通过 session 关联 — 详见 §6)

data: {"type":"step","phase":"phase1","message":"采集市场数据 (§1-§17)..."}
data: {"type":"substep","phase":"phase1","step":3,"total":17,"message":"§3 利润表..."}
...
data: {"type":"step","phase":"phase1","message":"市场数据包 ✅"}

data: {"type":"step","phase":"phase1b","message":"WebSearch 补充 §7/§8/§10..."}
data: {"type":"step","phase":"phase1b","message":"WebSearch ✅(共 14 条来源)"}

data: {"type":"step","phase":"phase2","message":"解析 PDF 附注..."}  ← 若有 PDF
data: {"type":"step","phase":"phase2","message":"PDF 解析 ✅(P2/P3/P4/P6)"}

data: {"type":"step","phase":"qualitative","message":"定性分析(6 维度)..."}
data: {"type":"step","phase":"qualitative","message":"定性分析 ✅"}

data: {"type":"step","phase":"phase3.1","message":"定量分析 Agent B 启动..."}
data: {"type":"substep","phase":"phase3.1","step":0,"message":"Step 0 数据校验"}
data: {"type":"substep","phase":"phase3.1","step":3,"message":"Step 3 利润穿透"}
...
data: {"type":"step","phase":"phase3.1","message":"定量分析 ✅(GG=11.2%, II=10.5%)"}

data: {"type":"step","phase":"phase3.2","message":"估值与报告组装..."}
data: {"type":"step","phase":"phase3.2","message":"报告 ✅"}

data: {"type":"done","success":true,
       "content":"# 比亚迪(002594.SZ) 投资分析报告\n\n## 结论\n...(完整 markdown)",
       "artifacts":[{"name":"比亚迪_002594.SZ_分析报告.md",
                     "url":"/api/v1/agent/sessions/{sid}/artifacts/比亚迪_002594.SZ_分析报告.md"}]}
```

### 4.3 SSE 事件类型表(v2 完整)

| type | 字段 | 用途 |
|---|---|---|
| `step` | `phase, message` | 阶段切换 |
| `substep` | `phase, step, total, message` | 阶段内子步骤(Agent B 11 步) |
| `request_upload` | `accept, prompt, optional` | 请求前端弹文件上传 |
| `ask` | `question, options[], multiple` | AskUserQuestion(持股渠道等) |
| `done` | `success, content, artifacts[]` | 终态 |
| `error` | `error, message, phase` | 中途致命错误 |

> 前端 `agentChatStore.ts:268-283` 已有 `step/done/error` 处理,新增 3 种事件需要小幅扩展(详见 §6)。

### 4.4 异常路径

| 情况 | 处理 |
|---|---|
| 股票代码识别失败 | 发 `ask` 事件让用户确认 |
| PDF 下载失败(Phase 0)| 标注 `[数据缺失|中]`,继续走无 PDF 降级方案 |
| WebSearch 失败 | §7/§8/§10 标"⚠️ 数据不可用",继续 |
| LLM 调用失败 | 重试 1 次;再失败发 `error` 事件,**保留**已生成的中间产物(下次可断点续跑) |
| 用户 abort | 检测 `request.is_disconnected()`,中断后续 phase,`_meta.json` 标 `status=cancelled` |
| 阶段超时(见 §4.5)| 强制中止该 phase,发 `error` 给前端 |

### 4.5 阶段超时(对齐 turtle)

| 阶段 | 超时 |
|---|---|
| Phase 0 PDF 下载 | 60s |
| Phase 1 数据包 | 60s(本地 DuckDB,极快)|
| Phase 1B WebSearch | 5 min |
| Phase 2 PDF 解析 | 5 min |
| Qualitative 定性 | 5 min |
| Phase 3.1 Agent B | 10 min |
| Phase 3.2 Agent C | 5 min |
| **总管线** | **≤ 30 min** |

### 4.6 追问模式分支

Coordinator 入口判断:

```python
def route_message(session, message, context):
    output_dir = session.output_dir
    if output_dir and (output_dir / "分析报告.md").exists():
        return run_qa_followup(session, message)        # 轻量问答
    elif extracted_stock := stock_resolver.extract(message, context):
        return run_full_pipeline(session, extracted_stock)  # 完整流水线
    else:
        return run_chitchat(session, message)            # 闲聊(简单调 LLM)
```

---

## 5. LLM 客户端(多协议)

### 5.1 抽象

```python
# services/system_config/llm_client.py
class LLMClient(ABC):
    @abstractmethod
    async def stream(self, messages: list[Message], **kwargs) -> AsyncIterator[str]: ...
    @abstractmethod
    async def complete(self, messages: list[Message], **kwargs) -> str: ...

class OpenAICompatibleClient(LLMClient):
    """OpenAI / DeepSeek / OpenRouter 共用,POST /v1/chat/completions"""

class AnthropicClient(LLMClient):
    """POST /v1/messages,事件流格式 message_start/content_block_delta/..."""

def build_client(channel_id: str) -> LLMClient:
    cfg = system_config.get_channel(channel_id)
    if cfg.provider in ("openai", "deepseek", "openrouter"):
        return OpenAICompatibleClient(cfg)
    if cfg.provider == "anthropic":
        return AnthropicClient(cfg)
    raise ValueError(f"Unknown provider: {cfg.provider}")
```

### 5.2 重试与超时

- 单次调用超时跟随 `channel.timeout`(默认 120s)
- 网络错误/5xx 重试 1 次,带 2s 退避
- 4xx(API key 错/参数错)立即抛 `LLMError`(用户友好的中文错误)

### 5.3 Token 计费(v2 简单版)

- 每次调用记 `tokens_in / tokens_out` 到 `chat_messages` 表
- v2 暂不做用量统计页,只是埋点

---

## 6. 前端小幅扩展(不重做)

### 6.1 新增 SSE 事件渲染

`agentChatStore.ts` 的 `processLine` 增加 3 个类型:

```typescript
if (event.type === 'request_upload') {
  // 推入特殊 progressStep,ChatPage 渲染时识别并显示上传按钮 + "跳过"按钮
  set((s) => ({ progressSteps: [...s.progressSteps, event] }));
  // 阻塞:等用户点击上传或跳过
}
if (event.type === 'ask') {
  // 推入特殊 progressStep,ChatPage 显示 ask 选项按钮组
  set((s) => ({ progressSteps: [...s.progressSteps, event] }));
}
if (event.type === 'substep') {
  // 直接当 step 推入(已有 progressSteps 渲染逻辑)
  set((s) => ({ progressSteps: [...s.progressSteps, event] }));
}
```

ChatPage 渲染 `progressSteps[]` 时,识别 `type` 决定 UI:
- `step / substep`:文字 + 旋转图标
- `request_upload`:文字 + [上传 PDF] [跳过] 按钮
- `ask`:文字 + 选项按钮组

### 6.2 文件上传 API(新增)

```
POST /api/v1/upload/pdf
  multipart/form-data
  ├── session_id: string
  └── file: File
→ {success:true, path:"data/uploads/{session_id}/年报_2025.pdf"}
```

后端把 path 写入 session 的某个临时通道(Redis-less:写到 `data/uploads/{session_id}/_pending.json`),Coordinator 在 Phase 0 阻塞等这个文件出现。

```
POST /api/v1/upload/skip
  { session_id }
→ 写入 _pending.json: {"action":"skip"}
```

前端在 `request_upload` step 旁渲染按钮,点击后调用对应 API。

### 6.3 报告 artifact 渲染

`done.content` 已经是完整 markdown 报告,前端 react-markdown 已支持。`artifacts[]` 提供下载链接(可选,先不做下载,只显示在消息底部 "📄 完整报告.md" 文字)。

---

## 7. Phase 1:DuckDB → data_pack_market.md 适配器

### 7.1 turtle 数据包结构(§1-§17)

| 章节 | 内容 | 我们的来源 |
|---|---|---|
| §1 基础信息 | 代码/上市结构/币种/汇率 | `services/stock_index.py` + `repositories/basic_repo` |
| §2 市值/股价 | 当前价、市值、流通股 | `duckdb_store.query_qfq_kline(latest)` + `circulating_shares.py` |
| §3 利润表 | 5 年 income | `v_a_income / v_hk_income / v_us_income` |
| §3P 母公司利润表 | A 股专属 | `eastmoney_adapter`(A 股有母表)|
| §4 资产负债表 | 5 年 balance | `v_*_balance` |
| §4P 母公司资产负债表 | A 股专属 | 同 §3P |
| §5 现金流量表 | 5 年 cashflow | `v_*_cashflow` |
| §6 每股股息 | 5 年 DPS | `v_a_dividend`(已有) |
| §7 控股股东+管理层 | 需要 WebSearch | **Phase 1B**(LLM Agent) |
| §8 行业竞争+监管 | 需要 WebSearch | **Phase 1B** |
| §9 主营拆分 | 业务结构 | `eastmoney` 主营拆分接口(若有,否则降级) |
| §9B 上市子公司 | 条件触发 | WebSearch |
| §10 ESG/争议事件 | WebSearch | **Phase 1B** |
| §11 历史价格 | 周线 5 年 | `duckdb_store` 周线 |
| §12 关键比率(预计算)| ROE/毛利率等 | `v_a_indicator` |
| §13 Warnings | 自动检测异常 | 适配器自检 |
| §14 无风险利率 Rf | 10 年国债 | 配置写死或新数据源 |
| §15 行业平均估值 | PE/PB 行业中位数 | `duckdb_store` 行业聚合 |
| §16 同业可比公司 | 前 10 大 | 行业代码筛选 |
| §17 衍生指标 | MACD/MA/分位数 | `services/backtest/indicators.py` |

### 7.2 适配器实现要点

```python
# services/agent/pipeline/phase1_data_pack.py
class DataPackBuilder:
    def build(self, code: str, output_dir: Path) -> Path:
        sections = []
        sections.append(self._section_1_basic(code))
        sections.append(self._section_2_market(code))
        sections.append(self._section_3_income(code, years=5))
        sections.append(self._section_3p_parent_income(code))  # A股
        sections.append(self._section_4_balance(code, years=5))
        sections.append(self._section_4p_parent_balance(code))
        sections.append(self._section_5_cashflow(code, years=5))
        sections.append(self._section_6_dividend(code, years=5))
        # §7/§8/§10/§13.2 留给 Phase 1B
        sections.append(self._section_9_segments(code))
        sections.append(self._section_11_weekly_kline(code, years=5))
        sections.append(self._section_12_ratios(code, years=5))
        sections.append(self._section_13_warnings(code))
        sections.append(self._section_14_rf())
        sections.append(self._section_15_industry_valuation(code))
        sections.append(self._section_16_peers(code))
        sections.append(self._section_17_derived(code))
        out = output_dir / "data_pack_market.md"
        out.write_text("\n\n".join(sections), encoding="utf-8")
        return out
```

每个 `_section_*` 方法返回符合 turtle 规范的 markdown 块。**单位统一为百万元**(Tushare 原始单位元 ÷ 1e6)。

### 7.3 与 turtle 原始 `tushare_collector.py` 的差异

| 项 | turtle | 我们 |
|---|---|---|
| 数据源 | Tushare API | DuckDB(本地 parquet)|
| 速度 | 网络往返 ~30s | 本地 ~1s |
| 字段 | 中文(eastmoney 风)→ 英文映射 | 已统一英文,直接用 |
| §11 价格 | tushare daily | `duckdb_store.query_qfq_kline` |
| §14 Rf | yfinance ^TNX | 配置文件里写死(可季度更新)或加新数据源 |

---

## 8. /business-analysis 子模块(定性分析)

完整搬 `Turtle_investment_framework/shared/qualitative/`:

```
backend/services/agent/prompts/qualitative/
├── coordinator.md                # 定性独立入口
├── qualitative_assessment.md    # 6 维度提示词
├── data_collection.md           # 轻量 WebSearch 指令
└── references/
    ├── output_schema.md          # 6 维度结构化参数 schema
    ├── judgment_examples.md
    ├── market_rules_hk.md
    └── market_rules_us.md
```

执行流程(由 turtle Coordinator 在 Phase 3.1 之前调度):

1. 读取 `data_pack_market.md` + `data_pack_report.md`(可选)
2. 跑 `qualitative_assessment.md`(LLM Agent A) → 6 维度评估
3. 末尾输出**结构化参数表**(`moat_rating / capital_intensity / management_quality / ...`)
4. 写入 `qualitative_report.md`

> Phase 3.1 Agent B / Phase 3.2 Agent C 通过 `factor_interface.md` schema 严格读取该参数表。

---

## 9. PDF 处理(Phase 0 + Phase 2)

### 9.1 Phase 0 流程

```
Coordinator → SSE: {type:'request_upload',prompt:'是否上传年报 PDF?',optional:true}
   ↓ (用户选项)
   ├─ 跳过 → POST /upload/skip → 写 _pending.json {action:'skip'}
   ├─ 自动下载 → 调 turtle/scripts/download_report.py(WebSearch + URL 下载)
   └─ 上传 → POST /upload/pdf → 写 _pending.json {action:'uploaded',path:...}

Coordinator 轮询 _pending.json 直到出现(超时 5 分钟回退 skip)
```

### 9.2 Phase 2 解析

直接复用 turtle 的 `scripts/pdf_preprocessor.py`:

- 输入:PDF 文件
- 输出:`data_pack_report.md`(P2/P3/P4/P6/P13/SUB 章节)
- 依赖:`pdfplumber`(添加到 `requirements.txt`)

如果 PDF 是扫描件 → 提示用户使用 OCR 工具或跳过(MVP 不做 OCR)。

---

## 10. 实施分期

### Phase A — 基础设施(2-3 天)

- [ ] `services/system_config/`(yaml 读写 + schema)
- [ ] `services/system_config/llm_client.py`(OpenAI/Anthropic/OpenRouter/DeepSeek 4 协议)
- [ ] `routers/system_config.py`(配合前端 SettingsPage)
- [ ] DB migration:`chat_sessions / chat_messages`
- [ ] `services/agent/session_store.py`
- [ ] `services/agent/stock_resolver.py`
- [ ] `services/agent/workspace.py`(目录管理)
- [ ] `routers/agent.py`:`GET /skills`(返回空)、sessions CRUD
- [ ] **里程碑:前端历史会话列表能加载、SettingsPage 能配 LLM key**

### Phase B — 闲聊+追问 MVP(1-2 天)

- [ ] `pipeline/coordinator.py` 骨架(只支持 chitchat 分支)
- [ ] `routers/agent.py:POST /chat/stream`(基础 SSE)
- [ ] **里程碑:用户可发"你好"得到 LLM 回复**

### Phase C — 数据包适配器(2-3 天)

- [ ] 同步 turtle prompts 到 `services/agent/prompts/`
- [ ] `phase1_data_pack.py` §1-§6, §11-§17(纯 DuckDB)
- [ ] `phase1b_websearch.py`(LLM Agent + Tavily/Bing API)
- [ ] tests:用 600519/比亚迪/腾讯 3 个标的对比 turtle 输出
- [ ] **里程碑:能产出合规的 `data_pack_market.md`**

### Phase D — 定性分析(2 天)

- [ ] `pipeline/qualitative.py`
- [ ] 同步 turtle `shared/qualitative/` prompts
- [ ] **里程碑:能产出 `qualitative_report.md` + 结构化参数表**

### Phase E — Phase 3 定量+估值(3-4 天)

- [ ] `pipeline/phase3_quantitative.py`(执行 Agent B prompt)
- [ ] `pipeline/phase3_valuation.py`(执行 Agent C prompt)
- [ ] Coordinator 完整流水线编排 + 阶段超时
- [ ] **里程碑:从 chat 输入"分析比亚迪"到产出完整分析报告**

### Phase F — PDF 处理(2 天)

- [ ] `routers/upload.py`
- [ ] 前端扩展:`request_upload` 事件 + 上传按钮组件
- [ ] `pipeline/phase0_pdf_download.py`(自动下载)
- [ ] `pipeline/phase2_pdf_parse.py`(复用 turtle pdf_preprocessor)
- [ ] **里程碑:支持上传 PDF + 自动下载,Agent B 用上 P2/P3/P4/P6 附注**

### Phase G — 追问模式 + 完善(1-2 天)

- [ ] Coordinator 检测"已分析" → 走 `qa_followup`
- [ ] SSE 心跳(防代理截断)
- [ ] 错误降级 + 断点续跑
- [ ] AGENTS.md 同步

**总计预估 13-19 天**(单人全职)。可按 Phase 拆 PR 逐步合并。

---

## 11. 关键决策汇总(已确认)

| # | 决策 | 选择 |
|---|---|---|
| 1 | LLM 协议 | OpenAI / Anthropic / OpenRouter / DeepSeek 4 选 1,channel 配置 |
| 2 | 核心抽象 | turtle 多 Agent 流水线(非"5 技能") |
| 3 | 流式粒度 | 只发 `step + substep`,不发 delta |
| 4 | Agent 通信 | **文件通信**(`{output_dir}` 下 markdown 文件)|
| 5 | 历史窗口 | qa 追问模式 ≤ 10 条历史 + 已生成产物作上下文 |
| 6 | 数据存储 | SQLite `chat_sessions/chat_messages` + `data/agent_runs/` 文件 |
| 7 | 实施分期 | A → G,共 7 阶段 |
| 8 | system_config 存储 | `data/system_config.yaml` |
| 9 | /business-analysis | 一并实现(搬 turtle `shared/qualitative/`)|
| 10 | Tushare | 不引入,用 DuckDB 适配器导出 turtle 格式 |
| 11 | PDF 处理 | 一并支持,在 chat 中提示用户上传(`request_upload` 事件)|
| 12 | 前端 | 不重做,只加 3 种 SSE 事件渲染 |
| 13 | 代码 normalize | `XXXXXX.SH/SZ` / `XXXXX.HK` / `AAPL.US` |

---

## 12. 风险与开放问题

1. **WebSearch 依赖**:Phase 1B 需要 Tavily/Bing API key。若用户未配,§7/§8/§10 会标"⚠️ 数据不可用",影响 Agent B 可用数据。建议默认走 Tavily(每月 1000 次免费)。
2. **§14 Rf 数据源**:turtle 用 yfinance ^TNX,我们项目暂无国债数据。**MVP 写死季度更新的常量**(2.7% 中国 10 年国债),后续接 akshare `bond_china_yield`。
3. **PDF OCR**:扫描件 PDF 我们不处理,会直接降级。turtle 也只是 fallback(`pdf_preprocessor.py` 有 OCR 占位但不强制)。
4. **港股/美股财务数据完整度**:`data/market/HK,US/financial/` 数据是否够 5 年?需先验证再做 §3-§5。如不够要在 §13 标 warning。
5. **A 股母公司报表(§3P/§4P)**:eastmoney 是否有?需验证。
6. **同业可比 §16**:本项目没有行业分类元数据(stock_index 只有名字)。需要新增行业分类来源(akshare `stock_individual_info_em`?)或先降级。
7. **成本估算**:一次完整分析 ≈ 50K tokens(prompts + 数据包 + reports)。Anthropic Sonnet ~$0.15/次,DeepSeek ~$0.005/次。建议默认 routing 用 DeepSeek,关键 phase(qualitative/phase3)允许切 Sonnet。
8. **并发限制**:同 session 同时只一条 in-flight stream(前端已 abort 旧的);跨 session 限制?MVP 不做,让 LLM API 自己限流。

---

## 13. 附录 A:turtle 文件复制清单

| turtle 路径 | 目标路径 |
|---|---|
| `strategies/turtle/coordinator.md` | `backend/services/agent/prompts/coordinator.md` |
| `strategies/turtle/phase3_quantitative.md` | 同上目录 |
| `strategies/turtle/phase3_valuation.md` | 同上 |
| `strategies/turtle/references/*.md` | `backend/services/agent/prompts/references/` |
| `shared/qualitative/qualitative_assessment.md` | `backend/services/agent/prompts/qualitative/` |
| `shared/qualitative/references/*.md` | `backend/services/agent/prompts/qualitative/references/` |
| `scripts/pdf_preprocessor.py` | `backend/services/agent/pipeline/_pdf_preprocessor.py`(复制并去 Tushare 依赖)|
| `scripts/download_report.py` | `backend/services/agent/pipeline/_pdf_downloader.py` |

> 复制前先取 turtle main 分支最新版,后续 turtle 升级时手动 sync。可加 `_TURTLE_VERSION` 注释标记同步日期。

---

## 14. 附录 B:示例分析报告片段

```markdown
# 比亚迪(002594.SZ) 投资分析报告

## 一、结论

> **建议:观察(GG=11.2% > II=10.5%,但 ROIC 趋势承压)**

## 二、关键数据

| 指标 | 值 |
|---|---|
| 当前价 | 268.50 元(2026-05-23)|
| 市值 | 7,820 亿元 |
| 报表币种 | CNY |
| Rf(中国 10Y)| 2.70% |
| 门槛 II | 10.5% |
| 精算穿透回报率 GG | **11.2%** |

## 三、定性视角(/business-analysis)

| 维度 | 评级 | 关键发现 |
|---|---|---|
| 商业模式 | 优质 | 垂直整合 + 三电自研... |
| 护城河 | 较强 | 规模效应 + 技术壁垒... |
| 行业地位 | 优质 | 全球 BEV 销量 #1 |
| 管理层 | 中性 | 创始人主导,治理稳定 |
| 财务质量 | 较强 | 经营现金流稳定增长... |
| 估值合理性 | 中性 | PE 25x vs 行业 30x |

**结构化参数**:moat_rating=较强, capital_intensity=高, management_quality=中性, ...

## 四、定量视角(Agent B 11 步穿透回报率)

### Step 0:数据校验
- 利润口径:**扣非归母净利润**(§3 行 51)
- 现金口径:狭义(现金 + 短期投资)
- 中报数据:有(2026Q1)

### Step 1-11:略
...
**精算 GG = 11.2%**(详细公式见附件)

## 五、估值定价(Agent C)

### 价值陷阱排查
- ✅ 现金流恶化:不存在
- ✅ 护城河收窄:不存在
- ⚠️ 行业结构性衰退:**新能源补贴退坡 + 价格战**,标记中度风险
...

## 六、风险提示
1. 价格战持续吞噬利润率
...

## 七、操作建议(仅供参考,投资有风险)
- 当前价位 268.50 处于 PE 历史 60 分位,GG 略超门槛但安全边际不足
- 建议**观察**,等待回调至 PE 50 分位以下(对应价位约 230 元)再考虑建仓
- 若已持有,**不加仓,继续持有**

---

> 本报告由 stock_investment 系统结合 Turtle Investment Framework v2.0 自动生成
> 报告时间:2026-05-23 19:30:00
> 数据快照:2026-05-22 收盘
```

---

*问股(Ask Stock)v2 设计文档 | 2026-05-23 | 待评审*
