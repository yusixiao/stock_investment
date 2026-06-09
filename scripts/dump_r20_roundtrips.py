"""基于 /tmp/r20_ledger.csv 派生两份汇总:

1) /tmp/r20_roundtrips.csv  — 每笔 round-trip 一行(BUY+SELL 合并)
   字段:code | name | buy_date | sell_date | buy_price | sell_price |
        amount | shares | hold_days | profit | return_pct | status

2) /tmp/r20_per_stock.csv   — 每只股票一行(汇总该 code 所有 round-trip)
   字段:code | name | n_trades | total_amount(累计投入) |
        realized_profit | unrealized_profit | total_profit |
        win_rate | weighted_return_pct
"""

from __future__ import annotations

import pandas as pd

LEDGER = "/tmp/r20_ledger.csv"
OUT_RT = "/tmp/r20_roundtrips.csv"
OUT_STOCK = "/tmp/r20_per_stock.csv"


def main():
    df = pd.read_csv(LEDGER, dtype={"code": str})
    # 把空字符串转 NaN,数值列转 float
    for col in ["buy_price", "sell_price", "amount", "profit"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # ---- 1) 配对成 round-trip ----
    # 每个 code 按 date 排序,FIFO 配对 BUY ↔ SELL/SELL(期末)
    rt_rows = []
    for code, g in df.sort_values(["code", "date"]).groupby("code"):
        name = g["name"].iloc[0] if not g.empty else ""
        buys = []  # 队列:存待平仓 BUY
        for _, r in g.iterrows():
            if r["action"] == "BUY":
                buys.append(r)
            elif r["action"] in ("SELL", "SELL(期末)"):
                if not buys:
                    continue  # 不该发生
                b = buys.pop(0)
                shares = b["amount"] / b["buy_price"] if b["buy_price"] else 0
                hold_days = (pd.to_datetime(r["date"]) - pd.to_datetime(b["date"])).days
                ret_pct = (
                    (r["sell_price"] / b["buy_price"] - 1) if b["buy_price"] else 0
                )
                status = "已实现" if r["action"] == "SELL" else "未实现(期末)"
                rt_rows.append(
                    {
                        "code": code,
                        "name": name,
                        "buy_date": b["date"],
                        "sell_date": r["date"],
                        "buy_price": round(b["buy_price"], 4),
                        "sell_price": round(r["sell_price"], 4),
                        "amount": round(b["amount"], 2),
                        "shares": round(shares, 2),
                        "hold_days": hold_days,
                        "profit": round(r["profit"], 2),
                        "return_pct": round(ret_pct * 100, 2),
                        "status": status,
                    }
                )

    rt = pd.DataFrame(rt_rows)
    rt = rt.sort_values(["buy_date", "code"]).reset_index(drop=True)
    rt.to_csv(OUT_RT, index=False, encoding="utf-8-sig")

    # ---- 2) 每只股票汇总 ----
    grp = rt.groupby(["code", "name"], as_index=False)
    per_stock = grp.agg(
        n_trades=("profit", "size"),
        total_amount=("amount", "sum"),
        total_profit=("profit", "sum"),
        n_win=("profit", lambda s: int((s > 0).sum())),
    )
    # 已实现 / 未实现 拆分
    realized = (
        rt[rt["status"] == "已实现"]
        .groupby("code", as_index=False)["profit"]
        .sum()
        .rename(columns={"profit": "realized_profit"})
    )
    unrealized = (
        rt[rt["status"] == "未实现(期末)"]
        .groupby("code", as_index=False)["profit"]
        .sum()
        .rename(columns={"profit": "unrealized_profit"})
    )
    per_stock = per_stock.merge(realized, on="code", how="left").merge(
        unrealized, on="code", how="left"
    )
    per_stock["realized_profit"] = per_stock["realized_profit"].fillna(0).round(2)
    per_stock["unrealized_profit"] = per_stock["unrealized_profit"].fillna(0).round(2)
    per_stock["total_profit"] = per_stock["total_profit"].round(2)
    per_stock["total_amount"] = per_stock["total_amount"].round(2)
    per_stock["win_rate"] = (per_stock["n_win"] / per_stock["n_trades"] * 100).round(1)
    # 资金加权收益率 = total_profit / total_amount
    per_stock["weighted_return_pct"] = (
        per_stock["total_profit"] / per_stock["total_amount"] * 100
    ).round(2)
    per_stock = per_stock.sort_values("total_profit", ascending=False).reset_index(
        drop=True
    )
    per_stock = per_stock[
        [
            "code",
            "name",
            "n_trades",
            "total_amount",
            "realized_profit",
            "unrealized_profit",
            "total_profit",
            "win_rate",
            "weighted_return_pct",
        ]
    ]
    # 中文表头(导出 CSV 用)
    per_stock_cn = per_stock.rename(
        columns={
            "code": "代码",
            "name": "名称",
            "n_trades": "交易笔数",
            "total_amount": "累计投入金额",
            "realized_profit": "已实现利润",
            "unrealized_profit": "未实现利润",
            "total_profit": "总利润",
            "win_rate": "胜率(%)",
            "weighted_return_pct": "资金加权收益率(%)",
        }
    )
    per_stock_cn.to_csv(OUT_STOCK, index=False, encoding="utf-8-sig")

    # round-trip 明细同步加中文表头(覆盖之前英文版)
    rt_cn = rt.rename(
        columns={
            "code": "代码",
            "name": "名称",
            "buy_date": "买入日期",
            "sell_date": "卖出日期",
            "buy_price": "买入价",
            "sell_price": "卖出价",
            "amount": "投入金额",
            "shares": "股数",
            "hold_days": "持有天数",
            "profit": "盈亏(元)",
            "return_pct": "收益率(%)",
            "status": "状态",
        }
    )
    rt_cn.to_csv(OUT_RT, index=False, encoding="utf-8-sig")

    # ---- 控制台预览 ----
    print(f"Round-trip 总数:{len(rt)} 笔")
    print(f"  已实现:    {(rt['status'] == '已实现').sum()} 笔")
    print(f"  未实现(期末):{(rt['status'] == '未实现(期末)').sum()} 笔")
    realized_sum = rt[rt["status"] == "已实现"]["profit"].sum()
    unrealized_sum = rt[rt["status"] == "未实现(期末)"]["profit"].sum()
    print(f"\n累计盈亏:{rt['profit'].sum():,.2f} 元")
    print(f"  已实现部分:    {realized_sum:,.2f} 元")
    print(f"  未实现(账面):  {unrealized_sum:,.2f} 元")
    print(
        f"\n持有天数:中位 {rt['hold_days'].median():.0f}d, 均值 {rt['hold_days'].mean():.0f}d"
    )
    print(
        f"单笔收益率:中位 {rt['return_pct'].median():.2f}%, 均值 {rt['return_pct'].mean():.2f}%"
    )

    print("\n=== Round-trip 前 10 笔 ===")
    print(rt.head(10).to_string(index=False))

    print("\n=== 个股盈亏 TOP 15(按总盈亏降序) ===")
    print(per_stock.head(15).to_string(index=False))

    print("\n=== 个股盈亏 BOTTOM 10(亏损最多) ===")
    print(per_stock.tail(10).to_string(index=False))

    print(f"\n输出文件:")
    print(f"  {OUT_RT}     ({len(rt)} 行 round-trip)")
    print(f"  {OUT_STOCK}  ({len(per_stock)} 行 个股)")


if __name__ == "__main__":
    main()
