"""问股期 1 — Task 12/18:agent 路由(skills + sessions CRUD + /chat/stream)。

每个测试用 monkeypatch 设 DSA_PORTFOLIO_DB,_conn() 每次请求都从 env 读路径。
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import yaml
from fastapi.testclient import TestClient

from main import app
from services.system_config.llm_client import CompletionResult


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("DSA_PORTFOLIO_DB", str(tmp_path / "p.db"))
    return TestClient(app)


def test_skills_returns_empty_array(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/agent/skills")
    assert r.status_code == 200
    assert r.json() == {"skills": []}


def test_sessions_empty_initially(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/agent/sessions")
    assert r.status_code == 200
    assert r.json() == {"items": []}


def test_session_upsert_via_get(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/agent/sessions/sid-1")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == "sid-1"

    r = c.get("/api/v1/agent/sessions/sid-1/messages")
    assert r.status_code == 200
    assert r.json() == {"items": []}


def test_session_delete(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.get("/api/v1/agent/sessions/sid-1")
    r = c.delete("/api/v1/agent/sessions/sid-1")
    assert r.status_code == 200

    r = c.get("/api/v1/agent/sessions")
    assert r.json() == {"items": []}


def test_sessions_list_after_create(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.get("/api/v1/agent/sessions/sid-a")
    c.get("/api/v1/agent/sessions/sid-b")
    r = c.get("/api/v1/agent/sessions")
    items = r.json()["items"]
    ids = {it["session_id"] for it in items}
    assert ids == {"sid-a", "sid-b"}


# ===== Task 18:/chat/stream =====


def _setup_chat_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DSA_PORTFOLIO_DB", str(tmp_path / "p.db"))
    monkeypatch.setenv("DSA_CONFIG_PATH", str(tmp_path / "cfg.yaml"))
    monkeypatch.setenv("DSA_AGENT_RUNS", str(tmp_path / "runs"))
    (tmp_path / "cfg.yaml").write_text(
        yaml.safe_dump(
            {
                "LLM_X_PROVIDER": "openai",
                "LLM_X_BASE_URL": "https://x",
                "LLM_X_API_KEY": "k",
                "LLM_X_MODEL": "m",
                "LLM_DEFAULT_CHANNEL": "X",
            }
        ),
        encoding="utf-8",
    )


def test_chat_stream_clarify_when_no_stock(tmp_path, monkeypatch):
    """无股票码时走硬编码澄清,不调 LLM,不抛 INTERNAL。"""
    _setup_chat_env(tmp_path, monkeypatch)

    # llm_factory 即使被调也立刻 raise,验证 clarify 路径完全不依赖 LLM
    def _should_not_be_called(phase):
        raise AssertionError(f"clarify 路径不应调 build_client_for_phase({phase})")

    with patch(
        "routers.agent.build_client_for_phase", side_effect=_should_not_be_called
    ):
        c = TestClient(app)
        with c.stream(
            "POST",
            "/api/v1/agent/chat/stream",
            json={
                "message": "你好",
                "session_id": "s1",
                "skills": [],
                "context": None,
            },
        ) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            events = []
            for line in r.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))

    types = [e["type"] for e in events]
    assert types[-1] == "done"
    assert "error" not in types
    final_text = events[-1]["content"]
    assert "股票" in final_text


def test_chat_stream_full_pipeline_e2e(tmp_path, monkeypatch):
    """E2E:识别股票码 → 三阶段 SSE 事件序列 + 报告写盘 + session output_dir 落库。"""
    _setup_chat_env(tmp_path, monkeypatch)

    QUANT = (
        "# Phase 3.1\n<results>\n"
        "owner_earnings_I=100\nfinal_return_GG=12.5\nthreshold_II=10\n"
        "margin_KK=0.5\ntrap_risk=低\nextrapolation_confidence=高\n"
        "</results>\n"
    )
    REPORT = "# 投资分析报告\n\n## 评级\nA\n"

    class _StreamLLM:
        """fake LLMClient,stream(messages) 异步生成。"""

        def __init__(self, text):
            self._text = text
            self.complete = AsyncMock(
                return_value=CompletionResult(text=text, tokens_in=1, tokens_out=1)
            )

        async def stream(self, messages, **kwargs):
            # 分两 chunk
            mid = len(self._text) // 2
            yield self._text[:mid]
            yield self._text[mid:]

    quant_llm = _StreamLLM(QUANT)
    val_llm = _StreamLLM(REPORT)

    def factory(phase: str):
        if phase == "phase3_quant":
            return quant_llm
        if phase == "phase3_valuation":
            return val_llm
        return _StreamLLM("")

    # patch DataPackBuilder 的 build,避开真实 DuckDB 依赖
    def fake_build(self, ref, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / "data_pack_market.md"
        out.write_text(f"# 数据包 {ref.code}\n", encoding="utf-8")
        return out

    # patch stock_index 让股票码被识别
    fake_si = MagicMock()
    fake_si.get_name.return_value = "贵州茅台"

    with (
        patch("routers.agent.build_client_for_phase", side_effect=factory),
        patch("routers.agent.stock_index", fake_si),
        patch(
            "services.agent.agents.cpa.pipeline.phase1_data_pack.builder.DataPackBuilder.build",
            new=fake_build,
        ),
    ):
        c = TestClient(app)
        with c.stream(
            "POST",
            "/api/v1/agent/chat/stream",
            json={
                "message": "600519 怎么样",
                "session_id": "sFull",
                "skills": [],
                "context": None,
            },
        ) as r:
            assert r.status_code == 200
            events = []
            for line in r.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))

    types = [e["type"] for e in events]
    # 三阶段 tool_start / tool_done
    assert types.count("tool_start") == 3
    assert types.count("tool_done") == 3
    # 至少有 generating(LLM 流式片段)
    assert any(t == "generating" for t in types)
    # 最终 done
    assert types[-1] == "done"
    artifacts = events[-1]["artifacts"]
    assert artifacts and any("分析报告" in a["name"] for a in artifacts)

    # 报告确实写盘(在 DSA_AGENT_RUNS 下)
    runs = tmp_path / "runs"
    reports = list(runs.rglob("*_分析报告.md"))
    assert reports, f"应至少有一份报告写盘,当前 runs 内容: {list(runs.rglob('*'))}"

    # session output_dir 已写回
    sess = c.get("/api/v1/agent/sessions/sFull").json()
    assert sess.get("output_dir")
    assert "贵州茅台" in sess["output_dir"] or "600519" in sess["output_dir"]


def test_chat_stream_persists_user_message(tmp_path, monkeypatch):
    """无股票码 → clarify 路径,user + assistant 两条都要落库。"""
    _setup_chat_env(tmp_path, monkeypatch)

    c = TestClient(app)
    with c.stream(
        "POST",
        "/api/v1/agent/chat/stream",
        json={"message": "hello world", "session_id": "sx"},
    ) as r:
        for _ in r.iter_lines():
            pass
    # 用户消息 + clarify assistant 消息都应当落库
    msgs = c.get("/api/v1/agent/sessions/sx/messages").json()["items"]
    roles = [m["role"] for m in msgs]
    contents = [m["content"] for m in msgs]
    assert "user" in roles
    assert "assistant" in roles
    assert "hello world" in contents
    # clarify 文案中包含「股票」关键词
    assert any("股票" in c for c in contents)
