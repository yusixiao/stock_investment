"""把 R20 的 BUY/SELL 事件展开成「每笔交易一行」的明细账。

口径:
- 初始资金 1,000,000 RMB
- 调仓日 D 计算当时组合权益 equity_t,新开仓位 amount = equity_t / N(N=持仓数,等权)
- BUY:记买入价 = 当日 qfq close,amount(元)= 该次分配的资金,shares = amount / buy_price
- SELL:记卖出价 = 当日 qfq close,profit = (sell - buy) × shares
- HOLD(跨调仓继续持有)不出行(简化:不计中间再平衡微调)
- 期末仍持有的:输出 SELL 行,sell_price 用 2025-12-31 收盘价(浮动盈亏 → unrealized)
"""

from __future__ import annotations

import sys

import pandas as pd

sys.path.insert(0, "backend")
sys.path.insert(0, "scripts")

from services.duckdb_store import init_duckdb, get_store  # noqa: E402

from backtest_low_pb_value import (  # noqa: E402
    build_roe_lookup,
    equal_weight,
    gen_rebalance_dates,
    load_pe_pb_panel,
    load_qfq_close_panel,
    load_roe_panel,
    metrics,
    run_backtest,
    select_pb_roe_momentum,
)


INIT_CAPITAL = 1_000_000.0


def main():
    init_duckdb()
    START, END = "2010-05-01", "2025-12-31"

    print("加载数据 ...")
    val_panel = load_pe_pb_panel(START, END)
    qfq = load_qfq_close_panel(START, END)
    roe_panel = load_roe_panel(START, END)
    roe_lookup = build_roe_lookup(roe_panel)
    quarterly_dates = gen_rebalance_dates(qfq.index, [(5, 1), (9, 1), (11, 1)])

    sel = select_pb_roe_momentum(
        roe_lookup,
        qfq,
        roe_min=0.05,
        mom_lookback_days=120,
        drop_pct=0.2,
        top_n=15,
    )

    # 名称映射
    name_map: dict[str, str] = {}
    try:
        df = (
            get_store()
            ._conn.execute(
                "SELECT DISTINCT _symbol, SECURITY_NAME_ABBR FROM v_a_indicator "
                "WHERE SECURITY_NAME_ABBR IS NOT NULL"
            )
            .fetchdf()
        )
        name_map = dict(zip(df["_symbol"], df["SECURITY_NAME_ABBR"]))
    except Exception as e:
        print(f"名称加载失败:{e}")

    res = run_backtest(val_panel, qfq, quarterly_dates, sel, weight_fn=equal_weight)
    m = metrics(res.equity)
    print(
        f"\n[校验] R20: CAGR={m['CAGR']:.2%}  total={m['total_return']:.1%}  "
        f"DD={m['max_drawdown']:.1%}  Sharpe={m['sharpe']:.2f}\n"
    )

    eq = res.equity  # 归一化权益序列(初始 1.0)
    holdings = res.holdings_log.sort_values("date").reset_index(drop=True)

    # 把权益序列转成 Series(date 是字符串索引)
    eq_dict = eq.to_dict()

    # 逐次调仓推导事件 + 价格 + 仓位金额
    open_pos: dict[str, dict] = {}  # code → {buy_date, buy_price, shares, amount}
    rows: list[dict] = []
    prev_codes: set[str] = set()

    for _, row in holdings.iterrows():
        d = row["date"]
        cur = set(row["codes"])
        # 当日组合权益(元)
        equity_at_d = eq_dict.get(d, 1.0) * INIT_CAPITAL
        n = len(cur)

        # 1) SELL — 不再持有的标的,先卖出(释放资金)
        for c in prev_codes - cur:
            pos = open_pos.pop(c, None)
            if pos is None:
                continue
            sell_price = (
                float(qfq.at[d, c]) if c in qfq.columns and d in qfq.index else None
            )
            if sell_price is None or pd.isna(sell_price):
                continue
            profit = (sell_price - pos["buy_price"]) * pos["shares"]
            rows.append(
                {
                    "date": d,
                    "action": "SELL",
                    "code": c,
                    "name": name_map.get(c, ""),
                    "buy_price": "",
                    "sell_price": round(sell_price, 4),
                    "amount": round(pos["amount"], 2),
                    "profit": round(profit, 2),
                }
            )

        # 2) BUY — 新进入的标的
        for c in cur - prev_codes:
            if c not in qfq.columns or d not in qfq.index:
                continue
            buy_price = float(qfq.at[d, c])
            if pd.isna(buy_price) or buy_price <= 0:
                continue
            amount = equity_at_d / n  # 等权,每只 = 当时总权益 / N
            shares = amount / buy_price
            open_pos[c] = {
                "buy_date": d,
                "buy_price": buy_price,
                "shares": shares,
                "amount": amount,
            }
            rows.append(
                {
                    "date": d,
                    "action": "BUY",
                    "code": c,
                    "name": name_map.get(c, ""),
                    "buy_price": round(buy_price, 4),
                    "sell_price": "",
                    "amount": round(amount, 2),
                    "profit": "",
                }
            )

        prev_codes = cur

    # 期末仍持有的标的:用最后一日收盘价"账面平仓"
    last_d = qfq.index[-1]
    for c, pos in open_pos.items():
        if c not in qfq.columns:
            continue
        sell_price = float(qfq.at[last_d, c])
        if pd.isna(sell_price):
            continue
        profit = (sell_price - pos["buy_price"]) * pos["shares"]
        rows.append(
            {
                "date": last_d,
                "action": "SELL(期末)",
                "code": c,
                "name": name_map.get(c, ""),
                "buy_price": "",
                "sell_price": round(sell_price, 4),
                "amount": round(pos["amount"], 2),
                "profit": round(profit, 2),
            }
        )

    df = pd.DataFrame(
        rows,
        columns=[
            "date",
            "action",
            "code",
            "name",
            "buy_price",
            "sell_price",
            "amount",
            "profit",
        ],
    )
    df.to_csv("/tmp/r20_ledger.csv", index=False, encoding="utf-8-sig")

    # 汇总:总盈亏(只算已平仓的) + 总交易笔数
    closed_profits = [
        r["profit"] for r in rows if isinstance(r.get("profit"), (int, float))
    ]
    print(f"总记账行数:{len(rows)} 行")
    print(f"  BUY:    {sum(1 for r in rows if r['action'] == 'BUY')} 笔")
    print(f"  SELL:   {sum(1 for r in rows if r['action'] == 'SELL')} 笔(已平仓)")
    print(
        f"  SELL(期末): {sum(1 for r in rows if r['action'] == 'SELL(期末)')} 笔(回测结束账面)"
    )
    if closed_profits:
        s = pd.Series(closed_profits)
        print(f"\n所有 SELL(含期末)合计盈亏:{s.sum():,.2f} 元")
        print(f"  胜率:{(s > 0).mean():.1%}")
        print(f"  单笔盈利平均:{s[s > 0].mean():,.2f} 元")
        print(f"  单笔亏损平均:{s[s < 0].mean():,.2f} 元")
        print(f"  最大盈利:{s.max():,.2f} 元")
        print(f"  最大亏损:{s.min():,.2f} 元")

    print("\n=== 前 15 行预览 ===")
    print(df.head(15).to_string(index=False))
    print("\n=== 后 15 行预览(含期末账面平仓) ===")
    print(df.tail(15).to_string(index=False))

    print(f"\n完整账本 → /tmp/r20_ledger.csv ({len(df)} 行)")


if __name__ == "__main__":
    main()
