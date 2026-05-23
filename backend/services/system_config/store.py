"""ConfigStore:扁平 KV 配置的 yaml 原子读写。

- 所有 value 强制 str(化(yaml 默认会保留 int/bool 类型,这里统一化简)
- 保存使用 tmp + replace 原子语义,避免半写状态
- 文件不存在时 load() 返回 {}
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import yaml


class ConfigStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        return {str(k): str(v) for k, v in data.items()}

    def save(self, kv: dict) -> None:
        normalized = {str(k): str(v) for k, v in kv.items()}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            yaml.safe_dump(normalized, allow_unicode=True, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def get(self, key: str, default: str = "") -> str:
        return self.load().get(key, default)

    def set(self, key: str, value) -> None:
        kv = self.load()
        kv[key] = str(value)
        self.save(kv)

    def delete(self, keys: Iterable[str]) -> None:
        kv = self.load()
        for k in keys:
            kv.pop(k, None)
        self.save(kv)
