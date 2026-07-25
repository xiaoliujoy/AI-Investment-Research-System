# -*- coding: utf-8 -*-
"""
AgentResult — 所有 Agent 的统一输出契约。

用户要求：Agent 不是一个裸字典，而是有 score/stage/narrative 的结构化结果。
同时保留现有字段（raw/signal/confidence/risk_note/upstream/gaps），确保下游
orchestrator/render 零改动兼容。
"""
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class AgentResult:
    """八层决策 Agent 的统一返回结构。

    score  (0-100) — 该层当前评分（置信度归一化）
    stage  (str)    — 方向信号：bullish / neutral_bullish / neutral / neutral_bearish / bearish / human / unknown
    narrative (str) — 一句话阐述该层结论，供 L0 叙事与推理链消费
    """
    layer: str
    title: str
    score: int
    stage: str
    narrative: str
    raw: Optional[Dict[str, Any]] = field(default_factory=dict)
    signal: Dict[str, Any] = field(default_factory=dict)
    confidence: int = 0
    risk_note: str = ""
    upstream: str = ""
    gaps: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """向后兼容现有代码：dict 形式输出（含 legacy 字段）。"""
        d = asdict(self)
        d["output"] = self.narrative
        d["direction"] = self.stage  # legacy key for conflict detection
        return d


def make_result(layer: str, title: str, stage: str, narrative: str,
                raw: Any = None, signal: Dict = None,
                confidence: int = 0, risk_note: str = "",
                upstream: str = "", gaps: List = None) -> AgentResult:
    """快捷构造一个 AgentResult。score 由 confidence 映射。"""
    if signal is None:
        signal = {}
    signal.setdefault("direction", stage)
    return AgentResult(
        layer=layer, title=title,
        score=confidence,
        stage=stage,
        narrative=narrative,
        raw=raw or {}, signal=signal,
        confidence=confidence,
        risk_note=risk_note,
        upstream=upstream,
        gaps=gaps or [],
    )


def l35_evidence(l35_raw):
    """从 L3.5 产业链推理的 raw 抽取「证据 / 诚实护栏」结构化摘要，供 L5 / fundamental 消费。

    返回：
      validated_sectors : set  获资金验证的瓶颈广义键（INDUSTRY_CHAIN 键，如「医药」「半导体」）
      validated_names   : set  获验证瓶颈对应的真实板块名（sector_name，如「医疗服务」「半导体」）
      name_to_segments  : dict 真实板块名 -> 该板块获验证的瓶颈环节列表（"板块·环节"）
      top_segments      : list 全局获验证瓶颈环节名（按 score 降序前 6，供概览展示）
      candidate_gaps    : dict 候选个股 -> 数据缺口列表（诚实护栏：绝不编造未接入数据）
      downgraded_stocks : list 蹭热点降级个股（需基本面层复核）
      downgraded_count  : int
    """
    l35_raw = l35_raw or {}
    bottlenecks = l35_raw.get("bottlenecks") or []
    candidates = l35_raw.get("candidates") or []
    downgraded = l35_raw.get("downgraded_themes") or []

    validated_sectors = set()
    validated_names = set()
    name_to_segments = {}
    top_segments = []
    for b in sorted(bottlenecks, key=lambda x: x.get("score", 0), reverse=True):
        if not b.get("fund_validated"):
            continue
        validated_sectors.add(b.get("sector"))
        nm = b.get("sector_name") or b.get("sector")
        validated_names.add(nm)
        seg = f"{nm}·{b.get('segment')}"
        name_to_segments.setdefault(nm, []).append(seg)
        top_segments.append(seg)
    candidate_gaps = {}
    for c in candidates:
        if c.get("data_gaps"):
            candidate_gaps[c.get("name")] = c.get("data_gaps")
    return {
        "validated_sectors": validated_sectors,
        "validated_names": validated_names,
        "name_to_segments": name_to_segments,
        "top_segments": top_segments[:6],
        "candidate_gaps": candidate_gaps,
        "downgraded_stocks": [d.get("stock") for d in downgraded],
        "downgraded_count": len(downgraded),
    }


def l35_sector_validated(sec, ev):
    """容忍板块命名差异，判断某主线板块是否落在 L3.5 已验证瓶颈上。

    L3.5 的 bottleneck 同时带广义键（sector，如「医药」）与真实板块名（sector_name，
    如「医疗服务」）。L4 主线用同花顺细名。匹配优先级：
      1) 真实板块名精确相等；2) 真实板块名双向子串包含；3) 广义键双向子串包含。
    """
    if not sec:
        return False
    sec = str(sec)
    for nm in (ev.get("validated_names") or set()):
        nm = str(nm)
        if nm and (nm == sec or nm in sec or sec in nm):
            return True
    for k in (ev.get("validated_sectors") or set()):
        k = str(k)
        if k and (k in sec or sec in k):
            return True
    return False
