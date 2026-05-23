"""闲聊 agent manifest — 不通过 alias 关键字路由,由 LLM router / coordinator 显式选。"""

MANIFEST = {
    "id": "chitchat",
    "label": "闲聊",
    "aliases": [],
    "description": "通用对话与帮助,不走分析流水线。",
    "version": "1.0.0",
    "steps": [],
    "requires": ["llm.chat"],
    "enabled": True,
}
