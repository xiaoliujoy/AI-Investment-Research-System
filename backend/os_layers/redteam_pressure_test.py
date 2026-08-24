# -*- coding: utf-8 -*-
"""
观察层 Red-Team 压力测试 PoC 编排器（红方 → 蓝方 → 裁判 三节点）
==================================================
归属：observation 观察层独立子模块，与生产交易决策系统物理隔离。
协议：docs/governance_poc_redteam.md（2026-08-22 修订：输出契约升级为红蓝裁三节点）

拓扑（单向线性管道，无状态）：
  [ memo HTML ] -> 红方 Red Team Lead -> 蓝方 Blue Team Defender -> 裁判 Judge
                                                          |
                                            ┌-------------┴--------------┐
                                      合规入库《Red-Team 审查记录》  INVALID_ROUND 占位(不入人工视图)

设计要点（源自协议 + 用户拓扑决策 2026-08-22）：
  - 红方 / 蓝方 / 裁判 均为 LLM 调用；Schema Gatekeeper 为纯 Python 规则引擎（非 LLM）。
  - 单轮靶向审查：红方产出 2~4 个攻击点；蓝方按 attack_id 逐条抗辩；裁判独立终审评分(0~100)。
  - 容错：任一节点首次未过 Gatekeeper，注入错误并至多重试 1 次；二次失败标记 INVALID_ROUND，
    渲染占位记录（供人工审计，不进入正式观察视图）。
  - 零生产权限：本模块只产出观察层归档，不碰交易打分/调仓/下单。

运行方式：
  # 自检（mock LLM，不需真实模型，验证管道 + 硬卡 + INVALID_ROUND 路径）
  python redteam_pressure_test.py --self-test

  # 真实运行（需配置 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 环境变量）
  python redteam_pressure_test.py --input output/memo_YYYY-MM-DD.html --output output/redteam_record_YYYY-MM-DD.md
"""

import argparse
import datetime as _dt
import html
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.request
from typing import List, Optional

LOG = logging.getLogger("redteam")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ---------------------------------------------------------------------------
# 硬卡规则常量（协议第 3 节，2026-08-22 修订版）
# ---------------------------------------------------------------------------

# 红方攻击维度枚举
DIMENSIONS = {"宏观", "资金", "产业", "技术", "安检闸门", "仓位风控"}
# 蓝方抗辩立场枚举
STANCES = {"完全化解", "规则对冲", "部分承认", "无法化解"}

# 禁用表达库：命中即校验失败（延续原协议）
BANNED_PHRASES = [
    "注意市场波动",
    "政策存在不确定性",
    "未来走势需观察",
    "市场有风险",
    "注意风险",
    "存在不确定性",
    "需进一步观察",
    "走势尚不明朗",
]


# ---------------------------------------------------------------------------
# 节点 Prompts（红方 / 蓝方 / 裁判）
# ---------------------------------------------------------------------------

RED_TEAM_PROMPT = """你负责担任 A股 Trading OS 观察层的「红方首席审查官（Red Team Lead）」。
你的职责是对日终生成的 InvestmentDecisionMemo（投资决策备忘录）展开穿透式逻辑压力测试与漏洞挖掘。

【审查原则】
1. 严禁泛泛而谈，必须针对备忘录中的具体数据、主线板块、裁决逻辑和资金假设发起攻击。
2. 重点审查：宏观外围背离（如美债/SOXX/汇率）、板块资金分歧、安检闸门漏检、情绪高位退潮风险、因果强行归因。
3. 提出 2 至 4 个最具杀伤力的具体攻击点。

【输出约束】
必须且仅返回标准 JSON 对象，严禁包含任何 Markdown 格式外包裹文字。格式：
{
  "status": "SUCCESS",
  "attack_points": [
    {
      "id": 1,
      "dimension": "宏观 | 资金 | 产业 | 技术 | 安检闸门 | 仓位风控",
      "claim": "漏洞核心陈述（一句话明确问题）",
      "evidence_and_logic": "具体攻击推导、潜在黑天鹅场景或未被定价的矛盾数据"
    }
  ]
}
attack_points 数量必须为 2~4 个。dimension 必须从枚举中选择。禁止使用泛化风险提示。"""

BLUE_TEAM_PROMPT = """你负责担任 A股 Trading OS 的「蓝方首席防御官（Blue Team Defender）」。
你的职责是基于 InvestmentDecisionMemo 原文、前置安检记录、资金流数据与规则护栏，对红方的攻击点进行逐条抗辩。

【抗辩原则】
1. 事实第一：以备忘录已包含的客观事实（ETF净申购、板块流向、数据健康状态等）进行回击。
2. 护栏对冲：如果红方指出的风险客观存在，说明系统的仓位护栏、一票否决机制或盯盘清单是否已对该风险进行敞口锁死。
3. 诚实防御：若某一攻击点确实属于系统盲区且无规则防御，明确标注「无法化解」，严禁强词夺理。

【输出约束】
必须且仅返回标准 JSON 对象，严禁包含任何 Markdown 格式外包裹文字。格式：
{
  "status": "SUCCESS",
  "defense_points": [
    {
      "attack_id": 1,
      "stance": "完全化解 | 规则对冲 | 部分承认 | 无法化解",
      "counter_evidence": "引用的事实数据、安检指标或仓位收紧护栏",
      "residual_risk": "残余未化解风险说明（若已完全化解则填\"无\"）"
    }
  ]
}
defense_points 必须覆盖红方给出的每一个 attack_id。stance 必须从枚举中选择。禁止使用泛化风险提示。"""

JUDGE_PROMPT = """你负责担任 A股 Trading OS 观察层的「独立裁决仲裁员（Independent Judge）」。
你的职责是独立评估红方的攻击力度与蓝方的抗辩有效性，衡量原备忘录决策的鲁棒性并给出终审裁决。

【仲裁原则】
1. 综合评分（0~100）：
   - >=80 分：原决策逻辑扎实，护栏完备，红方攻击均被有效化解或对冲。
   - 65~79 分：存在局部盲区，但仓位与前置闸门已控制最大回撤，建议补充盯盘观察点。
   - <65 分：红方命中致命漏洞且蓝方防御失效，原决策存在显著风险。
2. 输出裁决结论：明确维持、谨慎修正或发出盘中预警信号。

【输出约束】
必须且仅返回标准 JSON 对象，严禁包含任何 Markdown 格式外包裹文字。格式：
{
  "status": "SUCCESS",
  "score": 85.0,
  "verdict": "维持原裁决 / 建议下调一级 / 补充盘中重点盯盘点",
  "rationale": "终审判定核心逻辑概述（说明红蓝双方谁的主张更具说服力）",
  "key_risk_watch": "盘中必须重点验证的单点条件（如：10:00 前龙头承接资金量）"
}
score 必须为 0~100 之间的数值。禁止使用泛化风险提示。"""


# ---------------------------------------------------------------------------
# LLM 接入点（节点 红方/蓝方/裁判）
# ---------------------------------------------------------------------------

def _call_llm_real(system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
    """
    基于 Python 标准库实现的通用 OpenAI 兼容协议客户端。
    通过环境变量读取配置，保持零第三方库依赖。
    """
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("LLM_MODEL") or os.getenv("REDTEAM_MODEL", "gpt-4o")

    if not api_key and "localhost" not in base_url and "127.0.0.1" not in base_url:
        raise ValueError("未检测到 LLM_API_KEY 或 OPENAI_API_KEY 环境变量，请先配置鉴权信息。")

    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"}
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"LLM API 响应异常 [HTTP {e.code}]: {err_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"LLM 网络连接失败: {e.reason}") from e


def call_llm(system: str, user: str, temperature: float) -> str:
    """统一 LLM 调用入口。"""
    return _call_llm_real(system, user, temperature)


# ---------------------------------------------------------------------------
# Schema Gatekeeper（纯 Python 规则引擎，非 LLM）
# ---------------------------------------------------------------------------

class GateResult:
    def __init__(self, ok: bool, errors: Optional[List[str]] = None):
        self.ok = ok
        self.errors = errors or []


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _contains_banned(text: str) -> Optional[str]:
    for phrase in BANNED_PHRASES:
        if phrase in text:
            return phrase
    return None


def _check_no_banned(obj) -> List[str]:
    """递归检查字符串字段是否命中禁用表达库。"""
    errors: List[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str):
                hit = _contains_banned(v)
                if hit:
                    errors.append(f"字段 {k} 命中禁用表达: 「{hit}」")
            else:
                errors.extend(_check_no_banned(v))
    elif isinstance(obj, list):
        for v in obj:
            errors.extend(_check_no_banned(v))
    return errors


def validate_attack_payload(raw: dict) -> GateResult:
    """校验红方输出：status / attack_points 2~4 个 / 字段非空 / dimension 枚举 / 禁用词。"""
    errors: List[str] = []
    if not isinstance(raw, dict):
        return GateResult(False, ["红方输出不是 JSON 对象"])
    if raw.get("status") != "SUCCESS":
        errors.append(f"红方 status 非法: {raw.get('status')!r}（须为 SUCCESS）")
    points = raw.get("attack_points")
    if not isinstance(points, list) or not (2 <= len(points) <= 4):
        errors.append(f"attack_points 数量须为 2~4 个，实际: {len(points) if isinstance(points, list) else '非列表'}")
    else:
        seen_ids = set()
        for p in points:
            if not isinstance(p, dict):
                errors.append("attack_points 含非对象条目")
                continue
            pid = p.get("id")
            if pid is None:
                errors.append("攻击点缺少 id")
            elif pid in seen_ids:
                errors.append(f"攻击点 id 重复: {pid}")
            seen_ids.add(pid)
            dim = str(p.get("dimension", "")).strip()
            if dim not in DIMENSIONS:
                errors.append(f"攻击点 {pid} dimension 非法: {dim!r}（须为 {sorted(DIMENSIONS)}）")
            for f in ("claim", "evidence_and_logic"):
                if not str(p.get(f, "")).strip():
                    errors.append(f"攻击点 {pid} 缺少或空字段: {f}")
    errors.extend(_check_no_banned(raw))
    return GateResult(len(errors) == 0, errors)


def validate_defense_payload(raw: dict, attack_ids: List[int]) -> GateResult:
    """校验蓝方输出：status / 覆盖全部 attack_id / stance 枚举 / 字段非空 / 禁用词。"""
    errors: List[str] = []
    if not isinstance(raw, dict):
        return GateResult(False, ["蓝方输出不是 JSON 对象"])
    if raw.get("status") != "SUCCESS":
        errors.append(f"蓝方 status 非法: {raw.get('status')!r}（须为 SUCCESS）")
    defenses = raw.get("defense_points")
    if not isinstance(defenses, list) or len(defenses) == 0:
        errors.append("defense_points 缺失或为空")
        defenses = []
    covered = set()
    for d in defenses:
        if not isinstance(d, dict):
            errors.append("defense_points 含非对象条目")
            continue
        aid = d.get("attack_id")
        if aid is None:
            errors.append("抗辩缺少 attack_id")
        else:
            covered.add(aid)
            if aid not in attack_ids:
                errors.append(f"抗辩指向不存在的 attack_id: {aid}")
        stance = str(d.get("stance", "")).strip()
        if stance not in STANCES:
            errors.append(f"抗辩 {aid} stance 非法: {stance!r}（须为 {sorted(STANCES)}）")
        for f in ("counter_evidence", "residual_risk"):
            if not str(d.get(f, "")).strip():
                errors.append(f"抗辩 {aid} 缺少或空字段: {f}")
    for aid in attack_ids:
        if aid not in covered:
            errors.append(f"红方攻击点 {aid} 未被蓝方抗辩覆盖")
    errors.extend(_check_no_banned(raw))
    return GateResult(len(errors) == 0, errors)


def validate_judge_payload(raw: dict) -> GateResult:
    """校验裁判输出：status / score 0~100 数值 / verdict / rationale / key_risk_watch / 禁用词。"""
    errors: List[str] = []
    if not isinstance(raw, dict):
        return GateResult(False, ["裁判输出不是 JSON 对象"])
    if raw.get("status") != "SUCCESS":
        errors.append(f"裁判 status 非法: {raw.get('status')!r}（须为 SUCCESS）")
    score = raw.get("score")
    try:
        score_f = float(score)
        if not (0 <= score_f <= 100):
            errors.append(f"score 超出 0~100 区间: {score_f}")
    except (TypeError, ValueError):
        errors.append(f"score 非法数值: {score!r}")
    for f in ("verdict", "rationale", "key_risk_watch"):
        if not str(raw.get(f, "")).strip():
            errors.append(f"裁判缺少或空字段: {f}")
    errors.extend(_check_no_banned(raw))
    return GateResult(len(errors) == 0, errors)


# ---------------------------------------------------------------------------
# 三节点执行（各含至多 1 次重试）
# ---------------------------------------------------------------------------

def _call_with_retry(system_prompt: str, user_prompt: str, temperature: float,
                     validate, node_name: str):
    """调用 LLM -> 解析 JSON -> Gatekeeper 校验；首轮失败注入错误重试 1 次。
    返回 (ok, data, errors)。二次失败 ok=False。"""
    last_errors: List[str] = []
    for attempt in range(2):
        sys_prompt = system_prompt
        if attempt == 1:
            sys_prompt = system_prompt + (
                "\n\n上一次输出未通过校验，错误如下，请修正后重新输出：\n" + "\n".join(last_errors)
            )
            LOG.warning("%s 重试（注入上轮错误）: %s", node_name, last_errors)
        raw_text = call_llm(sys_prompt, user_prompt, temperature)
        raw_text = _strip_code_fence(raw_text)
        if not raw_text:
            last_errors = ["模型返回空"]
            continue
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as e:
            last_errors = [f"JSON 解析失败: {e}"]
            continue
        res = validate(data)
        if res.ok:
            return True, data, []
        last_errors = res.errors
        LOG.warning("%s 被 Gatekeeper 拦截（轮次%d）: %s", node_name, attempt, res.errors)
    LOG.error("%s INVALID_ROUND：二次校验失败 %s", node_name, last_errors)
    return False, None, last_errors


def red_team_attack(memo_text: str):
    return _call_with_retry(RED_TEAM_PROMPT, memo_text, 0.4,
                            validate_attack_payload, "红方")


def blue_team_defense(attack_payload: dict, memo_text: str):
    attack_ids = [p.get("id") for p in attack_payload.get("attack_points", [])]
    user_prompt = json.dumps({
        "memo": memo_text[:6000],
        "red_team_attack": attack_payload,
    }, ensure_ascii=False)
    validate = lambda raw: validate_defense_payload(raw, attack_ids)  # noqa: E731
    return _call_with_retry(BLUE_TEAM_PROMPT, user_prompt, 0.3, validate, "蓝方")


def judge_verdict(attack_payload: dict, defense_payload: dict, memo_text: str):
    user_prompt = json.dumps({
        "memo": memo_text[:4000],
        "red_team_attack": attack_payload,
        "blue_team_defense": defense_payload,
    }, ensure_ascii=False)
    return _call_with_retry(JUDGE_PROMPT, user_prompt, 0.2, validate_judge_payload, "裁判")


# ---------------------------------------------------------------------------
# 备忘录核心裁决抽取（规则式，零 LLM 成本；提取不到不阻断）
# ---------------------------------------------------------------------------

def _extract_memo_context(memo_text: str) -> dict:
    """尽力从 memo 文本中规则抽取 最终裁决/建议仓位/主线候选，供渲染第 1 节。"""
    ctx = {"verdict": "未能自动提取", "position": "未能自动提取", "candidates": "未能自动提取"}
    text = re.sub(r"\s+", " ", memo_text)
    # 最终裁决：只取裁决等级（+ 可选的综合评分），避免贪婪吃到后续字段
    m = re.search(r"(?:最终裁决|裁决)[:：]?\s*(YES|NO|CAUTION|BUY|SELL|HOLD|看多|看空|中性|观望)", text)
    if m:
        verdict = m.group(1)
        m2 = re.search(r"综合评分[:：]?\s*([0-9]{1,3}(?:\.\d+)?)", text)
        if m2:
            verdict += f" (综合评分: {m2.group(1)})"
        ctx["verdict"] = verdict
    # 建议仓位：只取数字 + %，避免贪婪
    m = re.search(r"建议仓位[:：]?\s*([0-9]{1,3}\s*%?)", text)
    if m:
        ctx["position"] = m.group(1).strip()
    else:
        m = re.search(r"仓位护栏[:：]?\s*([0-9]{1,3}\s*%?)", text)
        if m:
            ctx["position"] = m.group(1).strip()
    # 主线候选：取到后续字段关键词或句号为止，最多 60 字
    m = re.search(r"(?:主线候选|候选主线)[:：]?\s*([^。；;]{0,60})", text)
    if m and m.group(1).strip():
        ctx["candidates"] = m.group(1).strip()
    return ctx


# ---------------------------------------------------------------------------
# Markdown 组装（协议第 4 节修订版：红蓝裁审查记录）
# ---------------------------------------------------------------------------

def render_record(round_data: dict, memo_path: str = "") -> str:
    """把单轮三节点结果渲染为《Red-Team 观察层审查记录》Markdown。"""
    today = _dt.date.today().isoformat()
    if round_data.get("status") == "INVALID_ROUND":
        return "\n".join([
            "# Red-Team 观察层审查记录",
            f"- 日期: {today}",
            f"- Target Memo: {memo_path or '(未提供)'}",
            "- Status: INVALID_ROUND",
            f"- 失败原因: {'；'.join(round_data.get('errors', [])) or '未知'}",
            "",
            "_本记录为 INVALID_ROUND 占位（供人工审计，不进入正式观察视图）。_",
        ])

    ctx = round_data.get("memo_context", {})
    attacks = round_data.get("attacks", [])
    defenses = round_data.get("defenses", [])
    judge = round_data.get("judge", {})

    lines = [
        "# Red-Team 观察层审查记录",
        f"- 日期: {today}",
        f"- Target Memo: {memo_path or '(未提供)'}",
        "- Status: VALID",
        "",
        "## 一、原始备忘录核心裁决",
        f"- 最终裁决: {ctx.get('verdict', '未能自动提取')}",
        f"- 建议仓位: {ctx.get('position', '未能自动提取')}",
        f"- 主线候选: {ctx.get('candidates', '未能自动提取')}",
        "",
        "## 二、红方攻击点清单",
    ]
    for i, a in enumerate(attacks, 1):
        lines.append(f"{i}. 【{a.get('dimension', '?')}】{a.get('claim', '')}。{a.get('evidence_and_logic', '')}")

    lines += ["", "## 三、蓝方抗辩与对冲依据"]
    for i, d in enumerate(defenses, 1):
        lines.append(
            f"{i}. 【针对攻击 {d.get('attack_id', '?')} ({d.get('stance', '?')})】"
            f"{d.get('counter_evidence', '')}。残余风险：{d.get('residual_risk', '无')}"
        )

    lines += [
        "", "## 四、裁判终审评分与判定",
        f"- 综合评分: {judge.get('score', '?')}",
        f"- 裁决结论: {judge.get('verdict', '?')}",
        f"- 终审评语: {judge.get('rationale', '?')}",
        f"- 盘中关键观察点: {judge.get('key_risk_watch', '?')}",
        "",
        "---",
        "_本记录由观察层 Red-Team 管道自动生成（红方→蓝方→裁判），仅作人工决策参考，不耦合生产打分。_",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run_pipeline(report_text: str, memo_path: str = "") -> str:
    """执行红方->蓝方->裁判->渲染。返回 Markdown（VALID 或 INVALID_ROUND 占位）。"""
    memo_text = report_text.strip()
    # 节点1 红方
    ok1, attack_payload, err1 = red_team_attack(memo_text)
    if not ok1:
        return render_record({"status": "INVALID_ROUND", "errors": err1}, memo_path)
    # 节点2 蓝方
    ok2, defense_payload, err2 = blue_team_defense(attack_payload, memo_text)
    if not ok2:
        return render_record({"status": "INVALID_ROUND", "errors": err2}, memo_path)
    # 节点3 裁判
    ok3, judge_payload, err3 = judge_verdict(attack_payload, defense_payload, memo_text)
    if not ok3:
        return render_record({"status": "INVALID_ROUND", "errors": err3}, memo_path)

    return render_record({
        "status": "VALID",
        "memo_context": _extract_memo_context(memo_text),
        "attacks": attack_payload.get("attack_points", []),
        "defenses": defense_payload.get("defense_points", []),
        "judge": judge_payload,
    }, memo_path)


def _read_input(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    # 兼容真实产物（os2_report 输出为 HTML）：剥离标签并反转义，得到喂给 LLM 的纯净文本
    if path.lower().endswith((".html", ".htm")):
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
    return text


# ---------------------------------------------------------------------------
# 自检（mock LLM，验证三节点管道 + 硬卡 + INVALID_ROUND 路径）
# ---------------------------------------------------------------------------

_SAMPLE_REPORT = """
投资决策备忘录 2026-08-22
最终裁决: CAUTION (综合评分: 72)
建议仓位: 30%
主线候选: 半导体 ★★★★☆ · 赚钱效应
关注标的：贵州茅台(600519)直销渠道占比提升驱动毛利率扩张；半导体 ETF 连续 3 日净流入超 15 亿。
"""


def _mock_llm(system: str, user: str, temperature: float) -> str:
    if system.startswith("你负责担任 A股 Trading OS 观察层的「红方首席审查官"):
        return json.dumps({
            "status": "SUCCESS",
            "attack_points": [
                {"id": 1, "dimension": "宏观",
                 "claim": "SOXX 隔夜重挫 2.8%，海外半导体链情绪承压",
                 "evidence_and_logic": "备忘录仅以 ETF 净申购作为支撑，低估了开盘抛压"},
                {"id": 2, "dimension": "资金",
                 "claim": "领涨核心股连续 2 日缩量，板块内部流动性衰竭",
                 "evidence_and_logic": "缩量上涨存在假突破风险，主力集中度数据未在决策链引用"},
            ],
        }, ensure_ascii=False)
    if system.startswith("你负责担任 A股 Trading OS 的「蓝方首席防御官"):
        return json.dumps({
            "status": "SUCCESS",
            "defense_points": [
                {"attack_id": 1, "stance": "规则对冲",
                 "counter_evidence": "国内半导体 ETF 连续 3 日净流入超 15 亿，且 10:00 盯盘清单已设硬条件",
                 "residual_risk": "海外情绪传导仍可能造成开盘低开"},
                {"attack_id": 2, "stance": "完全化解",
                 "counter_evidence": "Capital Score 主力资金集中度 82 分，缩量属锁仓特征",
                 "residual_risk": "无"},
            ],
        }, ensure_ascii=False)
    if system.startswith("你负责担任 A股 Trading OS 观察层的「独立裁决仲裁员"):
        return json.dumps({
            "status": "SUCCESS",
            "score": 84.0,
            "verdict": "维持原裁决 (CAUTION)",
            "rationale": "蓝方抗辩成立，规则护栏与 10:00 盯盘点有效覆盖外部情绪传导风险",
            "key_risk_watch": "09:45~10:00 核心龙头分时承接量能是否达到昨日同期 1.2 倍",
        }, ensure_ascii=False)
    return ""


def _mock_llm_invalid(system: str, user: str, temperature: float) -> str:
    """INVALID_ROUND 路径：红蓝均合规，裁判输出违规（score 越界 + 禁用词）-> 二次校验失败 -> 占位记录。"""
    if system.startswith("你负责担任 A股 Trading OS 观察层的「红方首席审查官"):
        return json.dumps({
            "status": "SUCCESS",
            "attack_points": [
                {"id": 1, "dimension": "技术",
                 "claim": "图形结构破位",
                 "evidence_and_logic": "跌破关键均线支撑，存在继续下行风险"},
                {"id": 2, "dimension": "资金",
                 "claim": "主力资金连续两日净流出",
                 "evidence_and_logic": "板块资金共识转弱，赚钱效应收缩"},
            ],
        }, ensure_ascii=False)
    if system.startswith("你负责担任 A股 Trading OS 的「蓝方首席防御官"):
        return json.dumps({
            "status": "SUCCESS",
            "defense_points": [
                {"attack_id": 1, "stance": "部分承认",
                 "counter_evidence": "仓位护栏已收紧至 30%",
                 "residual_risk": "图形破位风险部分未化解"},
                {"attack_id": 2, "stance": "规则对冲",
                 "counter_evidence": "安检闸门已对该板块设一票否决观察位",
                 "residual_risk": "资金面持续恶化时需人工复核"},
            ],
        }, ensure_ascii=False)
    if system.startswith("你负责担任 A股 Trading OS 观察层的「独立裁决仲裁员"):
        return json.dumps({
            "status": "SUCCESS",
            "score": 150.0,
            "verdict": "建议下调一级",
            "rationale": "红方命中致命漏洞且蓝方防御失效，未来走势需观察",
            "key_risk_watch": "10:00 前龙头承接资金量",
        }, ensure_ascii=False)
    return ""


def _self_test() -> int:
    global call_llm
    LOG.info("=== 自检开始（mock LLM）===")
    # 路径1：红蓝裁全部合规 -> VALID 记录
    call_llm = _mock_llm  # 注入 mock
    md = run_pipeline(_SAMPLE_REPORT, memo_path="output/memo_2026-08-22.html")
    assert "Status: VALID" in md, "期望 VALID 记录"
    assert "## 二、红方攻击点清单" in md and "【宏观】" in md, "红方攻击清单缺失"
    assert "## 三、蓝方抗辩与对冲依据" in md and "完全化解" in md, "蓝方抗辩缺失"
    assert "## 四、裁判终审评分与判定" in md and "综合评分: 84.0" in md, "裁判终审缺失"
    LOG.info("路径1 通过：红蓝裁合规 -> VALID 记录\n%s", md)

    # 路径2：裁判输出违规（禁用词 + score 越界）-> INVALID_ROUND 占位
    call_llm = _mock_llm_invalid
    md2 = run_pipeline(_SAMPLE_REPORT, memo_path="output/memo_2026-08-22.html")
    assert "Status: INVALID_ROUND" in md2, "期望 INVALID_ROUND 占位"
    LOG.info("路径2 通过：违规输出 -> INVALID_ROUND 占位\n%s", md2)

    call_llm = _call_llm_real  # 还原
    LOG.info("=== 自检通过：VALID 与 INVALID_ROUND 两条路径均验证 ===")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="观察层 Red-Team 压力测试 PoC 编排器（红方→蓝方→裁判）")
    ap.add_argument("--input", help="os2_report HTML/Markdown 路径")
    ap.add_argument("--output", help="输出《Red-Team 审查记录》Markdown 路径")
    ap.add_argument("--self-test", action="store_true", help="使用 mock LLM 跑通管道自检")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()

    if not args.input:
        ap.error("需提供 --input os2_report 路径（或 --self-test）")

    report = _read_input(args.input)
    md = run_pipeline(report, memo_path=args.input)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(md)
        LOG.info("已写入《Red-Team 审查记录》: %s", args.output)
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
