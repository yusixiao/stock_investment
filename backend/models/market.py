from typing import Optional

from pydantic import BaseModel


class DailyKlineRecord(BaseModel):
    """日K线记录（不复权）"""

    date: str
    code: str
    open: float
    high: float
    low: float
    close: float
    preclose: Optional[float] = None
    volume: float
    amount: float
    adjustflag: Optional[str] = None
    turn: Optional[float] = None
    tradestatus: Optional[str] = None
    pctChg: Optional[float] = None
    peTTM: Optional[float] = None
    pbMRQ: Optional[float] = None
    psTTM: Optional[float] = None
    pcfNcfTTM: Optional[float] = None
    isST: Optional[str] = None


class AdjustFactorRecord(BaseModel):
    """复权因子记录"""

    code: str
    dividOperateDate: str
    foreAdjustFactor: float
    backAdjustFactor: Optional[float] = None
    adjustFactor: Optional[float] = None


class AggregatedKline(BaseModel):
    """聚合K线（周线/月线）— 由日线动态计算，不持久化"""

    date: str
    code: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
