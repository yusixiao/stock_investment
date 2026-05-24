"""问股期 1 — Task 17:Coordinator chitchat 分支与异常路径。"""

from unittest.mock import AsyncMock, MagicMock

from services.agent.coordinator import Coordinator
from services.system_config.llm_client import CompletionResult, LLMError


async def test_chitchat_emits_thinking_then_done():
    sent: list[dict] = []

    async def sse_send(ev):
        sent.append(ev)

    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(
        return_value=CompletionResult(text="你好!", tokens_in=3, tokens_out=2)
    )

    repo = MagicMock()
    repo.get.return_value = {"session_id": "s1", "output_dir": None, "status": "idle"}

    workspace = MagicMock()
    si = MagicMock()
    si.get_name.return_value = None  # 无股票码识别

    coord = Coordinator(
        sse_send=sse_send,
        repo=repo,
        workspace=workspace,
        stock_index=si,
        llm_factory=lambda phase: fake_llm,
    )
    await coord.run(session_id="s1", message="你好", context=None)

    types = [e["type"] for e in sent]
    assert types[0] == "thinking"
    assert types[-1] == "done"
    assert sent[-1]["content"] == "你好!"
    fake_llm.complete.assert_awaited_once()
    repo.append_message.assert_called_once()


async def test_chitchat_llm_error_emits_error_event():
    sent: list[dict] = []

    async def sse_send(ev):
        sent.append(ev)

    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(side_effect=LLMError("HTTP_401", "bad key"))

    repo = MagicMock()
    repo.get.return_value = {"session_id": "s1", "output_dir": None, "status": "idle"}
    si = MagicMock()
    si.get_name.return_value = None

    coord = Coordinator(
        sse_send=sse_send,
        repo=repo,
        workspace=MagicMock(),
        stock_index=si,
        llm_factory=lambda p: fake_llm,
    )
    await coord.run(session_id="s1", message="你好", context=None)
    types = [e["type"] for e in sent]
    assert "error" in types


async def test_chitchat_internal_error_path():
    """非 LLMError 也要进 error 事件而不是 raise。"""
    sent: list[dict] = []

    async def sse_send(ev):
        sent.append(ev)

    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(side_effect=RuntimeError("boom"))

    repo = MagicMock()
    repo.get.return_value = {"session_id": "s1", "output_dir": None, "status": "idle"}
    si = MagicMock()
    si.get_name.return_value = None

    coord = Coordinator(
        sse_send=sse_send,
        repo=repo,
        workspace=MagicMock(),
        stock_index=si,
        llm_factory=lambda p: fake_llm,
    )
    await coord.run(session_id="s1", message="hi", context=None)
    err = [e for e in sent if e["type"] == "error"]
    assert err and err[0]["error"] == "INTERNAL"


async def test_routes_to_full_pipeline_when_stock_detected():
    """识别到股票码时,走 full_pipeline 分支(此处由 NotImplementedError 触发)。"""
    sent: list[dict] = []

    async def sse_send(ev):
        sent.append(ev)

    repo = MagicMock()
    repo.get.return_value = {"session_id": "s1", "output_dir": None, "status": "idle"}
    si = MagicMock()
    si.get_name.return_value = "贵州茅台"  # 股票码 → name 命中,走 full_pipeline

    coord = Coordinator(
        sse_send=sse_send,
        repo=repo,
        workspace=MagicMock(),
        stock_index=si,
        llm_factory=lambda p: MagicMock(),
    )
    # full_pipeline 在 T17 阶段尚未实现,异常会被 INTERNAL 兜底
    await coord.run(session_id="s1", message="600519 怎么样", context=None)
    err = [e for e in sent if e["type"] == "error"]
    assert err and err[0]["error"] == "INTERNAL"
