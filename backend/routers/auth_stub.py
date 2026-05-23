"""auth_stub —— 期 1 占位鉴权路由。

期 1 不引入真实鉴权,前端 AuthContext 通过本接口判定 authEnabled=false 后
跳过登录页直接进入主界面。期 2 接入真实鉴权时整体替换本路由。
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/status")
def status():
    return {"authEnabled": False}
