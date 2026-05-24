"""问股期 1 — Task 25:§17 衍生指标测试。"""

from unittest.mock import MagicMock

from services.agent.agents.cpa.pipeline.phase1_data_pack.sections import s17_derived
from services.agent.core.symbol import StockRef


# ============================================================
# §17 头部:旧 indicators 接口(向后兼容)
# ============================================================


def _stub_store_empty():
    """store 返回全空,§17.8 全 — ,但不崩溃。"""
    s = MagicMock()
    s.query_qfq_kline_for_section.return_value = []
    s.query_total_shares_for_section.return_value = None
    s.query_financial_for_section.return_value = []
    return s


def test_section_17_macd_ma():
    ind = MagicMock()
    ind.get_indicator_snapshot.return_value = {
        "MA5": 268.0,
        "MA10": 265.0,
        "MA20": 260.5,
        "MA60": 255.0,
        "MACD_DIF": 0.5,
        "MACD_DEA": 0.2,
        "MACD_BAR": 0.6,
        "PE_PCT_5Y": 0.42,
        "PB_PCT_5Y": 0.38,
    }
    out = s17_derived.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=_stub_store_empty(),
        stock_index=MagicMock(),
        indicators=ind,
    )
    assert "## §17 衍生指标" in out
    assert "MA5" in out and "268.00" in out
    assert "MACD" in out
    assert "PE 历史分位" in out and "42" in out


def test_section_17_no_snapshot_no_crash():
    ind = MagicMock()
    ind.get_indicator_snapshot.return_value = None
    out = s17_derived.build(
        StockRef("X", "x", "A"),
        store=_stub_store_empty(),
        stock_index=MagicMock(),
        indicators=ind,
    )
    assert "## §17 衍生指标" in out
    assert "—" in out


def test_section_17_indicators_lacks_method():
    class _NoIndicators:
        pass

    out = s17_derived.build(
        StockRef("X", "x", "A"),
        store=_stub_store_empty(),
        stock_index=MagicMock(),
        indicators=_NoIndicators(),
    )
    assert "## §17 衍生指标" in out


# ============================================================
# §17.8 绝对估值预计算
# ============================================================


def _make_store_full():
    """构造完整的 BYD 仿真数据(数量级真实)。"""
    s = MagicMock()
    # 最新收盘价 280
    s.query_qfq_kline_for_section.return_value = [{"close": 280.0}]
    # 总股本 91 亿股
    s.query_total_shares_for_section.return_value = 9_117_197_565

    def _fin(code, table, years=1):
        if table == "income":
            return [
                {
                    "REPORT_DATE": "2024-12-31",
                    "PARENT_NETPROFIT": 40_000_000_000,  # 400 亿
                    "NETPROFIT": 40_000_000_000,
                    "OPERATE_PROFIT": 50_000_000_000,  # 500 亿
                }
            ]
        if table == "balance":
            return [
                {
                    "REPORT_DATE": "2024-12-31",
                    "MONETARY_FUND": 100_000_000_000,  # 1000 亿现金
                    "TOTAL_LIABILITIES": 400_000_000_000,  # 4000 亿
                    "TOTAL_EQUITY": 200_000_000_000,  # 2000 亿
                }
            ]
        if table == "cashflow":
            return [
                {
                    "REPORT_DATE": "2024-12-31",
                    "NETCASH_OPERATE": 150_000_000_000,  # 1500 亿
                    "CONSTRUCT_LONG_ASSET": 90_000_000_000,  # 900 亿 capex
                }
            ]
        return []

    s.query_financial_for_section.side_effect = _fin
    return s


def test_section_17_8_full_data_renders_metrics():
    out = s17_derived.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=_make_store_full(),
        stock_index=MagicMock(),
        indicators=MagicMock(get_indicator_snapshot=lambda c: None),
    )
    assert "§17.8 绝对估值预计算" in out
    # 总市值 = 280 × 91.17 亿 = 25,528 亿
    assert "总市值" in out
    # 扣除现金 PE = (25528亿 - 1000亿) / 400亿 = 61.32x
    assert "扣除现金 PE" in out
    assert "61.32x" in out
    # FCF Yield = (1500-900) / 25528 = 2.35%
    assert "FCF Yield" in out
    assert "2.35%" in out
    # 净负债权益比 = (4000-1000) / 2000 = 150%
    assert "净负债权益比" in out
    assert "Net Debt / Equity" in out
    assert "不是" in out  # 显式提示不是 EBITDA
    assert "150.00%" in out
    # EV / EBIT = (25528 + 4000 - 1000) / 500 = 57.06x
    assert "EV / EBIT" in out
    assert "EBITDA 代理值" in out
    assert "57.06x" in out


def test_section_17_8_missing_price_degrades():
    s = _make_store_full()
    s.query_qfq_kline_for_section.return_value = []
    out = s17_derived.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(get_indicator_snapshot=lambda c: None),
    )
    # 没价格 → 总市值 — , 扣现金 PE / FCF Yield / EV/EBIT 全 —
    assert "§17.8" in out
    assert "总市值:—" in out
    assert "扣除现金 PE(Cash-Adjusted PE):—x" in out


def test_section_17_8_missing_total_share_degrades():
    s = _make_store_full()
    s.query_total_shares_for_section.return_value = None
    out = s17_derived.build(
        StockRef("X.SZ", "x", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(get_indicator_snapshot=lambda c: None),
    )
    assert "总市值:—" in out


def test_section_17_8_store_exception_safe():
    s = MagicMock()
    s.query_qfq_kline_for_section.side_effect = RuntimeError("boom")
    s.query_total_shares_for_section.side_effect = RuntimeError("boom")
    s.query_financial_for_section.side_effect = RuntimeError("boom")
    out = s17_derived.build(
        StockRef("X.SZ", "x", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(get_indicator_snapshot=lambda c: None),
    )
    assert "§17.8" in out
    assert "## §17 衍生指标" in out


def test_section_17_8_no_store_param():
    out = s17_derived.build(
        StockRef("X.SZ", "x", "A"),
        store=None,
        stock_index=MagicMock(),
        indicators=MagicMock(get_indicator_snapshot=lambda c: None),
    )
    assert "store 不可用" in out


def test_section_17_8_zero_netprofit_safe_div():
    s = _make_store_full()

    def _fin(code, table, years=1):
        if table == "income":
            return [
                {
                    "REPORT_DATE": "2024-12-31",
                    "PARENT_NETPROFIT": 0,  # 零利润
                    "OPERATE_PROFIT": 0,
                }
            ]
        if table == "balance":
            return [
                {
                    "REPORT_DATE": "2024-12-31",
                    "MONETARY_FUND": 100,
                    "TOTAL_LIABILITIES": 400,
                    "TOTAL_EQUITY": 200,
                }
            ]
        if table == "cashflow":
            return [
                {
                    "REPORT_DATE": "2024-12-31",
                    "NETCASH_OPERATE": 100,
                    "CONSTRUCT_LONG_ASSET": 50,
                }
            ]
        return []

    s.query_financial_for_section.side_effect = _fin
    out = s17_derived.build(
        StockRef("X.SZ", "x", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(get_indicator_snapshot=lambda c: None),
    )
    # 0 分母不应崩,降级到 —
    assert "扣除现金 PE(Cash-Adjusted PE):—x" in out
    assert "EV / EBIT" in out and "—x" in out
