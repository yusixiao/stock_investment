"""Harness 工作目录:每次 dispatch 创建独立目录,允许多 agent / 多次运行隔离。

目录格式:<WORKSPACE_ROOT>/<session_id>/<agent_id>__<run_id>/
其中 run_id = YYYYMMDD_HHMMSS_<rand4hex>
"""

from __future__ import annotations

import secrets
from datetime import datetime
from pathlib import Path

WORKSPACE_ROOT = Path("report/agent_runs")


def create_workspace(*, session_id: str, agent_id: str) -> Path:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(2)
    path = WORKSPACE_ROOT / session_id / f"{agent_id}__{run_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path
