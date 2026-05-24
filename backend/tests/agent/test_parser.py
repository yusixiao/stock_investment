"""问股期 1 — Task 28:phase3_quant <results> 块解析器测试。"""

from services.agent.parser import parse_phase3_quant_results

SAMPLE = """
# Phase 3 定量分析报告

## Step 11 最终输出

<results>
owner_earnings_I=4523.5
gross_return_R=12.3
threshold_II=10.5
final_return_GG=11.2
margin_KK=0.7
roic_avg=15.6
payout_ratio_M=35.0
g_capex_coef=0.85
trap_risk=低
extrapolation_confidence=中
</results>
"""


def test_parse_complete_results_block():
    out = parse_phase3_quant_results(SAMPLE)
    assert out["owner_earnings_I"] == 4523.5
    assert out["final_return_GG"] == 11.2
    assert out["trap_risk"] == "低"
    assert out["extrapolation_confidence"] == "中"


def test_parse_missing_block_returns_empty():
    out = parse_phase3_quant_results("# 报告\n\n无 results 块")
    assert out == {}


def test_parse_partial_fields_tolerated():
    text = "<results>\nfinal_return_GG=8.5\nthreshold_II=10.0\n</results>"
    out = parse_phase3_quant_results(text)
    assert out["final_return_GG"] == 8.5
    assert out["threshold_II"] == 10.0
    assert "owner_earnings_I" not in out


def test_parse_handles_pct_suffix():
    text = "<results>\nfinal_return_GG=11.2%\nowner_earnings_I=4,523.5 百万\n</results>"
    out = parse_phase3_quant_results(text)
    assert out["final_return_GG"] == 11.2
    assert out["owner_earnings_I"] == 4523.5
