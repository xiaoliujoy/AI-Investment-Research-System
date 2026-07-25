# -*- coding: utf-8 -*-
"""
orchestrator：总指挥（大脑）。

用户要求：从"八份平行分析"跃迁为"一条推理链 + 唯一决策结论"。

本模块职责：
  1) 按依赖顺序运行各 Agent（L1→L2→L4→L3→L5→sentiment→fundamental→L6→L7→L8），
     上一层结论写入 ctx，下一层读取 → 真正的因果链。
  2) 生成 L0 叙事（消费 L1-L4 + sentiment + fundamental），作为报告定调。
  3) 跑跨层冲突检测（层间打架显式暴露）。
  4) 聚合置信度（带冲突惩罚）。
  5) 输出唯一交易结论：can_buy / reason / position_pct / confidence_overall / conflicts / chain。

设计原则（守用户边界）：
  - 系统只"定方向 + 验证 + 给决策建议"，价格行为/图形/个股硬过滤归用户。
  - 决策逻辑透明（规则投票 + 强否决），非黑箱模型。
"""
import os
import sys
import json

BASE = os.path.dirname(os.path.abspath(__file__))
BACK = os.path.dirname(BASE)
if BACK not in sys.path:
    sys.path.insert(0, BACK)

from .context import ReasoningContext  # noqa
from .agents import (run_L1, run_L2, run_L4, run_L3, run_L3_5, run_L5, run_sentiment,  # noqa
                     run_fundamental, run_L6, run_L7, run_L8, run_gold, run_flow)  # noqa (agents 子包)
from .narrative_l0 import build as build_l0  # noqa
from .conflict import detect as detect_conflicts  # noqa
from .confidence import aggregate_overall  # noqa
from committee.investment_committee import (decide as ic_decide,  # noqa
                                             RESEARCH_CENTER_LAYERS)  # noqa


def _dir(results, layer):
    return (results.get(layer) or {}).get("signal", {}).get("direction")


def run(date=None):
    if date is None:
        from decision_tree import latest_date
        date = latest_date()

    ctx = ReasoningContext(trade_date=date)

    def _safe(fn, label):
        """label 显式传入：各 agent 以 `from .X import run as run_LN` 别名导入，
        fn.__name__ 恒为 'run'，若靠它命名会让多层失败写入同一个 key 互相覆盖，
        掩盖『多层同时失效』。显式 label 保证每层失败写入独立正确的 key。"""
        try:
            return fn(ctx)
        except Exception as e:
            ctx.put(label, {"layer": label, "title": label, "raw": {},
                            "signal": {"direction": "unknown"},
                            "output": f"该层计算失败：{type(e).__name__}",
                            "confidence": 20, "risk_note": "", "upstream": "",
                            "gaps": [repr(e)[:120]]})

    # 1) 推理流水线（保持依赖顺序，单层失败不阻断整条链）
    if run_flow:
        _safe(run_flow, "FLOW")    # L0 资金情报中心（消费 GOLD → 反哺 L1 全球宏观校准）
    _safe(run_L1, "L1")
    _safe(run_gold, "GOLD")        # 跨资产黄金引擎（消费 L1 全球宏观 → 反哺 L1 校准）
    _safe(run_L2, "L2")
    _safe(run_L4, "L4")            # 共识先算，供 L3/L5/fundamental 消费
    _safe(run_L3, "L3")            # 依赖 L4
    _safe(run_L3_5, "L3_5")        # L3.5 产业链推理（依赖 L3/L4 + 盘前纪要热榜），喂 L5
    _safe(run_L5, "L5")            # 依赖 L4 主线
    _safe(run_sentiment, "sentiment")
    _safe(run_fundamental, "fundamental")  # 依赖 L4 主线
    _safe(run_L6, "L6")
    _safe(run_L7, "L7")            # 依赖 L4 + L6
    _safe(run_L8, "L8")

    # 2) L0 叙事（消费 L1-L4 + sentiment + fundamental 定调）
    l0 = build_l0(ctx)
    ctx.put("L0", {"layer": "L0", "title": "市场叙事", "raw": l0, "signal": {},
                   "output": l0["headline"] + " " + l0["body"],
                   "confidence": 90, "risk_note": "", "upstream": "", "gaps": []})

    # 3) L8 学习反哺信号（Learning OS ──▶ Decision OS 唯一反向箭头）
    try:
        from learning_feedback import learning_feedback
        feedback = learning_feedback()
    except Exception as e:
        feedback = {"applied": False, "status": "反哺不可用",
                    "conf_delta": 0, "pos_scale": 1.0, "sector_bias": {},
                    "notes": [repr(e)[:80]], "count": 0}

    # 4) 冲突 + 置信度 + 决策
    conflicts = detect_conflicts(ctx)
    ctx.conflicts = conflicts
    conf = aggregate_overall(ctx.results, conflicts)
    # 学习反哺净调整总置信度（透明可见）
    delta = feedback.get("conf_delta", 0) if feedback.get("applied") else 0
    if delta:
        conf["learning_delta"] = delta
        conf["overall"] = max(0, min(100, conf["overall"] + delta))
    # ★ Investment Committee（投资委员会）：唯一决策出口，汇总 Research Center(L1~L8)
    #   不做研究，只把各层评分/证据/概率/冲突 → 唯一投资决策，供 CIO 生成日报。
    committee = ic_decide(ctx.results, conflicts, conf, feedback)
    decision = committee  # 权威决策（旧 _decide 逻辑已并入 IC，避免双决策源）

    report = {
        "generated_at": ctx.generated_at,
        "trade_date": date,
        "L0": l0,
        "decision": decision,
        "committee": committee,  # 投资委员会结论（与 decision 同源，语义更明确）
        "research_center": {
            "layers": RESEARCH_CENTER_LAYERS,
            "note": "研究中枢（Research Center）= L1~L8 八层分析引擎，只做研究，不做决策",
        },
        "confidence": conf,
        "conflicts": conflicts,
        "learning_feedback": feedback,
        "chain": ["L0"] + ctx.order,   # 展示顺序：L0 定调 → L1..L8
        "results": ctx.results,
        "cio_memo": None,  # 占位，下面 CIO Agent 跑完再回填
    }

    # 先写 JSON：让 CIO Agent 读到「本轮」新鲜数据。
    # 修复 stale-read：旧逻辑 produce_cio() 在写盘前调用 → _load_data() 读到的是
    # 上一轮 brain_report.json（缺本轮 L3_5 / 最新冲突 / 最新决策）。
    jpath = os.path.join(BACK, "output", "brain_report.json")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    # 5) CIO Agent：首席投资官（阅读八层结论 → 输出投资决策备忘录）
    cio_memo = None
    try:
        from brain.cio_agent import produce as produce_cio
        cio_memo_raw = produce_cio()
        # 序列化为可 JSON 的字典
        if hasattr(cio_memo_raw, '__dataclass_fields__'):
            from dataclasses import asdict
            cio_memo = asdict(cio_memo_raw)
        else:
            cio_memo = cio_memo_raw
    except Exception as e:
        cio_memo = {"error": f"CIO Agent 执行失败: {type(e).__name__}: {e}"}

    report["cio_memo"] = cio_memo
    # 再写一次（含 CIO 备忘录）
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    return report


def build_report(report, path=None):
    from .render import render_html
    path = path or os.path.join(BACK, "output", "brain_report.html")
    render_html(report, path)
    return path
