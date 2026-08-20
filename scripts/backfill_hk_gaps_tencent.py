"""用腾讯(gtimg)实际成交价回补 yfinance 港股「批量漏抓」缺口日的平bar。

背景(审计结论,见 claude-mem):yfinance auto_adjust=False 会在个别日期对一大批
活跃股注入「假平bar」(open=high=low=close=前收, volume=0),实际当天市场开市、这些
股有真实成交。全史扫描确认只有 3 个腾讯可达(~8yr 内)的危险缺口日:
    2024-01-15 / 2024-02-09 (各 ~301 只流动股, 67%, 严重)
    2020-03-17              (~60 只, 17%, 轻微)
本脚本只回补「流动集」(非平bar日 median(volume*close) > 1e7 且 nonflat_days >= 60,
共 ~574 只) 在这 3 天的平bar —— 已验证这些日 100% 真缺口、零误报。

尺度对齐(关键):v_hk_daily_raw 对 spinoff/拆股股(如 00700 因美团/京东分拆)做了
**乘法型后向调整**,与腾讯「不复权实际价」差一个因子 k。直接灌腾讯原始价会在缺口日造成
假跳空。故对每只股用「缺口日邻近的真实交易日」两源收盘比算 k = yf_close/tx_close,再把
腾讯价×k(回到 yfinance 尺度)、量/k(成交额守恒)。普通股 k≈1 为恒等。

自校验:腾讯查不到真实成交(无此日 或 high==low 且 vol==0)的股一律跳过(真停牌),
**不可能误补**。

安全:
  默认 dry-run —— 拉腾讯、算 patch、存 plan.json、打印预览,**不写盘**。
  --apply   —— 读 plan.json,先备份受影响 parquet 到 report/exported/hk_gapfix/backup/,
               再原地改行写回,最后验证(平bar 消失 / 价格对齐 / qfq 可重算)。

用法:
  python scripts/backfill_hk_gaps_tencent.py            # dry-run,出预览
  python scripts/backfill_hk_gaps_tencent.py --apply    # 从 plan.json 落盘(需先跑过 dry-run)
"""
import argparse
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

ROOT = Path("/Users/11182300/PycharmProjects/stock_investment")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
from services.market_data.duckdb_store import get_store  # noqa: E402

GAP_DAYS = ["2020-03-17", "2024-01-15", "2024-02-09"]
LIQ_TURNOVER = 1e7          # 流动集门槛:非平bar日成交额中位数 > 1e7 港元
LIQ_MIN_NONFLAT = 60        # 且至少 60 个非平bar交易日
N_NEIGHBORS = 5             # 算尺度因子 k 时每侧最多取的真实邻近交易日数
K_SPREAD_WARN = 1.02        # 邻近日 k 比值 max/min 超此值 -> 邻近可能有拆股,标记复核

DAILY_DIR = ROOT / "data" / "market" / "HK" / "daily"
OUT_DIR = ROOT / "report" / "exported" / "hk_gapfix"
PLAN_PATH = OUT_DIR / "plan.json"
BACKUP_DIR = OUT_DIR / "backup"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://gu.qq.com/",
}


def is_flat_row(o, h, low, c, v) -> bool:
    """yfinance 假平bar 判据:四价相等且量为 0。"""
    return o == h and h == low and low == c and v == 0


def find_flat_candidates() -> dict:
    """返回 {code: [gap_day, ...]} —— 流动集中、在各缺口日为平bar 的股票。"""
    store = get_store()
    con = store._conn
    con.execute("""
        CREATE OR REPLACE TEMP TABLE _base AS
        SELECT _symbol AS code, date,
               (open=high AND high=low AND low=close AND volume=0) AS is_flat,
               volume*close AS turnover
        FROM v_hk_daily_raw
    """)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE _liq AS
        SELECT code,
               median(CASE WHEN NOT is_flat THEN turnover END) AS med_turnover,
               COUNT(*) FILTER (WHERE NOT is_flat) AS nonflat_days
        FROM _base GROUP BY code
    """)
    days_sql = ",".join(f"'{d}'" for d in GAP_DAYS)
    df = con.execute(f"""
        SELECT b.code, b.date, l.med_turnover
        FROM _base b JOIN _liq l ON b.code = l.code
        WHERE b.date IN ({days_sql}) AND b.is_flat
          AND l.med_turnover > {LIQ_TURNOVER} AND l.nonflat_days >= {LIQ_MIN_NONFLAT}
        ORDER BY l.med_turnover DESC
    """).fetchdf()

    cand: dict = {}
    turnover: dict = {}
    for _, r in df.iterrows():
        cand.setdefault(r["code"], []).append(r["date"])
        turnover[r["code"]] = float(r["med_turnover"])
    return cand, turnover


def fetch_tencent(code: str, tries: int = 3) -> dict:
    """拉腾讯 day K线(最近 2000 根, ~8yr),返回 {date: (o, c, h, l, v)}。"""
    txc = "hk" + code.replace(".HK", "")
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={txc},day,,,2000,"
    last_err = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            rows = ((r.json().get("data") or {}).get(txc) or {}).get("day") or []
            out = {}
            for row in rows:
                # 腾讯 day 行: [date, open, close, high, low, volume, (amount...)]
                out[row[0]] = (float(row[1]), float(row[2]), float(row[3]),
                               float(row[4]), float(row[5]))
            return out
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"tencent fetch failed for {code}: {last_err}")


def nearest_real_neighbors(df: pd.DataFrame, gap_day: str, n: int):
    """在 yf parquet 里取 gap_day 两侧最近的非平bar交易日 (date, close),每侧最多 n 个。"""
    flat = (df["open"] == df["high"]) & (df["high"] == df["low"]) & \
           (df["low"] == df["close"]) & (df["volume"] == 0)
    df = df.assign(_flat=flat).sort_values("date").reset_index(drop=True)
    idx = df.index[df["date"] == gap_day]
    if len(idx) == 0:
        return []
    g = idx[0]
    res = []
    # 向前
    cnt = 0
    j = g - 1
    while j >= 0 and cnt < n:
        if not df.at[j, "_flat"]:
            res.append((df.at[j, "date"], float(df.at[j, "close"])))
            cnt += 1
        j -= 1
    # 向后
    cnt = 0
    j = g + 1
    while j < len(df) and cnt < n:
        if not df.at[j, "_flat"]:
            res.append((df.at[j, "date"], float(df.at[j, "close"])))
            cnt += 1
        j += 1
    return res


def build_plan() -> list:
    """dry-run 主体:对每只候选股拉腾讯、算 k、生成 patch 行。"""
    cand, turnover = find_flat_candidates()
    print(f"候选:流动集中在 {GAP_DAYS} 为平bar 的股票共 {len(cand)} 只 "
          f"(股次 {sum(len(v) for v in cand.values())})\n")

    plan = []
    codes = sorted(cand, key=lambda c: -turnover[c])
    for i, code in enumerate(codes, 1):
        fp = DAILY_DIR / f"{code}.parquet"
        if not fp.exists():
            print(f"  [{i}/{len(codes)}] {code}: parquet 缺失,跳过")
            continue
        df = pd.read_parquet(fp)
        try:
            tx = fetch_tencent(code)
        except Exception as e:  # noqa: BLE001
            print(f"  [{i}/{len(codes)}] {code}: 腾讯失败 {e},跳过")
            continue

        for day in cand[code]:
            tx_bar = tx.get(day)
            # 自校验:腾讯无此日 或 当天也无成交 -> 真停牌,跳过
            if tx_bar is None:
                plan.append(_skip(code, day, turnover[code], "tencent_no_day"))
                continue
            t_o, t_c, t_h, t_l, t_v = tx_bar
            if t_h == t_l and t_v == 0:
                plan.append(_skip(code, day, turnover[code], "tencent_also_flat"))
                continue

            # 尺度因子 k = yf_close / tx_close,用邻近真实交易日两源比值的中位数
            ratios = []
            for nd, nclose in nearest_real_neighbors(df, day, N_NEIGHBORS):
                if nd in tx and tx[nd][1] > 0:
                    ratios.append(nclose / tx[nd][1])
            if not ratios:
                plan.append(_skip(code, day, turnover[code], "no_common_neighbor"))
                continue
            ratios.sort()
            k = ratios[len(ratios) // 2]  # median
            k_spread = max(ratios) / min(ratios) if min(ratios) > 0 else 99.0

            # preclose 取自缺口日那行(平bar 的 close==preclose,已是前收,无需改)
            row = df[df["date"] == day]
            preclose = float(row["preclose"].iloc[0]) if "preclose" in df.columns and \
                len(row) and pd.notna(row["preclose"].iloc[0]) else None
            old_close = float(row["close"].iloc[0]) if len(row) else None

            new_close = t_c * k
            new_open = t_o * k
            new_high = t_h * k
            new_low = t_l * k
            new_vol = t_v / k  # 成交额守恒:price×k, vol/k
            new_pct = ((new_close / preclose - 1) * 100) if preclose else None

            plan.append({
                "code": code, "date": day, "status": "ok",
                "med_turnover": turnover[code],
                "k": round(k, 6), "k_spread": round(k_spread, 5),
                "n_ratios": len(ratios),
                "warn_split": k_spread > K_SPREAD_WARN,
                "old_close": old_close, "preclose": preclose,
                "new_open": new_open, "new_high": new_high,
                "new_low": new_low, "new_close": new_close,
                "new_volume": new_vol, "new_amount": 0.0,
                "new_pctChg": new_pct,
                "tx_raw": {"o": t_o, "c": t_c, "h": t_h, "l": t_l, "v": t_v},
            })
        time.sleep(0.35)  # 礼貌限速,避免触发腾讯封禁
    return plan


def _skip(code, day, turnover, reason):
    return {"code": code, "date": day, "status": "skip", "reason": reason,
            "med_turnover": turnover}


def print_preview(plan: list):
    ok = [p for p in plan if p["status"] == "ok"]
    skip = [p for p in plan if p["status"] == "skip"]
    warn = [p for p in ok if p.get("warn_split")]

    print("\n" + "=" * 78)
    print(f"回补预览:可补 {len(ok)} 股次 / 跳过 {len(skip)} 股次 / 尺度复核警告 {len(warn)}")
    print("=" * 78)
    for day in GAP_DAYS:
        rows = sorted([p for p in ok if p["date"] == day],
                      key=lambda p: -p["med_turnover"])
        if not rows:
            continue
        print(f"\n--- {day}  (可补 {len(rows)} 只,按成交额降序取前 20)---")
        print(f"{'code':>10} {'中位成交M':>9} {'旧close':>9} {'新close':>9} "
              f"{'k':>7} {'tx_vol':>12} {'pctChg':>8}")
        for p in rows[:20]:
            print(f"{p['code']:>10} {p['med_turnover']/1e6:>9.0f} "
                  f"{p['old_close']:>9.3f} {p['new_close']:>9.3f} "
                  f"{p['k']:>7.4f} {int(p['tx_raw']['v']):>12} "
                  f"{(p['new_pctChg'] or 0):>8.2f}"
                  f"{'  ⚠split' if p.get('warn_split') else ''}")
    if skip:
        from collections import Counter
        c = Counter(p["reason"] for p in skip)
        print(f"\n--- 跳过原因汇总 ---")
        for reason, n in c.items():
            print(f"    {reason}: {n} 股次")
    if warn:
        print(f"\n--- ⚠ 尺度复核(邻近日 k 不稳, 可能夹拆股, 共 {len(warn)})---")
        for p in warn[:20]:
            print(f"    {p['code']} {p['date']}: k={p['k']} spread={p['k_spread']} "
                  f"(n={p['n_ratios']})")


def apply_plan():
    if not PLAN_PATH.exists():
        print(f"未找到 {PLAN_PATH},请先跑 dry-run。")
        return
    plan = json.loads(PLAN_PATH.read_text())
    ok = [p for p in plan if p["status"] == "ok"]
    if not ok:
        print("plan 中无可补行,退出。")
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bdir = BACKUP_DIR / ts
    bdir.mkdir(parents=True, exist_ok=True)

    # 按 code 分组,每只股读一次 parquet,先备份,改行,写回
    by_code: dict = {}
    for p in ok:
        by_code.setdefault(p["code"], []).append(p)

    n_rows = 0
    for code, patches in by_code.items():
        fp = DAILY_DIR / f"{code}.parquet"
        shutil.copy2(fp, bdir / fp.name)  # 备份原文件
        df = pd.read_parquet(fp)
        for p in patches:
            m = df["date"] == p["date"]
            if not m.any():
                print(f"  ⚠ {code} {p['date']} 行不存在,跳过")
                continue
            df.loc[m, "open"] = p["new_open"]
            df.loc[m, "high"] = p["new_high"]
            df.loc[m, "low"] = p["new_low"]
            df.loc[m, "close"] = p["new_close"]
            df.loc[m, "volume"] = p["new_volume"]
            df.loc[m, "amount"] = p["new_amount"]
            if p["new_pctChg"] is not None and "pctChg" in df.columns:
                df.loc[m, "pctChg"] = p["new_pctChg"]
            n_rows += 1
        df.to_parquet(fp, index=False)

    print(f"已落盘:{len(by_code)} 只股 / {n_rows} 行;备份在 {bdir}")
    verify(ok)


def verify(ok: list):
    """落盘后验证:1) 平bar 消失 2) 价格对齐 plan 3) qfq 可重算。"""
    print("\n=== 验证 ===")
    bad_flat = 0
    bad_price = 0
    # 抽样:所有 k≠1(尺度对齐过的关键行)必查 + 其余前 50
    scaled = [p for p in ok if abs(p.get("k", 1.0) - 1.0) > 1e-6]
    rest = [p for p in ok if abs(p.get("k", 1.0) - 1.0) <= 1e-6]
    sample = scaled + rest[:50]
    for p in sample:
        df = pd.read_parquet(DAILY_DIR / f"{p['code']}.parquet")
        row = df[df["date"] == p["date"]]
        if not len(row):
            continue
        o, h, low, c, v = (float(row["open"].iloc[0]), float(row["high"].iloc[0]),
                           float(row["low"].iloc[0]), float(row["close"].iloc[0]),
                           float(row["volume"].iloc[0]))
        if is_flat_row(o, h, low, c, v):
            bad_flat += 1
            print(f"  ⚠ {p['code']} {p['date']} 仍是平bar!")
        if abs(c - p["new_close"]) > 1e-4:
            bad_price += 1
            print(f"  ⚠ {p['code']} {p['date']} close 不匹配 plan: {c} vs {p['new_close']}")
    print(f"  抽样 {len(sample)} (含全部 {len(scaled)} 个尺度对齐行):"
          f"仍平bar {bad_flat} / 价格不匹配 {bad_price}")

    # qfq 重算冒烟:取第一只补过的股跑一次前复权,确认不报错且缺口日有值
    code = ok[0]["code"]
    day = ok[0]["date"]
    try:
        store = get_store()
        res = store.query_qfq_kline_bulk(market="HK", symbols=[code])  # 返回 {symbol: df}
        qdf = res.get(code)
        if isinstance(qdf, pd.DataFrame) and len(qdf):
            hit = qdf[qdf["date"] == day]
            print(f"  qfq 重算冒烟 OK:{code} 返回 {len(qdf)} 行,"
                  f"缺口日 {day} {'有值' if len(hit) else '★缺失'}")
        else:
            print(f"  ⚠ qfq 重算返回空:{code}")
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ qfq 重算异常:{e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="从 plan.json 落盘(默认仅 dry-run)")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.apply:
        apply_plan()
        return

    t0 = time.time()
    plan = build_plan()
    PLAN_PATH.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    print_preview(plan)
    print(f"\nplan 已存:{PLAN_PATH}  (耗时 {time.time()-t0:.0f}s)")
    print("确认无误后运行:python scripts/backfill_hk_gaps_tencent.py --apply")


if __name__ == "__main__":
    main()
