# AGENTS.md — 问股(Ask Stock)子系统

> 本文件聚焦**问股多 agent 平台**。跨切面铁律(数据源、DuckDB 唯一入口、`data/cache/` 缓存路径、长任务 nohup、沟通语言等)见**根 `AGENTS.md`**,此处不重复。

## Terminology(术语铁律,2026-05-26)

- 本项目内部统一使用 **「现金流保守策略」**(英文标识符 `conservative` / `cpa_conservative`)指代基于穿透回报率的保守估值策略。
- **历史代号「龟龟策略 / Turtle」已弃用**,不要在新代码、新 prompt、新文档中出现。
- **唯一例外**:`/Users/11182300/PycharmProjects/Turtle_investment_framework` 是外部 sibling 项目的真实路径,引用该路径或描述「prompt 来源于 Turtle 框架」时保留 `Turtle` 字样,不替换。
- **Python 符号对应**:`MoatRatingConservative` / `map_moat_rating_conservative` / `_MOAT_RATING_CONSERVATIVE_MAP`。
- **Prompt 文件**:`judgment_examples_conservative.md`(原 `judgment_examples_turtle.md`)。

## 架构 — 多 Agent + 4 层 Fallback(2026-05-24 决策)

### 总体定位
问股**不是单 agent 系统**,而是**多 agent 平台**。当前已实现 **CPA 问股(cpa)**,后续将扩展 **团队分析问股(team)** 等。目录结构、Coordinator、Prompts 都必须按 agent 维度可扩展,**禁止把单一 agent 的实现细节硬编码进顶层模块**。

### 目录结构
```
backend/services/agent/
├── coordinator.py              # 顶层路由:4 层 fallback(暂留 agent/ 根)
├── core/                       # 通用基础设施(跨 agent 复用)
│   ├── parser.py / sse.py / session_repo.py / workspace.py
│   ├── symbol.py / llm_routing.py / tavily_client.py
│   ├── prompts_loader.py       # 原 prompts/loader.py
│   └── qualitative/            # 定性分析共享 service(见下)
├── agents/                     # 每个 agent 一个子包,自包含
│   ├── __init__.py             # AGENT_REGISTRY = {"cpa": CpaAgent, ...}
│   ├── cpa/                    # CPA 问股(现有)
│   │   ├── agent.py            # CpaAgent.run(ctx) → AsyncIterator[SSEEvent]
│   │   ├── pipeline/           # phase1_data_pack / phase3_quant / phase3_valuation
│   │   └── prompts/            # coordinator.md / phase3_*.md / references/
│   ├── business_analysis/      # 定性分析用户入口(2026-05-26)
│   └── team/                   # 团队分析问股(未来)
```

### 设计原则
1. **每个 agent 自包含** — `agents/<name>/` 含自己的 pipeline + prompts + 解析逻辑,**不跨 agent 共享业务代码**;共享的下沉到 `core/`。
2. **统一入口契约** — 每个 agent 实现 `Agent.run(ctx) -> AsyncIterator[SSEEvent]`,Coordinator 只关心这个接口。
3. **AGENT_REGISTRY** — `agents/__init__.py` 维护 `name → class` 映射,Coordinator 按意图分类结果路由。
4. **Prompts 跟着 agent 走** — cpa 的在 `agents/cpa/prompts/`,各自独立演进。

### Coordinator 4 层 Fallback(规则 + LLM 意图分析混合)
**不让用户显式选 agent**,Coordinator 自动路由:

```
Layer 1 (规则): session.output_dir 已有完整报告 → qa_followup
              ↓ (无报告)
Layer 2 (规则): 无股票上下文 + 消息无股票码 → chitchat
              ↓ (识别到股票码)
Layer 2.5 (规则): 扫 BA 关键词(护城河/管理层/周期性/...)命中 → business_analysis
              ↓
Layer 3 (LLM): 意图分类器(轻量 LLM call)→ 选 agent  【未实现】
              ↓ (LLM 失败/超时/置信度低)
Layer 4 (兜底): 默认 agent = cpa(当前唯一稳定 agent)
```

- Layer 1/2 是规则快路径,毫秒级;Layer 3 仅在识别到股票码后触发;Layer 4 兜底永不阻塞。
- Layer 1 `_has_completed_report` 判定靠**读 `_meta.json` 的 `phase3_valuation.status==done`**(非 glob)。

### 当前实现状态(2026-05-26)
- ✅ Layer 1/2/2.5/4 已实现;目录重构已完成(`agents/cpa/` + `core/` 全部到位)。
- ✅ **business_analysis agent**:`agents/business_analysis/` 用户入口 + `core/qualitative/` 共享 service(6 维度全部真实实现)。
- ❌ **Layer 3 LLM 意图分类未实现**,识别到股票码 + 无 BA 关键词时直接走 `DEFAULT_AGENT = cpa`。

## CPA 问股 Phase 1 数据包构成

`DataPackBuilder` 共 19 sections,002594.SZ 端到端跑通:
- §1 基础 / §2 市值股价 / §3·§3P 利润表 / §4·§4P 资产负债 / §5 现金流 / §6 股息
- §7 股东(EastMoney F10 三表) / §8 行业 + §10 ESG(Tavily search,7 天文件缓存,无 key 优雅降级)
- §9 主营 / §11 周线 / §12 比率 / §13 warnings / §14 Rf(`RF_CHINA_10Y` 常量) / §15 行业估值 / §16 同行对比 / §17 衍生
- ⬜ §7 质押 / 高管增减持(待单独 issue);⬜ §17.8 D&A → EV/EBITDA

LLM 流水线三阶段:Phase 1 数据包 → Phase 3.1 量化(`run_phase3_quant`,穿透回报率/阈值/安全边际)→ Phase 3.2 估值(`run_phase3_valuation`,生成 `*_分析报告.md`)。Coordinator `_run_full_pipeline` 串接,统一发 `tool_start/tool_done` + `_meta.json` 状态原子写,失败带 phase 标注。SSE 6 事件:thinking / tool_start / tool_done / generating / done / error。Workspace 按 `<code>_<name>/` 隔离。

## agent_runs 产物/过程分家(2026-06-15 完成)

`report/agent_runs/<code>_<name>/` 拆 `report/`(产物 `*_分析报告.md`)+ `work/`(可复用中间产物 `_meta.json` / `data_pack_market.md` / `phase3_quantitative.md` / `_quant_results.json`)。

- **复用语义**:cpa 流水线跑前先看 `work/`,`data_pack_market.md` 在则跳过 Phase1 构建、`phase3_quantitative.md` 在则跳过 Phase3.1 LLM(读回解析还原 quant_parsed),缺失才调 LLM(断点续跑)。
- `Workspace` 新增 `work_dir()/report_dir()` + 文件名常量;`read_meta` 改读 `work/_meta.json` 并回退旧平铺位置。
- `coordinator._run_qa_followup` glob 改 `report/` 子目录带旧目录回退;`run_phase3_valuation` 加 `report_dir` 参数。

## 定性分析子系统(`core/qualitative/` + business_analysis agent · 2026-05-26)

### 架构
```
backend/services/agent/
├── core/qualitative/                # 共享 service(cpa Phase 0 / business_analysis 复用)
│   ├── schema.py                    # DimensionReport / QualitativeParams(14 字段) / QualitativeReport
│   ├── runner.py                    # run_qualitative(ref, store, tavily, llm) 编排 6 维度
│   ├── cache.py                     # data/cache/qualitative/<code>_<name>/ 30 天 TTL + REPORT_DATE 失效
│   ├── dimensions/d{1..6}.py        # 6 维度真实实现
│   └── prompts/d{1..6}.md           # LLM prompt(评级指引固化保守策略口径)
└── agents/business_analysis/agent.py  # 用户入口(SSE 6 事件)→ run_qualitative + 落 qualitative_report.md
```

### 6 维度数据源
| 维度 | 数据源 | 输出参数 |
|---|---|---|
| **D1** 商业模式 | DuckDB(资产负债 + 指标视图) | `capital_intensity / collection_mode` |
| **D2** 护城河 | DuckDB(长期 ROE/毛利率)+ Tavily | `moat_type / moat_flywheel / moat_rating / competitors[]` |
| **D3** 行业周期 | DuckDB(营收/利润波动)+ Tavily | `cyclicality / cycle_position` |
| **D4** 管理层 | EastMoney emweb F10(A 股)/ yfinance(HK+US)+ Tavily | `management_rating ∈ {优秀/合格/损害价值/观察期}` |
| **D5** 经营评述 | EastMoney `RPT_F10_OP_BUSINESSANALYSIS` | `mda_credibility / mda_impact` |
| **D6** 控股结构 | DuckDB(十大股东 + 流通 + 户数)+ Tavily | `holding_structure / sotp_discount_pct` |

### 设计铁律
- **降级优先于抛异常**:任一数据源不可用 → `narrative="⚠️ ..."` + DEFAULT_PARAMS,**不阻塞**。
- **30 天 TTL + REPORT_DATE 失效**:DuckDB 出现新报告期则强制刷新。
- **cpa Phase 0 前置**:cpa agent 启动先调 `run_qualitative()`,失败容忍(降级,Phase 1/3.1/3.2 仍跑通)。
- **价值陷阱 5 项排查**:Phase 3.2 valuation 启用 D2 护城河 / D3 周期 / D4 管理层 / D6 控股结构 5 项二元规则。
- **mock_dimension_dN = dimension_dN 别名**:让 `MOCK_DIMENSION_FNS` 自动用真实实现(无需改 runner)。

## 历史教训(HK/US 数据源)

- EastMoney HK 单次 ≤ 250 行 / ≤ 12 个月,长历史必须切片。
- yfinance 美股全量(~7400 只)极易触发限速,后台跑必须加 retry + 进度日志。
- HK/US 分红字段语义与 A 股不同,适配层必须显式映射。

## TODO

- L3 LLM 意图分类器(coordinator `_classify_intent` 实现 + 4 层 fallback 测试)。
- team agent 骨架(`agents/team/`,多角色协作)。
- §17.8 D&A → EV/EBITDA;§7 质押 / 高管增减持。

## 测试策略

- `backend/tests/agent/test_qualitative_d{1..6}.py` 共 ~115 用例。全量基线 1332 passed + 1 skipped。
- AGENT_REGISTRY 单测:确保新 agent 注册后 coordinator 能路由到它。
- 意图分类 mock LLM 返回值,验证 4 层 fallback 在不同条件下的分支。
