"""港股 yfinance ↔ 腾讯(gtimg) 原始日K线交叉校验 —— 审计用独立第三源验证。

动机(2026-06-23):投实盘前要证明喂回测的 yfinance 港股 K线可信。EM(eastmoney)
push2his 接口已被 IP 级封禁,用户拍板改用另一独立源(腾讯 gtimg)做交叉校验。

🚨 铁律备注:腾讯仅作【审计交叉验证】,**不入生产采集层**(生产仍 baostock/
eastmoney/yfinance)。本脚本只读、不写任何业务数据。

口径(实测确认,非猜测):
  - 腾讯 fqkline/get 的 'day' 序列 = **不复权实际成交价**(00700 2023-11-09=306.8,
    与真实历史一致;且传 qfq 参数返回同一 'day' 序列,即 HK 不做前复权)。
  - 我方 v_hk_daily_raw = yfinance auto_adjust=False(**拆股调整、分红未调整**)。
  - 故二者在【无拆股窗口】应逐日近乎相等;若某段出现近常数比值跳变 = 拆股口径差
    (一方调一方不调),属可解释差异,**非数据错误**。

逻辑链(为何 raw↔raw 一致即足以背书 qfq):
  (A) 我方 qfq = raw × foreAdjustFactor —— 已本地实证(00700 288.06=296.60×0.9712);
  (B) factor 无 phantom —— 已本地审计(腾讯/洛钼/01413/BYD 全 0);
  (C) 本脚本证明 我方 raw ≈ 腾讯 raw  ⇒  我方 raw 可信
   ⇒ 传递得 我方 qfq(=raw×干净factor)可信。

腾讯接口实测特性:count-only 形式 `code,day,,,N,fqtype`;N≤2000(N≥3000 报 param error);
返回 data[hkXXXXX].day = [[日期,开,收,高,低,量], ...](注意 close 在 index 2)。

用法:
    python3 scripts/crosscheck_hk_tencent.py            # 默认 10 只
    python3 scripts/crosscheck_hk_tencent.py --codes 00700.HK,03993.HK
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from backend.services.market_data.duckdb_store import get_store  # noqa: E402

REPORT_MD = ROOT / "report" / "exported" / "hk_tencent_crosscheck.md"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
TX_BASE = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
TX_COUNT = 2000          # 实测上限(2000 可,3000 报错)
THROTTLE_S = 0.5         # 礼貌间隔(腾讯实测不限流,仍保守)

# 代表性 10 只:大盘股 + 策略相关 + 仙股(噪声样本)+ 冒烟背离样本
DEFAULT_CODES = {
    "00700.HK": "腾讯控股(大盘)",
    "00005.HK": "汇丰控股(大盘)",
    "00388.HK": "香港交易所(大盘)",
    "01299.HK": "友邦保险(大盘)",
    "00939.HK": "建设银行(大盘)",
    "01211.HK": "比亚迪股份(事故主角)",
    "03993.HK": "洛阳钼业(2025 top winner)",
    "01413.HK": "仙股(微结构噪声样本)",
    "00136.HK": "冒烟背离样本",
    "00439.HK": "冒烟背离样本",
}


def to_tencent_code(symbol: str) -> str:
    """'00700.HK' -> 'hk00700'(腾讯小写 hk 前缀,保留前导零)。"""
    base = symbol.split(".")[0]
    return f"hk{base}"


def fetch_tencent(symbol: str, retries: int = 2) -> dict[str, tuple[float, float, float, float]]:
    """取腾讯不复权日K -> {date: (open, close, high, low)}。失败抛异常(由调用方捕获)。"""
    txcode = to_tencent_code(symbol)
    param = f"{txcode},day,,,{TX_COUNT},"
    url = f"{TX_BASE}?param={param}"
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Referer": "https://gu.qq.com/"})
            with urllib.request.urlopen(req, timeout=12) as r:
                obj = json.loads(r.read().decode("utf-8", "ignore"))
            node = obj.get("data", {})
            if not isinstance(node, dict) or txcode not in node:
                raise ValueError(f"data 无 {txcode}: msg={obj.get('msg')!r}")
            rows = node[txcode].get("day") or node[txcode].get("qfqday") or []
            out: dict[str, tuple[float, float, float, float]] = {}
            for row in rows:
                # row = [日期, 开, 收, 高, 低, 量, ...] —— close 在 index 2
                d = str(row[0])
                out[d] = (float(row[1]), float(row[2]), float(row[3]), float(row[4]))
            return out
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < retries:
                time.sleep(1.0 + attempt)
    raise last_err  # type: ignore[misc]


def top_hk_codes(store, n: int) -> dict[str, str]:
    """按流动性代理 median(close*volume) 取最活跃 N 只 HK(价>1 避免全仙股)= 实际可交易宇宙。"""
    df = store._conn.execute(
        "SELECT _symbol FROM v_hk_daily_raw WHERE date >= '2025-01-01' "
        "GROUP BY _symbol HAVING count(*) > 100 AND median(close) > 1.0 "
        "ORDER BY median(close*volume) DESC LIMIT ?", [n]
    ).fetchdf()
    return {sym: "" for sym in df["_symbol"].tolist()}


def date_anomaly_histogram(results: list[dict], spike_pct: float = 0.5) -> list[tuple[str, int]]:
    """跨股聚合"孤立单日尖峰":某日比值同时偏离前后相邻日(>spike_pct)且前后日彼此一致
    (=尖峰复原)。返回 [(date, 命中股票数)] 按命中数降序。用于规模化定位系统性坏日(如 2026-05-14)。
    持续性拆股偏移因前后不一致而被自动排除。"""
    thr = spike_pct / 100.0
    counter: dict[str, int] = {}
    for r in results:
        if r.get("status") != "OK":
            continue
        dates = r.get("_dates", [])
        ratios = r.get("_ratios", [])
        for i in range(1, len(ratios) - 1):
            a, b, c = ratios[i - 1], ratios[i], ratios[i + 1]
            if a <= 0 or b <= 0 or c <= 0:
                continue
            jump_in = abs(np.log(b / a))
            jump_out = abs(np.log(c / b))
            neigh = abs(np.log(c / a))            # 前后相邻日是否一致(尖峰复原)
            if jump_in > thr and jump_out > thr and neigh < thr:
                counter[dates[i]] = counter.get(dates[i], 0) + 1
    return sorted(counter.items(), key=lambda kv: -kv[1])


def load_ours(store, symbol: str) -> dict[str, tuple[float, float, float, float]]:
    """我方 v_hk_daily_raw -> {date: (open, close, high, low)}。"""
    df = store._conn.execute(
        "SELECT date, open, close, high, low FROM v_hk_daily_raw "
        "WHERE _symbol = ? ORDER BY date", [symbol]
    ).fetchdf()
    out: dict[str, tuple[float, float, float, float]] = {}
    for _, r in df.iterrows():
        d = str(r["date"])[:10]
        out[d] = (float(r["open"]), float(r["close"]), float(r["high"]), float(r["low"]))
    return out


def analyze(symbol: str, name: str, ours: dict, tx: dict) -> dict:
    """对齐共同交易日,算 close 偏差分布 + 比值 regime(拆股签名)+ open 抽查。"""
    common = sorted(set(ours) & set(tx))
    res: dict = {"code": symbol, "name": name,
                 "n_ours": len(ours), "n_tx": len(tx), "n_common": len(common)}
    if len(common) < 30:
        res["status"] = "OVERLAP_TOO_SMALL"
        return res

    close_pct = []   # |our_c - tx_c| / tx_c * 100
    open_pct = []
    ratios = []      # our_c / tx_c (查拆股口径差)
    n_bad = 0        # 非有限/非正收盘对(仙股数据质量信号)
    jump_dates = []  # 与 ratios 对齐的日期(用于定位跳变日)
    for d in common:
        o_o, o_c, _, _ = ours[d]
        t_o, t_c, _, _ = tx[d]
        # 过滤 NaN/inf/非正(仙股偶有 0/缺失收盘),避免污染统计
        if not (np.isfinite(o_c) and np.isfinite(t_c) and o_c > 0 and t_c > 0):
            n_bad += 1
            continue
        close_pct.append(abs(o_c - t_c) / t_c * 100.0)
        ratios.append(o_c / t_c)
        jump_dates.append(d)
        if np.isfinite(o_o) and np.isfinite(t_o) and o_o > 0 and t_o > 0:
            open_pct.append(abs(o_o - t_o) / t_o * 100.0)
    res["n_bad_close"] = n_bad
    if len(close_pct) < 30:
        res["status"] = "TOO_FEW_VALID"
        return res

    close_pct_arr = np.array(close_pct)
    ratios_arr = np.array(ratios)

    # 最近 250 个共同交易日(近端:理应无拆股口径差,最干净的"价是否一致"信号)
    recent = close_pct_arr[-250:]
    res.update({
        "status": "OK",
        "recent250_mean": float(recent.mean()),
        "recent250_max": float(recent.max()),
        "full_median": float(np.median(close_pct_arr)),
        "full_p99": float(np.percentile(close_pct_arr, 99)),
        "full_max": float(close_pct_arr.max()),
        "n_gt_1pct": int((close_pct_arr > 1.0).sum()),
        "n_gt_3pct": int((close_pct_arr > 3.0).sum()),
        "open_median": float(np.median(open_pct)) if open_pct else None,
        # 比值 regime:若 max/min 比值跨度大 = 存在拆股口径差(可解释)
        "ratio_min": float(ratios_arr.min()),
        "ratio_max": float(ratios_arr.max()),
        "ratio_span": float(ratios_arr.max() / ratios_arr.min()) if ratios_arr.min() > 0 else None,
    })

    # 找比值"跳变日"(相邻有效交易日比值变化 >1% = 疑似拆股/合股签名)
    jumps = []
    for i in range(1, len(ratios)):
        if ratios[i - 1] > 0:
            chg = ratios[i] / ratios[i - 1]
            if abs(np.log(chg)) > 0.01:  # >~1% 比值跃迁
                jumps.append((jump_dates[i], round(ratios[i - 1], 4), round(ratios[i], 4)))
    res["ratio_jumps"] = jumps[:8]
    # 暂存对齐后的(日期, 比值)供日级异常直方图聚合(下划线=内部,不入表)
    res["_dates"] = jump_dates
    res["_ratios"] = ratios
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", type=str, default="", help="逗号分隔覆盖默认股票")
    ap.add_argument("--top", type=int, default=0, help="按流动性取最活跃 N 只 HK")
    args = ap.parse_args()

    store = get_store()

    if args.codes:
        codes = {c.strip(): "" for c in args.codes.split(",") if c.strip()}
    elif args.top:
        codes = top_hk_codes(store, args.top)
        print(f"[crosscheck] 流动性 top{args.top}: {len(codes)} 只", flush=True)
    else:
        codes = DEFAULT_CODES
    results: list[dict] = []

    for symbol, name in codes.items():
        try:
            tx = fetch_tencent(symbol)
        except Exception as e:  # noqa: BLE001
            print(f"  [SKIP] {symbol} 腾讯取数失败: {type(e).__name__}: {e}", flush=True)
            results.append({"code": symbol, "name": name, "status": f"TX_FAIL: {e}"})
            time.sleep(THROTTLE_S)
            continue
        ours = load_ours(store, symbol)
        if not ours:
            print(f"  [SKIP] {symbol} 我方无 raw 数据", flush=True)
            results.append({"code": symbol, "name": name, "status": "NO_OURS"})
            time.sleep(THROTTLE_S)
            continue
        r = analyze(symbol, name, ours, tx)
        results.append(r)
        if r["status"] == "OK":
            span_s = f"{r['ratio_span']:.4f}" if r["ratio_span"] is not None else "N/A"
            print(f"  [OK] {symbol} {name}: common={r['n_common']} "
                  f"recent250 mean={r['recent250_mean']:.4f}% max={r['recent250_max']:.3f}% | "
                  f"full median={r['full_median']:.4f}% p99={r['full_p99']:.3f}% "
                  f"max={r['full_max']:.3f}% | ratio_span={span_s} "
                  f"jumps={len(r['ratio_jumps'])}", flush=True)
        else:
            print(f"  [{r['status']}] {symbol} common={r.get('n_common')}", flush=True)
        time.sleep(THROTTLE_S)

    # ---------- 报告 ----------
    L = ["# 港股 yfinance ↔ 腾讯(gtimg) 原始日K线交叉校验", ""]
    L.append("- 口径:我方 v_hk_daily_raw(yfinance,拆股调整/分红未调整) vs 腾讯 day(不复权实际价)")
    L.append("- 近端无拆股窗口理应逐日≈相等;比值跨度大=拆股口径差(可解释,非错误)")
    L.append(f"- 腾讯窗口上限 {TX_COUNT} 交易日(约 8 年);更早历史我方有但腾讯截断,只比重叠段")
    L.append("")
    L.append("| 代码 | 名称 | 共同日 | 近250 mean% | 近250 max% | 全窗 median% | 全窗 p99% | 全窗 max% | >1%天 | >3%天 | 比值跨度 | 跳变 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        if r.get("status") != "OK":
            L.append(f"| {r['code']} | {r.get('name','')} | - | - | - | - | - | - | - | - | - | {r.get('status')} |")
            continue
        span_s = f"{r['ratio_span']:.4f}" if r["ratio_span"] is not None else "N/A"
        L.append(
            f"| {r['code']} | {r['name']} | {r['n_common']} | {r['recent250_mean']:.4f} | "
            f"{r['recent250_max']:.3f} | {r['full_median']:.4f} | {r['full_p99']:.3f} | "
            f"{r['full_max']:.3f} | {r['n_gt_1pct']} | {r['n_gt_3pct']} | "
            f"{span_s} | {len(r['ratio_jumps'])} |")
    L.append("")
    # ---- 日级异常直方图:孤立单日尖峰命中股数(规模化定位系统性坏日)----
    hist = date_anomaly_histogram(results)
    ok_n = sum(1 for r in results if r.get("status") == "OK")
    L.append("## 日级孤立尖峰直方图(某日多股同时偏离前后日且复原 = 系统性坏 bar 嫌疑)")
    L.append(f"统计口径:>0.5% 单日尖峰且次日复原;OK 股票数={ok_n}")
    L.append("")
    L.append("| 日期 | 命中股数 | 占比 |")
    L.append("|---|---|---|")
    for d, c in hist[:20]:
        L.append(f"| {d} | {c} | {c / ok_n * 100:.1f}% |")
    L.append("")
    L.append("## 比值跳变明细(疑似拆股/合股口径差签名)")
    for r in results:
        if r.get("status") == "OK" and r["ratio_jumps"]:
            span_s = f"{r['ratio_span']:.4f}" if r["ratio_span"] is not None else "N/A"
            L.append(f"- **{r['code']} {r['name']}** ratio_span={span_s} "
                     f"n_bad_close={r.get('n_bad_close', 0)}:")
            for d, a, b in r["ratio_jumps"]:
                L.append(f"    - {d}: {a} -> {b}")
    L.append("")

    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text("\n".join(L))

    print(f"\n[日级孤立尖峰 top10] OK股={ok_n}")
    for d, c in hist[:10]:
        print(f"    {d}: {c} 只 ({c / ok_n * 100:.1f}%)")
    print(f"\n报告: {REPORT_MD}")


if __name__ == "__main__":
    main()
