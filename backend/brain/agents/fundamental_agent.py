# -*- coding: utf-8 -*-
"""基本面验证 Agent —— 板块级业绩（营收/净利同比/ROE）vs 估值（PE），验证方向"""
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from .base_agent import make_result


def run(ctx):
    from fundamental_engine import layer_fundamental

    l4 = (ctx.get("L4") or {}).get("raw") or {}
    focus = [str(m.get("sector")) for m in (l4.get("main_lines") or [])
             if m.get("stage") != "退潮"][:5]
    # Phase 3-1：把 L3.5 产业链证据 / 诚实护栏喂给基本面层
    l35 = (ctx.get("L3_5") or {}).get("raw") or {}
    raw = layer_fundamental(focus, l35=l35)
    sectors = raw.get("sectors") or []
    driven = [s for s in sectors if s.get("verdict") == "业绩驱动"]
    over = [s for s in sectors if "估值偏高" in (s.get("verdict") or "")]
    if driven and not over:
        stage = "bullish"
    elif over and not driven:
        stage = "bearish_weak"
    else:
        stage = "neutral"
    conf = 80 if sectors else 50
    narrative = raw.get("read", "")
    risk = f"{len(over)} 个板块估值偏高且业绩未跟上，谨慎追高。" if (over and not driven) else ""
    up = f"接 L4 主线焦点（非退潮）：{('、'.join(focus[:5]) or '无')}"
    res = make_result("fundamental", "基本面验证", stage, narrative, raw=raw,
                      signal={"direction": stage, "driven": len(driven), "overvalued": len(over),
                              "sectors": [s.get("sector") for s in sectors]},
                      confidence=conf, risk_note=risk, gaps=raw.get("gaps"), upstream=up)
    ctx.put("fundamental", res.to_dict())
    return res
