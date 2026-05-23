"""问股期 1 — Task 13:LLMClient 抽象基类与基础类型。

本文件后续 Task 14 会扩展 OpenAICompatibleClient 的真实测试。
"""

from services.system_config.llm_client import LLMClient, LLMError, Message


def test_message_dataclass():
    m = Message(role="user", content="hi")
    assert m.role == "user"
    assert m.content == "hi"


def test_llm_error_is_exception():
    assert issubclass(LLMError, Exception)


def test_llm_error_carries_code():
    e = LLMError("HTTP_401", "bad key")
    assert e.code == "HTTP_401"
    assert e.message == "bad key"
    assert "HTTP_401" in str(e)


def test_client_is_abstract():
    import inspect

    assert inspect.isabstract(LLMClient)
