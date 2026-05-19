"""决策日志写入器:JSONL 格式,带内存缓冲 + flush。

三类事件:
- pass/reject:决策层(每条 = 一个 symbol 在某个 stage 的过滤结果)→ decisions.jsonl
- flow:流量层(每条 = 一个 stage 的 input/passed 计数)→ flow.jsonl
- exec:执行层(每条 = 一次买卖)→ exec.jsonl
"""

from __future__ import annotations

import atexit
import json
from pathlib import Path
from typing import Any


class DecisionLogSink:
    DECISIONS = "decisions.jsonl"
    FLOW = "flow.jsonl"
    EXEC = "exec.jsonl"

    def __init__(self, log_dir: Path | None, enabled: bool = True):
        self._enabled = enabled and log_dir is not None
        self._dir = Path(log_dir) if log_dir else None
        self._buffer: dict[str, list[str]] = {
            self.DECISIONS: [],
            self.FLOW: [],
            self.EXEC: [],
        }
        if self._enabled:
            self._dir.mkdir(parents=True, exist_ok=True)
            atexit.register(self.flush)

    def log_pass(
        self,
        symbol: str,
        stage: str,
        *,
        idx: int,
        ts: str,
        freq: str = "daily",
        **values: Any,
    ) -> None:
        if not self._enabled:
            return
        rec = {
            "ts": ts,
            "idx": idx,
            "freq": freq,
            "stage": stage,
            "symbol": symbol,
            "decision": "pass",
            **values,
        }
        self._buffer[self.DECISIONS].append(json.dumps(rec, ensure_ascii=False))

    def log_reject(
        self,
        symbol: str,
        stage: str,
        *,
        reason: str,
        idx: int,
        ts: str,
        freq: str = "daily",
        **values: Any,
    ) -> None:
        if not self._enabled:
            return
        rec = {
            "ts": ts,
            "idx": idx,
            "freq": freq,
            "stage": stage,
            "symbol": symbol,
            "decision": "reject",
            "reason": reason,
            **values,
        }
        self._buffer[self.DECISIONS].append(json.dumps(rec, ensure_ascii=False))

    def log_flow(self, stage: str, *, idx: int, ts: str, **counts: Any) -> None:
        if not self._enabled:
            return
        rec = {"ts": ts, "idx": idx, "stage": stage, "counts": counts}
        self._buffer[self.FLOW].append(json.dumps(rec, ensure_ascii=False))

    def log_exec(
        self,
        action: str,
        symbol: str,
        *,
        idx: int,
        ts: str,
        shares: int,
        price: float,
        note: str = "",
    ) -> None:
        if not self._enabled:
            return
        rec = {
            "ts": ts,
            "idx": idx,
            "action": action,
            "symbol": symbol,
            "shares": shares,
            "price": price,
            "note": note,
        }
        self._buffer[self.EXEC].append(json.dumps(rec, ensure_ascii=False))

    def flush(self) -> None:
        if not self._enabled:
            return
        for fname, lines in self._buffer.items():
            if not lines:
                continue
            path = self._dir / fname
            with path.open("a", encoding="utf-8") as f:
                f.write("\n".join(lines))
                f.write("\n")
            lines.clear()
