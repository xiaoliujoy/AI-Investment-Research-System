# -*- coding: utf-8 -*-
"""
panqian_ingest.py —— 盘前纪要「灌入」模块（Phase 1）

把 panqian_parser 产出的结构化 JSON 派生为 4 类 feed，
供系统其他引擎在「叙事 / 催化 / 情绪 / 风控」层消费：

  1) narrative_feed  热点事件 + 利好公告 → Narrative Engine 的「为什么」催化候选
  2) catalyst_feed   含政策/日期的公告与事件 → 催化剂日历的真实事件锚点
  3) cro_feed        连板高度 / 新高 / 热榜 top → CRO「最大边际变化」情绪信号
  4) risk_landmines  公告里的减持/风险/利空/解禁 → 风控「地雷阵」

产物：output/panqian_feed.json（latest，覆盖写）。
所有下游读取方都以「文件存在且非空 + has_data」为前置，缺失安全降级。
"""
from __future__ import annotations

import os
import re
import json
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "output")
FEED_FILE = os.path.join(OUT, "panqian_feed.json")

# 含明确日期/政策表述的热点 → 催化剂候选
_CATALYST_KW = ["政策", "会议", "发布", "落地", "实施", "补贴", "规划", "目标", "截止", "申报",
                "中标", "合同签订", "获批", "牌照", "令", "法案", "数据公布", "将于", "拟于", "日起",
                "大会", "发布会", "量产", "开幕", "上线", "首发", "试飞", "挂牌", "通车", "投产"]


def _name_of(code, code2name):
    return code2name.get(code, code) if code2name else code


def _load_map():
    code2name = {}
    try:
        import sqlite3
        db = os.path.join(BASE, "database", "vibe_research.db")
        if os.path.exists(db):
            con = sqlite3.connect(db)
            for code, name in con.execute("SELECT code, name FROM stock_info"):
                code2name[str(code).strip()] = name
            con.close()
    except Exception:
        pass
    return code2name


def derive_feed(parsed: dict) -> str:
    """从一条已解析的盘前纪要 dict 派生 feed，写盘并返回路径。"""
    code2name = _load_map()
    sections = parsed.get("sections", {})
    adate = parsed.get("article_date", "")

    # ── 1) narrative_feed ──
    nf = []
    for it in sections.get("hotspot", {}).get("items", []):
        stocks = it.get("stocks", [])
        if stocks or it.get("text"):
            nf.append({
                "theme": (it.get("text") or "")[:80],
                "stocks": [_name_of(c, code2name) for c in stocks],
                "kind": "热点事件",
            })
    for it in sections.get("announce", {}).get("items", []):
        if it.get("type") == "利好" and it.get("stocks"):
            nf.append({
                "theme": it.get("detail", "")[:80],
                "stocks": [_name_of(c, code2name) for c in it["stocks"]],
                "kind": "利好公告",
            })

    # ── 2) catalyst_feed ──
    cf = []
    for it in sections.get("hotspot", {}).get("items", []):
        txt = it.get("text", "") or ""
        if any(k in txt for k in _CATALYST_KW):
            # 抽日期
            dm = re.search(r"(\d{1,2})月(\d{1,2})[日号]", txt)
            date_cn = f"{dm.group(1)}月{dm.group(2)}日" if dm else ""
            cf.append({
                "name": txt[:40],
                "related_stocks": [_name_of(c, code2name) for c in it.get("stocks", [])],
                "date_cn": date_cn,
                "source": "盘前纪要·热点",
            })
    for it in sections.get("announce", {}).get("items", []):
        if it.get("type") in ("利好",) and any(k in it.get("detail", "") for k in _CATALYST_KW):
            cf.append({
                "name": it.get("detail", "")[:40],
                "related_stocks": [_name_of(c, code2name) for c in it.get("stocks", [])],
                "date_cn": "",
                "source": "盘前纪要·公告",
            })

    # ── 3) cro_feed（情绪 / 热度信号）──
    max_days = 0
    chain_stocks = []
    for it in sections.get("limit_up", {}).get("items", []):
        if it.get("days"):
            max_days = max(max_days, it["days"])
            chain_stocks.extend(_name_of(c, code2name) for c in it.get("stocks", []))
    new_high = []
    for it in sections.get("new_high", {}).get("items", []):
        new_high.extend(_name_of(c, code2name) for c in it.get("stocks", []))
    hot_top = []
    for it in sections.get("hot_list", {}).get("items", []):
        if it.get("rank") and it["rank"] <= 5:
            # 优先用原文列出的名字（含未入库标的，如长鑫科技），保证热榜完整性
            names = it.get("names") or [_name_of(c, code2name) for c in it.get("stocks", [])]
            hot_top.append({
                "rank": it["rank"],
                "stock": names,
                "reason": "、".join(names)[:40],
            })
    cro_feed = {
        "limit_up_max_days": max_days,
        "limit_up_stocks": chain_stocks[:10],
        "new_high_stocks": new_high[:15],
        "hot_list_top": hot_top,
    }

    # ── 4) risk_landmines ──
    risk = []
    for r in parsed.get("risk_flags", []):
        risk.append({
            "stock": _name_of(r.get("stock", ""), code2name),
            "type": r.get("type", ""),
            "detail": r.get("detail", "")[:80],
        })

    feed = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "article_date": adate,
        "has_data": True,
        "narrative_feed": nf,
        "catalyst_feed": cf,
        "cro_feed": cro_feed,
        "risk_landmines": risk,
        "stats": parsed.get("stats", {}),
        "headline": parsed.get("headline", ""),
    }
    os.makedirs(OUT, exist_ok=True)
    with open(FEED_FILE, "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, indent=2)
    return FEED_FILE


def run_cli(argv=None):
    """可选：直接对某个 panqian_*.json 重算 feed。"""
    import argparse
    ap = argparse.ArgumentParser(description="盘前纪要 feed 派生")
    ap.add_argument("json", nargs="?", help="panqian_*.json 路径（缺省取最新）")
    args = ap.parse_args(argv)
    if args.json:
        p = args.json
    else:
        files = sorted([f for f in os.listdir(OUT) if f.startswith("panqian_") and f.endswith(".json")],
                       reverse=True)
        if not files:
            print("[盘前纪要] 没有可派生的 panqian_*.json", file=sys.stderr) if False else None
            print("[盘前纪要] 没有可派生的 panqian_*.json")
            return 1
        p = os.path.join(OUT, files[0])
    with open(p, encoding="utf-8") as f:
        parsed = json.load(f)
    out = derive_feed(parsed)
    print(f"[盘前纪要] feed → {out}（article_date={parsed.get('article_date','')}）")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(run_cli())
