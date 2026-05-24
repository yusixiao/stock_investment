"""扁平 KV 系统配置 CRUD。

GET    /api/v1/system/config         返回全部 KV(已排序)
PUT    /api/v1/system/config         整体替换(先 validate_kv 再原子写)
DELETE /api/v1/system/config/{key}   删除单 key
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.system_config.schema import ConfigError, validate_kv
from services.system_config.store import ConfigStore

router = APIRouter(prefix="/api/v1/system/config", tags=["system_config"])


def _store() -> ConfigStore:
    # 锚定项目根而非 cwd(uvicorn 从 backend/ 启动时 cwd 不是项目根)
    from config import BASE_DIR

    raw = os.environ.get("DSA_CONFIG_PATH")
    path = Path(raw) if raw else BASE_DIR / "config" / "system_config.yaml"
    return ConfigStore(path)


class Item(BaseModel):
    key: str
    value: str


class ItemList(BaseModel):
    items: list[Item]


@router.get("", response_model=ItemList)
def get_all() -> dict:
    kv = _store().load()
    return {"items": [{"key": k, "value": v} for k, v in sorted(kv.items())]}


@router.put("", response_model=ItemList)
def put_all(payload: ItemList) -> dict:
    new_kv = {it.key: it.value for it in payload.items}
    try:
        validate_kv(new_kv)
    except ConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _store().save(new_kv)
    return {"items": [{"key": k, "value": v} for k, v in sorted(new_kv.items())]}


@router.delete("/{key}")
def delete_one(key: str) -> dict:
    _store().delete([key])
    return {"ok": True}
