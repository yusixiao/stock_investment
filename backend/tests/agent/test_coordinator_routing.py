"""问股期 1 — Task 17/19:Coordinator chitchat / qa_followup 分支测试。"""

from unittest.mock import AsyncMock, MagicMock

from services.agent.coordinator import Coordinator
from services.system_config.llm_client import CompletionResult, LLMError


async def test_clarify_when_no_stock_detected_does_not_call_llm():
    """未识别到股票码 → 硬编码澄清提示,不调 LLM,不抛 INTERNAL。

    (取代旧 chitchat LLM 调用路径 — 问股场景下没识别到股票码时
    引导用户提供明确意图,比闲聊 LLM 更稳更省 token,且 LLM 配置缺失也不会挂)
    """
    sent: list[dict] = []

    async def sse_send(ev):
        sent.append(ev)

    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock()  # 不应被调用

    # 显式让 llm_factory 抛错,确认硬编码路径完全不触达 LLM 配置
    def llm_factory_should_not_be_called(phase):
        raise AssertionError(f"clarify 路径不应调 llm_factory(phase={phase})")

    repo = MagicMock()
    repo.get.return_value = {"session_id": "s1", "output_dir": None, "status": "idle"}
    si = MagicMock()
    si.get_name.return_value = None  # 无股票码识别

    coord = Coordinator(
        sse_send=sse_send,
        repo=repo,
        workspace=MagicMock(),
        stock_index=si,
        llm_factory=llm_factory_should_not_be_called,
    )
    await coord.run(session_id="s1", message="你好", context=None)

    types = [e["type"] for e in sent]
    assert types[-1] == "done"
    assert "error" not in types
    # 澄清文案应包含引导关键词
    final_content = sent[-1]["content"]
    assert "股票" in final_content
    assert any(
        kw in final_content for kw in ("代码", "比亚迪", "002594", "SZ", "SH", "HK")
    )
    # assistant 消息应入库,保证下次 qa_followup 能看到完整历史
    repo.append_message.assert_called_once()
    fake_llm.complete.assert_not_awaited()


async def test_clarify_works_even_when_llm_config_missing():
    """LLM_DEFAULT_CHANNEL 未配置时,clarify 路径仍能成功响应(不抛 INTERNAL)。"""
    sent: list[dict] = []

    async def sse_send(ev):
        sent.append(ev)

    def llm_factory_raises(phase):
        raise LLMError("CONFIG", "LLM_DEFAULT_CHANNEL 未配置")

    repo = MagicMock()
    repo.get.return_value = {"session_id": "s1", "output_dir": None, "status": "idle"}
    si = MagicMock()
    si.get_name.return_value = None

    coord = Coordinator(
        sse_send=sse_send,
        repo=repo,
        workspace=MagicMock(),
        stock_index=si,
        llm_factory=llm_factory_raises,
    )
    await coord.run(session_id="s1", message="随便聊聊", context=None)

    types = [e["type"] for e in sent]
    assert "error" not in types
    assert types[-1] == "done"


async def test_routes_to_full_pipeline_when_stock_detected():
    """识别到股票码时应走 full_pipeline 分支(发出 phase1_data_pack 的 tool_start)。"""
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
    # full_pipeline 已实现,此用例只验证路由到该分支(第一个事件来自 phase1_data_pack)
    await coord.run(session_id="s1", message="600519 怎么样", context=None)
    tool_starts = [e for e in sent if e["type"] == "tool_start"]
    assert tool_starts, "应至少有一个 tool_start 事件(说明进入了 full_pipeline 分支)"
    # Phase 5 起 cpa 首阶段是 phase0_qualitative,phase1_data_pack 紧随
    tools = [e["tool"] for e in tool_starts]
    assert tools[0] == "phase0_qualitative"
    assert "phase1_data_pack" in tools


# ===== Task 19: qa_followup =====


async def test_qa_followup_uses_existing_report(tmp_path):
    sent: list[dict] = []

    async def sse_send(ev):
        sent.append(ev)

    output_dir = tmp_path / "002594.SZ_比亚迪"
    output_dir.mkdir()
    (output_dir / "比亚迪_002594.SZ_分析报告.md").write_text(
        "# 报告\n\nROIC=15%", encoding="utf-8"
    )

    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(
        return_value=CompletionResult(text="第 5 段...", tokens_in=10, tokens_out=4)
    )

    repo = MagicMock()
    repo.get.return_value = {
        "session_id": "s1",
        "output_dir": str(output_dir),
        "status": "done",
    }
    repo.list_messages.return_value = []

    workspace = MagicMock()
    workspace.read_meta.return_value = {
        "phases": {"phase3_valuation": {"status": "done"}}
    }

    coord = Coordinator(
        sse_send=sse_send,
        repo=repo,
        workspace=workspace,
        stock_index=MagicMock(),
        llm_factory=lambda p: fake_llm,
    )
    await coord.run(
        session_id="s1",
        message="第 5 段那个 G 系数怎么算的?",
        context=None,
    )

    types = [e["type"] for e in sent]
    assert types[0] == "thinking"
    assert types[-1] == "done"
    sent_msgs = fake_llm.complete.call_args[0][0]
    assert any("ROIC=15%" in m.content for m in sent_msgs)
    assert any(m.role == "user" and "第 5 段" in m.content for m in sent_msgs)


async def test_qa_followup_includes_recent_history():
    sent: list[dict] = []

    async def sse_send(ev):
        sent.append(ev)

    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp())
    (tmp / "x_分析报告.md").write_text("R", encoding="utf-8")

    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(
        return_value=CompletionResult(text="ok", tokens_in=1, tokens_out=1)
    )

    repo = MagicMock()
    repo.get.return_value = {
        "session_id": "s1",
        "output_dir": str(tmp),
        "status": "done",
    }
    # 12 条历史 — 应只取最后 10
    repo.list_messages.return_value = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
        for i in range(12)
    ]

    workspace = MagicMock()
    workspace.read_meta.return_value = {
        "phases": {"phase3_valuation": {"status": "done"}}
    }

    coord = Coordinator(
        sse_send=sse_send,
        repo=repo,
        workspace=workspace,
        stock_index=MagicMock(),
        llm_factory=lambda p: fake_llm,
    )
    await coord.run(session_id="s1", message="续问", context=None)

    sent_msgs = fake_llm.complete.call_args[0][0]
    contents = [m.content for m in sent_msgs]
    # m0/m1 应被截断,m2..m11 应在 prompt 中
    assert "m0" not in contents
    assert "m1" not in contents
    assert "m11" in contents


# ===== 会话内换股(方向②):不被旧报告粘滞 =====


async def test_switches_to_new_stock_instead_of_qa_followup(tmp_path):
    """会话粘滞 bug 回归:会话已锚定旧股 01104.HK 且有完整报告,
    用户在同一会话改问新股 603939.SH 时,应路由到分析流水线分析新股,
    而不是拿旧报告走 qa_followup(否则 LLM 拿着 01104 报告答 603939,答非所问)。
    """
    from services.agent.core.symbol import StockRef
    from services.agent.core.workspace import Workspace

    sent: list[dict] = []

    async def sse_send(ev):
        sent.append(ev)

    # 预置旧股 01104.HK 的"完整报告"(work/_meta.json phase3_valuation=done + report/*.md)
    ws = Workspace(tmp_path / "ws")
    old_ref = StockRef(code="01104.HK", name="APAC RESOURCES", market="HK")
    d_old = ws.ensure(old_ref)
    ws.mark_phase(d_old, "phase3_valuation", status="done")
    (ws.report_dir(d_old) / "APAC RESOURCES_01104.HK_分析报告.md").write_text(
        "# 旧报告 01104", encoding="utf-8"
    )

    repo = MagicMock()
    repo.get.return_value = {
        "session_id": "s1",
        "stock_code": "01104.HK",
        "output_dir": str(d_old),
        "status": "done",
    }

    si = MagicMock()
    si.get_name.return_value = "益丰药房"  # 603939.SH 命中 → extract 返回新股 ref

    # qa_followup 用 complete();若被调用即说明仍粘滞(测试应红)
    qa_complete = AsyncMock(
        return_value=CompletionResult(text="旧报告答复", tokens_in=1, tokens_out=1)
    )

    def llm_factory(phase):
        m = MagicMock()
        m.complete = qa_complete
        return m

    coord = Coordinator(
        sse_send=sse_send,
        repo=repo,
        workspace=ws,
        stock_index=si,
        llm_factory=llm_factory,
        qualitative_dir=tmp_path / "qual",
    )
    await coord.run(
        session_id="s1",
        message="使用现金流分析一下603939.SH",
        context=None,
    )

    # 不得走 qa_followup(拿旧报告让 LLM 续答)
    qa_complete.assert_not_awaited()
    # 应进入分析流水线(cpa 首阶段 phase0_qualitative)
    tool_starts = [e for e in sent if e["type"] == "tool_start"]
    assert tool_starts, "应进入分析流水线(至少一个 tool_start)"
    assert tool_starts[0]["tool"] == "phase0_qualitative"
