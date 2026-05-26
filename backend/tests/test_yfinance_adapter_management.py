"""§7 D4 — YFinanceAdapter.fetch_company_management 测试(HK / US 路径)。

emweb F10 不支持 HK/US,故由 yfinance 兜底:
- Ticker.info["companyOfficers"] 给核心高管(name / title / age / yearBorn / totalPay)
- Ticker.insider_transactions 给内部人交易(Insider / Position / Transaction / Shares / Value / Start Date)

测试覆盖:
1. 正常 path:officers + insider_transactions 都解析成模型
2. age 兜底:age 缺时由 fiscalYear - yearBorn 推算
3. Transaction 文本 → 增/减方向判定
4. 无法识别的 Transaction 文本被跳过
5. info 抛异常 / insider_transactions 为空 / 全 None 优雅降级
"""

from __future__ import annotations

from unittest.mock import patch, PropertyMock

import pandas as pd

from backend.adapters.yfinance_adapter import YFinanceAdapter
from backend.models.management import ExecutiveRecord, ExecutiveHoldChangeRecord


def _make_ticker(officers, insider_df):
    """构造一个伪 Ticker 对象,绕过 yfinance.Ticker 实例化。"""

    class FakeTicker:
        def __init__(self, *a, **kw):
            pass

        @property
        def info(self):
            return {"companyOfficers": officers}

        @property
        def insider_transactions(self):
            return insider_df

    return FakeTicker


def test_officers_and_insider_normal():
    officers = [
        {
            "name": "Tim Cook",
            "title": "CEO",
            "age": 64,
            "totalPay": 16200000,
        },
        {
            "name": "Luca Maestri",
            "title": "CFO",
            "yearBorn": 1963,  # 用 fiscalYear-yearBorn 推算 age
            "fiscalYear": 2024,
            "totalPay": 27000000,
        },
    ]
    insider_df = pd.DataFrame(
        [
            {
                "Insider": "COOK TIMOTHY D",
                "Position": "Chief Executive Officer",
                "Transaction": "Sale at price 220.00",
                "Shares": 200000,
                "Value": 44000000,
                "Start Date": "2024-04-01",
                "Ownership": "Direct",
            },
            {
                "Insider": "MAESTRI LUCA",
                "Position": "CFO",
                "Transaction": "Stock Purchase",
                "Shares": 5000,
                "Value": 1000000,
                "Start Date": "2024-05-15",
                "Ownership": "Direct",
            },
        ]
    )

    FakeTicker = _make_ticker(officers, insider_df)
    with patch("backend.adapters.yfinance_adapter.yf.Ticker", FakeTicker):
        execs, changes = YFinanceAdapter().fetch_company_management("AAPL")

    assert len(execs) == 2
    assert execs[0].name == "Tim Cook"
    assert execs[0].position == "CEO"
    assert execs[0].age == 64
    assert execs[0].source == "yfinance"
    # age 兜底
    luca = execs[1]
    assert luca.age == 2024 - 1963

    assert len(changes) == 2
    # 排序按日期降序
    assert changes[0].end_date == "2024-05-15"
    assert changes[0].change_num == 5000  # Purchase → 正
    assert changes[0].average_price == 200.0
    assert changes[1].change_num == -200000  # Sale → 负
    assert isinstance(changes[1], ExecutiveHoldChangeRecord)


def test_unknown_transaction_skipped():
    """无方向关键字的 Transaction 行被跳过。"""
    insider_df = pd.DataFrame(
        [
            {
                "Insider": "Alice",
                "Position": "Director",
                "Transaction": "Statement of Ownership",  # 既非 buy 也非 sell
                "Shares": 1000,
                "Value": 100000,
                "Start Date": "2024-03-01",
                "Ownership": "Direct",
            },
            {
                "Insider": "Bob",
                "Position": "Director",
                "Transaction": "Sale at price 100.00",
                "Shares": 500,
                "Value": 50000,
                "Start Date": "2024-03-15",
                "Ownership": "Direct",
            },
        ]
    )
    FakeTicker = _make_ticker([], insider_df)
    with patch("backend.adapters.yfinance_adapter.yf.Ticker", FakeTicker):
        _, changes = YFinanceAdapter().fetch_company_management("AAPL")

    assert len(changes) == 1
    assert changes[0].executive_name == "Bob"


def test_info_exception_returns_empty_executives():
    """Ticker.info 抛异常时,executives 为空,但不影响 insider 处理。"""

    class FakeTicker:
        def __init__(self, *a, **kw):
            pass

        @property
        def info(self):
            raise RuntimeError("rate limit")

        @property
        def insider_transactions(self):
            return pd.DataFrame()

    with patch("backend.adapters.yfinance_adapter.yf.Ticker", FakeTicker):
        execs, changes = YFinanceAdapter().fetch_company_management("AAPL")

    assert execs == []
    assert changes == []


def test_empty_insider_transactions():
    FakeTicker = _make_ticker([{"name": "X", "title": "CEO", "age": 50}], None)
    with patch("backend.adapters.yfinance_adapter.yf.Ticker", FakeTicker):
        execs, changes = YFinanceAdapter().fetch_company_management("0700.HK")

    assert len(execs) == 1
    assert changes == []


def test_ticker_init_failure_graceful():
    def boom(*a, **kw):
        raise RuntimeError("dns fail")

    with patch("backend.adapters.yfinance_adapter.yf.Ticker", boom):
        execs, changes = YFinanceAdapter().fetch_company_management("AAPL")

    assert execs == []
    assert changes == []


def test_officers_empty_name_skipped():
    officers = [
        {"name": "", "title": "Ghost"},
        {"name": "Real Person", "title": "CEO", "age": 50},
    ]
    FakeTicker = _make_ticker(officers, pd.DataFrame())
    with patch("backend.adapters.yfinance_adapter.yf.Ticker", FakeTicker):
        execs, _ = YFinanceAdapter().fetch_company_management("AAPL")

    assert len(execs) == 1
    assert execs[0].name == "Real Person"
    assert isinstance(execs[0], ExecutiveRecord)
