# Core Data Model 实施计划

> 日期：2026-05-13
> 设计文档：2026-05-13-core-data-model-design.md
> 状态：待执行

## 总体策略

分 6 阶段渐进实施。Phase 1-4 搭建新架构骨架，Phase 5 执行数据迁移（含新旧数据源对比验证），Phase 6 将现有系统切换到新架构。

**关键原则**：Phase 5 数据迁移前保留旧数据源，获取新数据后随机选择 50 只股票对比相同字段，确认一致后才进入 Phase 6 集成。

---

## Phase 1: Models 层（Pydantic Schema）

**目标**：定义所有数据结构，无外部依赖

**新增文件**：
- `backend/models/__init__.py`
- `backend/models/market.py` — `DailyKlineRecord`, `AdjustFactorRecord`, `AggregatedKline`
- `backend/models/basic.py` — `StockBasicInfo`
- `backend/models/financial.py` — `IncomeStatement`, `BalanceSheet`, `CashFlow`, `FinancialIndicator`
- `backend/models/event.py` — `DividendRecord`

**要点**：
- 所有字段严格按设计文档定义（类型、必填/可选、默认值）
- 财报类的大量列（170/221/316/141）使用代码生成或动态字段定义
- `model_config = ConfigDict(extra="allow")` 允许财报类保留未显式定义的列

**测试**：
- 验证必填字段校验（缺失时报错）
- 验证可选字段默认为 None
- 验证类型转换（如字符串数字 → float）

**预计工作量**：0.5 天

---

## Phase 2: Repository 层（Parquet I/O）

**目标**：统一的数据读写接口

**依赖**：Phase 1

**新增文件**：
- `backend/repositories/__init__.py`
- `backend/repositories/base.py` — 通用 Parquet 读写辅助函数
- `backend/repositories/market_repo.py` — `MarketRepository`
- `backend/repositories/basic_repo.py` — `BasicRepository`
- `backend/repositories/financial_repo.py` — `FinancialRepository`
- `backend/repositories/event_repo.py` — `EventRepository`

**要点**：
- 读取时：Parquet → DataFrame → Pydantic 校验（批量）→ 返回 List[Model]
- 写入时：List[Model] → DataFrame → Parquet（按日期降序排列）
- 文件命名统一为 `{code}.{exchange}.parquet`
- 增量追加逻辑：读取现有文件 → 合并新数据 → 去重 → 写回
- 路径配置集中管理（从 config.py 读取基础目录）

**测试**：
- 用 `tmp_path` fixture 测试读写往返一致性
- 测试增量追加去重
- 测试文件不存在时的行为（读返回空列表，写创建新文件）

**预计工作量**：1 天

---

## Phase 3: Adapter 层（数据源适配）

**目标**：封装外部 API 调用，返回 Pydantic 模型实例

**依赖**：Phase 1

**新增文件**：
- `backend/adapters/__init__.py`
- `backend/adapters/base.py` — 4 个抽象接口（`MarketDataAdapter`, `FinancialDataAdapter`, `BasicDataAdapter`, `EventDataAdapter`）
- `backend/adapters/baostock_adapter.py` — 实现 Market + Basic + Event 接口
- `backend/adapters/akshare_adapter.py` — 实现 Financial 接口
- `backend/adapters/data_source.py` — `DataSource` 注册表 + `create_default_data_source()`

**BaoStock Adapter 要点**：
- `fetch_daily_kline(code, start, end)` — 调用 `query_history_k_data_plus`，映射 18 字段
- `fetch_adjust_factor(code)` — 调用 `query_adjust_factor`
- `fetch_stock_list()` — 调用 `query_stock_basic` + `query_stock_industry`
- `fetch_dividends(code, year)` — 调用 `query_dividend_data`
- 连接管理：login/logout 上下文管理器
- 错误处理：超时重试 + 空数据处理

**AKShare Adapter 要点**：
- `fetch_income(code)` — 调用 `stock_profit_sheet_by_report_em(symbol="SH600000")`
- `fetch_balance(code)` — 调用 `stock_balance_sheet_by_report_em`
- `fetch_cashflow(code)` — 调用 `stock_cash_flow_sheet_by_report_em`
- `fetch_indicator(code)` — 调用 `stock_financial_analysis_indicator_em(symbol="600000.SH")`
- 注意代码格式差异（前三个 API 用 `SH600000`，第四个用 `600000.SH`）

**测试**：
- 全部使用 mock（环境中 API 超时）
- 验证字段映射正确性
- 验证错误处理（超时、空数据、格式异常）

**预计工作量**：2 天

---

## Phase 4: Domain 层（聚合根 + 子域对象）

**目标**：业务逻辑封装，提供高层接口

**依赖**：Phase 1 + Phase 2

**新增文件**：
- `backend/domain/__init__.py`
- `backend/domain/stock.py` — `Stock`, `StockMarket`, `StockFinancial`, `StockEvent`

**StockMarket 方法实现**：
- `get_qfq_kline()` — 使用 adjust_factor 动态计算前复权
- `get_weekly_kline()` / `get_monthly_kline()` — 从日线聚合
- `get_close_on(date)` / `get_qfq_close_on(date)` — 指定日期收盘价
- `is_trade_day(date)` / `is_suspended(date)` / `is_st(date)` — 状态判断

**StockFinancial 方法实现**：
- `get_latest_report()` — 最新报告
- `get_report_on(date)` — 避免未来数据（按公告日期筛选）
- `get_roe_history(n)` / `get_revenue_growth(n)` / `get_net_profit_history(n)` — 财务序列

**StockEvent 方法实现**：
- `get_dividends_in_range(start, end)` — 日期范围分红
- `get_annual_dividend_yield(year, close_price)` — 股息率

**Stock 聚合根**：
- 按需加载：`load_market()`, `load_financial()`, `load_event()`, `load_all()`
- 内部通过 Repository 读取数据

**测试**：
- 复权计算与手算结果对比
- 周月线聚合与 pandas resample 对比
- 财务数据时间点正确性（不引入未来数据）

**预计工作量**：2 天

---

## Phase 5: 数据迁移（含验证）

**目标**：将现有数据迁移到新目录结构，并通过对比验证新数据源正确性

**依赖**：Phase 2 + Phase 3

### Step 5.1: 保留旧数据快照

```
cp -r data/kline/A/raw/ data/_validation/old_raw/
cp -r data/kline/A/qfq/ data/_validation/old_qfq/
```

保留旧数据作为对比基准。

### Step 5.2: 使用新 Adapter 拉取数据

迁移脚本：`scripts/migrate_to_new_structure.py`

1. **BaoStock 日K线**：全量拉取 → `data/market/A/daily/`（18列）
2. **BaoStock 复权因子**：全量拉取 → `data/market/A/adjust_factor/`
3. **BaoStock 股票列表**：拉取 → `data/basic/A/stock_list.parquet`
4. **AKShare 财报**：全量拉取 → `data/financial/A/{income,balance,cashflow,indicator}/`
5. **分红数据**：迁移 `data/dividend/A/` → `data/event/A/dividend/`（结构不变则直接复制）

### Step 5.3: 数据对比验证

验证脚本：`scripts/validate_migration.py`

1. 随机选择 **50 只股票**
2. 对比内容：
   - **日K线**：新 `data/market/A/daily/` 的 date/open/high/low/close/volume/amount 7 字段 vs 旧 `data/_validation/old_raw/` 同字段
   - **前复权**：新 Domain 层动态计算的 qfq 价格 vs 旧 `data/_validation/old_qfq/` 的价格
3. 对比方式：
   - 取两者共同日期范围
   - 浮点数比较容差：`abs(new - old) / old < 0.001`（0.1% 以内视为一致）
   - 输出：每只股票的一致率、不一致的具体行（如有）
4. 判定标准：
   - 50 只股票的 7 字段全部 ≥99.9% 一致率 → **通过**
   - 任何股票低于 99% → **失败**，需排查原因
5. 生成验证报告：`data/_validation/report.json`

### Step 5.4: 清理

验证通过后：
- 删除 `data/_validation/`
- 删除 `data/kline/A/qfq/`（前复权改为动态计算）
- 保留 `data/kline/A/raw/` 作为备份（可选，后续确认无问题再删）

**预计工作量**：3 天（含拉取时间和排错）

---

## Phase 6: 集成现有系统

**目标**：将现有服务切换到新架构，确保 177 个测试通过

**依赖**：Phase 1-5 全部完成且验证通过

### 改动清单

| 文件 | 改动 |
|------|------|
| `config.py` | 新增目录常量：`MARKET_DIR`, `BASIC_DIR`, `FINANCIAL_DIR`, `EVENT_DIR` |
| `services/stock_data.py` | 使用 `MarketRepository` 读取数据，保留 `aggregate_kline()` |
| `services/backtest/engine.py` | 数据加载改用 Repository；复权用 Domain 层 |
| `services/backtest/context.py` | `get_history()` 等方法适配新数据格式（18列 → 选取需要的列） |
| `routers/stock.py` | K线接口路径不变，内部改用 Repository |
| `services/data_updater.py` | 日常更新改用 BaoStockAdapter + MarketRepository |
| `services/qfq_cache.py` | 简化为调用 `StockMarket.get_qfq_kline()`，或直接废弃 |
| `main.py` | lifespan 中初始化 DataSource |

### 兼容性策略

- API 接口签名不变（前端无需改动）
- 回测结果格式不变
- 逐步替换：先切数据读取路径，再切写入路径，最后切更新逻辑
- 每步替换后跑全量测试

### 测试适配

- 更新 fixture 中的数据路径
- Mock 数据格式从 7 列扩展到需要的列
- 新增集成测试：验证 Repository → Domain → Service 数据流

**预计工作量**：3 天

---

## 总预计工作量

| Phase | 工作量 | 累计 |
|-------|--------|------|
| 1. Models | 0.5 天 | 0.5 天 |
| 2. Repository | 1 天 | 1.5 天 |
| 3. Adapter | 2 天 | 3.5 天 |
| 4. Domain | 2 天 | 5.5 天 |
| 5. 数据迁移 + 验证 | 3 天 | 8.5 天 |
| 6. 集成 | 3 天 | 11.5 天 |

## 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| BaoStock 全量拉取耗时长（~5200只×多年数据） | 分批拉取 + 断点续传 + 并发（BaoStock 支持单连接） |
| 新旧数据不一致 | Step 5.3 验证发现问题后排查：可能是数据源差异（AKShare vs BaoStock） |
| 现有测试大面积失败 | Phase 6 逐步替换，每步确认测试通过后再进入下一步 |
| 财报 API 限流 | AKShare 东方财富接口加 sleep 间隔 |
| 环境中 API 超时 | 实际拉取需在网络通畅环境执行，本地开发全部 mock |
