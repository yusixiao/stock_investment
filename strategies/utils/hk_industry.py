"""港股行业分类工具 —— 为策略提供 code → sector/industry 映射。

数据源:`data/market/HK/membership/hk_industry.parquet`(yfinance 周更,
DuckDB 视图 `v_hk_industry`),schema: code / name / sector / industry。

⚠️ 已知偏差:
- 仅覆盖约 608 只港股(yfinance 有分类的标的,偏大盘/有研究覆盖的「龙头」名字),
  全 H股 2734 只中其余无分类。`require_industry` 过滤本身即一种「龙头」代理。
- **当前快照,无 point-in-time 历史**:行业分类极少变动,影响远小于成分股,
  但严格 PIT 场景需注意。

符号规格:daily 符号形如 `01536.HK`,parquet code 形如 `01536`(5 位零填充)。
本模块统一以「去掉 .HK 后缀」为键匹配。
"""

from __future__ import annotations

import os

import pandas as pd

from backend.config import MARKET_DIR

_PARQUET = MARKET_DIR / "HK" / "membership" / "hk_industry.parquet"

_SECTOR: dict[str, str] | None = None
_INDUSTRY: dict[str, str] | None = None


def _norm(symbol: str) -> str:
    """归一化为 parquet code 键:去掉 .HK 后缀、转大写去空格。"""
    s = str(symbol).strip().upper()
    if s.endswith(".HK"):
        s = s[:-3]
    return s


def _load() -> None:
    global _SECTOR, _INDUSTRY
    if _SECTOR is not None:
        return
    _SECTOR = {}
    _INDUSTRY = {}
    if not os.path.exists(_PARQUET):
        return
    try:
        df = pd.read_parquet(_PARQUET, columns=["code", "sector", "industry"])
    except Exception:
        return
    for code, sector, industry in zip(df["code"], df["sector"], df["industry"]):
        key = _norm(code)
        if sector is not None and not pd.isna(sector):
            _SECTOR[key] = str(sector)
        if industry is not None and not pd.isna(industry):
            _INDUSTRY[key] = str(industry)


def get_sector(symbol: str) -> str | None:
    """返回 GICS-like 一级行业(sector),无分类返回 None。"""
    _load()
    return _SECTOR.get(_norm(symbol))


def get_industry(symbol: str) -> str | None:
    """返回二级行业(industry),无分类返回 None。"""
    _load()
    return _INDUSTRY.get(_norm(symbol))


def has_classification(symbol: str) -> bool:
    """是否有行业分类(可作「龙头/大盘覆盖」代理)。"""
    _load()
    return _norm(symbol) in _SECTOR


def reset_cache() -> None:
    global _SECTOR, _INDUSTRY
    _SECTOR = None
    _INDUSTRY = None
