from typing import Optional

from pydantic import BaseModel


class StockBasicInfo(BaseModel):
    """股票基本信息"""

    code: str
    name: str
    ipo_date: str
    delist_date: Optional[str] = None
    stock_type: Optional[str] = None
    status: str
    industry: Optional[str] = None
