"""Small, self-contained market parquet fixture for DuckDB integration tests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from services.market_data import duckdb_store
from services.market_data.duckdb_store import DuckDBStore


SYMBOLS = {
    "A": ["002594.SZ"] + [f"60{i:04d}.SH" for i in range(1, 10)],
    "HK": ["00700.HK"] + [f"0{i:04d}.HK" for i in range(1, 10)],
    "US": ["AAPL"] + [f"US{i:04d}" for i in range(1, 10)],
}


def _write(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def _daily_frame(dates: pd.DatetimeIndex, seed: int) -> pd.DataFrame:
    close = 100.0 + seed + pd.Series(range(len(dates)), dtype=float) * 0.05
    return pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "open": close - 1.0,
            "high": close + 1.0,
            "low": close - 2.0,
            "close": close,
            "volume": 100000.0 + seed,
            "amount": close * (100000.0 + seed),
            "peTTM": 10.0,
            "pbMRQ": 1.5,
        }
    )


def _financial_frame(market: str, symbol: str, table: str) -> pd.DataFrame:
    dates = ["2023-12-31", "2024-12-31", "2025-12-31"]
    rows = []
    for i, report_date in enumerate(dates, 1):
        row: dict[str, object] = {"REPORT_DATE": report_date}
        if table == "indicator":
            row.update(
                {
                    "EPSJB": 2.0 + i,
                    "ROEJQ": 15.0,
                    "ROA": 8.0,
                    "ZZCJLL": 8.0,
                    "ROIC": 10.0,
                    "BPS": 20.0,
                    "DILUTED_EPS": 2.5,
                    "XSMLL": 30.0,
                    "XSJLL": 12.0,
                    "ZCFZL": 40.0,
                    "LD": 1.2,
                    "GROSS_PROFIT_YOY": 8.0,
                    "OPERATE_INCOME_YOY": 9.0,
                    "PARENT_NETPROFIT_YOY": 10.0,
                }
            )
            if market == "A":
                row.update(
                    {
                        "PARENTNETPROFIT": 1_000_000.0,
                        "TOTAL_SHARE": 1_000_000_000.0,
                        "FCFF_BACK": 2.0,
                        "PARENTNETPROFITTZ": 1_100_000.0,
                    }
                )
        elif table == "income":
            row.update(
                {
                    "PARENT_NETPROFIT": 1_000_000.0,
                    "NETPROFIT": 1_000_000.0,
                    "OPERATE_INCOME": 10_000_000.0,
                    "OPERATE_PROFIT": 1_500_000.0,
                    "TOTAL_PROFIT": 1_500_000.0,
                    "BASIC_EPS": 2.0,
                    "OPERATE_EXPENSE": 500_000.0,
                    "FINANCE_EXPENSE": 100_000.0,
                    "INCOME_TAX": 200_000.0,
                    "GROSS_PROFIT": 4_000_000.0,
                }
            )
            if market == "A":
                row.update(
                    {
                        "OPERATE_COST": 6_000_000.0,
                        "TOTAL_OPERATE_COST": 6_000_000.0,
                        "TOTAL_OPERATE_INCOME": 10_000_000.0,
                        "DEDUCT_PARENT_NETPROFIT": 900_000.0,
                    }
                )
            elif market == "US":
                row["DEDUCT_PARENT_NETPROFIT"] = 900_000.0
        elif table == "balance":
            row.update(
                {
                    "TOTAL_ASSETS": 20_000_000.0,
                    "TOTAL_LIABILITIES": 8_000_000.0,
                    "TOTAL_EQUITY": 12_000_000.0,
                    "TOTAL_PARENT_EQUITY": 12_000_000.0,
                    "FIXED_ASSET": 3_000_000.0,
                    "INTANGIBLE_ASSET": 500_000.0,
                    "INVENTORY": 1_000_000.0,
                    "ACCOUNTS_RECE": 800_000.0,
                    "SHARE_CAPITAL": 1_000_000_000.0,
                    "GOODWILL": 200_000.0,
                    "DEBT_ASSET_RATIO": 40.0,
                }
            )
            if market == "A":
                row.update({"MONETARYFUNDS": 5_000_000.0, "INDUSTRY_NAME": "制造业"})
            else:
                row.update(
                    {
                        "CASH_EQUIVALENTS": 5_000_000.0,
                        "CURRENT_ASSETS": 10_000_000.0,
                        "CURRENT_LIABILITIES": 5_000_000.0,
                    }
                )
        elif table == "cashflow":
            row.update(
                {
                    "NETCASH_OPERATE": 2_000_000.0,
                    "NETCASH_INVEST": -500_000.0,
                    "NETCASH_FINANCE": 100_000.0,
                    "BEGIN_CCE": 3_000_000.0,
                    "END_CCE": 4_600_000.0,
                    "CCE_ADD": 1_600_000.0,
                }
            )
            row["CONSTRUCT_LONG_ASSET" if market == "A" else "CAPEX"] = 500_000.0
            if market == "US":
                row["DEPRECIATION_AMORTIZATION"] = 100_000.0
        rows.append(row)
    return pd.DataFrame(rows)


def _create_market(root: Path, market: str) -> None:
    dates = pd.bdate_range("2024-01-02", periods=520)
    for seed, symbol in enumerate(SYMBOLS[market], 1):
        _write(root / market / "daily" / f"{symbol}.parquet", _daily_frame(dates, seed))
        _write(
            root / market / "adjust_factor" / f"{symbol}.parquet",
            pd.DataFrame(
                {
                    "dividOperateDate": dates.strftime("%Y-%m-%d"),
                    "foreAdjustFactor": 1.0,
                    "backAdjustFactor": 1.0,
                }
            ),
        )
        for table in ("indicator", "income", "balance", "cashflow"):
            _write(
                root / market / "financial" / table / f"{symbol}.parquet",
                _financial_frame(market, symbol, table),
            )
        _write(
            root / market / "dividend" / f"{symbol}.parquet",
            pd.DataFrame(
                {
                    "dividOperateDate": ["2023-06-30", "2024-06-30", "2025-06-30"],
                    "dividCashPsBeforeTax": [1.0, 1.1, 1.2],
                    "dividStocksPs": [0.0, 0.0, 0.0],
                    "dividRegistDate": ["2023-06-29", "2024-06-29", "2025-06-29"],
                    "dividPayDate": ["2023-07-01", "2024-07-01", "2025-07-01"],
                }
            ),
        )


def _create_index_and_membership(root: Path) -> None:
    _write(
        root / "HK" / "index" / "HSI.parquet",
        pd.DataFrame(
            {
                "date": ["2024-01-02", "2024-01-03"],
                "open": [17000.0, 17100.0],
                "high": [17200.0, 17300.0],
                "low": [16900.0, 17000.0],
                "close": [17100.0, 17200.0],
                "preclose": [16950.0, 17100.0],
                "volume": [1000.0, 1100.0],
                "amount": [0.0, 0.0],
                "pctChg": [0.8, 0.6],
            }
        ),
    )
    _write(
        root / "HK" / "membership" / "hk_connect.parquet",
        pd.DataFrame(
            {"code": ["00700"], "name": ["Tencent"], "board": ["main"], "as_of_date": ["2025-12-31"]}
        ),
    )


@pytest.fixture
def mini_market(tmp_path, monkeypatch) -> Path:
    """Create a complete, tiny three-market parquet tree and point DuckDB at it."""
    for market in ("A", "HK", "US"):
        _create_market(tmp_path, market)
    _create_index_and_membership(tmp_path)
    monkeypatch.setattr(duckdb_store, "MARKET_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def mini_store(mini_market):
    store = DuckDBStore()
    try:
        yield store
    finally:
        store.close()
