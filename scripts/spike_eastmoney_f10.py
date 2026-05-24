"""§7 控股股东 — EastMoney F10 接口 Phase 0 spike。

目的:
- 验证 5 个 reportName 是否真实可用
- 拿到每个接口的字段清单 + 首条样例
- 决定后续 Pydantic models 字段命名和 sort 字段

跑法:
    python scripts/spike_eastmoney_f10.py [code1 code2 ...]
默认用 002594.SZ + 600519.SH

输出:
- 控制台逐表打印结果
- notes/eastmoney_f10_spike.md 落笔记
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# 项目根入 sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

# 每行 = 一个目标表 + 多个候选 reportName(F10 接口命名经验值)
# spike 任务:逐个试,首个返回有效数据的胜出
TABLES: list[tuple[str, list[str], str]] = [
    (
        "十大股东",
        ["RPT_F10_EH_HOLDERS", "RPT_F10_EH_HOLDER", "RPT_F10_EH_RELATION_HOLDER"],
        "≥2 期对比,看 HOLD_RATIO 变化",
    ),
    (
        "十大流通股东",
        ["RPT_F10_EH_FREEHOLDERS", "RPT_F10_EH_FREEHOLDER", "RPT_F10_EH_FREE_HOLDER"],
        "同上",
    ),
    (
        "股东户数",
        [
            "RPT_F10_EH_HOLDERSNUMLATEST",
            "RPT_F10_EH_HOLDERSNUM",
            "RPT_F10_HOLDERSNUM",
            "RPT_HOLDERNUMLATEST",
            "RPT_HOLDERNUM_DET",
        ],
        "4-8 期趋势",
    ),
    (
        "股权质押",
        [
            "RPT_PLEDGE_HOLDERSTAT",
            "RPT_F10_EH_PLEDGE",
            "RPT_F10_PLEDGE",
            "RPT_HOLDERS_PLEDGE",
            "RPT_PLEDGE_DET",
        ],
        "12 月事件流",
    ),
    (
        "高管变动",
        [
            "RPT_EXECUTIVE_CHANGE",
            "RPT_F10_EH_EMPLOYEECHANGE",
            "RPT_F10_EH_PERSONCHANGE",
            "RPT_F10_PERSONCHANGE",
            "RPT_PERSONNEL_CHANGE",
        ],
        "12 月事件清单",
    ),
]

API_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
TIMEOUT = 10
SORT_CANDIDATES = ["REPORT_DATE", "END_DATE", "NOTICE_DATE", "CHANGE_DATE", ""]


def _request(report_name: str, code: str, sort_col: str) -> dict | None:
    sec = code.split(".")[0] if "." in code else code
    params = {
        "reportName": report_name,
        "columns": "ALL",
        "quoteColumns": "",
        "filter": f'(SECURITY_CODE="{sec}")',
        "pageNumber": 1,
        "pageSize": 5,
        "source": "HSF10",
        "client": "PC",
    }
    if sort_col:
        params["sortColumns"] = sort_col
        params["sortTypes"] = -1
    try:
        r = requests.get(API_URL, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        return {"_error": str(e)}


def _try_with_sort_fallback(report_name: str, code: str) -> tuple[str, dict]:
    """依次尝试 sort 字段。message 含「排序列不存在」时换下个 sort 继续试。"""
    last_msg: str = ""
    for sort_col in SORT_CANDIDATES:
        data = _request(report_name, code, sort_col)
        if data is None:
            continue
        if data.get("_error"):
            last_msg = data["_error"]
            continue
        if data.get("success") and data.get("result"):
            return sort_col, data
        msg = data.get("message", "") or ""
        last_msg = msg
        # 「排序列不存在」继续 fallback;「报表配置不存在」表名错,直接跳出
        if "排序列不存在" in msg:
            continue
        # 报表名不存在或其他错误 → 提前返回
        return sort_col, data
    return "", {"_error": last_msg or "all sort cols failed"}


def _try_report_candidates(report_names: list[str], code: str) -> tuple[str, str, dict]:
    """逐个尝试 reportName,首个有效返回。"""
    last_data: dict = {}
    for rn in report_names:
        sort_col, data = _try_with_sort_fallback(rn, code)
        if data.get("success") and data.get("result"):
            return rn, sort_col, data
        last_data = data
    return report_names[-1], "", last_data


def _summarize(records: list[dict]) -> tuple[list[str], dict]:
    if not records:
        return [], {}
    cols = sorted(records[0].keys())
    sample = records[0]
    return cols, sample


def main(codes: list[str]) -> None:
    notes_dir = ROOT / "notes"
    notes_dir.mkdir(exist_ok=True)
    out_path = notes_dir / "eastmoney_f10_spike.md"

    lines: list[str] = ["# EastMoney F10 §7 spike 笔记", ""]
    lines.append(f"测试代码:{', '.join(codes)}")
    lines.append("")

    for label, report_names, note in TABLES:
        header = f"## {label}"
        print("\n" + "=" * 80)
        print(header + f"  候选 reportName: {report_names}")
        print(f"备注:{note}")
        lines.append(header)
        lines.append(f"备注:{note}")
        lines.append(f"候选 reportName:{report_names}")

        for code in codes:
            print(f"\n  → {code}")
            rn, sort_col, data = _try_report_candidates(report_names, code)
            if data.get("_error"):
                msg = f"FAIL ({rn}): {data['_error']}"
                print(f"    {msg}")
                lines.append(f"- **{code}**:{msg}")
                continue
            if not data.get("success"):
                msg = data.get("message") or "success=False"
                print(f"    {rn} → {msg}")
                lines.append(f"- **{code}**:`{rn}` → {msg}")
                continue
            result = data.get("result") or {}
            records = result.get("data") or []
            total = result.get("count", len(records))
            cols, sample = _summarize(records)
            print(f"    ✅ {rn}  sort={sort_col!r}  count={total}  fields={len(cols)}")
            if cols:
                print(f"    cols: {cols}")
                key_preview = {k: sample.get(k) for k in list(cols)[:8]}
                print(f"    sample(前 8 字段):{key_preview}")
            lines.append(
                f"- **{code}**:✅ `{rn}` sort=`{sort_col}` count={total} fields={len(cols)}"
            )
            if cols:
                lines.append(f"  - cols: `{cols}`")
                lines.append(f"  - sample: `{sample}`")
            time.sleep(0.3)
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n笔记已落:{out_path}")


if __name__ == "__main__":
    args = sys.argv[1:] or ["002594.SZ", "600519.SH"]
    main(args)
