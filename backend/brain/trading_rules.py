# -*- coding: utf-8 -*-
"""
trading_rules.py —— 交易系统规则引擎
========================================
定义了交易操作系统的"安检清单"（Pre-flight Checklist）。

不再抽象地问"能不能买"，而是逐项检查6个条件是否满足。
每个条件有明确的 PASS/FAIL 判定逻辑 + 失败原因。

原则：
  - 规则驱动，非黑箱：每项判定都可追溯
  - 严守用户边界：不碰 ma20/ma60/个股成交额
  - 失败要告诉你"为什么"、"哪个条件不满足"、"差多少"
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CheckResult:
    """单项安检结果。"""
    name: str = ""            # 条件名称（如"成交额放大"）
    passed: bool = False       # 是否通过
    reason: str = ""           # 原因（通过时写"为什么通过"，失败时写"为什么失败"）
    detail: str = ""           # 补充细节（数据）
    weight: float = 1.0        # 权重（核心条件=1.5，辅助=1.0）


@dataclass
class PreflightReport:
    """安检清单总报告。"""
    checks: list = field(default_factory=list)  # [CheckResult, ...]
    passed_count: int = 0
    total_count: int = 6
    required: int = 5          # 至少需要5/6才能YES
    verdict: str = ""           # YES/NO/CAUTION
    verdict_reason: str = ""    # 一句话总结
    failed_summary: list = field(default_factory=list)  # 失败的项（名称+原因）
    calibration: dict = field(default_factory=dict)  # 系统自校准（IC 命中率反哺）状态


# ═══════════════════════════════════════════════════════
#  单条件判定函数（每个独立可测试）
# ═══════════════════════════════════════════════════════

def _check_volume(tree) -> CheckResult:
    """条件①：成交额放大 —— 全市场/主线板块成交额>20日均量。"""
    layers = tree.get("layers", {})
    l4 = layers.get("L4_consensus", {}) or {}
    mains = l4.get("main_lines", [])[:3]

    amplifying = 0
    details = []
    for m in mains[:3]:
        vol_trend = m.get("vol_trend", "")
        if "放大" in str(vol_trend):
            amplifying += 1
            details.append(f"{m.get('sector','')}:放量")
        else:
            details.append(f"{m.get('sector','')}:{vol_trend or '平量'}")

    if amplifying >= 2:
        return CheckResult(
            name="成交额放大",
            passed=True,
            reason=f"前3大主线中{amplifying}个放量——资金正在涌入",
            detail="；".join(details),
        )
    elif amplifying == 1:
        return CheckResult(
            name="成交额放大",
            passed=False,
            reason="仅1个主线放量——资金集中但未扩散",
            detail="；".join(details),
        )
    else:
        return CheckResult(
            name="成交额放大",
            passed=False,
            reason="主线板块均未放量——场外资金观望",
            detail="；".join(details),
        )


def _check_persistence(tree) -> CheckResult:
    """条件②：主线持续性 —— 至少1个主线连续2天净流入。"""
    layers = tree.get("layers", {})
    l4 = layers.get("L4_consensus", {}) or {}
    mains = l4.get("main_lines", [])[:5]

    continuous = []
    for m in mains:
        net_now = m.get("net_now", 0)
        net_5d = m.get("net_5d", 0)
        # 持续流入：今日净流入>0 且 5日累计>今日（说明不是今天才开始）
        if net_now > 0 and net_5d > net_now * 0.8:
            continuous.append({
                "sector": m.get("sector", ""),
                "net_now": net_now,
                "net_5d": net_5d,
            })

    if len(continuous) >= 2:
        names = [c["sector"] for c in continuous[:2]]
        return CheckResult(
            name="主线持续性",
            passed=True,
            reason=f"{'、'.join(names)}持续流入——不是一日游",
            detail=f"连续流入板块数={len(continuous)}",
        )
    elif len(continuous) == 1:
        c = continuous[0]
        return CheckResult(
            name="主线持续性",
            passed=False,
            reason=f"仅{c['sector']}持续流入——概率是独立行情而非主线",
            detail=f"连续流入板块数=1（需≥2）",
        )
    else:
        return CheckResult(
            name="主线持续性",
            passed=False,
            reason="无板块连续2天净流入——今天流入可能是脉冲",
            detail="连续流入板块数=0（需≥2）",
        )


def _check_leader_consensus(tree) -> CheckResult:
    """条件③：龙头一致性 —— 至少1个板块4龙头中3个指向同一只。"""
    layers = tree.get("layers", {})
    l5 = layers.get("L5_leader", {}) or {}
    leaders = l5.get("leaders", {})

    has_consensus = []
    from collections import Counter

    for sec, ld in leaders.items():
        if "error" in ld:
            continue
        ca = (ld.get("产业龙头", {}) or {}).get("name", "")
        fund = (ld.get("资金龙头", {}) or {}).get("name", "")
        tech = (ld.get("技术龙头", {}) or {}).get("name", "")
        sent = (ld.get("情绪龙头", {}) or {}).get("name", "")

        names = [n for n in [ca, fund, tech, sent] if n and not n.startswith("ST")]
        if not names:
            continue
        top_name, top_count = Counter(names).most_common(1)[0]
        if top_count >= 3:
            has_consensus.append({"sector": sec, "name": top_name, "count": top_count})

    if has_consensus:
        h = has_consensus[0]
        return CheckResult(
            name="龙头一致性",
            passed=True,
            reason=f"{h['sector']}的{h['name']}——{h['count']}/4龙头指向同一只",
            detail=f"共振板块数={len(has_consensus)}",
        )
    else:
        return CheckResult(
            name="龙头一致性",
            passed=False,
            reason="所有板块4龙头分散指向不同个股——资金未形成龙头共识",
            detail="共振板块数=0（需≥1个板块3/4共振）",
        )


def _check_diffusion(tree) -> CheckResult:
    """条件④：板块扩散 —— 至少2个同产业链板块同步上涨。"""
    layers = tree.get("layers", {})
    l4 = layers.get("L4_consensus", {}) or {}
    mains = l4.get("main_lines", [])[:8]

    # 产业链分组计数
    from brain.cio_agent import CHAIN_DETAIL, _match_chain

    chain_groups = {}
    for m in mains:
        sector = m.get("sector", "")
        net = m.get("net_now", 0)
        if net <= 0:
            continue
        chain = _match_chain(sector)
        chain_name = chain["name"] if chain else "其他"
        if chain_name not in chain_groups:
            chain_groups[chain_name] = []
        chain_groups[chain_name].append(sector)

    # 找到最大的产业链组
    best_chain = ""
    best_count = 0
    best_sectors = []
    for cn, sectors in chain_groups.items():
        if len(sectors) > best_count and cn != "其他":
            best_count = len(sectors)
            best_chain = cn
            best_sectors = sectors

    if best_count >= 2:
        return CheckResult(
            name="板块扩散",
            passed=True,
            reason=f"「{best_chain}」中{'、'.join(best_sectors)}同步流入——产业逻辑成立",
            detail=f"同链板块数={best_count}",
        )
    elif best_count == 1:
        return CheckResult(
            name="板块扩散",
            passed=False,
            reason=f"「{best_chain}」仅{best_sectors[0]}一个板块流入——未扩散到产业链其他环节",
            detail=f"同链板块数=1（需≥2）",
        )
    else:
        return CheckResult(
            name="板块扩散",
            passed=False,
            reason="流入板块不在同一产业链——资金离散，无主线逻辑",
            detail="同链板块数=0（需≥2）",
        )


def _check_macro_support(tree) -> CheckResult:
    """条件⑤：宏观支持 —— L1+L2 均无重大风险信号。"""
    layers = tree.get("layers", {})
    l1 = layers.get("L1_global_macro", {}) or {}
    l2 = layers.get("L2_china_macro", {}) or {}

    l1_score = l1.get("score", 0) if isinstance(l1.get("score"), (int, float)) else 0
    l2_score = l2.get("score", 0) if isinstance(l2.get("score"), (int, float)) else 0
    l1_read = l1.get("read", "") or ""
    l2_read = l2.get("read", "") or ""

    # 宏观风险信号
    global_risk = "避险" in l1_read or "危机" in l1_read or "暴跌" in l1_read
    china_risk = "紧信用" in l2_read or "收缩" in l2_read

    if l1_score >= 60 and l2_score >= 60 and not global_risk:
        return CheckResult(
            name="宏观支持",
            passed=True,
            reason="全球+中国宏观无重大风险——宏观环境支持交易",
            detail=f"全球={l1_read[:40]}；中国={l2_read[:40]}",
        )
    elif global_risk:
        return CheckResult(
            name="宏观支持",
            passed=False,
            reason=f"全球宏观风险信号：{l1_read[:60]}",
            detail=f"全球得分={l1_score}，中国={l2_score}",
        )
    elif china_risk:
        return CheckResult(
            name="宏观支持",
            passed=False,
            reason=f"中国宏观信号偏紧：{l2_read[:60]}",
            detail=f"中国得分={l2_score}，全球={l1_score}",
        )
    else:
        return CheckResult(
            name="宏观支持",
            passed=False,
            reason=f"宏观得分偏低（全球={l1_score}，中国={l2_score}）",
            detail="建议等宏观数据确认后再入场",
        )


def _check_sentiment_support(tree) -> CheckResult:
    """条件⑥：情绪支持 —— 赚钱效应>40%，情绪非冰点。"""
    layers = tree.get("layers", {})
    sentiment = layers.get("sentiment", {}) or {}
    sentiment_state = sentiment.get("state", "")
    up_ratio = sentiment.get("up_ratio", 0)
    up_pct = round(up_ratio * 100) if 0 < up_ratio < 1 else up_ratio

    if up_pct >= 40 and sentiment_state not in ("冰点", "恐慌"):
        return CheckResult(
            name="情绪支持",
            passed=True,
            reason=f"上涨家数{up_pct}%——市场有赚钱效应",
            detail=f"情绪状态={sentiment_state or '中性'}",
        )
    elif up_pct < 30:
        return CheckResult(
            name="情绪支持",
            passed=False,
            reason=f"上涨家数仅{up_pct}%——市场普跌，强行交易胜率极低",
            detail=f"情绪状态={sentiment_state or '冰点'}",
        )
    else:
        return CheckResult(
            name="情绪支持",
            passed=False,
            reason=f"上涨家数{up_pct}%——赚钱效应不足，观望",
            detail=f"情绪状态={sentiment_state or '偏弱'}",
        )


# ═══════════════════════════════════════════════════════
#  主入口：运行6项安检
# ═══════════════════════════════════════════════════════

def _check_system_calibration(tree, sig) -> CheckResult:
    """条件⑦（meta 项）：系统自校准 —— IC 方向历史命中率是否够格放行交易。

    IC 命中率来自 learning_center 的「预测回放」（每日回放 T+1 实际市场方向）。
    命中率 < 50% 说明当前系统对『该不该买』的方向判断劣于（或仅持平）随机，
    应提高入场标准：该检查 FAIL 会直接拉低通过数，并触发 verdict 降级（meta gate）。
    """
    acc = sig.get("accuracy")
    n = sig.get("n", 0)
    if acc is None:
        return CheckResult(
            name="系统自校准",
            passed=True,
            reason="IC 方向命中率暂未回放（预测样本积累中）",
            detail="—",
        )
    if acc >= 50:
        return CheckResult(
            name="系统自校准",
            passed=True,
            reason=f"IC 方向命中率 {acc}%（{n}日回放）——系统方向判断可信，正常放行",
            detail=f"命中率 {acc}% ≥ 50%",
        )
    if acc < 40:
        return CheckResult(
            name="系统自校准",
            passed=False,
            reason=(f"IC 方向命中率仅 {acc}%（{n}日回放），显著低于随机——"
                    f"系统当前『该不该买』的判断不可信，提高入场标准"),
            detail=f"命中率 {acc}% < 40%",
        )
    return CheckResult(
        name="系统自校准",
        passed=True,
        reason=(f"IC 方向命中率 {acc}%（{n}日回放）偏低——仓位护栏已自动收紧，"
                f"仅可小仓试探"),
        detail=f"命中率 {acc}% ∈ [40,50)",
    )


def _apply_calibration_gate(verdict, calibration):
    """系统自校准 meta gate（纯函数，便于单测）。

    IC 命中率<40% 时强制降级：YES→CAUTION、CAUTION→NO。
    返回 (verdict, calibration)；仅当 verdict 实际改变时标记 downgraded=True。
    """
    if not (calibration.get("available") and calibration.get("accuracy") is not None
            and calibration["accuracy"] < 40):
        return verdict, calibration
    new_verdict = verdict
    if verdict == "YES":
        new_verdict = "CAUTION"
    elif verdict == "CAUTION":
        new_verdict = "NO"
    if new_verdict != verdict:
        calibration["downgraded"] = True
        calibration["downgraded_from"] = verdict
    return new_verdict, calibration


def run_preflight(tree, ic_signal=None) -> PreflightReport:
    """运行安检清单（基础6项 + 可选「系统自校准」第7项）。

    ic_signal: dict，来自 learning_center.prediction_feedback() 或 cio_agent 构造，
               含 {available, accuracy, n, pos_scale}。命中率<40% 触发 meta 降级。
    """
    base_checks = [
        _check_volume(tree),
        _check_persistence(tree),
        _check_leader_consensus(tree),
        _check_diffusion(tree),
        _check_macro_support(tree),
        _check_sentiment_support(tree),
    ]
    all_checks = list(base_checks)

    calibration = {
        "available": False, "accuracy": None, "n": 0,
        "pos_scale": 1.0, "downgraded": False, "base_verdict": "",
    }
    if ic_signal and ic_signal.get("available"):
        calibration.update({
            "available": True,
            "accuracy": ic_signal.get("accuracy"),
            "n": ic_signal.get("n", 0),
            "pos_scale": ic_signal.get("pos_scale", 1.0),
        })
        all_checks.append(_check_system_calibration(tree, ic_signal))

    passed_count = sum(1 for c in all_checks if c.passed)
    total = len(all_checks)

    # 交易系统决策规则（基于全部检查项）
    if passed_count >= 5:
        verdict = "YES"
        verdict_reason = f"安检通过{passed_count}/{total}——系统允许交易。请人工确认图形买点。"
    elif passed_count >= 3:
        verdict = "CAUTION"
        verdict_reason = f"安检通过{passed_count}/{total}——部分条件未满足，可小仓位试探，但不宜重仓。"
    else:
        verdict = "NO"
        verdict_reason = f"安检仅通过{passed_count}/{total}——{total-passed_count}项条件失败，建议空仓等待。"

    # ── 系统自校准 meta gate：命中率<40% 时强制降级 ──
    calibration["base_verdict"] = verdict
    verdict, calibration = _apply_calibration_gate(verdict, calibration)
    if calibration.get("downgraded"):
        verdict_reason += (f"（⚠️ 系统自校准：IC 命中率仅 {calibration['accuracy']}%，"
                           f"已降级为 {verdict}）")
    elif (calibration.get("available") and calibration.get("accuracy") is not None
            and calibration["accuracy"] < 40):
        verdict_reason += (f"（⚠️ 系统自校准：IC 命中率仅 {calibration['accuracy']}%，"
                           f"系统处于防御态）")

    failed_summary = [
        {"condition": c.name, "reason": c.reason}
        for c in all_checks if not c.passed
    ]

    return PreflightReport(
        checks=all_checks,
        passed_count=passed_count,
        total_count=total,
        required=5,
        verdict=verdict,
        verdict_reason=verdict_reason,
        failed_summary=failed_summary,
        calibration=calibration,
    )
