"""扁平 KV 系统配置 CRUD + schema 渲染。

GET    /api/v1/system/config                返回 items(默认遮掩敏感字段)
GET    /api/v1/system/config?include_schema=true
                                            返回完整 SystemConfigResponse(含 schema)
GET    /api/v1/system/config/schema         单独返回 schema(categories)
PUT    /api/v1/system/config                整体替换;敏感字段值为 ****** 表示「保留」
POST   /api/v1/system/config/validate       预校验(前端 save 前调用,确保保存流畅)
DELETE /api/v1/system/config/{key}          删除单 key

未实现的 setup-status / export / import / test-channel / discover-models
端点统一返回 503 not_implemented,前端按预期把对应卡片标为「未启用」。
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.system_config.field_schema import (
    MASK_TOKEN,
    build_categories,
    build_items,
    unmask_for_save,
)
from services.system_config.schema import ConfigError, validate_kv
from services.system_config.store import ConfigStore

router = APIRouter(prefix="/api/v1/system/config", tags=["system_config"])

SCHEMA_VERSION = "1.0"


def _store() -> ConfigStore:
    # 锚定项目根而非 cwd(uvicorn 从 backend/ 启动时 cwd 不是项目根)
    from config import BASE_DIR

    raw = os.environ.get("DSA_CONFIG_PATH")
    path = Path(raw) if raw else BASE_DIR / "config" / "system_config.yaml"
    return ConfigStore(path)


def _config_version(kv: dict[str, str]) -> str:
    """基于 kv 内容的稳定哈希(8 位短)— 简单乐观锁版本号。"""
    canon = "\n".join(f"{k}={v}" for k, v in sorted(kv.items()))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:12]


# ===== 请求/响应模型 =====


class Item(BaseModel):
    key: str
    value: str


class ItemList(BaseModel):
    items: list[Item]


class UpdatePayload(BaseModel):
    items: list[Item]
    config_version: str | None = None
    mask_token: str | None = None
    reload_now: bool = True


# ===== GET =====


@router.get("")
def get_all(include_schema: bool = False) -> dict:
    kv = _store().load()
    items = build_items(kv)
    body: dict = {
        "items": items,
        "config_version": _config_version(kv),
        "mask_token": MASK_TOKEN,
    }
    if include_schema:
        body["schema_version"] = SCHEMA_VERSION
        body["categories"] = build_categories()
    return body


@router.get("/schema")
def get_schema() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "categories": build_categories(),
    }


# ===== PUT =====


@router.put("")
def put_all(payload: UpdatePayload) -> dict:
    store = _store()
    existing = store.load()
    new_kv_raw = {it.key: it.value for it in payload.items}
    # MASK_TOKEN 的敏感字段保留原值
    new_kv = unmask_for_save(new_kv_raw, existing)

    try:
        validate_kv(new_kv)
    except ConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))

    store.save(new_kv)
    saved = store.load()
    return {
        "success": True,
        "config_version": _config_version(saved),
        "applied_count": len(new_kv),
        "skipped_masked_count": sum(
            1 for k, v in new_kv_raw.items() if v == MASK_TOKEN
        ),
        "reload_triggered": payload.reload_now,
        "updated_keys": list(new_kv.keys()),
        "warnings": [],
        "items": build_items(saved),
    }


# ===== DELETE =====


@router.delete("/{key}")
def delete_one(key: str) -> dict:
    _store().delete([key])
    return {"ok": True}


# ===== 未实现端点 — 503 让前端统一降级展示「未启用」 =====


def _not_implemented():
    raise HTTPException(
        status_code=503,
        detail={
            "error": "not_implemented",
            "message": "该功能在当前版本未启用",
        },
    )


@router.get("/setup/status")
def get_setup_status() -> dict:
    _not_implemented()


@router.get("/export")
def export_env() -> dict:
    _not_implemented()


@router.post("/validate")
def validate_payload(payload: ItemList) -> dict:
    """前端 save 前调用:把 items 与现有 yaml 合并(MASK_TOKEN 解掩),
    再走 validate_kv()。返回 {valid, issues}。"""
    store = _store()
    existing = store.load()
    incoming = {it.key: it.value for it in payload.items}
    merged = {**existing, **unmask_for_save(incoming, existing)}
    try:
        validate_kv(merged)
        return {"valid": True, "issues": []}
    except ConfigError as e:
        # 把错误归到第一个未知/有问题的 key(简单实现);否则归 _global
        message = str(e)
        offending_key = next(
            (k for k in incoming if k in message or f"={incoming[k]}" in message),
            "_global",
        )
        return {
            "valid": False,
            "issues": [
                {
                    "key": offending_key,
                    "code": "validation_error",
                    "message": message,
                    "severity": "error",
                }
            ],
        }


@router.post("/import")
def import_env() -> dict:
    _not_implemented()


@router.post("/llm/test-channel")
def test_llm_channel() -> dict:
    _not_implemented()


@router.post("/notification/test-channel")
def test_notification_channel() -> dict:
    _not_implemented()


@router.post("/llm/discover-models")
def discover_llm_models() -> dict:
    _not_implemented()
