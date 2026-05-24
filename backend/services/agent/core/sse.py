"""问股期 1 / Task 4:SSE 6 类事件工厂。

每类事件的 dict 形态严格对齐前端 ProgressStep 接口
(frontend/src/stores/agentChatStore.ts)。允许字段集见 test_sse_contract.py。

事件类型:
  - thinking      LLM 思考过程文本(可选,折叠展示)
  - tool_start    工具/阶段开始(显示进度条 / 标题)
  - tool_done     工具/阶段结束(success/duration/message)
  - generating    生成式增量内容(append 到当前消息)
  - done          整个流程结束(包含最终内容 + artifacts)
  - error         任意阶段错误(error_code + message + 可选 phase)

encode():dict → SSE wire bytes(``data: {json}\\n\\n``)。
"""

from __future__ import annotations

import json
from typing import Optional


def thinking(content: str) -> dict:
    """LLM 思考过程文本。"""
    return {"type": "thinking", "content": content}


def tool_start(tool: str, display_name: str) -> dict:
    """工具/阶段开始。tool 是机器名(eg phase3_quant),display_name 是中文展示名。"""
    return {"type": "tool_start", "tool": tool, "display_name": display_name}


def tool_done(
    tool: str,
    *,
    success: bool,
    duration: Optional[float] = None,
    message: Optional[str] = None,
    display_name: Optional[str] = None,
) -> dict:
    """工具/阶段结束。可选字段为 None 时不写入 dict(保持 wire size 紧凑)。"""
    e: dict = {"type": "tool_done", "tool": tool, "success": success}
    if duration is not None:
        e["duration"] = duration
    if message is not None:
        e["message"] = message
    if display_name is not None:
        e["display_name"] = display_name
    return e


def generating(content: str) -> dict:
    """生成式增量内容(LLM 流式输出片段)。"""
    return {"type": "generating", "content": content}


def done(content: str, artifacts: list[dict]) -> dict:
    """整个流程结束。content 是最终 markdown,artifacts 是文件列表。"""
    return {
        "type": "done",
        "success": True,
        "content": content,
        "artifacts": artifacts,
    }


def error(error_code: str, message: str, *, phase: Optional[str] = None) -> dict:
    """错误事件。phase 可选(标识在哪一阶段失败)。"""
    e: dict = {"type": "error", "error": error_code, "message": message}
    if phase is not None:
        e["phase"] = phase
    return e


def encode(event: dict) -> bytes:
    """dict → SSE wire bytes。ensure_ascii=False 让中文不被转义。"""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")
