# Business Analysis Agent 实施 Plan(方案 C:共享 service + 独立 agent 入口)

> 目标:把原 turtle 策略 v1 内嵌的「6 维度定性分析」按 prompt 原作者的解耦意图,
> 移植到本仓库 multi-agent 架构,做成**`core/qualitative/` 共享 service + `agents/business_analysis/` 用户入口**,
> 让 cpa(Phase 0 前置)与未来 team agent 都能复用。
>
> 节奏:**与 L3 意图分类并行,BA 优先**(节奏 ii)。

---

## 决策汇总(已拍板)

| # | 决策 | 选择 |
|---|---|---|
| Q1 | 定性产物缓存粒度 | **d**:30 天 TTL + 报告期变化(§3 最新 `REPORT_DATE`)自动失效 |
| Q2 | Web search 数据源 | **b**:Tavily + EastMoney F10 公告/股东/研报组合,**不引入 PDF RAG** |
| Q3 | service 接口形态 | **c**:外部异步生成器 + SSE 事件;内部 6 维度独立函数,各自缓存 |
| Q4 | cpa 集成方式 | **d**:cpa Phase 0 前置,缓存命中即跳过 |
| Q5 | BA agent 触发 | **c + 节奏 ii**:Layer 2.5 关键词快路径(独立工作)+ Layer 3 LLM 兜底(待 L3 落地后增量补) |

**关键词清单**(初版):`定性分析 / 商业模式 / 护城河 / 管理层 / 周期性 / 行业地位 / 治理 / 资本配置 / 战略`

---

## 架构概览

```
backend/services/agent/
├── core/
│   └── qualitative/                    ← 新增,共享 service
│       ├── __init__.py
│       ├── schema.py                   ← Pydantic:14 参数 + 6 维度报告模型
│       ├── cache.py                    ← 30 天 TTL + REPORT_DATE 失效
│       ├── runner.py                   ← async run_qualitative(ref, on_event=None)
│       ├── dimensions/                 ← 6 维度独立函数
│       │   ├── d1_business_model.py
│       │   ├── d2_moat.py
│       │   ├── d3_industry_cycle.py
│       │   ├── d4_management.py
│       │   ├── d5_mda.py
│       │   └── d6_holding_structure.py
│       └── prompts/                    ← 各维度 LLM prompt
│           ├── d1.md
│           ├── ...
│           └── d6.md
├── agents/
│   ├── business_analysis/              ← 新增,用户入口 agent
│   │   ├── __init__.py
│   │   ├── agent.py                    ← BusinessAnalysisAgent(Agent.run 协议)
│   │   └── prompts/
│   │       └── coordinator.md
│   └── cpa/
│       ├── agent.py                    ← 改:加 Phase 0,调 core/qualitative/
│       └── pipeline/
│           └── phase0_qualitative.py   ← 新增:适配层,封装 service 调用
└── coordinator.py                      ← 改:Layer 2.5 关键词路由
```

**数据落盘**:
```
data/qualitative/                       ← 新增缓存目录(进备份)
└── <code>_<name>/
    ├── report_<YYYYMMDD>.json          ← 14 参数结构化结果
    ├── report_<YYYYMMDD>.md            ← 6 维度叙事报告(Agent C 用)
    └── _meta.json                      ← {report_date, ttl_until, sources}
```

> 按 AGENTS.md 项目结构铁律,定性产物属于「用户产物 = 花 token 的 artifact」,**进备份**。
> 但同一 cpa 任务的产物已经在 `report/agent_runs/<code>_<name>/` 下,这里独立放 `data/qualitative/` 是因为它**跨任务共享**(被 cpa Phase 0 和未来 team agent 复用),需要按股票码而非任务隔离。

---

## 阶段拆分

### 阶段 1:Schema + Service 骨架(2-3 天)

**目标**:定义数据模型,搭起 service 框架,所有维度 mock 实现先跑通。

**RED**:
- `backend/tests/test_qualitative_schema.py` — 14 参数 Pydantic 序列化/反序列化,值域校验
- `backend/tests/test_qualitative_cache.py` — 30 天 TTL 命中/失效 / REPORT_DATE 变化触发失效
- `backend/tests/test_qualitative_runner.py` — `run_qualitative(ref)` 流式产出 6 维度事件,mock 维度返回

**GREEN**:
- `core/qualitative/schema.py`:
  - `QualitativeParams`(14 字段,见 `factor_interface.md`)
  - `DimensionReport`(`name`, `narrative`, `evidence`, `params`)
  - `QualitativeReport`(6 个 DimensionReport + 末尾参数表)
- `core/qualitative/cache.py`:
  - `QualitativeCache(data_dir).get(code) -> QualitativeReport | None`
  - `.put(code, report, report_date)` 写 `_meta.json`
  - 失效条件:`ttl_until < now` OR DuckDB 查 `v_a_indicator` 最新 REPORT_DATE > 缓存 REPORT_DATE
- `core/qualitative/runner.py`:
  - `async def run_qualitative(ref, *, on_event=None, force_refresh=False) -> QualitativeReport`
  - 流程:cache.get → 命中即返回 + emit `cache_hit`;否则顺序调 6 维度,每维度 emit `dimension_start / dimension_done`,最终 cache.put
- `dimensions/d{1..6}.py`:**先全 mock**,返回固定 fixture
- `prompts/d{1..6}.md`:占位符,1 句话描述

**DoD**:`pytest backend/tests/test_qualitative_*` 全绿;`run_qualitative` 端到端跑通 mock 维度,30 个 SSE 事件 + 缓存写盘正确。

---

### 阶段 2:6 维度真实实现(5-7 天,逐维 RED→GREEN)

**通用约定**:
- 每维度签名:`async def assess_dN(ref, *, store, tavily, llm) -> DimensionReport`
- 数据获取层:DuckDB(财务/股东)+ EastMoney F10(公告/研报)+ Tavily(行业舆情)
- LLM 调用:用 `system_config.llm_routing` 取 `qualitative` channel(可与 `phase3_quant` 同源,允许独立配)
- 失败降级:任一数据源不可用 → 该维度产出 `DimensionReport(narrative="⚠️ 数据不可用", params=None)`,**不抛异常**

**逐维度任务**:

#### D1 商业模式(0.5 天)
- 数据源:§3 利润表 / §4 资产负债 / §5 现金流(纯 DuckDB,无 search)
- LLM 推理:从「应付/应收占比、预收账款、固定资产/总资产、研发投入、毛利率结构」拍 `capital_intensity` + `collection_mode`
- 不需要 web search,token 成本最低

#### D2 护城河(1.5 天,最复杂)
- 数据源:§7 股东(EastMoney F10)+ Tavily 检索 `<公司名> 护城河 / 竞争优势 / 同行对比`
- 需要识别**竞争对手列表**(`competitors`)— 用 LLM 从 Tavily 结果提取 + EastMoney 行业内同流通市值 top N 兜底
- 缓存 Tavily 结果(沿用 `core/tavily_client.py` 7 天文件缓存)

#### D3 行业周期(1 天)
- 数据源:EastMoney 行业(已有)+ Tavily `<行业名> 政策 / 周期 / 监管`
- 周期判定靠 LLM 综合,`industry_keywords` 用于后续监控

#### D4 管理层(1 天)
- 数据源:EastMoney F10 公告(高管变动 / 增减持 / 分红回购历史)+ Tavily `<公司名> 管理层 / 资本配置`
- 评级 4 档:优秀 / 合格 / 损害价值 / 观察期

#### D5 MD&A(1 天)
- 数据源:EastMoney 历年公告全文(若可拉到)+ 历年财报关键摘要交叉校验
- **简化版**:不做完整言行核查,先做"最近 1 年 MD&A 关键论断 vs 实际财务结果"对比,产出可信度评级

#### D6 控股结构(0.5 天,大多数票"不适用")
- 数据源:EastMoney 子公司列表 + 股东表(已有 §7)
- 大多数 A 股直接产出 `holding_structure=False`,跳过 SOTP

**DoD**:`002594.SZ`(已端到端跑通的样本)的 6 维度真实输出 ≠ mock,人工 review 报告合理;每个维度独立单测 mock LLM 验证 prompt 解析逻辑。

---

### 阶段 3:`agents/business_analysis/` 用户入口(1-2 天)

**RED**:
- `backend/tests/test_business_analysis_agent.py` — 注入 mock service,验证 SSE 事件序列(`tool_start: "定性分析" → 6 × dimension_done → done`)

**GREEN**:
- `agents/business_analysis/agent.py`:
  ```python
  class BusinessAnalysisAgent:
      async def run(self, session_id, ref):
          d = self.workspace.ensure(ref)
          await self.sse_send(sse.tool_start("qualitative", "定性分析(6 维度)"))
          
          async def _on_event(evt):
              # 把维度事件转发到 SSE
              await self.sse_send(sse.generating(evt["text"]))
          
          report = await run_qualitative(ref, on_event=_on_event, ...)
          
          # 落盘 markdown 报告 → workspace
          report_path = d / "qualitative_report.md"
          report_path.write_text(render_markdown(report), encoding="utf-8")
          
          await self.sse_send(sse.done(report_path.read_text(), artifacts=[...]))
  ```
- `agents/__init__.py` 注册:`AGENT_REGISTRY["business_analysis"] = BusinessAnalysisAgent`
- `prompts/coordinator.md`:简短引导,告诉 LLM 这个 agent 干啥

**DoD**:从前端发"看下 600519 的护城河",路由命中 BA agent,SSE 事件流完整,workspace 产物 OK。

---

### 阶段 4a:Coordinator 关键词路由(0.5 天,**必做**)

**RED**:
- `backend/tests/test_coordinator_routing.py` 加用例:
  - 「分析 600519 的护城河」→ business_analysis
  - 「分析 600519」→ cpa(默认)
  - 「看下伊利的管理层」→ business_analysis
  - 「比较伊利和蒙牛」→ cpa(team 还没有,**降级 cpa**;L3 上线后改 team)

**GREEN**:
- `coordinator.py` 加 Layer 2.5:
  ```python
  BA_KEYWORDS = {"定性分析", "商业模式", "护城河", "管理层", "周期性", 
                 "行业地位", "治理", "资本配置", "战略"}
  
  if has_stock_ref and any(k in user_msg for k in BA_KEYWORDS):
      return "business_analysis"
  ```

**DoD**:全部新增路由用例通过,旧 cpa 默认路由不回归。

---

### 阶段 4b:与 L3 LLM 兜底协同(0.5 天,**L3 落地后增量补**)

L3 实现后,在 `_classify_intent` 里增加 `business_analysis` 作为返回值之一,关键词路径与 L3 互为冗余。

**注**:此阶段不在本 plan 范围,但保留接口锚点,避免来回改。

---

### 阶段 5:cpa 集成(1-2 天)

**目标**:cpa Phase 0 调 `core/qualitative/`,缓存命中跳过,Phase 3.2 启用价值陷阱排查 5 项全开。

**RED**:
- `backend/tests/test_cpa_phase0_qualitative.py` —
  - 缓存命中:Phase 0 < 1s 完成
  - 缓存未命中:走完整定性,workspace 产物正确
  - 服务异常:Phase 0 标记 failed,但 Phase 1/3.1/3.2 仍降级跑通(关键!)
- `backend/tests/test_phase3_valuation_with_qualitative.py` — Agent C 读到 14 参数,价值陷阱 5 项全启用

**GREEN**:
- `cpa/pipeline/phase0_qualitative.py`:
  ```python
  async def run_phase0_qualitative(workspace, ref, runner, on_chunk):
      report = await runner(ref, on_event=lambda e: on_chunk(e["text"]))
      (workspace / "qualitative_report.md").write_text(...)
      (workspace / "qualitative_params.json").write_text(report.params.model_dump_json())
      return report
  ```
- `cpa/agent.py` 加 Phase 0(参考现有 `_run_phase` 模式),失败容忍(降级)
- `cpa/pipeline/phase3_valuation.py`:加载 `qualitative_params.json`,塞进 prompt 上下文
- `cpa/prompts/phase3_valuation.md`:删 `/business-analysis` 引用,改成"Phase 0 已前置生成"

**DoD**:`002594.SZ` 端到端 Phase 0+1+3.1+3.2 全跑通,最终报告价值陷阱排查 5 项全有结论。

---

### 阶段 6:文档与回归(1 天)

- `AGENTS.md`:
  - "问股(Ask Stock)" 段加 **business_analysis agent** 子章节
  - TODO 段:「⬜ qualitative_report.md / business-analysis agent 立项」改为 ✅,新增 L3 协同的 4b 子任务
  - Project Timeline:加 2026-05-26 段(本次实施)
- `docs/agents.md`(新建,可选):每个 agent 一段,简介 + 入口 + 产物路径
- `docs/deployment.md`:新增 `data/qualitative/` 备份说明
- 全量回归:
  - `python -m pytest backend/tests/ -x -q`(应 800+ 全绿)
  - `cd frontend && npm test && npx tsc --noEmit && npm run lint`
- 端到端 smoke:对话发 "分析 600519 的护城河",观察 SSE 事件 + workspace 产物 + cache 落盘

---

## Token 预算与成本估算

| 阶段 | 单次成本(input + output)|
|---|---|
| D1 商业模式 | 5K + 1K(无 search) |
| D2 护城河 | 15K + 3K(Tavily 5 次 ≈ $0.025) |
| D3 行业周期 | 8K + 2K(Tavily 3 次 ≈ $0.015) |
| D4 管理层 | 10K + 2K(Tavily 3 次 ≈ $0.015) |
| D5 MD&A | 12K + 3K(无 search,纯文本对比) |
| D6 控股结构 | 3K + 1K(无 search,大多数跳过) |
| **合计** | **~53K input + ~12K output + $0.06 search** |

按 deepseek-r1 ¥4/M input + ¥16/M output 算:**单次定性 ≈ ¥0.4**;Tavily 折人民币 ≈ ¥0.5。
**30 天缓存** = 同股票码月内重复问股 0 增量成本。

---

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| Tavily 搜索结果质量参差 | 多 query 组合 + LLM 多源交叉验证 + 7 天缓存避免重复浪费 |
| EastMoney F10 字段命名不稳 | 已有 §7 实现可参考,新接口走同样的 hash 字段法兜底 |
| LLM 推理产出不可解析 | 每维度 prompt 强制 JSON 输出 + Pydantic 校验失败重试 1 次 |
| cpa Phase 0 失败影响主流程 | Phase 0 降级:产物不存在时 Phase 3.2 自动退化("无定性"分支) |
| `data/qualitative/` 占用增长 | 30 天 TTL + 失效自动清理;7400 美股全跑也 < 100MB |
| 6 维度 LLM 调用串行慢 | 阶段 1 完成后评估,**D1/D6 不依赖 search 可与其他并行**(asyncio.gather) |

---

## 工时汇总

| 阶段 | 工时 |
|---|---|
| 1. Schema + Service 骨架 | 2-3 天 |
| 2. 6 维度真实实现 | 5-7 天 |
| 3. agents/business_analysis 入口 | 1-2 天 |
| 4a. 关键词路由 | 0.5 天 |
| 5. cpa 集成 | 1-2 天 |
| 6. 文档与回归 | 1 天 |
| **合计** | **10.5-15.5 天** |

> 4b(L3 协同)不计入本 plan,L3 落地后另行 0.5 天补丁。

---

## 验收标准(End-to-End)

1. **独立 BA 入口**:对话发「看下 600519 的护城河」→ 走 BA agent → 产出 `qualitative_report.md` + 14 参数 JSON
2. **cpa 集成**:对话发「分析 600519」→ Phase 0 调定性 → Phase 3.2 价值陷阱 5 项全启用 → 最终报告含 D2/D3/D4 判断
3. **缓存命中**:同股票码 30 天内第二次问 → Phase 0 < 1s 完成,token 0 消耗
4. **失效自动**:DuckDB 中该股票出现新报告期 → 下次问触发刷新
5. **降级容错**:Tavily key 缺失 → D2/D3/D4 narrative 标 ⚠️ 但流程不中断
6. **回归**:全量测试 800+ case 全绿,前端 tsc/lint 0 错误

---

*Plan 版本 v1 · 2026-05-25 · 待 review*
