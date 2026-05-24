# Plans

## 问股 §7 / §8 / §10 数据源接入(2026-05-24 决策)

### 决策已敲定
- §7 控股股东 → **EastMoney F10 五表**(替代被禁用的 akshare)
- §8 行业 / §10 ESG → **Tavily search API**
- 缓存:按需拉 + on-disk 7 天
- §7 五表全部历史保留(不用 latest_only),repository 用 append + dedup

### Tavily 决策
- key:环境变量 `TAVILY_API_KEY`
- 调用:§8 查 1 次 + §10 查 1 次,每股每周一次
- SDK:官方 `tavily-python` 包
- 缓存:`data/cache/tavily/<code>_<section>.json` + 7 天 mtime 过期

### §7 表清单 + 用途(2026-05-24 spike 后修订)

| # | 表 | reportName | sortColumns | 历史需求 | 渲染策略 | 状态 |
|---|---|---|---|---|---|---|
| 1 | 十大股东 | `RPT_F10_EH_HOLDERS` | `END_DATE` | ≥2 期对比 | 最近一期 + 较上期 +/- pp | ✅ spike 通过 |
| 2 | 十大流通股东 | `RPT_F10_EH_FREEHOLDERS` | `END_DATE` | 同上 | 同上 | ✅ spike 通过 |
| 3 | 股东户数 | `RPT_HOLDERNUMLATEST` | `END_DATE` | 单期(自带 PRE_END_DATE / PRE_HOLDER_NUM) | 当期 vs 上期对比 | ✅ spike 通过 |
| 4 | 股权质押 | — | — | — | — | ⏸ **placeholder,后续单独迭代** |
| 5 | 高管变动 | — | — | — | — | ⏸ **placeholder,后续单独迭代** |

**Spike 结论**(2026-05-24):
- F10 接口 `sortColumns` 必须用 `END_DATE`(`REPORT_DATE` 失败)
- 质押 / 高管变动 5 个候选 reportName 全部「报表配置不存在」,turtle 框架历史上也从未实现(只有 placeholder doc)
- **决策路径 1**:接受现状先落 3 表,§7 主体跑通,质押 + 高管标注「数据待补」,后续单独迭代

数据量评估:单股 3 表合计 < 30 KB;5000 只 A 股全量 ≈ 150 MB。

---

## 执行 Phase

### Phase 0 — Spike 验证(30 分钟)

- 写 `scripts/spike_eastmoney_f10.py`
- 拿 002594.SZ + 600519.SH 跑 5 个 reportName
- 打印每接口 result.data[0] 字段清单 + 首条样例
- 笔记落到 `notes/eastmoney_f10_spike.md`(本地工作笔记)
- 如 reportName 错误,查 EastMoney F10 网页抓包修正

### Phase 1 — §7 EastMoney F10 接入(~1 天,3 表方案)

1. **Pydantic models**(`backend/models/holder.py`):3 个 record class
   - `Top10HolderRecord / Top10FreeHolderRecord / HolderCountRecord`
   - 字段以 spike 确认的英文 schema 命名(SECURITY_CODE / END_DATE / HOLDER_NAME / HOLD_NUM / HOLD_NUM_RATIO …)
2. **Adapter 扩展**(`backend/adapters/eastmoney_adapter.py`):3 个新方法
   - `_fetch_report` 签名加 `sort_column="REPORT_DATE"` 参数(默认保持向后兼容)
   - `fetch_top10_holders / fetch_top10_free_holders / fetch_holder_count_history`
   - 全部传 `sort_column="END_DATE"`
3. **Repository**(`backend/repositories/holder_repo.py`):append + dedup
   - `data/market/A/holders/{top10, top10_free, holder_count}/<code>.parquet`
   - dedup key:`(SECURITY_CODE, END_DATE, HOLDER_NAME)`(holder_count 用 END_DATE)
4. **按需拉服务**(`backend/services/holder_updater.py`):`fetch_with_cache(code, table, ttl_days=7)`
   - mtime < 7 天直接读;否则调 adapter → append → 返回
   - 失败优雅降级到旧数据 + warning log
5. **DuckDBStore 视图 + 查询**(`backend/services/duckdb_store.py`):
   - `v_a_top10_holders / v_a_top10_free_holders / v_a_holder_count` 3 视图
   - `query_top10_holders(code, latest_n_periods=2)` / `query_top10_free_holders(...)` / `query_holder_count_history(code, n=8)`
6. **§7 section**(`s07_holders_placeholder.py` → `s07_holders.py`):重写为真实实现
   - 渲染:十大股东最新一期 + 较上期变化 / 十大流通股东 / 股东户数 当期 vs PRE_HOLDER_NUM
   - **质押 + 高管变动留空降级文本**:「数据待补 — 暂无可用数据源,后续迭代接入」
7. **builder.py 注册**:替换 SECTION_REGISTRY 中的占位

TDD:3 adapter mock 测试 + repo roundtrip + cache 命中/过期 + section 渲染缺失场景 ≈ 18-20 case

### Phase 2 — Tavily 客户端基建(~0.5 天)

1. `requirements.txt` 加 `tavily-python>=0.3.0`
2. 新建 `backend/services/agent/core/tavily_client.py`:
   ```python
   class TavilyClient:
       def __init__(self, api_key=None, cache_dir=...):
           self.api_key = api_key or os.getenv("TAVILY_API_KEY")
           self.client = _TavilyClient(self.api_key) if self.api_key else None
           self.cache_dir = cache_dir
       def search_with_cache(code, section, query, ttl_days=7, max_results=5):
           # 1) 读 cache,mtime < 7 天直接返
           # 2) 否则调 search,写 JSON
           # 3) 失败返 None,上游降级
   ```
3. TDD:6-8 case(cache hit/miss/expired/no_key/network_error/exception)

### Phase 3 — §8 行业 + §10 ESG section(~0.5 天)

1. `s08_industry.py`:
   - 入参 `ref / stock_index / tavily=None`
   - industry 缺失 → 降级文本
   - tavily 缺失 → 降级文本(LLM 用先验)
   - query = `"{industry} 行业发展 政策 竞争格局 近6个月"`
   - 渲染 industry / query / top-5 results (title + content[:300] + url)
2. `s10_esg.py`:
   - tavily 缺失 → 降级
   - query = `'"{company}" 处罚 OR 诉讼 OR 事故 OR 环保 近12个月'`
   - 渲染 top-5 results
3. `DataPackBuilder.__init__` 接收可选 `tavily=None`,传给所有 section
4. TDD:fake tavily 返回 + no-tavily 降级 + 行业缺失等

### Phase 4 — 集成 + 端到端验证(~0.5 天)

1. `CpaAgent.__init__`:构造 `TavilyClient`(无 key=None),传给 `DataPackBuilder`
2. `test_phase1_data_pack_builder.py` 扩展:patch eastmoney + tavily,断言 19 sections 都有真实内容(无 "数据待补",除非外部依赖缺失主动降级)
3. `scripts/smoke_data_pack.py 002594.SZ`:后台 nohup 跑,产出 `data_pack.md` 人工 review
4. 文档:
   - AGENTS.md Update 段加完成记录
   - README.md 加 `TAVILY_API_KEY` 配置说明

### 提交策略

按 phase 拆 4 次 commit:
1. `feat(agent): 接入 §7 控股股东 - EastMoney F10 五表`
2. `feat(agent): 新增 TavilyClient + 7 天文件缓存`
3. `feat(agent): §8 行业 + §10 ESG 接入 Tavily`
4. `chore(agent): 端到端集成 + smoke + 文档`

每次 commit 前跑 `pytest -x -q` 0 回归。

### 风险与回退

| 风险 | 检测点 | 回退 |
|---|---|---|
| F10 reportName 错 | Phase 0 spike | 改用 EastMoney F10 网页抓包修正 |
| EastMoney 字段名变化 | Phase 1.2 mock 通过但真实数据空 | 详细 logging + 字段宽容 fallback |
| Tavily free tier 用完 | Phase 4.3 smoke 503 | 缓存层兜住,7 天周期不会击穿 |
| 部分 A 股 F10 无数据(新股/退市) | s07 section | 字段独立降级,不阻塞整体 |

### 可选(默认不做)

- `scripts/warmup_holders.py`:首次问股 0 等待。后台跑 1 次 ~1-2 小时全市场 5 表落 parquet。
