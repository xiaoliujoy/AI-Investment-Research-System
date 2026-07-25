# -*- coding: utf-8 -*-
"""L5 龙头体系 Agent —— 四龙头（产业/资金/技术/情绪），确认主线板块代表性

Phase 3-1 升级：接入 L3.5 产业链推理的「证据 / 诚实护栏」。
  - 每个主线板块的四龙头，标注其是否落在 L3.5 已验证的产业链瓶颈上（共振可信度↑）。
  - 诚实护栏：主线板块若未获 L3.5 产业链验证，明确记为「仅资金维度」；
    若 L3.5 已把相关蹭热点个股降级，提示需基本面层复核（不替 L5 下买卖结论）。
"""
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from .base_agent import make_result, l35_evidence, l35_sector_validated


def _annotate_leaders(raw, ev):
    """把 L3.5 证据注入每个板块龙头结果（不破坏 leader_engine 既有结构）。"""
    leaders = raw.get("leaders") or {}
    n2s = ev.get("name_to_segments") or {}
    for sec, v in leaders.items():
        if not isinstance(v, dict):
            continue
        validated = l35_sector_validated(sec, ev)
        segs = []
        if validated:
            for nm, segs_list in n2s.items():
                if nm == str(sec) or nm in str(sec) or str(sec) in nm:
                    segs.extend(segs_list)
        v["l35"] = {"validated": validated, "top_segments": segs}
    raw["l35_evidence"] = ev


def run(ctx):
    from decision_tree import layer5_leaders, latest_date

    date = ctx.trade_date or latest_date()
    l4 = (ctx.get("L4") or {}).get("raw") or {}
    main_sectors = [str(m.get("sector")) for m in (l4.get("main_lines") or [])]
    raw = layer5_leaders(date, main_sectors)

    # ── L3.5 证据 / 诚实护栏 注入 ──
    l35 = (ctx.get("L3_5") or {}).get("raw") or {}
    ev = l35_evidence(l35)
    _annotate_leaders(raw, ev)

    leaders = raw.get("leaders") or {}
    n = len([k for k, v in leaders.items() if isinstance(v, dict) and not v.get("error")])
    # 主线板块中，获 L3.5 产业链验证的部分（产业链+龙头共振，容忍命名差异）
    overlap = [s for s in main_sectors if l35_sector_validated(s, ev)]

    stage = "bullish" if n > 0 else "neutral"
    conf = 85 if n > 0 else 40
    if overlap:
        conf = min(95, conf + 5)  # 产业链+龙头共振 → 加分

    # 诚实护栏：哪些主线只有资金维度、未获产业链验证
    only_fund = [s for s in main_sectors if s and not l35_sector_validated(s, ev)]
    gaps = list(raw.get("gaps") or [])
    if ev["validated_sectors"]:
        # 有验证 → 标注共振
        nar_l35 = (f"L3.5 产业链已验证瓶颈与龙头体系共振板块：{('、'.join(overlap) or '无')}。"
                   if overlap else
                   f"L3.5 产业链验证板块（{('、'.join(sorted(ev['validated_sectors'])))}）"
                   f"与当前资金主线无重叠，需注意主线偏主题炒作。")
    else:
        nar_l35 = "L3.5 产业链推理本轮无资金验证瓶颈，龙头结论仅基于资金/技术/情绪维度。"
    if only_fund and ev["validated_sectors"]:
        gaps.append(f"诚实护栏：主线 {('、'.join(only_fund[:5]) or '')} 未获 L3.5 产业链验证"
                    f"（仅资金维度，共识生命周期待观察）")

    narrative = f"四龙头体系覆盖 {n} 个主线板块。" + ("" if n else "（无龙头确认）") + " " + nar_l35
    risk = "断板/龙头切换是共识破裂的先行信号。" if n else "缺代表性龙头，难形成一致预期。"
    if ev["downgraded_count"]:
        risk += (f" L3.5 已将 {ev['downgraded_count']} 只蹭热点个股降级"
                 f"（见产业链推理层），相关板块需基本面层复核。")

    up = (f"接 L4 主线板块：{('、'.join(main_sectors[:5]) or '无')}"
          f" + L3.5 证据（验证板块 {len(ev['validated_sectors'])} 个）")
    res = make_result("L5", "龙头体系", stage, narrative, raw=raw,
                      signal={
                          "direction": stage,
                          "leader_count": n,
                          "l35_validated": len(overlap),
                          "l35_top_segments": ev["top_segments"],
                          "only_fund_sectors": only_fund,
                      },
                      confidence=conf, risk_note=risk, gaps=gaps, upstream=up)
    ctx.put("L5", res.to_dict())
    return res
