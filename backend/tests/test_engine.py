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

from services.backtest.engine import BacktestEngine
from strategies.base import Strategy


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


def test_engine_writes_run_lifecycle_flow_records(tmp_path, stock_data):
    """flow.jsonl 应包含 engine.run.start / engine.run.done 事件,
    含 strategy 名、参数、bars、trades 等字段,便于离线追溯。"""
    log_dir = tmp_path / "lifecycle"
    BacktestEngine(
        strategy=_LoggingStrategy(),
        stock_data=stock_data,
        log_dir=log_dir,
        enable_decision_log=True,
    ).run()
    flow_lines = [
        json.loads(line)
        for line in (log_dir / "flow.jsonl").read_text().splitlines()
        if line
    ]
    stages = {rec["stage"] for rec in flow_lines}
    assert "engine.run.start" in stages
    assert "engine.run.done" in stages
    start = next(r for r in flow_lines if r["stage"] == "engine.run.start")
    assert start["counts"]["strategy"] == "_LoggingStrategy"
    assert start["counts"]["bars"] > 0


def test_engine_writes_exec_log_on_fills(tmp_path, stock_data, daily_dates):
    """成交事件应写入 exec.jsonl(策略侧无法捕获 T+1 撮合,由 engine 兜底)。"""

    class _BuyOnce(Strategy):
        frequency = "daily"

        def __init__(self):
            super().__init__()
            self.bought = False

        def screen(self, ctx, symbols):
            return list(symbols)

        def on_buy(self, ctx):
            if not self.bought and "000001" in ctx.target_symbols:
                ctx.order_shares("000001", 100)
                self.bought = True

    log_dir = tmp_path / "exec_run"
    BacktestEngine(
        strategy=_BuyOnce(),
        stock_data=stock_data,
        log_dir=log_dir,
        enable_decision_log=True,
    ).run()
    exec_path = log_dir / "exec.jsonl"
    assert exec_path.exists()
    lines = [json.loads(line) for line in exec_path.read_text().splitlines() if line]
    assert len(lines) == 1
    rec = lines[0]
    assert rec["action"] == "buy"
    assert rec["symbol"] == "000001"
    assert rec["shares"] == 100
    assert rec["ts"] == daily_dates[1]


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


# ============= 实际下单 + T+1 撮合 =============


def test_engine_order_shares_fills_next_bar(stock_data, daily_dates):
    """on_buy 中 ctx.order_shares 应在下一根 bar 通过 fill_orders 成交(T+1)。

    回归 T3.1 遗留 bug:Context.order_shares 之前误传 date 给 broker.submit_order,
    且未传 direction → 调用直接抛 TypeError。
    """

    class _BuyOnce(Strategy):
        frequency = "daily"

        def __init__(self):
            super().__init__()
            self.bought = False

        def screen(self, ctx, symbols):
            return list(symbols)

        def on_buy(self, ctx):
            if not self.bought and "000001" in ctx.target_symbols:
                ctx.order_shares("000001", 100)
                self.bought = True

    strat = _BuyOnce()
    result = BacktestEngine(
        strategy=strat, stock_data=stock_data, enable_decision_log=False
    ).run()
    # 只买不卖 → round-trip 为空,但原始单边事件保留在 raw_trades
    assert result["trades"] == []
    raw = result["raw_trades"]
    assert len(raw) == 1
    trade = raw[0]
    assert trade["symbol"] == "000001"
    assert trade["direction"] == "buy"
    assert trade["shares"] == 100
    # T+1:bar 0 提交,bar 1 成交,所以成交日 == daily_dates[1]
    assert trade["date"] == daily_dates[1]
    # end_prices 含交易过的 symbol → 回测结束日的收盘价(strict=False,允许非交易日回退到上一交易日)
    end_prices = result["end_prices"]
    assert "000001" in end_prices
    assert isinstance(end_prices["000001"], float)
    # 未交易过的 symbol 不在 end_prices 里(节省 payload)
    assert "000002" not in end_prices


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


# ============= iter window(2026-05-22 引入)=============


def test_engine_iter_window_limits_main_loop(stock_data, daily_dates):
    """iter_start/iter_end 限定主循环范围,equity_curve 长度 = 窗口大小。"""
    strategy = Strategy()
    eng = BacktestEngine(
        strategy=strategy,
        stock_data=stock_data,
        iter_start=10,
        iter_end=15,
    )
    result = eng.run()
    # 闭区间 [10, 15] = 6 根 bar
    assert len(result["equity_curve"]) == 6
    assert result["equity_curve"][0]["date"] == daily_dates[10]
    assert result["equity_curve"][-1]["date"] == daily_dates[15]


def test_engine_iter_window_default_full_history(stock_data, daily_dates):
    """未传 iter window → 跑全历史(向后兼容)。"""
    strategy = Strategy()
    eng = BacktestEngine(strategy=strategy, stock_data=stock_data)
    result = eng.run()
    assert len(result["equity_curve"]) == len(daily_dates)


def test_engine_progress_uses_iter_window_size(stock_data):
    """on_progress 的 total = 迭代窗口大小,不是全历史。"""
    progress_calls: list[tuple[int, int]] = []

    def on_progress(cur, total):
        progress_calls.append((cur, total))

    eng = BacktestEngine(
        strategy=Strategy(),
        stock_data=stock_data,
        iter_start=20,
        iter_end=24,
        on_progress=on_progress,
    )
    eng.run()
    assert len(progress_calls) == 5
    assert progress_calls[-1] == (5, 5)


def test_run_scan_writes_decision_log(tmp_path, stock_data):
    """run_scan 接 log_sink 后,helper 内 log_pass/log_reject 应当落盘
    (修复 ScreenContext 空 pass bug,2026-05-22)。"""

    class MyScreener(Strategy):
        name = "test_screener"
        frequency = "daily"

        def screen(self, ctx, symbols):
            for s in symbols:
                ctx.log_pass(s, "test_stage", value=1)
            ctx.log_flow("test_stage", input=len(symbols), passed=len(symbols))
            return list(symbols)

    log_dir = tmp_path / "scan_log"
    eng = BacktestEngine(
        strategy=MyScreener(),
        stock_data=stock_data,
        iter_start=0,
        iter_end=2,
        log_dir=log_dir,
    )
    eng.run_scan()

    # 只要日志目录里写了内容即视为通过(不依赖具体文件名)
    files = list(log_dir.rglob("*.jsonl"))
    assert files, "decision log 文件未生成"
    contents = "\n".join(p.read_text() for p in files)
    assert "test_stage" in contents
