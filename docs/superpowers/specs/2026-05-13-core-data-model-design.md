# Core Data Model 设计

> 日期：2026-05-13
> 状态：已确认

## 核心架构原则

**Pydantic Schema 是唯一真相来源（Single Source of Truth）**

```
Pydantic Schema（唯一数据结构定义）
        │
        ├── 写入：Adapter 获取外部数据 → validate → serialize to Parquet
        ├── 读取：Parquet → deserialize → validate → 业务层使用
        └── API：FastAPI 直接复用同一 Schema 返回前端
```

- **Pydantic 类** = Core Data Model 的唯一定义（字段名、类型、是否必填、业务约束）
- **Parquet 文件** = 持久化层（类比数据库表文件，只是存储介质，不承担 schema 约束职责）
- **Adapter（BaoStock/AKShare）** = 数据源适配层（负责将外部数据映射为 Pydantic 模型实例）

代码层面的数据类是唯一的数据结构表示来源，存储结构和内容只是数据类的本地化存储。

## 设计原则

1. **Pydantic Schema 定义一切**：字段名、类型、必填/可选、默认值、校验规则全部在代码中定义
2. **数据源是 Adapter**：数据源只负责填充 core model 中的字段，允许部分字段为空（数据源能力不同）
3. **存储格式统一为 Parquet**：按报表类型分目录，每股一个文件，仅作为持久化介质
4. **日期格式**：统一 `YYYY-MM-DD` 字符串
5. **排序**：时间倒序（最新在前）
6. **文件命名**：`{code}.{exchange}.parquet`（如 `600000.SH.parquet`、`000001.SZ.parquet`）

## 当前数据源选择

| 数据类别 | 数据源 | 理由 |
|----------|--------|------|
| 日K线（含估值） | BaoStock | 18字段丰富，含PE/PB/换手率，稳定 |
| 复权因子 | BaoStock | 直接提供 foreAdjustFactor |
| 股票基本信息 | BaoStock | 含退市日期/状态/行业 |
| 分红/送转 | BaoStock | 结构化好，字段清晰 |
| 利润表 | AKShare | BaoStock 无原始科目，AKShare 170列完整 |
| 资产负债表 | AKShare | BaoStock 无原始科目，AKShare 221列完整 |
| 现金流量表 | AKShare | BaoStock 无原始科目，AKShare 316列完整 |
| 财务指标 | AKShare | BaoStock 仅~10个指标，AKShare 141列 |

## 目录结构

```
data/
├── market/A/                       # 行情数据层（日级更新）
│   ├── daily/                      # 日K线
│   │   ├── 000001.SZ.parquet
│   │   └── ...                    # ~5500 文件
│   └── adjust_factor/             # 复权因子
│       ├── 000001.SZ.parquet
│       └── ...
│
├── basic/A/                        # 基础数据层（周级更新）
│   └── stock_list.parquet         # 单文件，全市场股票清单
│
├── financial/A/                    # 财务数据层（季度更新）
│   ├── income/                    # 利润表
│   │   ├── 000001.SZ.parquet
│   │   └── ...
│   ├── balance/                   # 资产负债表
│   │   └── ...
│   ├── cashflow/                  # 现金流量表
│   │   └── ...
│   └── indicator/                 # 财务指标
│       └── ...
│
├── event/A/                        # 事件数据层（不规则更新）
│   └── dividend/                  # 分红/送转
│       ├── 000001.SZ.parquet
│       └── ...
│
└── portfolio.db                    # 组合管理（SQLite）
```

## 数据 Schema

### 1. 日K线 (`market/A/daily/`)

来源：BaoStock `query_history_k_data_plus`，adjustflag=3（不复权）

| 列名 | 类型 | 必填 | 说明 |
|------|------|------|------|
| date | str | ✅ | 日期 YYYY-MM-DD |
| code | str | ✅ | 股票代码 sh.600000 |
| open | float64 | ✅ | 开盘价 |
| high | float64 | ✅ | 最高价 |
| low | float64 | ✅ | 最低价 |
| close | float64 | ✅ | 收盘价 |
| preclose | float64 | | 前收盘价 |
| volume | float64 | ✅ | 成交量（股） |
| amount | float64 | ✅ | 成交额（元） |
| adjustflag | str | | 复权标志 |
| turn | float64 | | 换手率（%） |
| tradestatus | str | | 交易状态 1=正常,0=停牌 |
| pctChg | float64 | | 涨跌幅（%） |
| peTTM | float64 | | 滚动市盈率 |
| pbMRQ | float64 | | 市净率 |
| psTTM | float64 | | 滚动市销率 |
| pcfNcfTTM | float64 | | 滚动市现率 |
| isST | str | | 是否ST（0/1） |

- 排序：时间倒序
- 前复权计算：`qfq_price = raw_price × (factor / latest_factor)`

### 2. 复权因子 (`market/A/adjust_factor/`)

来源：BaoStock `query_adjust_factor`

| 列名 | 类型 | 必填 | 说明 |
|------|------|------|------|
| code | str | ✅ | 股票代码 |
| dividOperateDate | str | ✅ | 除权除息日 |
| foreAdjustFactor | float64 | ✅ | 前复权因子 |
| backAdjustFactor | float64 | | 后复权因子 |
| adjustFactor | float64 | | 复权因子（累计） |

- 排序：时间正序
- 每股约 20-30 行

### 3. 股票基本信息 (`basic/A/stock_list.parquet`)

来源：BaoStock `query_stock_basic` + `query_stock_industry`

| 列名 | 类型 | 必填 | 说明 |
|------|------|------|------|
| code | str | ✅ | 股票代码 000001.SZ |
| name | str | ✅ | 股票名称 |
| ipo_date | str | ✅ | 上市日期 YYYY-MM-DD |
| delist_date | str | | 退市日期（空=在市） |
| stock_type | str | | 1=股票,2=指数,3=其他 |
| status | str | ✅ | 1=上市,0=退市 |
| industry | str | | 行业分类 |

- 单文件，全市场 ~5500 行

### 4. 利润表 (`financial/A/income/`)

来源：AKShare `stock_profit_sheet_by_report_em`

170 列完整保留。核心字段包括：

| 核心列名 | 说明 |
|----------|------|
| REPORT_DATE | 报告期 |
| REPORT_TYPE | 报告类型（一季报/中报/三季报/年报） |
| NOTICE_DATE | 公告日期 |
| OPERATE_INCOME | 营业总收入 |
| OPERATE_EXPENSE | 营业总支出 |
| OPERATE_PROFIT | 营业利润 |
| TOTAL_PROFIT | 利润总额 |
| INCOME_TAX | 所得税 |
| NETPROFIT | 净利润 |
| PARENT_NETPROFIT | 归母净利润 |
| DEDUCT_PARENT_NETPROFIT | 扣非归母净利润 |
| BASIC_EPS | 基本每股收益 |

- 每股约 100 行（历史所有报告期）
- 排序：报告期倒序
- 所有 `*_YOY` 后缀列为同比增长率

### 5. 资产负债表 (`financial/A/balance/`)

来源：AKShare `stock_balance_sheet_by_report_em`

221 列完整保留。核心字段包括：

| 核心列名 | 说明 |
|----------|------|
| REPORT_DATE | 报告期 |
| TOTAL_ASSETS | 总资产 |
| TOTAL_LIABILITIES | 总负债 |
| TOTAL_EQUITY | 总权益 |
| TOTAL_PARENT_EQUITY | 归母权益 |
| SHARE_CAPITAL | 股本 |
| CAPITAL_RESERVE | 资本公积 |
| SURPLUS_RESERVE | 盈余公积 |
| UNASSIGN_RPOFIT | 未分配利润 |
| ACCOUNTS_RECE | 应收账款 |
| FIXED_ASSET | 固定资产 |
| INTANGIBLE_ASSET | 无形资产 |
| GOODWILL | 商誉 |

- 每股约 100 行
- 排序：报告期倒序

### 6. 现金流量表 (`financial/A/cashflow/`)

来源：AKShare `stock_cash_flow_sheet_by_report_em`

316 列完整保留。核心字段包括：

| 核心列名 | 说明 |
|----------|------|
| REPORT_DATE | 报告期 |
| TOTAL_OPERATE_INFLOW | 经营活动现金流入 |
| TOTAL_OPERATE_OUTFLOW | 经营活动现金流出 |
| NETCASH_OPERATE | 经营活动净现金流 |
| TOTAL_INVEST_INFLOW | 投资活动现金流入 |
| TOTAL_INVEST_OUTFLOW | 投资活动现金流出 |
| NETCASH_INVEST | 投资活动净现金流 |
| TOTAL_FINANCE_INFLOW | 筹资活动现金流入 |
| TOTAL_FINANCE_OUTFLOW | 筹资活动现金流出 |
| NETCASH_FINANCE | 筹资活动净现金流 |
| CCE_ADD | 现金净增加额 |
| BEGIN_CCE | 期初现金余额 |
| END_CCE | 期末现金余额 |

- 每股约 90 行
- 排序：报告期倒序

### 7. 财务指标 (`financial/A/indicator/`)

来源：AKShare `stock_financial_analysis_indicator_em`

141 列完整保留。核心字段包括：

| 核心列名 | 说明 |
|----------|------|
| REPORT_DATE | 报告期 |
| EPSJB | 基本每股收益 |
| EPSKCJB | 扣非每股收益 |
| BPS | 每股净资产 |
| ROEJQ | 净资产收益率（加权） |
| ZZCJLL | 总资产净利率 |
| XSMLL | 销售毛利率 |
| XSJLL | 销售净利率 |
| ZCFZL | 资产负债率 |
| LD | 流动比率 |
| SD | 速动比率 |
| ZZCZZTS | 总资产周转天数 |
| CHZZTS | 存货周转天数 |
| YSZKZZTS | 应收账款周转天数 |

- 每股约 100 行
- 排序：报告期倒序

### 8. 分红/送转 (`event/A/dividend/`)

来源：BaoStock `query_dividend_data`

| 列名 | 类型 | 必填 | 说明 |
|------|------|------|------|
| code | str | ✅ | 股票代码 |
| dividPreNoticeDate | str | | 预披露日 |
| dividAgmPumDate | str | | 股东大会日 |
| dividPlanAnnounceDate | str | | 预案公告日 |
| dividPlanDate | str | | 分红实施公告日 |
| dividRegistDate | str | | 股权登记日 |
| dividOperateDate | str | ✅ | 除权除息日 |
| dividPayDate | str | | 派息日 |
| dividStockMarketDate | str | | 红股上市日 |
| dividCashPsBeforeTax | float64 | | 每股税前派息（元） |
| dividCashPsAfterTax | str | | 每股税后派息 |
| dividStocksPs | float64 | | 每股送股 |
| dividCashStock | str | | 分红描述 |
| dividReserveToStockPs | float64 | | 每股转增 |

- 每股约 10-30 行
- 排序：时间倒序

## 派生数据（不持久化）

以下数据从 core model 动态计算，不存储为文件：

| 数据 | 计算方式 |
|------|----------|
| 前复权K线 | raw_price × (foreAdjustFactor / latest_factor) |
| 周线/月线 | 从日K线聚合（引擎启动时计算并缓存） |
| 技术指标（MA/MACD/KDJ/BOLL） | 从K线实时计算 |

## 数据更新策略

| 数据 | 频率 | 策略 |
|------|------|------|
| 日K线 | 每交易日 | 增量追加（读取文件最新日期，只取新数据） |
| 复权因子 | 每交易日 | 全量刷新（数据量极小） |
| 股票基本信息 | 每周 | 全量刷新 |
| 财务报表（4张） | 季度报告季（4/7/8/10月） | 检测新报告期，增量追加 |
| 分红/送转 | 年度 | 按年查询，增量追加 |

## 代码架构（三层分离 + DDD）

### 分层结构

```
┌─────────────────────────────────────────────────────────┐
│  Domain Layer (领域模型 — Business Model)                 │
│  backend/domain/                                         │
│  - Stock 聚合根 + 子域对象                                │
│  - 业务方法：复权计算、周月线聚合、财务分析                  │
├─────────────────────────────────────────────────────────┤
│  Data Class Layer (数据定义 — Pydantic Schema)            │
│  backend/models/                                         │
│  - 纯数据结构：字段、类型、校验规则                        │
│  - 无业务逻辑方法                                         │
├─────────────────────────────────────────────────────────┤
│  Storage Layer (持久化 — Repository + Parquet)            │
│  backend/repositories/                                   │
│  - read/write Parquet 文件                               │
│  - 物理约束：列名、类型、nullable                         │
├─────────────────────────────────────────────────────────┤
│  Adapter Layer (数据源适配)                               │
│  backend/adapters/                                        │
│  - 外部 API → Pydantic Schema 映射                       │
└─────────────────────────────────────────────────────────┘
```

### 领域模型设计（方案 C：Stock 聚合根 + 子域对象）

```python
# backend/domain/stock.py

class Stock:
    """股票聚合根 — 统一入口，子域按需加载"""
    code: str                          # 000001.SZ
    basic: Optional[StockBasicInfo]     # 基本信息
    market: Optional[StockMarket]       # 行情子域
    financial: Optional[StockFinancial] # 财务子域
    event: Optional[StockEvent]         # 事件子域

    def load_market(self) -> None: ...
    def load_financial(self) -> None: ...
    def load_event(self) -> None: ...
    def load_all(self) -> None: ...


class StockMarket:
    """行情子域 — 回测引擎主要消费者"""
    code: str
    daily_kline: List[DailyKlineRecord]
    adjust_factor: List[AdjustFactorRecord]

    def get_qfq_kline(self) -> List[DailyKlineRecord]:
        """动态计算前复权K线"""
        ...

    def get_weekly_kline(self) -> List[AggregatedKline]:
        """从日线聚合周线"""
        ...

    def get_monthly_kline(self) -> List[AggregatedKline]:
        """从日线聚合月线"""
        ...

    def get_close_on(self, date: str) -> Optional[float]:
        """获取指定日期收盘价"""
        ...

    def get_qfq_close_on(self, date: str) -> Optional[float]:
        """获取指定日期前复权收盘价"""
        ...

    def get_kline_range(self, start: str, end: str) -> List[DailyKlineRecord]:
        """获取日期范围内的K线"""
        ...

    def is_trade_day(self, date: str) -> bool:
        """判断是否交易日"""
        ...

    def is_suspended(self, date: str) -> bool:
        """判断是否停牌"""
        ...

    def is_st(self, date: str) -> bool:
        """判断是否ST"""
        ...


class StockFinancial:
    """财务子域 — 基本面策略主要消费者"""
    code: str
    income: List[IncomeStatement]
    balance: List[BalanceSheet]
    cashflow: List[CashFlow]
    indicator: List[FinancialIndicator]

    def get_latest_report(self, report_type: str = None) -> Optional[IncomeStatement]:
        """获取最新报告"""
        ...

    def get_report_on(self, date: str) -> Optional[IncomeStatement]:
        """获取指定日期可用的最新报告（按公告日期，避免未来数据）"""
        ...

    def get_roe_history(self, n: int = 20) -> List[float]:
        """获取历史ROE序列"""
        ...

    def get_revenue_growth(self, n: int = 4) -> List[float]:
        """获取营收增长率序列"""
        ...

    def get_net_profit_history(self, n: int = 20) -> List[float]:
        """获取净利润历史"""
        ...


class StockEvent:
    """事件子域 — 分红送转"""
    code: str
    dividends: List[DividendRecord]

    def get_dividend_on(self, date: str) -> Optional[DividendRecord]:
        """获取指定日期的分红事件"""
        ...

    def get_dividends_in_range(self, start: str, end: str) -> List[DividendRecord]:
        """获取日期范围内的所有分红事件"""
        ...

    def get_annual_dividend_yield(self, year: int, close_price: float) -> float:
        """计算指定年度股息率"""
        ...
```

### 数据类层（Pydantic Schema）

```python
# backend/models/market.py
class DailyKlineRecord(BaseModel):
    date: str
    code: str
    open: float
    high: float
    low: float
    close: float
    preclose: Optional[float] = None
    volume: float
    amount: float
    adjustflag: Optional[str] = None
    turn: Optional[float] = None
    tradestatus: Optional[str] = None
    pctChg: Optional[float] = None
    peTTM: Optional[float] = None
    pbMRQ: Optional[float] = None
    psTTM: Optional[float] = None
    pcfNcfTTM: Optional[float] = None
    isST: Optional[str] = None

class AdjustFactorRecord(BaseModel):
    code: str
    dividOperateDate: str
    foreAdjustFactor: float
    backAdjustFactor: Optional[float] = None
    adjustFactor: Optional[float] = None

# backend/models/basic.py
class StockBasicInfo(BaseModel):
    code: str
    name: str
    ipo_date: str
    delist_date: Optional[str] = None
    stock_type: Optional[str] = None
    status: str
    industry: Optional[str] = None

# backend/models/financial.py
class IncomeStatement(BaseModel):
    REPORT_DATE: str
    REPORT_TYPE: Optional[str] = None
    NOTICE_DATE: Optional[str] = None
    OPERATE_INCOME: Optional[float] = None
    NETPROFIT: Optional[float] = None
    PARENT_NETPROFIT: Optional[float] = None
    BASIC_EPS: Optional[float] = None
    # ... 其余 ~160 列均为 Optional[float]

class BalanceSheet(BaseModel):
    REPORT_DATE: str
    REPORT_TYPE: Optional[str] = None
    TOTAL_ASSETS: Optional[float] = None
    TOTAL_LIABILITIES: Optional[float] = None
    TOTAL_EQUITY: Optional[float] = None
    # ... 其余 ~210 列均为 Optional[float]

class CashFlow(BaseModel):
    REPORT_DATE: str
    REPORT_TYPE: Optional[str] = None
    NETCASH_OPERATE: Optional[float] = None
    NETCASH_INVEST: Optional[float] = None
    NETCASH_FINANCE: Optional[float] = None
    # ... 其余 ~300 列均为 Optional[float]

class FinancialIndicator(BaseModel):
    REPORT_DATE: str
    REPORT_TYPE: Optional[str] = None
    EPSJB: Optional[float] = None
    ROEJQ: Optional[float] = None
    XSMLL: Optional[float] = None
    ZCFZL: Optional[float] = None
    # ... 其余 ~130 列均为 Optional[float]

# backend/models/event.py
class DividendRecord(BaseModel):
    code: str
    dividOperateDate: str
    dividCashPsBeforeTax: Optional[float] = None
    dividCashPsAfterTax: Optional[str] = None
    dividStocksPs: Optional[float] = None
    dividReserveToStockPs: Optional[float] = None
    # ... 其余字段
```

### Repository 层

```python
# backend/repositories/market_repo.py
class MarketRepository:
    def read_daily_kline(self, code: str) -> List[DailyKlineRecord]: ...
    def write_daily_kline(self, code: str, records: List[DailyKlineRecord]) -> None: ...
    def read_adjust_factor(self, code: str) -> List[AdjustFactorRecord]: ...
    def write_adjust_factor(self, code: str, records: List[AdjustFactorRecord]) -> None: ...

# backend/repositories/financial_repo.py
class FinancialRepository:
    def read_income(self, code: str) -> List[IncomeStatement]: ...
    def write_income(self, code: str, records: List[IncomeStatement]) -> None: ...
    # balance, cashflow, indicator 同理

# backend/repositories/event_repo.py
class EventRepository:
    def read_dividends(self, code: str) -> List[DividendRecord]: ...
    def write_dividends(self, code: str, records: List[DividendRecord]) -> None: ...
```

### Adapter 层（接口分离 + 组合入口）

**按子域拆分抽象接口**：

```python
# backend/adapters/base.py
from abc import ABC, abstractmethod

class MarketDataAdapter(ABC):
    """行情数据适配器接口"""
    @abstractmethod
    def fetch_daily_kline(self, code: str, start: str, end: str) -> List[DailyKlineRecord]: ...
    @abstractmethod
    def fetch_adjust_factor(self, code: str) -> List[AdjustFactorRecord]: ...

class FinancialDataAdapter(ABC):
    """财务数据适配器接口"""
    @abstractmethod
    def fetch_income(self, code: str) -> List[IncomeStatement]: ...
    @abstractmethod
    def fetch_balance(self, code: str) -> List[BalanceSheet]: ...
    @abstractmethod
    def fetch_cashflow(self, code: str) -> List[CashFlow]: ...
    @abstractmethod
    def fetch_indicator(self, code: str) -> List[FinancialIndicator]: ...

class BasicDataAdapter(ABC):
    """基础数据适配器接口"""
    @abstractmethod
    def fetch_stock_list(self) -> List[StockBasicInfo]: ...

class EventDataAdapter(ABC):
    """事件数据适配器接口"""
    @abstractmethod
    def fetch_dividends(self, code: str, year: str) -> List[DividendRecord]: ...
```

**具体实现 — 一个 Adapter 可实现多个接口**：

```python
# backend/adapters/baostock_adapter.py
class BaoStockAdapter(MarketDataAdapter, BasicDataAdapter, EventDataAdapter):
    def fetch_daily_kline(self, code, start, end) -> List[DailyKlineRecord]: ...
    def fetch_adjust_factor(self, code) -> List[AdjustFactorRecord]: ...
    def fetch_stock_list(self) -> List[StockBasicInfo]: ...
    def fetch_dividends(self, code, year) -> List[DividendRecord]: ...

# backend/adapters/akshare_adapter.py
class AKShareAdapter(FinancialDataAdapter):
    def fetch_income(self, code) -> List[IncomeStatement]: ...
    def fetch_balance(self, code) -> List[BalanceSheet]: ...
    def fetch_cashflow(self, code) -> List[CashFlow]: ...
    def fetch_indicator(self, code) -> List[FinancialIndicator]: ...
```

**组合入口 — DataSource 注册表**：

```python
# backend/adapters/data_source.py
class DataSource:
    """统一数据源入口，内部路由到具体 adapter。可配置切换。"""
    market: MarketDataAdapter
    financial: FinancialDataAdapter
    basic: BasicDataAdapter
    event: EventDataAdapter

# 默认配置
def create_default_data_source() -> DataSource:
    baostock = BaoStockAdapter()
    akshare = AKShareAdapter()
    return DataSource(
        market=baostock,
        financial=akshare,
        basic=baostock,
        event=baostock,
    )
```

**混合数据源场景（预留设计）**：

当同一个接口内部需要由不同 Adapter 实现时（如利润表来自 A 源，现金流来自 B 源），
采用 Composite 代理模式，对外保持接口不变，内部路由到不同实现：

```python
class CompositeFinancialAdapter(FinancialDataAdapter):
    """组合多个数据源实现一个接口 — 需要时再引入"""
    def __init__(self, income_src, balance_src, cashflow_src, indicator_src):
        self._income = income_src
        self._balance = balance_src
        self._cashflow = cashflow_src
        self._indicator = indicator_src

    def fetch_income(self, code): return self._income.fetch_income(code)
    def fetch_balance(self, code): return self._balance.fetch_balance(code)
    def fetch_cashflow(self, code): return self._cashflow.fetch_cashflow(code)
    def fetch_indicator(self, code): return self._indicator.fetch_indicator(code)
```

当前不涉及此场景，后续碰到时按此模式实现。

**切换数据源时**：只需实现对应接口并替换注册：

```python
# 未来切换到 TuShare
class TuShareAdapter(MarketDataAdapter, FinancialDataAdapter, BasicDataAdapter, EventDataAdapter):
    ...

# 全部切换
source = DataSource(
    market=TuShareAdapter(),
    financial=TuShareAdapter(),
    basic=TuShareAdapter(),
    event=TuShareAdapter(),
)

# 或部分切换（K线用TuShare，财务继续用AKShare）
source = DataSource(
    market=TuShareAdapter(),
    financial=AKShareAdapter(),
    basic=TuShareAdapter(),
    event=TuShareAdapter(),
)
```

### 使用示例

```python
# 回测引擎中
stock = Stock("600000.SH")
stock.load_market()  # 只加载行情数据
qfq = stock.market.get_qfq_kline()
weekly = stock.market.get_weekly_kline()

# 基本面选股策略中
stock.load_financial()  # 按需追加加载
if stock.financial.get_roe_history(4)[-1] > 0.15:
    selected.append(stock.code)

# 数据更新服务中
adapter = BaoStockAdapter()
records = adapter.fetch_daily_kline("600000.SH", "2026-05-01", "2026-05-13")
repo = MarketRepository()
repo.write_daily_kline("600000.SH", records)
```

## 迁移计划（从旧结构）

| 旧路径 | 处理 |
|--------|------|
| `data/kline/A/raw/` | → 迁移到 `data/market/A/daily/`（字段扩展为18列） |
| `data/kline/A/qfq/` | → 删除（改为动态计算） |
| `data/valuation/A/` | → 删除（估值已在K线18字段中） |
| `data/financial/A/`（旧16列版） | → 替换为新4表结构 |
| `data/dividend/A/`（旧19列中文版） | → 迁移到 `data/event/A/dividend/` |
| `data/indicators/A/` | → 删除（改为动态计算） |
| `data/meta/` | → 合并到 `data/basic/A/` |
