"""Engine v2 端到端集成测(Phase 3.4)。

用 ``MaTangleValueStrategy`` + 真实 parquet (``data/market/A/daily/``) +
mock valuation/dividend/financial dict,跑 24 个月回测,断言:

- 返回结构完整(metrics / equity_curve / trades / log_dir)
- decisions.jsonl 存在且包含 ``strategy.screen.start`` flow 行
- equity_curve 长度 == 输入参考股的 bar 数
- 至少一笔 buy 成交(若 ma 缠绕在 24 个月内命中 — 允许 0)

CI 缺数据时按 plan §3.4 跳过。
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from backend import config
from services.backtest.engine import BacktestEngine
from services.backtest.strategies.deployed.ma_tangle_value_strategy import MaTangleValueStrategy


MARKET_DAILY_DIR = config.MARKET_DIR / "A" / "daily"

# 24 个月窗口(用相对最近的 2 年,避免依赖具体年份)
END_DATE = "2025-12-31"
START_DATE = "2024-01-01"


def _load_parquet(symbol_file: Path) -> pd.DataFrame:
    df = pd.read_parquet(symbol_file)
    # parquet 列含 OHLCV + 指标列;Engine 只需 date/open/high/low/close/volume/amount
    df = df[["date", "open", "high", "low", "close", "volume", "amount"]].copy()
    # 项目约定:date 为字符串
    if not isinstance(df["date"].iloc[0], str):
        df["date"] = df["date"].astype(str)
    return df


def _pick_symbols_with_history(n: int = 5) -> dict[str, pd.DataFrame]:
    """从 ``data/market/A/daily`` 中挑选窗口内有完整历史的前 ``n`` 只股票。"""
    chosen: dict[str, pd.DataFrame] = {}
    for f in sorted(MARKET_DAILY_DIR.glob("*.parquet")):
        df = _load_parquet(f)
        df = df[(df["date"] >= START_DATE) & (df["date"] <= END_DATE)]
        df = df.sort_values("date").reset_index(drop=True)
        # 24 月 ≈ 480 个交易日;放宽到 200 以容忍停牌
        if len(df) < 200:
            continue
        # 取 ticker 部分(000001.SZ → 000001.SZ);策略不关心 symbol 形式
        chosen[f.stem] = df
        if len(chosen) >= n:
            break
    return chosen


def _build_mock_valuation(symbols: list[str], start: str, end: str) -> dict:
    """每只股票一条早于 start 的 valuation 记录,Mock 值确保 PE*PB ∈ [0, 22]。
    English schema:peTTM / pbMRQ。"""
    out = {}
    for sym in symbols:
        out[sym] = pd.DataFrame([{"date": "2020-01-01", "peTTM": 10.0, "pbMRQ": 1.5}])
    return out


def _build_mock_dividend(symbols: list[str]) -> dict:
    """每只股票 6 个不同年度的现金分红记录,确保 ``min_dividend_years=5`` 通过。
    English schema:date / cash_dividend。"""
    rows = [
        {"date": f"{y}-12-31", "cash_dividend": 1.0}
        for y in (2018, 2019, 2020, 2021, 2022, 2023)
    ]
    out = {}
    for sym in symbols:
        out[sym] = pd.DataFrame(rows)
    return out


def _build_mock_financial(symbols: list[str]) -> dict:
    """每只股票一条 ROE=15 的财务记录,确保 ``min_roe=10`` 通过。
    English schema:REPORT_DATE / ROEJQ / EPSJB / PARENTNETPROFITTZ / TOTAL_SHARE。"""
    out = {}
    for sym in symbols:
        out[sym] = pd.DataFrame(
            [
                {
                    "REPORT_DATE": "2023-12-31",
                    "ROEJQ": 15.0,
                    "EPSJB": 1.0,
                    "PARENTNETPROFITTZ": 10.0,
                    "TOTAL_SHARE": 1_000_000_000,
                }
            ]
        )
    return out


@pytest.fixture(scope="module")
def real_stock_data() -> dict[str, pd.DataFrame]:
    if not MARKET_DAILY_DIR.exists():
        pytest.skip(f"real parquet missing: {MARKET_DAILY_DIR} (CI without data)")
    data = _pick_symbols_with_history(n=5)
    if len(data) < 2:
        pytest.skip(f"not enough symbols with >=200 bars in {START_DATE}..{END_DATE}")
    return data


def test_engine_v2_e2e_with_real_parquet(tmp_path, real_stock_data):
    symbols = list(real_stock_data.keys())
    valuation = _build_mock_valuation(symbols, START_DATE, END_DATE)
    dividend = _build_mock_dividend(symbols)
    financial = _build_mock_financial(symbols)

    strategy = MaTangleValueStrategy()
    log_dir = tmp_path / "e2e_run"

    engine = BacktestEngine(
        strategy=strategy,
        stock_data=real_stock_data,
        valuation_data=valuation,
        dividend_data=dividend,
        financial_data=financial,
        log_dir=log_dir,
        enable_decision_log=True,
    )
    result = engine.run()

    # 1) 返回结构完整
    assert set(result.keys()) >= {"metrics", "equity_curve", "trades", "log_dir"}
    assert isinstance(result["metrics"], dict)
    assert isinstance(result["equity_curve"], list)
    assert isinstance(result["trades"], list)
    assert result["log_dir"] == str(log_dir)

    # 2) equity_curve 长度 == 参考股 bar 数(MarketData.dates 取首只股票的日历)
    ref_sym = symbols[0]
    expected_bars = len(real_stock_data[ref_sym])
    assert len(result["equity_curve"]) == expected_bars

    # 3) decisions.jsonl + flow.jsonl 存在;flow 含 strategy.screen.start
    flow_file = log_dir / "flow.jsonl"
    decisions_file = log_dir / "decisions.jsonl"
    assert flow_file.exists(), "flow.jsonl 应在启用决策日志后写盘"
    assert decisions_file.exists(), "decisions.jsonl 应在启用决策日志后写盘"

    flow_lines = [
        json.loads(line) for line in flow_file.read_text().splitlines() if line
    ]
    stages = {rec.get("stage") for rec in flow_lines}
    assert "strategy.screen.start" in stages
    assert "strategy.screen.done" in stages

    # 4) 若 24 个月内有 ma_tangle_breakout 命中 → 至少一笔 buy 成交
    #    若 0 命中,允许零交易(plan §3.4 说"若数据命中")
    buy_trades = [t for t in result["trades"] if t["direction"] == "buy"]
    final_pass_records = [
        json.loads(line)
        for line in decisions_file.read_text().splitlines()
        if line and json.loads(line).get("stage") == "strategy.screen.final"
    ]
    if final_pass_records:
        assert buy_trades, "有最终选股信号时应当至少触发一笔买入"
