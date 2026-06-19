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

## 🚨 历史教训(HK/US 数据源限制)

1. **EastMoney HK** 单次 ≤ 250 行 / ≤ 12 个月,长历史必须切片。
2. **yfinance 美股全量**(~7400 只)极易触发限速,后台跑必须加 retry + 进度日志。
3. **HK/US 分红字段语义与 A 股不同**,适配层必须显式映射。
4. **新增数据**(分红、估值等)**必须落到 `data/market/{A,HK,US}/<category>/`** 下,按市场分区,统一英文 schema(对齐 EastMoney/YFinance 原始字段)。
5. **DuckDB 是唯一业务数据入口**:新数据访问 API 必须先在 `DuckDBStore` 加方法/视图,**禁止** `glob` parquet 或读旧路径。
6. **A 股 volume 单位 = 股**(不是手)。

## 旧路径状态(已废弃)

`data/{kline,financial,dividend,valuation,indicators}/` 旧路径**完全废弃**,代码层残留已基本清理(2026-06-14):`config.py` 旧常量已移除,`data_cache._load_{valuation,dividend,financial}` 已走 DuckDB。6 个零活引用废弃目录已归入 `data/old/`(~4.2GB,业务代码零引用,可随时 `rm -rf`)。唯一指向旧路径的是 `scripts/migrate_*.py` 等归档/诊断脚本(不在运行链路)。
