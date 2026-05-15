from pathlib import Path
from typing import List

from backend.models.financial import (
    IncomeStatement,
    BalanceSheet,
    CashFlow,
    FinancialIndicator,
)
from backend.repositories.base import (
    read_parquet_as_models,
    write_models_as_parquet,
    append_models_to_parquet,
)


class FinancialRepository:
    """财务数据持久化 — 利润表/资产负债表/现金流量表/财务指标"""

    def __init__(self, financial_dir: Path):
        self._income_dir = financial_dir / "income"
        self._balance_dir = financial_dir / "balance"
        self._cashflow_dir = financial_dir / "cashflow"
        self._indicator_dir = financial_dir / "indicator"

    def _path(self, base_dir: Path, code: str) -> Path:
        return base_dir / f"{code}.parquet"

    def read_income(self, code: str) -> List[IncomeStatement]:
        return read_parquet_as_models(
            self._path(self._income_dir, code),
            IncomeStatement,
            sort_by="REPORT_DATE",
            ascending=False,
        )

    def write_income(self, code: str, records: List[IncomeStatement]) -> None:
        write_models_as_parquet(
            self._path(self._income_dir, code),
            records,
            sort_by="REPORT_DATE",
            ascending=False,
        )

    def append_income(self, code: str, new_records: List[IncomeStatement]) -> None:
        append_models_to_parquet(
            self._path(self._income_dir, code),
            new_records,
            IncomeStatement,
            dedup_key="REPORT_DATE",
            sort_by="REPORT_DATE",
            ascending=False,
        )

    def read_balance(self, code: str) -> List[BalanceSheet]:
        return read_parquet_as_models(
            self._path(self._balance_dir, code),
            BalanceSheet,
            sort_by="REPORT_DATE",
            ascending=False,
        )

    def write_balance(self, code: str, records: List[BalanceSheet]) -> None:
        write_models_as_parquet(
            self._path(self._balance_dir, code),
            records,
            sort_by="REPORT_DATE",
            ascending=False,
        )

    def append_balance(self, code: str, new_records: List[BalanceSheet]) -> None:
        append_models_to_parquet(
            self._path(self._balance_dir, code),
            new_records,
            BalanceSheet,
            dedup_key="REPORT_DATE",
            sort_by="REPORT_DATE",
            ascending=False,
        )

    def read_cashflow(self, code: str) -> List[CashFlow]:
        return read_parquet_as_models(
            self._path(self._cashflow_dir, code),
            CashFlow,
            sort_by="REPORT_DATE",
            ascending=False,
        )

    def write_cashflow(self, code: str, records: List[CashFlow]) -> None:
        write_models_as_parquet(
            self._path(self._cashflow_dir, code),
            records,
            sort_by="REPORT_DATE",
            ascending=False,
        )

    def append_cashflow(self, code: str, new_records: List[CashFlow]) -> None:
        append_models_to_parquet(
            self._path(self._cashflow_dir, code),
            new_records,
            CashFlow,
            dedup_key="REPORT_DATE",
            sort_by="REPORT_DATE",
            ascending=False,
        )

    def read_indicator(self, code: str) -> List[FinancialIndicator]:
        return read_parquet_as_models(
            self._path(self._indicator_dir, code),
            FinancialIndicator,
            sort_by="REPORT_DATE",
            ascending=False,
        )

    def write_indicator(self, code: str, records: List[FinancialIndicator]) -> None:
        write_models_as_parquet(
            self._path(self._indicator_dir, code),
            records,
            sort_by="REPORT_DATE",
            ascending=False,
        )

    def append_indicator(
        self, code: str, new_records: List[FinancialIndicator]
    ) -> None:
        append_models_to_parquet(
            self._path(self._indicator_dir, code),
            new_records,
            FinancialIndicator,
            dedup_key="REPORT_DATE",
            sort_by="REPORT_DATE",
            ascending=False,
        )
