# -*- coding: utf-8 -*-
"""
flow_evidence_archive.py — Flow Evidence Archive (P0-OBS-1 / P0-OBS-1A)
Decision Provenance 的第一块基础设施，并支持每日自动快照（含失败留证）。

设计目标（来自用户 2026-08-17 要求）：
  任何一天的 flow_score，都能沿证据链回溯到原始数据与计算过程。
  - 冻结 M1~M5 的 status，不只有分数（50 不能既代表中性、又代表没数据、又代表未接入）
  - 记录 nominal_weight 与 effective_weight，为「缺失如何处理」留出干净实验空间
  - 把 migration / stock_flow_daily / sector_daily 的真实数据状态一并留存

铁律：
  - 只读 / 观测层。零生产决策改动（不碰 run_daily / risk_guard / shadow / CIO / os2_report）
  - 读取的是引擎「当前产物」flow_report.json（即便它 stale 也照实记录，因为审计的就是它的真实输出）
  - 不修改任何生产表；仅向 output/archive/flow_snapshots/ 落盘

失败留证机制（P0-OBS-1A 新增）：
  - 任何未预期异常都会写出一份 status=FAILED 的 flow_snapshot_YYYY-MM-DD.json，
    含 failure_stage / error，确保「缺失证据本身也是证据」。
  - 数据库不可达、flow_report 缺失/损坏等「已知降级态」不视为失败：仍写出降级快照，
    在对应字段标记 NO_DATA/ERROR，这本身就是有效证据。
  - 每次运行追加一行 archive_manifest.jsonl，便于发现「哪天没有快照」。

用法：
  python flow_evidence_archive.py                 # 用今日日期 + 当前 flow_report.json
  python flow_evidence_archive.py --date 2026-08-14
  python flow_evidence_archive.py --flow-report /path/to/flow_report.json
"""
from __future__ import annotations
import argparse
import json
import os
import sqlite3
import sys
import datetime
import pathlib

HERE = pathlib.Path(__file__).resolve().parent          # backend/audit
BACKEND = HERE.parent                                  # backend
OUTPUT = BACKEND / "output"
ARCHIVE_DIR = OUTPUT / "archive" / "flow_snapshots"
MANIFEST = ARCHIVE_DIR / "archive_manifest.jsonl"
FLOW_REPORT = OUTPUT / "flow_report.json"
DB_PATH = BACKEND / "database" / "vibe_research.db"

SCHEMA_VERSION = "1.1"
SNAPSHOT_TYPE = "flow_evidence"

# flow_score 五层名义权重（flow_scorer.py: overall = mean(M1~M5)，等权）
LAYER_NOMINAL_WEIGHT = 0.20
N_LAYERS = 5

# composite 资本维度内部权重（os2_report.py: capital = 0.4*migration + 0.3*flow + 0.3*L4）
CAPITAL_DIM_COMPOSITE_WEIGHT = 0.40
MIGRATION_NOMINAL_IN_CAPITAL = 0.40
FLOW_NOMINAL_IN_CAPITAL = 0.30
L4_NOMINAL_IN_CAPITAL = 0.30

# 数据新鲜度阈值（天）
STALE_DAYS = 2


def _file_mtime_iso(path: pathlib.Path) -> str:
    return datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _load_flow_report(path: pathlib.Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return None


def derive_status(layer: dict) -> str:
    """把 layer 的 detail/direction 翻译成数据溯源状态。

    枚举（与用户 2026-08-17 定义对齐）：
      INFLOW / OUTFLOW / NEUTRAL  —— 有真实数据，分别对应资金流入/流出/中性
      NO_DATA     —— 无数据源（如 M1 缺 DXY/美债）
      NOT_CONNECTED —— 输入管线未接入（如 M4/M5 未传入 sector/individual score）
      STALE       —— 数据过期
      ERROR       —— 计算失败
    """
    detail = layer.get("detail") or ""
    direction = (layer.get("direction") or "").lower()
    if "待接入" in detail or "尚未接入" in detail:
        return "NOT_CONNECTED"
    if "数据不足" in detail or "无数据" in detail or "无份额" in detail:
        return "NO_DATA"
    if direction == "inflow":
        return "INFLOW"
    if direction == "outflow":
        return "OUTFLOW"
    return "NEUTRAL"


def build_layer_block(key: str, name_cn: str, layer: dict, flow_report_as_of: str) -> dict:
    status = derive_status(layer)
    has_real_data = status in ("INFLOW", "OUTFLOW", "NEUTRAL")
    effective = LAYER_NOMINAL_WEIGHT if has_real_data else 0.0
    source_date = flow_report_as_of if has_real_data else None
    return {
        "key": key,
        "name": name_cn,
        "score": layer.get("score"),
        "stars": layer.get("stars"),
        "market_state": layer.get("direction"),        # inflow/outflow/neutral
        "status": status,                              # 数据溯源状态
        "detail": layer.get("detail"),
        "source_date": source_date,
        "source_date_is_proxy": bool(has_real_data),   # flow_report 无日期，用文件 mtime 近似
        "nominal_weight": LAYER_NOMINAL_WEIGHT,
        "effective_weight": effective,
    }


def db_status(cur, table: str, today: str):
    cur.execute(f"SELECT MAX(date), COUNT(*) FROM {table}")
    latest, n = cur.fetchone()
    if latest is None:
        return {"exists": False, "latest_date": None, "rows": 0, "status": "MISSING"}
    try:
        d_latest = datetime.date.fromisoformat(latest)
        d_today = datetime.date.fromisoformat(today)
        age = (d_today - d_latest).days
    except Exception:
        age = None
    status = "OK" if (age is not None and age <= STALE_DAYS) else ("STALE" if age is not None else "UNKNOWN")
    return {"exists": True, "latest_date": latest, "rows": n, "age_days": age, "status": status}


def build_real_ashare_capital(cur, today: str) -> dict:
    """真实 A 股主力净流入（stock_flow_daily.main_net_buy）—— 这是 flow_score 缺失的信号源。"""
    cur.execute("SELECT MAX(date) FROM stock_flow_daily WHERE date<=?", (today,))
    row = cur.fetchone()
    if not row or not row[0]:
        return {"status": "NO_DATA", "source_date": None, "note": "stock_flow_daily 无数据"}
    d0 = row[0]
    cur.execute(
        "SELECT COUNT(*), SUM(CASE WHEN main_net_buy>0 THEN 1 ELSE 0 END), "
        "AVG(main_net_buy) FROM stock_flow_daily WHERE date=?", (d0,))
    total, pos, avg = cur.fetchone()
    cur.execute("SELECT main_net_buy FROM stock_flow_daily WHERE date=? AND main_net_buy IS NOT NULL", (d0,))
    vals = sorted(r[0] for r in cur.fetchall())
    median = vals[len(vals) // 2] if vals else None
    total = total or 0
    pos = pos or 0
    return {
        "status": "OK",
        "source_date": d0,
        "n_stocks": total,
        "n_positive_net_buy": pos,
        "positive_ratio": round(pos / total, 4) if total else None,
        "mean_net_buy": round(avg, 2) if avg is not None else None,
        "median_net_buy": round(median, 2) if median is not None else None,
        "note": "真实 A 股主力净流入信号；当前未接入 flow_score 的 M4/M5，也未回灌 composite 资本维度。",
    }


def build_migration_block() -> dict:
    p = OUTPUT / "migration_report.json"
    if not p.exists():
        return {
            "status": "MISSING",
            "score": None,
            "source_date": None,
            "nominal_weight_in_capital_dim": MIGRATION_NOMINAL_IN_CAPITAL,
            "effective_weight": 0.0,
            "note": "migration_report.json 不存在 → 资本维度 40% 权重的 migration 挂空（按 0 计）。"
                    "migration=0 与 migration=缺失 语义不同，目前系统无法区分。",
        }
    try:
        d = json.load(open(p, encoding="utf-8"))
        rating = d.get("rating") or d.get("migration_rating")
        return {
            "status": "OK",
            "score": rating,
            "source_date": d.get("date"),
            "nominal_weight_in_capital_dim": MIGRATION_NOMINAL_IN_CAPITAL,
            "effective_weight": MIGRATION_NOMINAL_IN_CAPITAL,
            "note": "migration_report.json 存在。",
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "score": None,
            "source_date": None,
            "nominal_weight_in_capital_dim": MIGRATION_NOMINAL_IN_CAPITAL,
            "effective_weight": 0.0,
            "note": f"读取 migration_report.json 失败: {e}",
        }


def build_snapshot(today: str, flow_path: pathlib.Path, flow_report_as_of: str) -> dict:
    """构建成功快照。任何未预期异常都向上抛出，由 main 捕获并写出 FAILED 留证。"""
    flow_report = _load_flow_report(flow_path)

    # ── 1. M1~M5 逐层冻结 ──
    layers = []
    if flow_report:
        fs = flow_report.get("flow_score", {})
        layer_defs = [
            ("m1_global", "全球流动性", fs.get("m1_global", {})),
            ("m2_cross_asset", "跨资产", fs.get("m2_cross_asset", {})),
            ("m3_etf", "ETF资金", fs.get("m3_etf", {})),
            ("m4_sector", "板块资金", fs.get("m4_sector", {})),
            ("m5_individual", "个股资金", fs.get("m5_individual", {})),
        ]
        for k, cn, ly in layer_defs:
            layers.append(build_layer_block(k, cn, ly, flow_report_as_of))
    else:
        for k, cn in [("m1_global", "全球流动性"), ("m2_cross_asset", "跨资产"),
                      ("m3_etf", "ETF资金"), ("m4_sector", "板块资金"), ("m5_individual", "个股资金")]:
            layers.append({
                "key": k, "name": cn, "score": None, "stars": None, "market_state": None,
                "status": "NO_DATA", "detail": "flow_report.json 缺失",
                "source_date": None, "source_date_is_proxy": False,
                "nominal_weight": LAYER_NOMINAL_WEIGHT, "effective_weight": 0.0,
            })

    eff_sum = sum(l["effective_weight"] for l in layers)
    nominal_sum = sum(l["nominal_weight"] for l in layers)
    eff_fraction = round(eff_sum / nominal_sum, 4) if nominal_sum else 0.0
    dead = [l["key"] for l in layers if l["effective_weight"] == 0.0]
    flow_overall = flow_report.get("flow_score", {}).get("overall") if flow_report else None

    # ── 2. 真实 A 股资金 + DB 数据状态（DB 不可达 = 降级而非失败）──
    real_ashare = {"status": "NO_DATA", "note": "DB 不可达"}
    db_statuses = {}
    if DB_PATH.exists():
        try:
            con = sqlite3.connect(str(DB_PATH))
            cur = con.cursor()
            real_ashare = build_real_ashare_capital(cur, today)
            for t in ["stock_flow_daily", "sector_daily"]:
                db_statuses[t] = db_status(cur, t, today)
            con.close()
        except Exception as e:
            real_ashare = {"status": "ERROR", "note": f"DB 查询失败: {e}"}
    else:
        db_statuses = {"stock_flow_daily": {"status": "MISSING"}, "sector_daily": {"status": "MISSING"}}

    # ── 3. migration 块 ──
    migration = build_migration_block()

    # ── 4. 资本维度 effective_weight 分析（composite 级）──
    flow_eff_in_capital = FLOW_NOMINAL_IN_CAPITAL * eff_fraction
    capital_dim = {
        "composite_weight": CAPITAL_DIM_COMPOSITE_WEIGHT,
        "effective_weight_in_composite": round(
            CAPITAL_DIM_COMPOSITE_WEIGHT *
            (migration["effective_weight"] + FLOW_NOMINAL_IN_CAPITAL * eff_fraction + L4_NOMINAL_IN_CAPITAL),
            4),
        "components": {
            "migration": {
                "nominal_weight_in_capital": MIGRATION_NOMINAL_IN_CAPITAL,
                "effective_weight_in_capital": round(MIGRATION_NOMINAL_IN_CAPITAL * migration["effective_weight"], 4),
                "status": migration["status"],
            },
            "flow_score": {
                "nominal_weight_in_capital": FLOW_NOMINAL_IN_CAPITAL,
                "overall": flow_overall,
                "internal_effective_weight_fraction": eff_fraction,
                "effective_weight_in_capital": round(flow_eff_in_capital, 4),
                "ashare_signal_effective": 0.0,  # M4/M5 断接 → A 股真实资金在 flow 内贡献为 0
            },
            "L4_direction": {
                "nominal_weight_in_capital": L4_NOMINAL_IN_CAPITAL,
                "effective_weight_in_capital": L4_NOMINAL_IN_CAPITAL,
            },
        },
        "note": ("资本维度名义占 composite 40%，但其中 A 股真实资金信号（stock_flow_daily）的有效权重≈0%："
                 "migration 缺失(40%挂空) + flow 内 M4/M5 断接(占 flow 40%)。"
                 "capital_score.py 已算好真实个股资金强度，仅用于『龙头资金层』展示，未回灌 composite。"),
    }

    # ── 5. 整体数据健康度 ──
    if eff_fraction >= 0.999 and migration["status"] == "OK":
        data_health = "OK"
    else:
        data_health = "DEGRADED"

    # ── 6. 组装快照 ──
    return {
        "schema_version": SCHEMA_VERSION,
        "snapshot_type": SNAPSHOT_TYPE,
        "status": "OK",
        "archive_status": "OK",
        "computation_date": today,
        "flow_report_as_of": flow_report_as_of,
        "flow_report_path": str(flow_path),
        "generated_at": _now_iso(),
        "flow_score": {
            "overall": flow_overall,
            "nominal_mean": True,
            "layers": layers,
            "effective_weight_fraction": eff_fraction,
            "dead_layers": dead,
            "data_health": data_health,
        },
        "migration": migration,
        "real_ashare_capital_flow": real_ashare,
        "db_data_status": db_statuses,
        "capital_dimension": capital_dim,
        "provenance_preview": {
            "flow_score_overall": flow_overall,
            "effective_weight_fraction": eff_fraction,
            "ashare_real_capital_present_in_db": real_ashare.get("status") == "OK",
            "ashare_signal_in_composite": False,
            "chain": [
                "Market", "Raw Data (stock_flow_daily / sector_daily / commodity / ETF)",
                "M1..M5", "Flow Score", "Capital Dimension (0.4*mig+0.3*flow+0.3*L4)",
                "Composite", "IC", "Final Decision", "User Output",
            ],
        },
        "incident_ref": "Signal Loss Incident · 2026-08",
        "audit_notes": (
            "本快照为 Decision Provenance 第一块基础设施（P0-OBS-1）。"
            "pre-2026-08-17 的逐层 M1~M5 证据链引擎从未归档，无法考古重建；"
            "本文件是断接持续性的基线锚点，后续每次运行追加一份同结构快照即可形成时间序列。"
        ),
    }


def write_failed_snapshot(today: str, flow_path: pathlib.Path, stage: str, error: Exception) -> None:
    """失败也留证：写出一份 status=FAILED 的快照，确保缺失证据本身也是证据。"""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    snap = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_type": SNAPSHOT_TYPE,
        "status": "FAILED",
        "archive_status": "FAILED",
        "computation_date": today,
        "flow_report_path": str(flow_path),
        "generated_at": _now_iso(),
        "failure_stage": stage,
        "error": str(error)[:500],
        "incident_ref": "Signal Loss Incident · 2026-08",
        "note": "失败也必须留下证据：缺失证据本身也是证据。本文件记录本次快照生成失败的原因。",
    }
    out_path = ARCHIVE_DIR / f"flow_snapshot_{today}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)
    _append_manifest(today, "FAILED", None, None, str(out_path))
    print(f"[Flow Evidence Archive] FAILED 已写入(留证): {out_path}")
    print(f"  failure_stage = {stage}")
    print(f"  error         = {snap['error']}")


def _append_manifest(today: str, status: str, overall, eff_fraction, path: str) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(MANIFEST, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "date": today, "status": status, "overall": overall,
                "effective_weight_fraction": eff_fraction, "path": path, "ts": _now_iso(),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass  # manifest 失败不影响主流程


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.date.today().isoformat(),
                    help="快照计算日期（默认今日）")
    ap.add_argument("--flow-report", default=str(FLOW_REPORT),
                    help="要归档的 flow_report.json 路径")
    args = ap.parse_args()

    today = args.date
    flow_path = pathlib.Path(args.flow_report)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    flow_report_as_of = _file_mtime_iso(flow_path) if flow_path.exists() else "UNKNOWN"

    try:
        snapshot = build_snapshot(today, flow_path, flow_report_as_of)
    except Exception as e:
        write_failed_snapshot(today, flow_path, "build_snapshot", e)
        return 1

    out_path = ARCHIVE_DIR / f"flow_snapshot_{today}.json"
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
    except Exception as e:
        write_failed_snapshot(today, flow_path, "write", e)
        return 1

    # ── 打印摘要 + manifest ──
    eff_fraction = snapshot["flow_score"]["effective_weight_fraction"]
    print(f"[Flow Evidence Archive] 已写入: {out_path}")
    print(f"  计算日期        : {today}")
    print(f"  flow_report 日期: {flow_report_as_of}  overall={snapshot['flow_score']['overall']}")
    print(f"  有效权重占比    : {eff_fraction}  (死层: {snapshot['flow_score']['dead_layers']})")
    print(f"  migration 状态  : {snapshot['migration']['status']}  有效权重={snapshot['migration']['effective_weight']}")
    print(f"  真实A股资金     : {snapshot['real_ashare_capital_flow'].get('status')}  "
          f"日期={snapshot['real_ashare_capital_flow'].get('source_date')}  "
          f"净流入占比={snapshot['real_ashare_capital_flow'].get('positive_ratio')}")
    print(f"  capital维度有效 : {snapshot['capital_dimension']['effective_weight_in_composite']} "
          f"(名义 {CAPITAL_DIM_COMPOSITE_WEIGHT})")
    print(f"  数据健康度      : {snapshot['flow_score']['data_health']}")
    print(f"  A股信号进composite: {snapshot['provenance_preview']['ashare_signal_in_composite']}")
    _append_manifest(today, "OK", snapshot['flow_score']['overall'], eff_fraction, str(out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
