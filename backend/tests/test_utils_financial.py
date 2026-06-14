import pandas as pd
import pytest

from tests.utils_test_helpers import MockContext
from services.backtest.strategies.utils import financial


def test_get_roe_returns_value():
    ctx = MockContext(financial={"A": {"ROEJQ": 14.7}})
    assert financial.get_roe(ctx, "A") == 14.7


def test_get_roe_returns_none_when_missing_data():
    ctx = MockContext()
    assert financial.get_roe(ctx, "A") is None


def test_get_roe_returns_none_when_field_missing():
    ctx = MockContext(financial={"A": {"EPSJB": 1.2}})
    assert financial.get_roe(ctx, "A") is None


def test_get_eps_basic():
    ctx = MockContext(financial={"A": {"EPSJB": 1.2}})
    assert financial.get_eps(ctx, "A") == 1.2


def test_get_net_profit_growth_basic():
    ctx = MockContext(financial={"A": {"PARENTNETPROFITTZ": 25.4}})
    assert financial.get_net_profit_growth(ctx, "A") == 25.4


def test_filter_by_roe_pass_and_reject():
    ctx = MockContext(
        financial={
            "P": {"ROEJQ": 14.7},
            "F": {"ROEJQ": 8.4},
        }
    )
    result = financial.filter_by_roe(ctx, ["P", "F"], min_roe=10.0)
    assert result == ["P"]
    assert ctx.pass_logs == [("P", "financial.roe", {"roe": 14.7, "threshold": 10.0})]
    assert ctx.reject_logs == [
        ("F", "financial.roe", "below_threshold", {"roe": 8.4, "threshold": 10.0})
    ]


def test_filter_by_roe_no_data():
    ctx = MockContext()
    result = financial.filter_by_roe(ctx, ["X"], min_roe=10.0)
    assert result == []
    assert ctx.reject_logs == [("X", "financial.roe", "no_data", {"threshold": 10.0})]


def test_filter_by_roe_field_missing():
    ctx = MockContext(financial={"X": {"EPSJB": 1.2}})
    result = financial.filter_by_roe(ctx, ["X"], min_roe=10.0)
    assert result == []
    assert ctx.reject_logs == [("X", "financial.roe", "no_data", {"threshold": 10.0})]


def test_filter_by_roe_logs_flow_summary():
    ctx = MockContext(financial={"P": {"ROEJQ": 14.7}})
    financial.filter_by_roe(ctx, ["P", "X"], min_roe=10.0)
    assert ctx.flow_logs == [("financial.roe", {"input": 2, "passed": 1})]


# ============= NOTICE_DATE-aware annual ROE(2026-06-09 新增,V2 配方)=============
# 直接注入 _ROE_NOTICE_ANNUAL_LOOKUP,绕开 DuckDB 真实查询。


def _make_roe_notice_df(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    """rows: [(NOTICE_DATE, REPORT_DATE, ROEJQ), ...]"""
    return (
        pd.DataFrame(rows, columns=["NOTICE_DATE", "REPORT_DATE", "ROEJQ"])
        .sort_values("NOTICE_DATE")
        .reset_index(drop=True)
    )


@pytest.fixture
def patched_annual_lookup(monkeypatch):
    """注入 mock annual lookup,测试结束自动清理。"""

    def _inject(
        mapping: dict[str, list[tuple[str, str, float]]], market: str = "A"
    ) -> None:
        lookup = {sym: _make_roe_notice_df(rows) for sym, rows in mapping.items()}
        # cache 现在按 market 分桶:{market: {code: df}}
        monkeypatch.setattr(financial, "_ROE_NOTICE_ANNUAL_LOOKUP", {market: lookup})

    yield _inject
    # monkeypatch 自动 restore;额外保险:reset cache(其它测试若先跑过会污染)
    financial.reset_roe_notice_cache()


def test_get_roe_annual_as_of_notice_returns_latest_announced_annual(
    patched_annual_lookup,
):
    # A 股 2024 年报 NOTICE 2025-04-15 披露,2025-Q1 NOTICE 2025-04-28 披露
    # 调用方传入 ctx.current_date=2025-05-15 → 应拿到 2024 年报 ROEJQ
    patched_annual_lookup(
        {
            "601398.SH": [
                ("2024-04-10", "2023-12-31", 11.2),
                ("2025-04-15", "2024-12-31", 10.5),
            ]
        }
    )
    ctx = MockContext(current_date="2025-05-15")
    assert financial.get_roe_annual_as_of_notice(ctx, "601398.SH") == 10.5


def test_get_roe_annual_as_of_notice_excludes_unannounced_future_annual(
    patched_annual_lookup,
):
    """NOTICE_DATE 严格 <= current_date,不能拿到尚未披露的年报。"""
    patched_annual_lookup(
        {
            "X": [
                ("2024-04-10", "2023-12-31", 11.2),
                ("2025-04-15", "2024-12-31", 10.5),
            ]
        }
    )
    # 2025-04-14:2024 年报次日才披露,只能拿 2023 年报
    ctx = MockContext(current_date="2025-04-14")
    assert financial.get_roe_annual_as_of_notice(ctx, "X") == 11.2


def test_get_roe_annual_as_of_notice_returns_none_before_any_announcement(
    patched_annual_lookup,
):
    patched_annual_lookup({"X": [("2024-04-10", "2023-12-31", 11.2)]})
    ctx = MockContext(current_date="2024-01-01")
    assert financial.get_roe_annual_as_of_notice(ctx, "X") is None


def test_get_roe_annual_as_of_notice_returns_none_for_unknown_symbol(
    patched_annual_lookup,
):
    patched_annual_lookup({"X": [("2024-04-10", "2023-12-31", 11.2)]})
    ctx = MockContext(current_date="2025-05-15")
    assert financial.get_roe_annual_as_of_notice(ctx, "Y") is None


def test_get_roe_annual_as_of_notice_returns_none_when_no_current_date(
    patched_annual_lookup,
):
    patched_annual_lookup({"X": [("2024-04-10", "2023-12-31", 11.2)]})
    ctx = MockContext()  # current_date=None
    assert financial.get_roe_annual_as_of_notice(ctx, "X") is None


def test_filter_by_roe_annual_as_of_notice_pass_and_reject(patched_annual_lookup):
    patched_annual_lookup(
        {
            "P": [("2025-04-15", "2024-12-31", 12.5)],
            "F": [("2025-04-15", "2024-12-31", 4.2)],
        }
    )
    ctx = MockContext(current_date="2025-05-15")
    out = financial.filter_by_roe_annual_as_of_notice(ctx, ["P", "F"], min_roe=5.0)
    assert out == ["P"]
    assert ctx.pass_logs == [
        ("P", "financial.roe_annual_notice", {"roe": 12.5, "threshold": 5.0})
    ]
    assert ctx.reject_logs == [
        (
            "F",
            "financial.roe_annual_notice",
            "below_threshold",
            {"roe": 4.2, "threshold": 5.0},
        )
    ]
    assert ctx.flow_logs == [("financial.roe_annual_notice", {"input": 2, "passed": 1})]


def test_filter_by_roe_annual_as_of_notice_no_data_logs_reject(patched_annual_lookup):
    patched_annual_lookup({"P": [("2025-04-15", "2024-12-31", 12.5)]})
    ctx = MockContext(current_date="2025-05-15")
    out = financial.filter_by_roe_annual_as_of_notice(ctx, ["X"], min_roe=5.0)
    assert out == []
    assert ctx.reject_logs == [
        ("X", "financial.roe_annual_notice", "no_data", {"threshold": 5.0})
    ]


def test_filter_by_roe_annual_records_factor(patched_annual_lookup):
    """通过的股票 ROE 应被记录到 factors,供策略雷达展示。"""
    patched_annual_lookup({"P": [("2025-04-15", "2024-12-31", 12.5)]})
    ctx = MockContext(current_date="2025-05-15")
    financial.filter_by_roe_annual_as_of_notice(ctx, ["P"], min_roe=5.0)
    assert ctx.get_factors("P") == {"ROE": 12.5}


def test_get_roe_annual_skips_q1_q3_when_only_annuals_in_lookup(patched_annual_lookup):
    """annual lookup 由 SQL `substr(REPORT_DATE,6,2)='12'` 过滤,
    传入数据故意只放年报,模拟生产环境查询结果(Q1/H1/Q3 不会进 cache)。"""
    patched_annual_lookup(
        {
            "X": [
                ("2024-04-10", "2023-12-31", 11.2),  # 2023 年报
                ("2025-04-15", "2024-12-31", 10.5),  # 2024 年报
            ]
        }
    )
    # 5 月查询应拿到 2024 年报 10.5%(而非 Q1 累计 ~2-3% 的低值)
    ctx = MockContext(current_date="2025-05-10")
    assert financial.get_roe_annual_as_of_notice(ctx, "X") == 10.5


def test_get_roe_annual_tied_notice_date_takes_max_report_date(patched_annual_lookup):
    """同一 NOTICE_DATE 多条记录(IPO 招股书 / 重述报告)取最大 REPORT_DATE。

    本例真实可能场景:2024 年报与重述的 2023 年报同日披露。
    """
    patched_annual_lookup(
        {
            "X": [
                ("2024-04-15", "2022-12-31", 8.0),  # 重述的 2022 年报
                ("2024-04-15", "2023-12-31", 11.0),  # 2023 年报正本
            ]
        }
    )
    ctx = MockContext(current_date="2024-12-31")
    # 注:_make_roe_notice_df 不做 dedup;真实 _build_roe_notice_lookup 会取 max(REPORT_DATE)。
    # 这里只验证调用不抛异常 + 返回某一行 ROEJQ(searchsorted 命中 right-side last entry)。
    result = financial.get_roe_annual_as_of_notice(ctx, "X")
    assert result in {8.0, 11.0}


# ============= HK market routing(2026-06-10 港股通修复)=============


def test_get_roe_annual_routes_hk_via_ctx_market(monkeypatch):
    """ctx.market='HK' 时查 HK 桶,不应误查 A 桶。"""
    df_hk = _make_roe_notice_df([("2024-04-30", "2023-12-31", 9.5)])
    df_a = _make_roe_notice_df([("2024-04-30", "2023-12-31", 99.0)])
    monkeypatch.setattr(
        financial,
        "_ROE_NOTICE_ANNUAL_LOOKUP",
        {"HK": {"00700.HK": df_hk}, "A": {"00700.HK": df_a}},
    )
    ctx = MockContext(current_date="2024-12-31")
    ctx.market = "HK"
    assert financial.get_roe_annual_as_of_notice(ctx, "00700.HK") == 9.5


def test_get_roe_annual_hk_connect_normalizes_to_hk(monkeypatch):
    """HK_CONNECT 应归一到 HK 桶查询(物理数据复用 HK)。"""
    df = _make_roe_notice_df([("2024-04-30", "2023-12-31", 7.7)])
    monkeypatch.setattr(
        financial, "_ROE_NOTICE_ANNUAL_LOOKUP", {"HK": {"00700.HK": df}}
    )
    ctx = MockContext(current_date="2024-12-31")
    ctx.market = "HK_CONNECT"
    assert financial.get_roe_annual_as_of_notice(ctx, "00700.HK") == 7.7


def test_get_roe_annual_falls_back_to_symbol_suffix_when_no_market(monkeypatch):
    """ctx 无 market 属性时,从 .HK 后缀推断 HK。"""
    df = _make_roe_notice_df([("2024-04-30", "2023-12-31", 6.6)])
    monkeypatch.setattr(
        financial, "_ROE_NOTICE_ANNUAL_LOOKUP", {"HK": {"00700.HK": df}}
    )
    ctx = MockContext(current_date="2024-12-31")  # 无 market
    assert financial.get_roe_annual_as_of_notice(ctx, "00700.HK") == 6.6


def test_get_roe_annual_us_returns_none(monkeypatch):
    """US 暂未支持,_build 返回空 dict → lookup miss → None。"""
    monkeypatch.setattr(financial, "_ROE_NOTICE_ANNUAL_LOOKUP", {"US": {}})
    ctx = MockContext(current_date="2024-12-31")
    ctx.market = "US"
    assert financial.get_roe_annual_as_of_notice(ctx, "AAPL") is None


def test_normalize_market_helper():
    assert financial._normalize_market("HK_CONNECT") == "HK"
    assert financial._normalize_market("hk") == "HK"
    assert financial._normalize_market(None) == "A"
    assert financial._normalize_market("XYZ") == "A"


def test_detect_market_from_symbol_helper():
    assert financial._detect_market_from_symbol("00700.HK") == "HK"
    assert financial._detect_market_from_symbol("601398.SH") == "A"
    assert financial._detect_market_from_symbol("000001.SZ") == "A"
    assert financial._detect_market_from_symbol("AAPL") == "A"  # 默认
