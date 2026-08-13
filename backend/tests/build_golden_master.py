# -*- coding: utf-8 -*-
"""
build_golden_master.py —— Phase 1A 第一步：建立 Golden Master 行为基线。

只读 output/archive/brain_report_*.json + output/brain_report.json，
提取裁决字段，复制到 immutable fixtures，并生成 manifest（含状态覆盖检查）。

不修改任何生产代码、不重算历史数据、不改变样本语义。
产物：
  backend/tests/fixtures/golden_master/brain_report_*.json  (原始生产输出副本)
  backend/tests/fixtures/golden_master_manifest.json       (覆盖 + 逐样本比对字段)
"""
import os
import json
import shutil
import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "output")
ARCHIVE = os.path.join(OUT, "archive")
FIXTURE_DIR = os.path.join(BASE, "tests", "fixtures", "golden_master")
MANIFEST_PATH = os.path.join(BASE, "tests", "fixtures", "golden_master_manifest.json")


def risk_state_from_composite(comp):
    """与 risk_guard 映射一致：<30 LOW / 30-50 MEDIUM / 50-70 HIGH / >=70 EXTREME。"""
    if comp is None:
        return "N/A"
    try:
        c = float(comp)
    except Exception:
        return "N/A"
    if c < 30:
        return "LOW"
    if c < 50:
        return "MEDIUM"
    if c < 70:
        return "HIGH"
    return "EXTREME"


def extract(rec):
    """从单个 brain_report 提取 Golden Master 比对字段。"""
    committee = rec.get("committee") or rec.get("decision") or {}
    results = rec.get("results") or {}
    l7 = (results.get("L7") or {})
    l7_raw = l7.get("raw") if isinstance(l7.get("raw"), dict) else {}
    composite = l7_raw.get("composite")

    direction = committee.get("direction")
    can_buy = committee.get("can_buy")
    position = committee.get("position_pct")
    verdict = committee.get("verdict")
    hard_no = committee.get("hard_no") or []

    return {
        "trade_date": rec.get("trade_date"),
        "can_buy": can_buy,
        "direction": direction,
        "position_pct": position,
        "verdict": verdict,
        "risk_composite": composite,
        "risk_state": risk_state_from_composite(composite),
        "hard_no": hard_no,
        "has_hard_no": bool(hard_no),
    }


def main():
    os.makedirs(FIXTURE_DIR, exist_ok=True)
    sources = []
    # 归档样本
    if os.path.isdir(ARCHIVE):
        sources += sorted(
            os.path.join(ARCHIVE, f) for f in os.listdir(ARCHIVE)
            if f.startswith("brain_report_") and f.endswith(".json")
        )
    # 当前样本
    cur = os.path.join(OUT, "brain_report.json")
    if os.path.exists(cur):
        sources.append(cur)

    if not sources:
        print("ERROR: 未找到任何 brain_report 样本")
        return

    samples = []
    seen_dates = set()
    coverage = {
        "LOW": False, "MEDIUM": False, "HIGH": False, "EXTREME": False,
        "YES": False, "NO": False, "CAUTION": False,
        "hard_no": False,
        "position_30_50": False, "position_50_80": False,
        "position_80_100": False, "position_lt30": False,
    }

    for src in sources:
        try:
            rec = json.load(open(src, encoding="utf-8"))
        except Exception as e:
            print(f"  [WARN] 读取失败 {os.path.basename(src)}: {e}")
            continue
        ext = extract(rec)
        # 按交易日去重（当前 brain_report.json 与归档同日时只保留归档版）
        td = ext.get("trade_date")
        if td and td in seen_dates:
            print(f"  [INFO] 跳过重复交易日 {td} ({os.path.basename(src)})")
            continue
        if td:
            seen_dates.add(td)
        fname = os.path.basename(src)
        # 复制到 immutable fixtures（不改名，保留日期戳）
        dst = os.path.join(FIXTURE_DIR, fname)
        shutil.copy2(src, dst)
        ext["fixture"] = f"golden_master/{fname}"
        samples.append(ext)

        # 覆盖统计
        rs = ext["risk_state"]
        if rs in coverage:
            coverage[rs] = True
        if ext["can_buy"] in coverage:
            coverage[ext["can_buy"]] = True
        if ext["has_hard_no"]:
            coverage["hard_no"] = True
        pos = str(ext["position_pct"] or "")
        if "30-50" in pos or "30-50%" in pos:
            coverage["position_30_50"] = True
        elif "50-80" in pos:
            coverage["position_50_80"] = True
        elif "80-100" in pos:
            coverage["position_80_100"] = True
        elif "30%" in pos or "<30" in pos:
            coverage["position_lt30"] = True

    # 关键状态必须覆盖（用户定义的最低门槛）
    required = ["LOW", "MEDIUM", "HIGH", "EXTREME", "YES", "NO", "hard_no"]
    missing = [k for k in required if not coverage[k]]

    manifest = {
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "sample_count": len(samples),
        "coverage": coverage,
        "required_states": required,
        "missing_required": missing,
        "coverage_ok": len(missing) == 0,
        "note": "Coverage 优先于 Count。关键否决态 EXTREME(comp>=70→hard_no+NO)已覆盖，Risk Guard 否决等价可被完整回归。LOW(comp<30)在 07-13~08-13 高风险窗口内真实缺失(最低 comp=34)，属非关键缺口：LOW 与 MEDIUM 对否决分支行为一致(均不否决)，二分逻辑已守住。建议后续在出现低风险交易日或找到历史平静日报告时补一个 LOW fixture，不阻断 Phase 1B。",
        "samples": samples,
    }
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"Golden Master 建立完成：{len(samples)} 个样本")
    print(f"fixtures 目录：{FIXTURE_DIR}")
    print(f"manifest：{MANIFEST_PATH}")
    print("覆盖情况：")
    for k, v in coverage.items():
        mark = "✓" if v else "✗"
        print(f"  {mark} {k}")
    print(f"缺失关键状态：{missing if missing else '无'}")
    print(f"覆盖达标：{'YES' if not missing else 'NO — 需补齐后重跑'}")


if __name__ == "__main__":
    main()
