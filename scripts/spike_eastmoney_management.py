"""D4 管理层数据源 spike — 双路对比 datacenter API vs emweb PageAjax。

目的:
- 找到稳定、字段齐全的管理层数据端点
- 包括:高管列表(姓名/职位/性别/年龄/学历/任期)+ 持股变动事件
- 决定 D4 用哪条路径,避免凭经验猜结构

跑法:
    python scripts/spike_eastmoney_management.py [code1 code2 ...]
默认 600519.SH(贵州茅台)+ 002594.SZ(比亚迪)

输出:
- 控制台逐项打印
- notes/eastmoney_management_spike.md 笔记
- notes/em_mgmt_raw_<code>_<source>.json 原始 JSON 落盘(供后续 adapter 测试 fixture 用)
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

NOTES_DIR = ROOT / "notes"
NOTES_DIR.mkdir(exist_ok=True)

TIMEOUT = 12

# ============ 路径 1: datacenter API(沿用现有模式)============
DATACENTER_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
DATACENTER_REPORTS = [
    # 高管基本信息候选
    "RPT_F10_BASIC_OFFICERS",
    "RPT_F10_OFFICER",
    "RPT_F10_OFFICERS",
    "RPT_F10_BASIC_OFFICER",
    "RPT_F10_PERSONNEL_INFO",
    # 高管增减持
    "RPT_F10_HOLDER_NUMOFFICERHOLD",
    "RPT_EXECUTIVE_HOLDCHANGE",
    "RPT_F10_OFFICERHOLD",
    "RPT_OFFICERSHOLDS",
]

# ============ 路径 2: emweb PageAjax(AGENTS.md 提示)============
# host: emweb.eastmoney.com 或 f10.eastmoney.com
EMWEB_HOSTS = [
    "https://emweb.eastmoney.com",
    "https://f10.eastmoney.com",
]
EMWEB_SECTIONS = [
    "CompanyManagement",
    "ManagerInfo",
    "PersonInfo",
    "GGRYJS",
]


# ============ 通用 helpers ============


def _market_prefix(code: str) -> str:
    """600519.SH → SH600519,000858.SZ → SZ000858。"""
    if "." in code:
        sec, suf = code.split(".")
        return f"{suf.upper()}{sec}"
    return code.upper()


def _bare(code: str) -> str:
    """600519.SH → 600519。"""
    return code.split(".")[0] if "." in code else code


def _try_datacenter(report_name: str, code: str) -> dict:
    sec = _bare(code)
    params = {
        "reportName": report_name,
        "columns": "ALL",
        "filter": f'(SECURITY_CODE="{sec}")',
        "pageNumber": 1,
        "pageSize": 50,
        "source": "HSF10",
        "client": "PC",
    }
    try:
        r = requests.get(DATACENTER_URL, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        return {"_error": str(e)}


def _try_emweb(host: str, section: str, code: str) -> dict:
    """emweb PageAjax 形如 host/PC_HSF10/<Section>/PageAjax?code=SH600519。"""
    em_code = _market_prefix(code)
    url = f"{host}/PC_HSF10/{section}/PageAjax"
    params = {"code": em_code}
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        try:
            return {"_status": r.status_code, "_json": r.json()}
        except ValueError:
            return {
                "_status": r.status_code,
                "_text_head": r.text[:300],
                "_text_len": len(r.text),
            }
    except Exception as e:  # noqa: BLE001
        return {"_error": str(e)}


# ============ runners ============


def run_datacenter(code: str, lines: list[str]) -> None:
    print(f"\n  [datacenter] {code}")
    lines.append(f"### datacenter — {code}")
    for rn in DATACENTER_REPORTS:
        data = _try_datacenter(rn, code)
        if data.get("_error"):
            msg = f"  {rn}  EXC: {data['_error']}"
            print(msg)
            lines.append(f"- {rn}: EXC `{data['_error']}`")
            time.sleep(0.2)
            continue
        if data.get("success") and data.get("result", {}).get("data"):
            recs = data["result"]["data"]
            total = data["result"].get("count", len(recs))
            cols = sorted(recs[0].keys()) if recs else []
            print(f"  ✅ {rn}  count={total}  fields={len(cols)}")
            print(f"     cols: {cols}")
            print(f"     sample[0]: {json.dumps(recs[0], ensure_ascii=False)[:400]}")
            lines.append(
                f"- ✅ **{rn}** count={total} fields={len(cols)}\n"
                f"  - cols: `{cols}`\n"
                f"  - sample: `{json.dumps(recs[0], ensure_ascii=False)[:400]}`"
            )
            # 落原始 JSON
            (NOTES_DIR / f"em_mgmt_raw_{_bare(code)}_dc_{rn}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        else:
            msg = data.get("message") or f"success={data.get('success')}"
            print(f"  ✗ {rn}  {msg}")
            lines.append(f"- ✗ {rn}: {msg}")
        time.sleep(0.3)


def run_emweb(code: str, lines: list[str]) -> None:
    print(f"\n  [emweb] {code}")
    lines.append(f"### emweb PageAjax — {code}")
    for host in EMWEB_HOSTS:
        for section in EMWEB_SECTIONS:
            data = _try_emweb(host, section, code)
            tag = f"{host}/{section}"
            if data.get("_error"):
                print(f"  {tag}  EXC: {data['_error']}")
                lines.append(f"- {tag}: EXC `{data['_error']}`")
                time.sleep(0.2)
                continue
            if "_json" in data:
                j = data["_json"]
                # 顶层 keys
                top_keys = list(j.keys()) if isinstance(j, dict) else None
                print(f"  ✅ {tag}  status={data['_status']}  top_keys={top_keys}")
                if isinstance(j, dict):
                    for k in top_keys[:6] if top_keys else []:
                        v = j.get(k)
                        preview = (
                            f"list[{len(v)}] sample={json.dumps(v[0] if v else None, ensure_ascii=False)[:200]}"
                            if isinstance(v, list)
                            else f"{type(v).__name__} {str(v)[:120]}"
                        )
                        print(f"     {k}: {preview}")
                lines.append(f"- ✅ **{tag}** top_keys=`{top_keys}`")
                (
                    NOTES_DIR / f"em_mgmt_raw_{_bare(code)}_emweb_{section}.json"
                ).write_text(
                    json.dumps(j, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            else:
                print(
                    f"  ⚠ {tag}  status={data.get('_status')}  text_len={data.get('_text_len')}"
                )
                lines.append(
                    f"- ⚠ {tag}: 非 JSON status={data.get('_status')} head=`{data.get('_text_head', '')[:200]}`"
                )
            time.sleep(0.3)


def main(codes: list[str]) -> None:
    out_path = NOTES_DIR / "eastmoney_management_spike.md"
    lines: list[str] = ["# EastMoney 管理层数据源 spike 笔记", ""]
    lines.append(f"测试代码:{', '.join(codes)}")
    lines.append("")

    for code in codes:
        print("\n" + "=" * 80)
        print(f"代码:{code}")
        lines.append("")
        lines.append(f"## {code}")
        run_datacenter(code, lines)
        run_emweb(code, lines)

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n笔记落:{out_path}")
    print(f"原始 JSON 落:{NOTES_DIR}/em_mgmt_raw_*.json")


if __name__ == "__main__":
    args = sys.argv[1:] or ["600519.SH", "002594.SZ"]
    main(args)
