# AGENTS.md — 市场数据子系统(首页·行情/财务/分红/估值)

> 本文件聚焦**数据采集 + DuckDB 查询层**。跨切面铁律(数据源禁 akshare、DuckDB 唯一入口、`data/market/` 唯一路径、长任务 nohup、沟通语言等)见**根 `AGENTS.md`**,此处只补子系统细节。

## 数据源(多 adapter 架构)

- `BaoStockAdapter` — A 股 K 线/基础
- `EastMoneyAdapter` — 财务/估值/股本默认
- `YFinanceAdapter` — 港股/美股
- `adapters/data_source.py::create_default_data_source()` 统一装配。
- **复权因子审计**:`adapters/adjust_factor_audit.py` 检测复权因子异常,剔除 yfinance 幻灵拆股。

## DuckDB 查询层(`duckdb_store.py`)

- 用 `read_parquet()` 注册视图,**不导入数据**:
  - `v_a_daily / v_hk_daily / v_us_daily`
  - `v_*_adjust_factor`
  - `v_*_{income,balance,cashflow,indicator}`
  - `v_hk_connect_membership`
- **唯一来源 = `data/market/`**:`data/market/{A,HK,US}/{daily,adjust_factor,financial/{income,balance,cashflow,indicator},dividend}/*.parquet`。
- 财务表统一英文 schema(`REPORT_DATE / NETPROFIT / BASIC_EPS / ROEJQ / EPSJB / BPS / ...`)。
- A 股前复权 K 线:`query_qfq_kline` 用 ASOF JOIN(`data/market/A/daily/` + `adjust_factor/`)派生,不存独立 qfq 文件。
- Parquet 7 列(date 字符串、open/high/low/close/volume/amount float64),日期降序。

## updaters(数据更新器)

```
market_data/updaters/
├── market_updater.py       # A/HK/US 多市场并行增量(K线+复权+财务),scheduler 06:00 调
├── financial_sync.py       # 财务 4 表周期同步
├── dividend_market_updater.py / dividend_yf_updater.py  # A 股 / HK·US 分红
├── hk_connect_updater.py   # 港股通成分(周更)→ get_latest_hk_connect_codes()
├── hk_industry_updater.py  # 港股行业分类(yfinance,覆盖偏大盘/龙头)
├── holder_updater.py       # 股东
├── index_updater.py        # 指数(query_index 供回测 HSI regime)
└── circulating_shares.py   # 流通股
```

- 其它:`stock_index.py`(全市场代码索引)、`stock_data.py::aggregate_kline`(W-FRI / M 聚合)、`indicator.py`(指标计算工具)。
- A 股代码索引源 `stock_index` 从 `data/market/A/stock_list.parquet` 读(`A_INDEX_DIR = MARKET_DIR/"A"`,与 HK/US 的 `data/market/<mkt>/stock_list.*` 对齐)。

## 🚨 批量写入 / 数据完整性铁律

- **批量写入改动铁律**:凡新增/修改任何批量数据更新或 parquet 写入逻辑(updater、repo 写方法、字段映射、dedup/merge、`model_dump` 参数等),**全量跑前必须做「改动前后抽样对比」**——**定向 + 分层**取样(优先覆盖改动直接影响的字段/报表类型,再跨 A/HK/US、含 `extra` 携带字段如 `INDUSTRY_NAME` 各取若干,合计 ≥100 条;纯随机抽样有盲区易全抽到正常数据,故必须定向+分层),核查三类**销毁信号**:①已有非空字段被写成 null ②整列消失 ③行数骤减,并抽验若干值是否合理;有任一非预期破坏即**停下排查、禁止全量跑**。改数据写入代码的往往是 AI,本条 AI 是首要约束对象。
- **与运行时护栏互补(两道防线不可偏废)**:上条是**开发期主动预防**(能查脏值 + 改代码引入的逻辑破坏);运行时护栏 `repositories/base.py::check_write_integrity` 是**被动兜底**(fail-closed,只防"销毁"不防脏值,且不依赖自觉)。各 updater/repo 已按类别 opt-in 传入 `IntegrityPolicy`(ledger:旧非空→null / 列消失 / 行数<50% 即拦并 raise `DataIntegrityError`;recompute:仅结构护栏);`write/append_models_as_parquet` 默认 `integrity=None`(OFF)。违规告警落 `logs/data_integrity.{log,jsonl}` + app.log;`GET /api/health` 近 24h 有违规(拒写或 `force=True` 放行)→ `status=degraded`。**误拦合法大改**时需临时把对应 `IntegrityPolicy.force` 设 True(当前硬编码,未做运行时开关)。
- **07-02 根因(为什么要两道防线)**:`fetch_balance` 某次命中明细报表(不含靠 `extra=allow` 携带的 `INDUSTRY_NAME`),`model_dump(exclude_none=False)` 把缺失字段写成显式 NULL,静默覆盖全历史该列(100%→6%),全程零校验零告警。**若由源漂移触发**(未改代码)→ 抽样纪律不生效,靠护栏兜;**若由改写入逻辑触发** → 靠抽样纪律在全量前拦下。

## 🚨 历史教训(HK/US 数据源限制)

1. **EastMoney HK** 单次 ≤ 250 行 / ≤ 12 个月,长历史必须切片。
2. **yfinance 美股全量**(~7400 只)极易触发限速,后台跑必须加 retry + 进度日志。
3. **HK/US 分红字段语义与 A 股不同**,适配层必须显式映射。
4. **新增数据**(分红、估值等)**必须落到 `data/market/{A,HK,US}/<category>/`** 下,按市场分区,统一英文 schema(对齐 EastMoney/YFinance 原始字段)。
5. **DuckDB 是唯一业务数据入口**:新数据访问 API 必须先在 `DuckDBStore` 加方法/视图,**禁止** `glob` parquet 或读旧路径。
6. **A 股 volume 单位 = 股**(不是手)。

## 旧路径状态(已废弃)

`data/{kline,financial,dividend,valuation,indicators}/` 旧路径**完全废弃**,代码层残留已基本清理(2026-06-14):`config.py` 旧常量已移除,`data_cache._load_{valuation,dividend,financial}` 已走 DuckDB。6 个零活引用废弃目录已归入 `data/old/`(~4.2GB,业务代码零引用,可随时 `rm -rf`)。唯一指向旧路径的是 `scripts/migrate_*.py` 等归档/诊断脚本(不在运行链路)。
