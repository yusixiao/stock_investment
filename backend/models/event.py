from typing import Optional

from pydantic import BaseModel


class DividendRecord(BaseModel):
    """分红/送转记录"""

    code: str
    dividPreNoticeDate: Optional[str] = None
    dividAgmPumDate: Optional[str] = None
    dividPlanAnnounceDate: Optional[str] = None
    dividPlanDate: Optional[str] = None
    dividRegistDate: Optional[str] = None
    dividOperateDate: str
    dividPayDate: Optional[str] = None
    dividStockMarketDate: Optional[str] = None
    dividCashPsBeforeTax: Optional[float] = None
    dividCashPsAfterTax: Optional[str] = None
    dividStocksPs: Optional[float] = None
    dividCashStock: Optional[str] = None
    dividReserveToStockPs: Optional[float] = None
