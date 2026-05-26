"""§7 D4 — EastMoneyAdapter.fetch_company_management 测试。

emweb F10 PageAjax 路径(2026-05-26 spike 验证):
- URL  https://emweb.eastmoney.com/PC_HSF10/CompanyManagement/PageAjax
- query: code=SH600519 / SZ002594(市场前缀大写 + 6 位代码)
- 返 {gglb: 高管列表, cgbd: 持股变动}

测试覆盖:
1. 真实 fixture(notes/em_mgmt_raw_600519_emweb_CompanyManagement.json)解析
2. URL / 市场前缀拼接正确(SH/SZ)
3. 非 A 股代码(00700.HK / AAPL.US)直接返回空,不发请求
4. 网络异常 / JSON 异常优雅降级
5. 字段缺失行被跳过,合法行入模型
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from backend.adapters.eastmoney_adapter import EastMoneyAdapter
from backend.models.management import ExecutiveRecord, ExecutiveHoldChangeRecord


FIXTURE = (
    Path(__file__).resolve().parent.parent.parent
    / "notes"
    / "em_mgmt_raw_600519_emweb_CompanyManagement.json"
)


def _fake_resp(payload: dict, status: int = 200):
    class R:
        status_code = status

        def raise_for_status(self):
            if status >= 400:
                raise RuntimeError(f"HTTP {status}")

        def json(self):
            return payload

    return R()


def test_real_fixture_maotai_parses():
    """600519.SH 真实 fixture:11 高管 + 2 持股变动。"""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    captured: dict = {}

    def fake_get(url, params, timeout):
        captured["url"] = url
        captured["params"] = params
        return _fake_resp(payload)

    with patch("backend.adapters.eastmoney_adapter.requests.get", fake_get):
        execs, changes = EastMoneyAdapter().fetch_company_management("600519.SH")

    assert captured["url"].endswith("/CompanyManagement/PageAjax")
    assert captured["params"] == {"code": "SH600519"}

    assert len(execs) == 11
    chairman = next(e for e in execs if "董事长" in (e.position or ""))
    assert chairman.name == "陈华"
    assert chairman.age == 54
    assert chairman.education == "硕士"
    assert chairman.tenure_text and "至今" in chairman.tenure_text
    assert chairman.source == "eastmoney"

    assert len(changes) == 2
    first = changes[0]
    assert isinstance(first, ExecutiveHoldChangeRecord)
    assert first.executive_name == "万波"
    assert first.change_num == -700  # 减持
    assert first.average_price == 725.92
    assert first.end_date == "2018-09-26"
    assert first.source == "eastmoney"


def test_market_prefix_sz():
    captured: dict = {}

    def fake_get(url, params, timeout):
        captured["params"] = params
        return _fake_resp({"gglb": [], "cgbd": []})

    with patch("backend.adapters.eastmoney_adapter.requests.get", fake_get):
        EastMoneyAdapter().fetch_company_management("002594.SZ")

    assert captured["params"]["code"] == "SZ002594"


def test_non_a_share_skipped_without_http():
    """HK / US 代码直接返空,不发请求(emweb 不支持)。"""
    called = {"count": 0}

    def fake_get(*a, **kw):
        called["count"] += 1
        return _fake_resp({})

    with patch("backend.adapters.eastmoney_adapter.requests.get", fake_get):
        execs, changes = EastMoneyAdapter().fetch_company_management("00700.HK")
        assert execs == [] and changes == []
        execs, changes = EastMoneyAdapter().fetch_company_management("AAPL.US")
        assert execs == [] and changes == []
        execs, changes = EastMoneyAdapter().fetch_company_management("AAPL")  # 无后缀
        assert execs == [] and changes == []
    assert called["count"] == 0


def test_network_failure_graceful():
    def boom(*a, **kw):
        raise RuntimeError("network down")

    with patch("backend.adapters.eastmoney_adapter.requests.get", boom):
        execs, changes = EastMoneyAdapter().fetch_company_management("600519.SH")
    assert execs == [] and changes == []


def test_malformed_rows_skipped():
    """缺 PERSON_NAME / END_DATE / CHANGE_NUM 的行被跳过。"""
    payload = {
        "gglb": [
            {"PERSON_NAME": "", "POSITION": "X"},  # 空名字 → 跳
            {"PERSON_NAME": "张三", "POSITION": "总经理", "AGE": "45"},
        ],
        "cgbd": [
            {"END_DATE": "", "EXECUTIVE_NAME": "李四", "CHANGE_NUM": 100},  # 空日期
            {
                "END_DATE": "2024-05-01 00:00:00",
                "EXECUTIVE_NAME": "李四",
                "CHANGE_NUM": None,  # 无变动数
            },
            {
                "END_DATE": "2024-06-01 00:00:00",
                "EXECUTIVE_NAME": "王五",
                "CHANGE_NUM": 5000,
                "AVERAGE_PRICE": 12.3,
                "TRADE_WAY": "二级市场买卖",
            },
        ],
    }

    with patch(
        "backend.adapters.eastmoney_adapter.requests.get",
        lambda *a, **kw: _fake_resp(payload),
    ):
        execs, changes = EastMoneyAdapter().fetch_company_management("600519.SH")

    assert len(execs) == 1
    assert execs[0].name == "张三"
    assert execs[0].age == 45
    assert isinstance(execs[0], ExecutiveRecord)

    assert len(changes) == 1
    assert changes[0].executive_name == "王五"
    assert changes[0].change_num == 5000
    assert changes[0].average_price == 12.3
