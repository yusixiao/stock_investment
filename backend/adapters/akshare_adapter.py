import logging
from typing import List

import akshare as ak
import pandas as pd

from backend.adapters.base import FinancialDataAdapter
from backend.models.financial import (
    IncomeStatement,
    BalanceSheet,
    CashFlow,
    FinancialIndicator,
)

logger = logging.getLogger(__name__)


def _to_akshare_symbol(code: str) -> str:
    """000001.SZ -> SZ000001 (利润表/资产负债表/现金流量表格式)"""
    parts = code.split(".")
    if len(parts) == 2:
        return f"{parts[1]}{parts[0]}"
    return code


def _to_akshare_indicator_symbol(code: str) -> str:
    """000001.SZ -> 000001.SZ (财务指标格式，直接使用)"""
    return code


def _df_to_models(df: pd.DataFrame, model_class, date_field: str = "REPORT_DATE"):
    """将 DataFrame 转换为 Pydantic 模型列表"""
    if df is None or df.empty:
        return []

    if date_field in df.columns:
        df[date_field] = df[date_field].astype(str).str[:10]

    records = []
    for _, row in df.iterrows():
        data = {}
        for col in df.columns:
            val = row[col]
            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            if isinstance(val, pd.Timestamp):
                data[col] = val.strftime("%Y-%m-%d")
            else:
                data[col] = val
        records.append(model_class(**data))

    return records


class AKShareAdapter(FinancialDataAdapter):
    """AKShare 数据源适配器 — 实现财务数据接口"""

    def fetch_income(self, code: str) -> List[IncomeStatement]:
        symbol = _to_akshare_symbol(code)
        try:
            df = ak.stock_profit_sheet_by_report_em(symbol=symbol)
        except Exception as e:
            logger.error(f"获取利润表失败 {code}: {e}")
            return []
        return _df_to_models(df, IncomeStatement)

    def fetch_balance(self, code: str) -> List[BalanceSheet]:
        symbol = _to_akshare_symbol(code)
        try:
            df = ak.stock_balance_sheet_by_report_em(symbol=symbol)
        except Exception as e:
            logger.error(f"获取资产负债表失败 {code}: {e}")
            return []
        return _df_to_models(df, BalanceSheet)

    def fetch_cashflow(self, code: str) -> List[CashFlow]:
        symbol = _to_akshare_symbol(code)
        try:
            df = ak.stock_cash_flow_sheet_by_report_em(symbol=symbol)
        except Exception as e:
            logger.error(f"获取现金流量表失败 {code}: {e}")
            return []
        return _df_to_models(df, CashFlow)

    def fetch_indicator(self, code: str) -> List[FinancialIndicator]:
        symbol = _to_akshare_indicator_symbol(code)
        try:
            df = ak.stock_financial_analysis_indicator_em(symbol=symbol)
        except Exception as e:
            logger.error(f"获取财务指标失败 {code}: {e}")
            return []
        return _df_to_models(df, FinancialIndicator)
