"""dispatcher 写 _meta.json 状态文件:running -> done/failed,记录每个 step 状态。

事件驱动更新:每收到 tool_start/tool_done/error 都同步写盘,便于断点续跑/排查。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .protocol import AgentManifest, Event


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write(workspace: Path, meta: dict) -> None:
    (workspace / "_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def init_meta(*, workspace: Path, manifest: AgentManifest, ref, llm) -> dict:
    meta = {
        "session_id": workspace.parent.name,
        "run_id": workspace.name,
        "agent_id": manifest["id"],
        "agent_label": manifest["label"],
        "agent_version": manifest["version"],
        "model": getattr(llm, "model", None),
        "channel": getattr(llm, "channel", None),
        "ref": {
            "symbol": getattr(ref, "symbol", None),
            "name": getattr(ref, "name", None),
            "market": getattr(ref, "market", None),
        },
        "started_at": _now(),
        "status": "running",
        "steps": {},
    }
    _write(workspace, meta)
    return meta


def update_meta_from_event(workspace: Path, meta: dict, ev: Event) -> None:
    sid = ev.get("step_id")
    t = ev["type"]
    if t == "tool_start" and sid:
        meta["steps"][sid] = {
            "status": "running",
            "started_at": _now(),
            "label": ev.get("step_label", sid),
        }
    elif t == "tool_done" and sid:
        meta["steps"].setdefault(sid, {})
        meta["steps"][sid].update({"status": "done", "ended_at": _now()})
    elif t == "error" and sid:
        meta["steps"].setdefault(sid, {})
        meta["steps"][sid].update({"status": "failed", "error": ev.get("message")})
    _write(workspace, meta)


def finalize_meta(
    workspace: Path, meta: dict, *, status: str, error: str | None = None
) -> None:
    meta["status"] = status
    meta["ended_at"] = _now()
    if error:
        meta["error"] = error
    _write(workspace, meta)
