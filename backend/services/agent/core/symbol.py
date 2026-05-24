"""问股期 1 / Task 3:股票代码识别与归一化。

提供两个核心 API:
  - normalize(raw)  原始字符串 → 标准化代码(带市场后缀;US 无后缀)
  - extract(message, context, *, stock_index)  从消息或上下文中识别 StockRef

归一化规则:
  - A 股:6 位数字,6/9 开头加 ".SH",其余加 ".SZ"(688 科创板属沪市)
  - 港股:1-5 位数字,zfill 到 5 位 + ".HK"
  - 美股:1-5 位字母,upper(),".US" 后缀去除
  - 已带正确后缀的直接通过(后缀大小写不敏感)

extract 顺序:
  1. context.stock_code(优先,前端透传)
  2. message 中正则扫描:A 股 → 港股 → 美股
  3. 须 stock_index.get_name(code) 命中(非 None)才计为有效引用,
     避免把消息中的随机 6 位数字误识别为股票
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional

Market = Literal["A", "HK", "US"]


@dataclass(frozen=True)
class StockRef:
    """单一股票引用:标准代码 + 名称 + 市场。"""

    code: str
    name: str
    market: Market


# -- normalize 用正则:严格匹配整个字符串 --------------------------------
_RE_A_FULL = re.compile(r"^(\d{6})\.(SH|SZ)$", re.IGNORECASE)
_RE_A_BARE = re.compile(r"^\d{6}$")
_RE_HK_FULL = re.compile(r"^(\d{1,5})\.HK$", re.IGNORECASE)
_RE_HK_BARE = re.compile(r"^\d{5}$")
_RE_US = re.compile(r"^[A-Za-z]{1,5}(\.US)?$", re.IGNORECASE)

# -- extract 用正则:在消息中查找子串 ------------------------------------
# 注意:Python re 默认 Unicode,`\w` 包含中文(分析603939 中的"析"会被
# `(?<!\w)` 误判为已有 word char),故 lookaround 必须用 ASCII 字符类。
# A 股:6 位数字(前后必须不是 ASCII 数字/字母,避免 6000000 长串误中)
_RE_INLINE_A = re.compile(r"(?<![0-9A-Za-z])(\d{6})(?![0-9A-Za-z])")
# 港股:5 位数字
_RE_INLINE_HK = re.compile(r"(?<![0-9A-Za-z])(\d{5})(?![0-9A-Za-z])")
# 美股:2-5 位大写字母(单字母 ticker 如 F/T 误识别风险高,放弃)
_RE_INLINE_US = re.compile(r"(?<![0-9A-Za-z])([A-Z]{2,5})(?![0-9A-Za-z])")


def _market_of(code: str) -> Market:
    """从已 normalize 后的 code 推断市场。"""
    upper = code.upper()
    if upper.endswith((".SH", ".SZ")):
        return "A"
    if upper.endswith(".HK"):
        return "HK"
    return "US"


def normalize(raw: str) -> str:
    """原始字符串 → 标准 code。无法识别时返回原 strip 值(小写化美股)。"""
    raw = raw.strip()
    if not raw:
        return raw

    if m := _RE_A_FULL.match(raw):
        return f"{m.group(1)}.{m.group(2).upper()}"

    if _RE_A_BARE.match(raw):
        # 6/9 开头 → SH(沪市主板 600/601/603/605/688 科创板/9 B 股),其余 → SZ
        first = raw[0]
        return f"{raw}.SH" if first in ("6", "9") else f"{raw}.SZ"

    if m := _RE_HK_FULL.match(raw):
        return f"{m.group(1).zfill(5)}.HK"

    if _RE_HK_BARE.match(raw):
        return f"{raw}.HK"

    if _RE_US.match(raw):
        # 去除 .US 后缀(项目内美股 code 不带 .US)
        return raw.upper().replace(".US", "")

    return raw


def extract(
    message: str, context: Optional[dict], *, stock_index
) -> Optional[StockRef]:
    """从 message 或 context 中识别股票引用。

    Args:
      message: 用户输入消息(可能含股票码)
      context: 前端传入的会话上下文 dict,期望含 stock_code / stock_name
      stock_index: services.stock_index 模块或具备 get_name(code) 方法的对象

    Returns:
      StockRef(code/name/market)或 None
    """
    # 1. 上下文优先(前端定位股票时直接透传 stock_code)
    if context and (raw := context.get("stock_code")):
        code = normalize(str(raw))
        name = context.get("stock_name") or stock_index.get_name(code) or ""
        return StockRef(code=code, name=name, market=_market_of(code))

    if not message:
        return None

    # 2. 消息内联匹配 — 须 get_name 命中以排除随机数字
    for rx, market in [
        (_RE_INLINE_A, "A"),
        (_RE_INLINE_HK, "HK"),
        (_RE_INLINE_US, "US"),
    ]:
        for m in rx.finditer(message):
            code = normalize(m.group(1))
            name = stock_index.get_name(code)
            if name:
                return StockRef(code=code, name=name, market=market)  # type: ignore[arg-type]

    return None
