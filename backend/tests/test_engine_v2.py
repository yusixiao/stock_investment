"""BacktestEngine (engine_v2) 单测 — Phase 3.3。

覆盖 plan 规定的最小测试集合:
- 默认 Strategy(全 no-op)→ 资产 == 初始资本
- monthly 频率仅在跨月时触发 screen
- daily 频率每根 bar 都 screen
- on_sell 先于 on_buy,且 on_sell 移除的 symbol 不会出现在 on_buy 的 new_symbols 中
- target_symbols 跨 bar 累加
- 返回结构(metrics / equity_curve / trades / log_dir)
- log_dir 传入 + 策略写日志 → decisions.jsonl 存在
- enable_decision_log=False → 不写盘
- on_progress 每 bar 触发一次
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from services.backtest.base import Strategy
from services.backtest.engine_v2 import BacktestEngine


def _make_daily(dates: list[str], base: float = 10.0) -> pd.DataFrame:
    n = len(dates)
    return pd.DataFrame(
        {
            "date": dates,
            "open": [base + i for i in range(n)],
            "high": [base + i + 0.5 for i in range(n)],
            "low": [base + i - 0.5 for i in range(n)],
            "close": [base + i + 0.2 for i in range(n)],
            "volume": [1000.0 + i for i in range(n)],
            "amount": [10000.0 + i for i in range(n)],
        }
    )


@pytest.fixture
def daily_dates() -> list[str]:
    # 跨 3 个自然月,确保 monthly 周期切换至少触发 3 次
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2024-01-02", "2024-03-29")]


@pytest.fixture
def stock_data(daily_dates) -> dict[str, pd.DataFrame]:
    return {
        "000001": _make_daily(daily_dates, base=10.0),
        "600000": _make_daily(daily_dates, base=20.0),
    }


# ============= 默认 Strategy =============


def test_engine_runs_one_bar_with_default_strategy(stock_data, daily_dates):
    """默认 Strategy:screen 全通过、on_buy/on_sell no-op,资产 == 初始资本。"""
    engine = BacktestEngine(
        strategy=Strategy(),
        stock_data=stock_data,
        enable_decision_log=False,
    )
    result = engine.run()
    initial = Strategy().settings["initial_capital"]
    assert result["equity_curve"]
    last_eq = result["equity_curve"][-1]["total_value"]
    assert last_eq == pytest.approx(initial)
    assert result["trades"] == []


# ============= 频率切换 =============


class _ScreenCounter(Strategy):
    """记录 screen 触发的 bar idx。"""

    frequency = "daily"

    def __init__(self, *, frequency: str = "daily"):
        super().__init__()
        self.__class__.frequency = frequency
        # 实例级别覆盖,避免污染其他用例
        self.frequency = frequency
        self.calls: list[str] = []

    def screen(self, ctx, symbols):
        self.calls.append(ctx.current_date)
        return list(symbols)


def test_engine_calls_screen_every_bar_daily(stock_data, daily_dates):
    strat = _ScreenCounter(frequency="daily")
    BacktestEngine(
        strategy=strat, stock_data=stock_data, enable_decision_log=False
    ).run()
    assert len(strat.calls) == len(daily_dates)


def test_engine_calls_screen_only_on_period_switch_monthly(stock_data, daily_dates):
    strat = _ScreenCounter(frequency="monthly")
    BacktestEngine(
        strategy=strat, stock_data=stock_data, enable_decision_log=False
    ).run()
    # 跨月才触发,3 个自然月 → 3 次
    months = sorted({d[:7] for d in daily_dates})
    assert len(strat.calls) == len(months)
    # 每个月只调一次,且都落在该月内首个 bar
    called_months = [c[:7] for c in strat.calls]
    assert called_months == months


# ============= sell 先于 buy =============


class _OrderRecorder(Strategy):
    frequency = "daily"

    def __init__(self):
        super().__init__()
        self.events: list[tuple[str, str, list[str]]] = []  # (kind, date, new_symbols)

    def screen(self, ctx, symbols):
        return list(symbols)

    def on_sell(self, ctx):
        self.events.append(("sell", ctx.current_date, list(ctx.new_symbols)))
        # 模拟卖出:把第一个 target 移除,验证 buy 不会再看到它
        if ctx.target_symbols:
            sym = next(iter(sorted(ctx.target_symbols)))
            ctx.remove_target(sym)

    def on_buy(self, ctx):
        self.events.append(("buy", ctx.current_date, list(ctx.new_symbols)))


def test_engine_calls_on_sell_before_on_buy_each_bar(stock_data, daily_dates):
    strat = _OrderRecorder()
    BacktestEngine(
        strategy=strat, stock_data=stock_data, enable_decision_log=False
    ).run()
    # 每根 bar 顺序应为 sell, buy, sell, buy, ...
    kinds = [e[0] for e in strat.events]
    assert kinds[::2] == ["sell"] * len(daily_dates)
    assert kinds[1::2] == ["buy"] * len(daily_dates)


def test_engine_on_sell_remove_excludes_from_on_buy_new_symbols(stock_data):
    """on_sell 调 ctx.remove_target,on_buy 当 bar 不再看到该 symbol。"""

    class _S(Strategy):
        frequency = "daily"

        def __init__(self):
            super().__init__()
            self.buy_seen: list[list[str]] = []

        def on_sell(self, ctx):
            # 第一根 bar:000001 与 600000 都新增,卖掉 000001
            if "000001" in ctx.target_symbols:
                ctx.remove_target("000001")

        def on_buy(self, ctx):
            self.buy_seen.append(sorted(ctx.target_symbols))

    strat = _S()
    BacktestEngine(
        strategy=strat, stock_data=stock_data, enable_decision_log=False
    ).run()
    # 第一根 bar buyer 看到的 target 不含 000001(被 sell 移除)
    assert "000001" not in strat.buy_seen[0]


# ============= 累计池 =============


def test_engine_target_symbols_accumulates_across_bars(stock_data, daily_dates):
    """连续不同月命中不同股票,target_symbols 累加。"""

    class _S(Strategy):
        frequency = "monthly"

        def __init__(self):
            super().__init__()
            self.snapshots: list[set[str]] = []

        def screen(self, ctx, symbols):
            # 第一个月仅 000001,后续月仅 600000;target_symbols 应累加为两者
            month = ctx.current_date[:7]
            if month == "2024-01":
                return ["000001"]
            return ["600000"]

        def on_buy(self, ctx):
            self.snapshots.append(set(ctx.target_symbols))

    strat = _S()
    BacktestEngine(
        strategy=strat, stock_data=stock_data, enable_decision_log=False
    ).run()
    # 最后一根 bar 应当累加了两只
    assert strat.snapshots[-1] == {"000001", "600000"}


# ============= 返回结构 =============


def test_engine_returns_metrics_equity_curve_trades(stock_data, daily_dates):
    result = BacktestEngine(
        strategy=Strategy(),
        stock_data=stock_data,
        enable_decision_log=False,
    ).run()
    assert set(result.keys()) >= {"metrics", "equity_curve", "trades", "log_dir"}
    assert len(result["equity_curve"]) == len(daily_dates)
    assert isinstance(result["metrics"], dict)
    assert isinstance(result["trades"], list)


# ============= 决策日志 =============


class _LoggingStrategy(Strategy):
    frequency = "daily"

    def screen(self, ctx, symbols):
        ctx.log_flow("screen.start", input=len(symbols))
        for s in symbols:
            ctx.log_pass(s, "screen", reason_ok=True)
        return list(symbols)


def test_engine_writes_decision_log_when_log_dir_given(tmp_path, stock_data):
    log_dir = tmp_path / "run1"
    result = BacktestEngine(
        strategy=_LoggingStrategy(),
        stock_data=stock_data,
        log_dir=log_dir,
        enable_decision_log=True,
    ).run()
    decisions = log_dir / "decisions.jsonl"
    flow = log_dir / "flow.jsonl"
    assert decisions.exists()
    assert flow.exists()
    # 每行可解析为 JSON
    lines = [json.loads(line) for line in decisions.read_text().splitlines() if line]
    assert any(rec.get("decision") == "pass" for rec in lines)
    assert result["log_dir"] == str(log_dir)


def test_engine_disabled_log_does_not_write(tmp_path, stock_data):
    log_dir = tmp_path / "run2"
    result = BacktestEngine(
        strategy=_LoggingStrategy(),
        stock_data=stock_data,
        log_dir=log_dir,
        enable_decision_log=False,
    ).run()
    assert not (log_dir / "decisions.jsonl").exists()
    assert result["log_dir"] is None


# ============= 进度回调 =============


def test_on_progress_called_per_bar(stock_data, daily_dates):
    progress: list[tuple[int, int]] = []

    BacktestEngine(
        strategy=Strategy(),
        stock_data=stock_data,
        on_progress=lambda done, total: progress.append((done, total)),
        enable_decision_log=False,
    ).run()
    n = len(daily_dates)
    assert len(progress) == n
    assert progress[0] == (1, n)
    assert progress[-1] == (n, n)
