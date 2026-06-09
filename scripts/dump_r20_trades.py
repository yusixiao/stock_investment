"""导出 R20 策略每次调仓的持仓 + 推导买/卖动作。

R20 = PB<1 + 排ST + 排亏损(peTTM>0) + ROE>5% + 季度调仓(5/1, 9/1, 11/1)
      + top 15 + 排过去 6m 动量最差 20% + 等权
"""

from __future__ import annotations

import sys

import pandas as pd

sys.path.insert(0, "backend")
sys.path.insert(0, "scripts")

from services.duckdb_store import init_duckdb  # noqa: E402

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


def main():
    init_duckdb()
    START, END = "2010-05-01", "2025-12-31"

    print("加载估值面板 ...")
    val_panel = load_pe_pb_panel(START, END)
    print("加载 qfq 收盘价 ...")
    qfq = load_qfq_close_panel(START, END)
    print("加载 ROE ...")
    roe_panel = load_roe_panel(START, END)
    roe_lookup = build_roe_lookup(roe_panel)

    quarterly_dates = gen_rebalance_dates(qfq.index, [(5, 1), (9, 1), (11, 1)])
    print(f"调仓日 {len(quarterly_dates)} 次")

    sel = select_pb_roe_momentum(
        roe_lookup,
        qfq,
        roe_min=0.05,
        mom_lookback_days=120,
        drop_pct=0.2,
        top_n=15,
    )

    # 加载股票名称映射(可选,从 v_a_indicator 取)
    print("加载股票名称 ...")
    from services.duckdb_store import get_store

    name_map = {}
    try:
        df = (
            get_store()
            ._conn.execute(
                "SELECT DISTINCT _symbol, SECURITY_NAME_ABBR FROM v_a_indicator "
                "WHERE SECURITY_NAME_ABBR IS NOT NULL"
            )
            .fetchdf()
        )
        # 同 code 多条 → 取第一条
        name_map = dict(zip(df["_symbol"], df["SECURITY_NAME_ABBR"]))
    except Exception as e:
        print(f"名称加载失败:{e}")

    res = run_backtest(val_panel, qfq, quarterly_dates, sel, weight_fn=equal_weight)
    m = metrics(res.equity)
    print(
        f"\n[校验] R20: CAGR={m['CAGR']:.2%}  total={m['total_return']:.1%}  "
        f"DD={m['max_drawdown']:.1%}  Sharpe={m['sharpe']:.2f}\n"
    )

    # holdings_log: date / codes
    holdings = res.holdings_log
    holdings = holdings.sort_values("date").reset_index(drop=True)

    # 推导买/卖事件
    events = []  # date, code, name, action(BUY/SELL/HOLD)
    prev_set: set[str] = set()
    for _, row in holdings.iterrows():
        d = row["date"]
        cur = set(row["codes"])
        for c in cur - prev_set:
            events.append(
                {"date": d, "action": "BUY", "code": c, "name": name_map.get(c, "")}
            )
        for c in prev_set - cur:
            events.append(
                {"date": d, "action": "SELL", "code": c, "name": name_map.get(c, "")}
            )
        for c in cur & prev_set:
            events.append(
                {"date": d, "action": "HOLD", "code": c, "name": name_map.get(c, "")}
            )
        prev_set = cur
    # 最后一次回测期末:把仍持有的标记为 STILL_HELD(用户视角是浮动持仓)
    if prev_set:
        last_date = holdings["date"].iloc[-1]
        # 已经在最后一次调仓里被标记了 BUY/HOLD,无需重复

    ev_df = pd.DataFrame(events)

    # 1) 调仓日持仓清单
    print("=" * 80)
    print(
        f"R20 全部调仓 {len(holdings)} 次,导出 /tmp/r20_holdings.csv 和 /tmp/r20_events.csv"
    )
    print("=" * 80)

    # 把 holdings 展开成长格式存
    rows = []
    for _, row in holdings.iterrows():
        for c in row["codes"]:
            rows.append({"date": row["date"], "code": c, "name": name_map.get(c, "")})
    holdings_long = pd.DataFrame(rows)
    holdings_long.to_csv("/tmp/r20_holdings.csv", index=False, encoding="utf-8-sig")
    ev_df.to_csv("/tmp/r20_events.csv", index=False, encoding="utf-8-sig")

    # 2) 打印前 3 次和后 3 次调仓详情(看个直觉)
    print("\n>>> 前 3 次调仓持仓:")
    for _, row in holdings.head(3).iterrows():
        names = [f"{c}({name_map.get(c, '?')})" for c in row["codes"]]
        print(f"  [{row['date']}] {len(row['codes'])} 只: {', '.join(names)}")

    print("\n>>> 后 3 次调仓持仓:")
    for _, row in holdings.tail(3).iterrows():
        names = [f"{c}({name_map.get(c, '?')})" for c in row["codes"]]
        print(f"  [{row['date']}] {len(row['codes'])} 只: {', '.join(names)}")

    # 3) 出现频率最高的股票(全周期"最爱")
    print("\n>>> 全周期出现频率 TOP 20(共参选次数):")
    code_freq = holdings_long["code"].value_counts().head(20)
    for code, cnt in code_freq.items():
        print(
            f"  {code} ({name_map.get(code, '?')}): {cnt} 次入选 (共 {len(holdings)} 次调仓)"
        )

    # 4) 按动作分类的事件统计
    print("\n>>> 事件统计(按调仓日累计):")
    print(f"  BUY 总次数: {(ev_df['action'] == 'BUY').sum()}")
    print(f"  SELL 总次数: {(ev_df['action'] == 'SELL').sum()}")
    print(f"  HOLD(连续持有过渡)总次数: {(ev_df['action'] == 'HOLD').sum()}")

    # 5) 持仓时长分布(连续 BUY → SELL 间隔多少次调仓)
    print("\n>>> 持仓时长(单笔 BUY 到 SELL 之间跨多少次调仓):")
    holding_periods = []
    open_pos: dict[str, str] = {}  # code → buy_date
    for _, ev in ev_df.iterrows():
        if ev["action"] == "BUY":
            open_pos[ev["code"]] = ev["date"]
        elif ev["action"] == "SELL" and ev["code"] in open_pos:
            buy_d = open_pos.pop(ev["code"])
            sell_d = ev["date"]
            days = (pd.to_datetime(sell_d) - pd.to_datetime(buy_d)).days
            holding_periods.append(days)
    if holding_periods:
        s = pd.Series(holding_periods)
        print(
            f"  样本 {len(s)} 笔,中位数={s.median():.0f}d,均值={s.mean():.0f}d,"
            f"min={s.min()}d,max={s.max()}d,p25={s.quantile(0.25):.0f}d,p75={s.quantile(0.75):.0f}d"
        )

    print("\n输出:")
    print("  /tmp/r20_holdings.csv  - 每次调仓日的完整持仓(date,code,name 长格式)")
    print("  /tmp/r20_events.csv    - 完整 BUY/SELL/HOLD 事件流")


if __name__ == "__main__":
    main()
