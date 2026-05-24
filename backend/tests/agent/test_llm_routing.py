"""问股期 1 — Task 16:phase → channel 名称解析。"""

import pytest

from services.agent.llm_routing import RoutingError, resolve_channel_name


def test_phase_specific_route():
    kv = {"LLM_DEFAULT_CHANNEL": "DEEPSEEK", "LLM_ROUTE_PHASE3_QUANT": "SONNET"}
    assert resolve_channel_name(kv, "phase3_quantitative") == "SONNET"


def test_falls_back_to_default():
    kv = {"LLM_DEFAULT_CHANNEL": "DEEPSEEK"}
    assert resolve_channel_name(kv, "chitchat") == "DEEPSEEK"


def test_no_default_raises():
    with pytest.raises(RoutingError):
        resolve_channel_name({}, "chitchat")


def test_unknown_phase_falls_back_to_default():
    kv = {"LLM_DEFAULT_CHANNEL": "D"}
    assert resolve_channel_name(kv, "totally_unknown_phase") == "D"


def test_known_phases_have_route_keys():
    kv = {
        "LLM_DEFAULT_CHANNEL": "D",
        "LLM_ROUTE_PHASE3_QUANT": "S",
        "LLM_ROUTE_PHASE3_VALUATION": "S",
        "LLM_ROUTE_QA_FOLLOWUP": "D",
        "LLM_ROUTE_CHITCHAT": "D",
    }
    for ph in [
        "phase3_quantitative",
        "phase3_valuation",
        "qa_followup",
        "chitchat",
    ]:
        assert resolve_channel_name(kv, ph) in {"S", "D"}
