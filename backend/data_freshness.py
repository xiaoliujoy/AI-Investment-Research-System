# -*- coding: utf-8 -*-
"""
data_freshness.py —— 数据新鲜度矩阵（Personal AI Research System）
==================================================================

移植自开源项目 AI-Portfolio-Compass（MIT License,
https://github.com/Elian-dan/AI-Portfolio-Compass-public）的
`backend/app/services/freshness.py` 的 **数据新鲜度评估框架**。

「取其精华去其糟粕」适配说明：
  - 精华：FRESHNESS_RULES + evaluate_freshness + alert_cooldown_seconds
    这套"每个数据源有独立时效阈值、统一评估新鲜度"的设计，正是我们
    当前 date_guard 缺失的能力——我们每天跑十几个数据源，但只做了
    "brain_report 日期 vs TDX 最新" 这一条比对。本模块把它升级成
    **全数据源新鲜度矩阵**，一眼看清今天哪些数据可信、哪些滞后。
  - 去糟粕：原项目阈值按"秒级行情"（quote=5分钟）设计，不适合我们的
    **日级批量**系统。我们把阈值重写为「日级时效」（如板块主线/决策树
    应 <=1 交易日新鲜；学习日志可容忍 7 天），并改用 TDX 最新交易日作为
    "市场数据地面真值"做相对新鲜度判定，比原项目的绝对秒数更符合本系统。
  - 数据源：沿用我们自己的 output/*.json + TDX 本地库，不依赖任何商业源。
  - 用法：run_daily 在末尾用本模块替换原 date_guard；CIO memo 顶部展示矩阵。

输出：build() 返回 dict（矩阵 + 总体健康度 + 告警），并写 output/freshness_report.json。
"""
from __future__ import annotations

import os
import json
import sqlite3
import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "output")
DB_PATH = os.path.join(ROOT, "database", "vibe_research.db")
REPORT_PATH = os.path.join(OUT, "freshness_report.json")

# ── 新鲜度规则（日级批量系统适配版）──
# max_age_days：相对"地面真值（TDX 最新交易日）"或"今天"允许的最大滞后（交易日/自然日近似）
# warn_days：超过则告警（aging），再翻倍则 stale（critical）
FRESHNESS_RULES = {
    "sector_mainline":      {"label": "板块主线",     "max_age_days": 1,  "kind": "market",  "ref": "tdx"},
    "decision_tree":        {"label": "决策树",       "max_age_days": 1,  "kind": "market",  "ref": "tdx"},
    "brain_report":         {"label": "决策简报",     "max_age_days": 1,  "kind": "market",  "ref": "tdx"},
    "flow_report":          {"label": "资金流",       "max_age_days": 1,  "kind": "produced","ref": "today"},
    "gold_report":          {"label": "黄金",         "max_age_days": 1,  "kind": "produced","ref": "today"},
    "capital_migration_snap":{"label": "资金迁移快照","max_age_days": 1,  "kind": "produced","ref": "today"},
    "panqian":              {"label": "盘前纪要",     "max_age_days": 1,  "kind": "market",  "ref": "today"},
    "global_history":       {"label": "全球行情",     "max_age_days": 2,  "kind": "market",  "ref": "tdx"},
    "tdx_stock_daily":      {"label": "个股日线(TDX)","max_age_days": 0,  "kind": "market",  "ref": "tdx"},
    "learning_log":         {"label": "学习日志",     "max_age_days": 7,  "kind": "produced","ref": "today"},
    "trade_journal":        {"label": "交易日志",     "max_age_days": 7,  "kind": "produced","ref": "today"},
}

# 重复告警冷却（秒）。同一数据源连续 stale 时，避免刷屏。
ALERT_COOLDOWN = {
    "sector_mainline": 86400,
    "global_history": 86400,
    "tdx_stock_daily": 86400,
}


def _today() -> datetime.date:
    return datetime.date.today()


def _parse_date(s) -> Optional[datetime.date]:
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y%m%d"):
        try:
            return datetime.datetime.strptime(s[:len(fmt) + 6] if "T" in fmt or " " in fmt else s[:len(fmt)], fmt).date()
        except Exception:
            continue
    # 退回：仅取前 10 字符再试
    try:
        return datetime.date.fromisoformat(s[:10])
    except Exception:
        return None


def _tdx_latest() -> Optional[str]:
    """TDX 个股日线最新交易日 = 市场数据地面真值。"""
    try:
        con = sqlite3.connect(DB_PATH)
        row = con.execute("SELECT MAX(date) FROM stock_daily").fetchone()
        con.close()
        return row[0] if row else None
    except Exception:
        return None


def _global_latest() -> Optional[str]:
    try:
        con = sqlite3.connect(DB_PATH)
        row = con.execute("SELECT MAX(date) FROM global_history").fetchone()
        con.close()
        return row[0] if row else None
    except Exception:
        return None


def _file_mtime_date(path) -> Optional[datetime.date]:
    if not os.path.exists(path):
        return None
    try:
        return datetime.date.fromtimestamp(os.path.getmtime(path))
    except Exception:
        return None


def evaluate_freshness(data_type: str, as_of_date: Optional[str],
                       produced_date: Optional[datetime.date] = None) -> dict:
    """评估单个数据源新鲜度。

    as_of_date：数据"最新交易日"（market 类用）；produced_date：文件产生日（produced 类用）。
    返回 {status, age_days, max_age_days, note}。
    """
    rule = FRESHNESS_RULES.get(data_type)
    if not rule:
        return {"status": "unknown", "age_days": None, "max_age_days": None,
                "note": "未注册的数据源"}
    today = _today()
    ref_date = None
    note = ""

    if rule["kind"] == "market" and rule["ref"] == "tdx":
        # 相对 TDX 地面真值判断（避免"今天跑但 TDX 未同步"误报）
        ground = _parse_date(_tdx_latest())
        ad = _parse_date(as_of_date)
        if not ad or not ground:
            return {"status": "unknown", "age_days": None,
                    "max_age_days": rule["max_age_days"], "note": "无法读取日期"}
        ref_date = ground
        age = (ref_date - ad).days  # >=0 表示滞后
        if data_type == "tdx_stock_daily":
            # 它本身就是地面真值，永远 fresh，但报告其日期
            return {"status": "fresh", "age_days": 0, "max_age_days": 0,
                    "note": f"地面真值 {ad}"}
    elif rule["kind"] == "produced":
        pd = produced_date or _file_mtime_date(os.path.join(OUT, f"{data_type}.json"))
        if not pd:
            # 尝试用文件存在性兜底
            return {"status": "unknown", "age_days": None,
                    "max_age_days": rule["max_age_days"], "note": "无法读取产生日"}
        ref_date = today
        age = (ref_date - pd).days
    else:  # market + today（如 panqian 应等于今天）
        ad = _parse_date(as_of_date)
        if not ad:
            return {"status": "unknown", "age_days": None,
                    "max_age_days": rule["max_age_days"], "note": "无法读取日期"}
        ref_date = today
        age = (ref_date - ad).days

    max_age = rule["max_age_days"]
    if age <= max_age:
        status = "fresh"
        note = f"新鲜（滞后{age}天，阈值{max_age}）"
    elif age <= max_age * 2 + 1:
        status = "aging"
        note = f"偏旧（滞后{age}天，阈值{max_age}）⚠"
    else:
        status = "stale"
        note = f"过期（滞后{age}天，阈值{max_age}）❌"
    return {"status": status, "age_days": age,
            "max_age_days": max_age, "note": note}


def _source_dates(data_type: str, raw: dict) -> tuple:
    """返回 (as_of_date, produced_date) 供 evaluate_freshness 使用。"""
    if data_type == "sector_mainline":
        return raw.get("trade_date"), None
    if data_type in ("decision_tree", "brain_report"):
        return raw.get("trade_date"), _parse_date(raw.get("generated_at"))
    if data_type in ("flow_report", "gold_report", "capital_migration_snap"):
        return None, _parse_date(raw.get("generated_at"))
    if data_type == "panqian":
        return raw.get("article_date"), None
    if data_type == "global_history":
        return _global_latest(), None
    if data_type == "tdx_stock_daily":
        return _tdx_latest(), None
    if data_type in ("learning_log", "trade_journal"):
        return None, _file_mtime_date(
            os.path.join(OUT, f"{data_type}.jsonl"))
    return None, None


# ═══════════════════════════════════════════════════════
#  主构建
# ═══════════════════════════════════════════════════════

def build(write: bool = True) -> dict:
    """构建全数据源新鲜度矩阵。失败单个不影响整体（优雅降级）。"""
    matrix = []
    for dt, rule in FRESHNESS_RULES.items():
        # 读取对应数据源原始内容
        raw = None
        p = os.path.join(OUT, f"{dt}.json")
        if os.path.exists(p):
            try:
                raw = json.load(open(p, encoding="utf-8"))
            except Exception:
                raw = {}
        # 特殊：snapshot（capital_migration）文件名不同
        if dt == "capital_migration_snap":
            sp = os.path.join(OUT, "sector_flow_history.json")
            if os.path.exists(sp):
                try:
                    hist = json.load(open(sp, encoding="utf-8"))
                    raw = {"generated_at": (hist[-1].get("date") if isinstance(hist, list) and hist else "")}
                except Exception:
                    raw = {}
        as_of, produced = _source_dates(dt, raw or {})
        ev = evaluate_freshness(dt, as_of, produced)
        matrix.append({
            "data_type": dt,
            "label": rule["label"],
            "status": ev["status"],
            "age_days": ev["age_days"],
            "max_age_days": ev["max_age_days"],
            "as_of": (str(as_of)[:10] if as_of else ""),
            "note": ev["note"],
        })

    # 总体健康度
    n_total = len(matrix)
    n_fresh = sum(1 for m in matrix if m["status"] == "fresh")
    n_aging = sum(1 for m in matrix if m["status"] == "aging")
    n_stale = sum(1 for m in matrix if m["status"] == "stale")
    n_unknown = sum(1 for m in matrix if m["status"] == "unknown")

    health = "HEALTHY"
    if n_stale > 0:
        health = "STALE"
    elif n_aging > 1 or n_unknown > n_total * 0.3:
        health = "WATCH"

    alerts = [f"{m['label']}（{m['as_of']}）{m['note']}"
              for m in matrix if m["status"] in ("stale", "aging")]

    result = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "tdx_latest": _tdx_latest(),
        "health": health,            # HEALTHY / WATCH / STALE
        "counts": {"fresh": n_fresh, "aging": n_aging,
                   "stale": n_stale, "unknown": n_unknown, "total": n_total},
        "matrix": matrix,
        "alerts": alerts,
        "summary": (f"数据新鲜度：{n_fresh}新鲜 / {n_aging}偏旧 / "
                    f"{n_stale}过期 / {n_unknown}未知（基准 TDX 最新 "
                    f"{_tdx_latest()}）。"),
    }
    if alerts:
        result["summary"] += "需关注：" + "；".join(alerts[:3]) + "。"

    if write:
        try:
            with open(REPORT_PATH, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return result


def alert_cooldown_seconds(alert_type: str) -> int:
    """返回某类告警的最小重复间隔（秒）。"""
    return ALERT_COOLDOWN.get(alert_type, 0)


if __name__ == "__main__":
    import pprint
    pprint.pprint(build())
