"""问股期 1 — Task 20:DataPackBuilder 骨架测试。"""

from unittest.mock import MagicMock, patch

from services.agent.pipeline.phase1_data_pack.builder import DataPackBuilder
from services.agent.pipeline.phase1_data_pack.sections import s14_rf
from services.agent.symbol import StockRef


def test_builder_produces_file_with_placeholders(tmp_path):
    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    store = MagicMock()
    builder = DataPackBuilder(
        store=store,
        stock_index=MagicMock(),
        indicators=MagicMock(),
        include=("s07", "s08", "s10", "s14", "s16"),
    )
    # §14 mock akshare 失败,走常量降级路径,避免测试触网
    with patch.object(s14_rf, "_fetch_china_10y_yield", return_value=None):
        out = builder.build(ref, tmp_path)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "## §7" in text and "Phase 2" in text
    assert "## §8" in text and "WebSearch" in text
    assert "## §10" in text
    assert "## §14 无风险利率" in text and "2.70" in text
    assert "## §16" in text
    assert "比亚迪" in text and "002594.SZ" in text


def test_unknown_section_keys_skipped(tmp_path):
    ref = StockRef(code="AAPL", name="Apple", market="US")
    builder = DataPackBuilder(
        store=MagicMock(),
        stock_index=MagicMock(),
        indicators=MagicMock(),
        include=("s07", "s14", "s99_nonexistent"),
    )
    out = builder.build(ref, tmp_path)
    text = out.read_text(encoding="utf-8")
    assert "§7" in text and "§14" in text
    assert "s99" not in text


def test_include_order_respected(tmp_path):
    ref = StockRef(code="600519.SH", name="贵州茅台", market="A")
    builder = DataPackBuilder(
        store=MagicMock(),
        stock_index=MagicMock(),
        indicators=MagicMock(),
        include=("s14", "s07"),
    )
    out = builder.build(ref, tmp_path)
    text = out.read_text(encoding="utf-8")
    i14 = text.index("§14")
    i07 = text.index("§7")
    assert i14 < i07


def test_full_pipeline_a_share_002594(tmp_path):
    """Task 26 端到端:全 19 sections 都渲染 + 关键内容存在。"""
    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    store = MagicMock()

    def _kline(code, **kw):
        if "limit" in kw:
            return [
                {
                    "date": "2026-05-22",
                    "close": 268.5,
                    "open": 265,
                    "high": 270,
                    "low": 264,
                    "volume": 1.2e8,
                    "amount": 3.2e10,
                }
            ]
        return [
            {
                "date": f"2026-{m:02d}-01",
                "close": 250 + m,
                "high": 260 + m,
                "low": 240 + m,
                "volume": 1e6,
            }
            for m in range(1, 5)
        ]

    store.query_qfq_kline.side_effect = _kline
    store.query_circulating_shares.return_value = 2.91e9
    store.query_financial.side_effect = lambda code, table, years: {
        "income": [
            {
                "REPORT_DATE": "2025-12-31",
                "TOTAL_OPERATE_INCOME": 7.7e11,
                "OPERATE_COST": 6.2e11,
                "GROSS_PROFIT": 1.5e11,
                "OPERATE_PROFIT": 3.0e10,
                "NETPROFIT": 3.5e10,
                "PARENT_NETPROFIT": 3.4e10,
                "DEDUCT_PARENT_NETPROFIT": 3.0e10,
                "BASIC_EPS": 11.7,
            }
        ],
        "income_parent": [
            {
                "REPORT_DATE": "2025-12-31",
                "TOTAL_OPERATE_INCOME": 1e10,
                "NETPROFIT": 2e9,
                "PARENT_NETPROFIT": 2e9,
            }
        ],
        "balance": [
            {
                "REPORT_DATE": "2025-12-31",
                "TOTAL_ASSETS": 8e11,
                "TOTAL_LIABILITIES": 5.5e11,
                "TOTAL_EQUITY": 2.5e11,
                "DEBT_ASSET_RATIO": 68.7,
                "GOODWILL": 5e9,
                "BPS": 85.5,
            }
        ],
        "balance_parent": [
            {
                "REPORT_DATE": "2025-12-31",
                "TOTAL_ASSETS": 1e11,
                "TOTAL_EQUITY": 3e10,
            }
        ],
        "cashflow": [
            {
                "REPORT_DATE": "2025-12-31",
                "NETCASH_OPERATE": 8e10,
                "NETCASH_INVEST": -7e10,
                "NETCASH_FINANCE": -1e10,
                "END_CASH": 7e10,
                "DEPRECIATION_FA": 3e10,
                "CONSTRUCT_LONG_ASSET": 5e10,
            }
        ],
        "indicator": [
            {
                "REPORT_DATE": "2025-12-31",
                "ROEJQ": 15.3,
                "ROAJQ": 7.5,
                "GROSSPROFIT_MARGIN": 19.5,
                "NETPROFIT_MARGIN": 4.5,
                "DEBT_ASSET_RATIO": 68.7,
                "CURRENT_RATIO": 1.05,
            }
        ],
    }.get(table, [])
    store.query_dividend_bulk.return_value = [
        {"year": "2025", "dps": 2.05},
        {"year": "2024", "dps": 1.10},
    ]
    store.query_industry_valuation_summary.return_value = {
        "industry": "汽车整车",
        "pe_median": 25.3,
        "pb_median": 3.1,
        "sample_size": 42,
    }
    store.query_business_segments.return_value = [
        {"segment": "汽车", "revenue_pct": 78.5, "gross_margin": 21.0}
    ]

    indicators = MagicMock()
    indicators.get_indicator_snapshot.return_value = {
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

    si = MagicMock()
    si.get_industry.return_value = "汽车整车"

    builder = DataPackBuilder(store=store, stock_index=si, indicators=indicators)
    out = builder.build(ref, tmp_path)
    text = out.read_text(encoding="utf-8")

    for sec in [
        "§1",
        "§2",
        "§3",
        "§3P",
        "§4",
        "§4P",
        "§5",
        "§6",
        "§7",
        "§8",
        "§9",
        "§10",
        "§11",
        "§12",
        "§13",
        "§14",
        "§15",
        "§16",
        "§17",
    ]:
        assert sec in text, f"missing {sec}"
    assert len(text) > 1500
