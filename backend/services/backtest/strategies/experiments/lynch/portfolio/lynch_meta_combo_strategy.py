#!/usr/bin/env python3
"""林奇多腿组合 · 共享单账户元策略 (Exp-3)。

把 N 条已定型的林奇子策略(slow_growers / turnarounds / asset_plays / ...)组合进
**同一个回测账户**:一份现金、按目标权重分配、重叠持仓自动净额合并、真实计交易成本。

与 Exp-2 的本质区别
--------------------
- Exp-2 = 各腿独立满仓回测取「逐日净值曲线」→ 按目标权重「月度再平衡」在净值层加权混合。
  它**不含**共享现金约束 / 跨腿再平衡换手成本 / 重叠持仓去重, 是**乐观估计**。
- 本元策略 = **单账户真回测**: 一份现金池、整手约束、T+1、佣金万3+印花税千一、滑点,
  各腿目标权重在同一账户内竞争现金, 重叠标的净额合并 —— 得出**可部署的真实数字**。

机制
----
- ``frequency="monthly"``: 引擎每月首个 bar 调一次 ``screen()``; ``screen()`` 内部再逐一调用
  各子策略的 ``screen()``。各子策略按自身 ``rebalance_months`` 自门控(非调仓月返回 [] 但
  **保留**上次 ``_target_holdings``), 故随时可从其 ``_target_holdings`` 读出「当前想持有的组合」。
- 组合目标权重: 对子策略 i, 每标的目标仓位份额 = ``W_i × exposure_i / len(holdings_i)``;
  重叠标的跨腿相加。Σ 全部目标 = Σ_i W_i×exposure_i ≤ 1(不加杠杆)。
- ``rebalance_mode``:
  - ``"monthly"``: 每月把所有目标标的用 ``order_target_percent`` 重置到目标权重(维持精确权重,
    换手最高, 最贴近 Exp-2 的「月度再平衡」口径)。
  - ``"on_change"``: 仅当某标的目标权重份额较上月变化时才交易(即某条腿在其调仓月改变了持仓/
    仓位), 其余标的任其随价格漂移(换手最低, 最贴近各腿独立行为)。
- ``on_sell`` 先行清掉已不在组合目标里的持仓; ``on_buy`` 建/调仓。二者均受 ``_pending`` 门控
  (引擎每根 bar 都调 on_sell/on_buy, 故必须像各腿一样只在「本月已算出新目标」的那根 bar 执行)。
"""
from collections import defaultdict

from services.backtest.strategy_base import Strategy


class LynchMetaComboStrategy(Strategy):
    name = "林奇多腿组合(共享账户)"
    description = "多条林奇子策略合入单一回测账户: 目标权重分配 + 重叠净额合并 + 真实成本"
    params: dict = {}
    frequency = "monthly"
    frequency_overridable = False

    def __init__(
        self,
        legs,
        weights,
        rebalance_mode: str = "monthly",
        param_overrides: dict | None = None,
    ):
        """
        legs: list[(name, strategy_instance)] —— 已实例化的子策略(各自 champion 参数)
        weights: dict[name -> W] —— 各腿资金权重(和应 ≤ 1)
        rebalance_mode: "monthly" | "on_change"
        """
        super().__init__(param_overrides)
        if rebalance_mode not in ("monthly", "on_change"):
            raise ValueError(f"bad rebalance_mode: {rebalance_mode}")
        self._legs = list(legs)
        self._weights = dict(weights)
        self._mode = rebalance_mode
        self._combined: dict[str, float] = {}      # sym -> 目标权重份额(占总权益)
        self._prev_target: dict[str, float] = {}   # 上月的 _combined(on_change 用)
        self._pending: bool = False                # 本月是否已算出新目标待执行

    # ---- screen: 每月合成组合目标权重 ----
    def screen(self, ctx, symbols: list[str]) -> list[str]:
        combined: dict[str, float] = defaultdict(float)
        for name, strat in self._legs:
            # 跑子策略 screen 以更新其内部 _target_holdings / _target_exposure;返回值不用
            strat.screen(ctx, symbols)
            holdings = list(getattr(strat, "_target_holdings", []) or [])
            if not holdings:
                continue
            exposure = float(getattr(strat, "_target_exposure", 1.0))
            w_leg = float(self._weights.get(name, 0.0))
            if w_leg <= 0 or exposure <= 0:
                continue
            per = w_leg * exposure / len(holdings)
            for sym in holdings:
                combined[sym] += per
        self._combined = dict(combined)
        self._pending = True
        ctx.log_flow(
            "meta.screen.done",
            legs=len(self._legs),
            targets=len(self._combined),
            gross=round(sum(self._combined.values()), 4),
        )
        return list(self._combined.keys())

    # ---- on_sell: 清掉已不在组合目标里的持仓 ----
    def on_sell(self, ctx) -> None:
        if not self._pending:
            return
        target = self._combined
        for sym, pos in list(ctx.get_positions().items()):
            shares = pos.shares if hasattr(pos, "shares") else pos.get("shares", 0)
            if shares <= 0:
                continue
            if sym not in target:
                ctx.order_shares(sym, -int(shares))
                try:
                    ctx.target_symbols.discard(sym)
                except AttributeError:
                    pass

    # ---- on_buy: 建/调仓到组合目标权重 ----
    def on_buy(self, ctx) -> None:
        if not self._pending:
            return
        target = self._combined
        prev = self._prev_target
        for sym, w in target.items():
            # on_change: 份额较上月未变 → 任其随价格漂移, 本月不交易
            if self._mode == "on_change" and abs(w - prev.get(sym, 0.0)) < 1e-9:
                continue
            ctx.order_target_percent(sym, w)
        self._prev_target = dict(target)
        self._pending = False
