"""闲聊 agent 实现 — 直接 stream LLM 输出,无 step 切分。"""

from __future__ import annotations

from services.agent_harness import events

from .manifest import MANIFEST


class ChitchatAgent:
    manifest = MANIFEST

    async def run(self, *, ref, llm, ctx):
        # ChitchatAgent 通过 ctx.user_message(coordinator 注入)读取用户原文;
        # 占位场景没有时,fallback 默认问候。
        user_msg = getattr(ctx, "user_message", "你好")
        prompt = f"你是问股(Ask Stock)助手。回答简洁、有帮助。\n用户:{user_msg}\n助手:"
        async for chunk in llm.stream(prompt):
            if not chunk:
                continue
            yield events.generating(
                agent_id=MANIFEST["id"], step_id="chat", delta=chunk
            )
        yield events.done(agent_id=MANIFEST["id"])
