"""
research_contract.py - Strategy Research Contract v0.1（研究语言的最小机器可读内核）

版本状态：v0.1 **FROZEN**（2026-08-14 用户定调冻结，不再扩展字段/加 UI/加 DB）。
          v0.2 仅允许在真实实验跑出字段缺口后，从实验需求反向产生。

定位：Observation 层规范定义。只描述实验、不修改生产决策链
      （run_daily / risk_guard / shadow）。不依赖任何生产模块。

来源文档：docs/Strategy_Research_Contract_v0.1.md

设计原则（来自用户架构修正 2026-08-14）：
  1. Research Contract / Protocol 是基础设施，先于 Exit / Robustness Engine。
  2. 每个字段必须带 Evidence Status（CLAIM→...→PRODUCTION 单向前进）。
  3. 聊天结论不能直接进 Research Record：任何数字要能追溯
     Claim→Source→Reproduce→Validate→Record。
  4. Erratum 机制（2026-08-14 增补）：Evidence Status 是当前证据状态，
     单向前进；任何回退（含纠错的 CLAIM/NOT LOCATED）只能走 add_erratum()，
     它只增加一条「历史事件」记录，不静默改写状态、不破坏审计链。

用法：
  python research_contract.py --skeleton RC-ID "标题" Layer
  python research_contract.py --check    backend/output/research_contracts/RC-XXX.json
  python research_contract.py --new      backend/output/research_contracts/RC-XXX.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

FROZEN = True  # v0.1 冻结标记；违反冻结的字段扩展须先与用户确认

# ----------------------------------------------------------------------------
# Evidence Status：研究可信度状态机（单向前进，不可静默回跳）
# ----------------------------------------------------------------------------
class EvidenceStatus(str, Enum):
    CLAIM = "CLAIM"            # 口头/聊天提出，无项目数据
    LOCATED = "LOCATED"        # 在项目数据/代码里找到对应事实（有路径+字段）
    REPRODUCED = "REPRODUCED"  # 能重跑脚本得到同一数字
    VALIDATED = "VALIDATED"    # 独立逻辑交叉验证通过
    ROBUST = "ROBUST"          # 稳健性验证通过（参数×时间×资产×Regime）
    ACCEPTED = "ACCEPTED"      # 经人工 Review Gate，进入研究库
    PRODUCTION = "PRODUCTION"  # 获生产资格（需 release_gate APPROVED + RISK_GUARD_ENABLED=1）

    @classmethod
    def rank(cls, s: "EvidenceStatus") -> int:
        return list(cls).index(s)

    def __lt__(self, other: "EvidenceStatus") -> bool:
        return self.rank(self) < self.rank(other)

    def __le__(self, other: "EvidenceStatus") -> bool:
        return self.rank(self) <= self.rank(other)


# 13 字段规范（顺序即研究流水线）
FIELD_SPECS = [
    ("01_hypothesis", "Hypothesis", "要验证的明确假设（先假设，后参数）"),
    ("02_universe", "Market/Universe", "资产/市场/样本边界，写死"),
    ("03_regime", "Regime", "市场状态；状态须是事前变量"),
    ("04_signal", "Signal", "触发关注的信号定义，是否可复现"),
    ("05_entry", "Entry", "进入条件，是否机械可执行"),
    ("06_stop", "Stop", "失效条件，失效位是否写死"),
    ("07_exit", "Exit", "兑现条件（当前最大价值泄漏点）"),
    ("08_position_sizing", "Position Sizing", "风险预算 ÷ 失效位距离"),
    ("09_costs", "Costs/Execution", "成本与执行摩擦假设"),
    ("10_testing", "Testing", "回测方法，样本内/外划分"),
    ("11_robustness", "Robustness", "换参数/时间/资产/Regime 是否成立"),
    ("12_attribution", "Attribution", "收益来自哪一层"),
    ("13_decision", "Decision", "采纳/否决/继续观察/进下一实验"),
]


@dataclass
class FieldSpec:
    """单个研究字段的值 + 可信度标签。"""
    name: str
    value: Any = "N/A"
    evidence_status: EvidenceStatus = EvidenceStatus.CLAIM
    source: str = ""          # 文件绝对路径 / 行号 / 字段名
    note: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["evidence_status"] = self.evidence_status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "FieldSpec":
        st = d.get("evidence_status", "CLAIM")
        return cls(
            name=d.get("name", ""),
            value=d.get("value", "N/A"),
            evidence_status=EvidenceStatus(st) if st in EvidenceStatus._value2member_map_
            else EvidenceStatus.CLAIM,
            source=d.get("source", ""),
            note=d.get("note", ""),
        )


@dataclass
class ErratumEvent:
    """纠错历史事件。不修改原字段的当前状态，只追加一条审计记录。

    用途：当某字段曾被误标（如误标 LOCATED/VALIDATED），发现来源不存在时，
    用 add_erratum() 追加本事件，并（可选地）把状态纠正为 CLAIM/NOT LOCATED。
    原状态机保持「单向前进」原则：任何回退必须经此函数，绝不允许静默改状态。
    """
    timestamp: str
    field: str                       # 受影响的字段 key，或 "contract"
    claim: str                       # 当时错误的声明/状态
    finding: str                     # 复核发现的事实
    previous_status: Optional[str] = None   # 纠错前的状态（历史）
    restored_status: Optional[str] = None   # 纠正后的状态（如 CLAIM）
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ErratumEvent":
        return cls(
            timestamp=d.get("timestamp", ""),
            field=d.get("field", ""),
            claim=d.get("claim", ""),
            finding=d.get("finding", ""),
            previous_status=d.get("previous_status"),
            restored_status=d.get("restored_status"),
            note=d.get("note", ""),
        )


@dataclass
class ResearchContract:
    contract_id: str
    title: str
    layer: str                      # 对应架构层，如 "Exit" / "Signal" / "Stop"
    hypothesis: str = ""
    fields: dict[str, FieldSpec] = field(default_factory=dict)
    evidence_status: EvidenceStatus = EvidenceStatus.CLAIM   # 整体状态
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    owner: str = "research"
    source_artifacts: list[str] = field(default_factory=list)
    errata: list[ErratumEvent] = field(default_factory=list)   # 纠错历史（审计用）

    def __post_init__(self):
        # 保证 13 字段都存在（缺的填 N/A / CLAIM）
        for key, _, _ in FIELD_SPECS:
            if key not in self.fields:
                self.fields[key] = FieldSpec(name=key, value="N/A",
                                             evidence_status=EvidenceStatus.CLAIM)

    # ---- 工厂：空白模板 ----
    @classmethod
    def skeleton(cls, contract_id: str, title: str, layer: str) -> "ResearchContract":
        fields = {
            key: FieldSpec(name=key, value="N/A", evidence_status=EvidenceStatus.CLAIM,
                           note="TODO: 待填写")
            for key, _, _ in FIELD_SPECS
        }
        return cls(contract_id=contract_id, title=title, layer=layer, fields=fields)

    # ---- 序列化 ----
    def to_dict(self) -> dict:
        return {
            "contract_id": self.contract_id,
            "title": self.title,
            "layer": self.layer,
            "hypothesis": self.hypothesis,
            "evidence_status": self.evidence_status.value,
            "created": self.created,
            "owner": self.owner,
            "source_artifacts": self.source_artifacts,
            "fields": {k: v.to_dict() for k, v in self.fields.items()},
            "errata": [e.to_dict() for e in self.errata],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ResearchContract":
        fields = {k: FieldSpec.from_dict(v) for k, v in d.get("fields", {}).items()}
        st = d.get("evidence_status", "CLAIM")
        return cls(
            contract_id=d.get("contract_id", ""),
            title=d.get("title", ""),
            layer=d.get("layer", ""),
            hypothesis=d.get("hypothesis", ""),
            fields=fields,
            evidence_status=EvidenceStatus(st) if st in EvidenceStatus._value2member_map_
            else EvidenceStatus.CLAIM,
            created=d.get("created", ""),
            owner=d.get("owner", "research"),
            source_artifacts=d.get("source_artifacts", []),
            errata=[ErratumEvent.from_dict(e) for e in d.get("errata", [])],
        )

    # ---- 校验 ----
    def validate(self) -> list[str]:
        """返回问题列表（空 = 通过）。不抛异常，便于 CLI 汇总。"""
        issues: list[str] = []
        if not self.contract_id:
            issues.append("contract_id 为空")
        if not self.title:
            issues.append("title 为空")
        if not self.layer:
            issues.append("layer 为空")
        for key, label, _ in FIELD_SPECS:
            fs = self.fields.get(key)
            if fs is None:
                issues.append(f"缺少字段 {key}（{label}）")
                continue
            if fs.value in (None, "", "N/A") and not fs.note:
                issues.append(f"字段 {key}（{label}）为空且未写 N/A 理由")
            if fs.evidence_status == EvidenceStatus.CLAIM and fs.source:
                # CLAIM 不应有 source（source 意味着已 LOCATED）
                issues.append(f"字段 {key} 标 CLAIM 却填了 source，状态矛盾")
        # 整体状态不可高于任何字段（不允许未验证就 ACCEPTED/PRODUCTION）
        for key, label, _ in FIELD_SPECS:
            fs = self.fields.get(key)
            if fs and self.evidence_status > fs.evidence_status and \
               self.evidence_status in (EvidenceStatus.ACCEPTED, EvidenceStatus.PRODUCTION):
                issues.append(
                    f"整体 {self.evidence_status.value} 高于字段 {key}（{fs.evidence_status.value}），"
                    f"禁止未验证即 ACCEPTED/PRODUCTION"
                )
        return issues

    # ---- 便捷赋值（强制单向前进）----
    def set(self, key: str, value: Any, status: EvidenceStatus,
            source: str = "", note: str = "") -> "ResearchContract":
        if key not in self.fields:
            raise KeyError(f"未知字段 {key}；合法字段见 FIELD_SPECS")
        cur = self.fields[key].evidence_status
        if status < cur:
            raise ValueError(
                f"禁止状态静默回退 {cur.value}→{status.value}；"
                f"回退须用 add_erratum() 并记录纠错事件"
            )
        self.fields[key] = FieldSpec(name=key, value=value,
                                     evidence_status=status, source=source, note=note)
        return self

    # ---- 纠错事件：唯一合法的「回退」通道 ----
    def add_erratum(self, field_key: str, claim: str, finding: str,
                    restored_status: Optional[EvidenceStatus] = None,
                    note: str = "") -> "ResearchContract":
        prev = self.fields.get(field_key).evidence_status.value if field_key in self.fields else None
        if restored_status is not None and field_key in self.fields:
            # 经 erratum 显式纠正状态（这是设计允许的唯一回退路径）
            self.fields[field_key].evidence_status = restored_status
        self.errata.append(ErratumEvent(
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            field=field_key,
            claim=claim,
            finding=finding,
            previous_status=prev,
            restored_status=restored_status.value if restored_status else None,
            note=note,
        ))
        return self


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def _write_skeleton(contract_id: str, title: str, layer: str, path: Optional[str]) -> int:
    rc = ResearchContract.skeleton(contract_id, title, layer)
    text = json.dumps(rc.to_dict(), ensure_ascii=False, indent=2)
    if path:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[skeleton] 已写入 {path}")
    else:
        print(text)
    return 0


def _check(path: str) -> int:
    if not os.path.exists(path):
        print(f"[check] 文件不存在：{path}")
        return 2
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    rc = ResearchContract.from_dict(data)
    issues = rc.validate()
    if issues:
        print(f"[check] {rc.contract_id} 发现 {len(issues)} 个问题：")
        for i in issues:
            print(f"  - {i}")
        return 1
    print(f"[check] {rc.contract_id} 通过（整体 {rc.evidence_status.value}）")
    if rc.errata:
        print(f"[check] 含 {len(rc.errata)} 条纠错事件（Erratum）：")
        for e in rc.errata:
            print(f"  - [{e.field}] {e.previous_status}→{e.restored_status} : {e.finding}")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Strategy Research Contract v0.1 (FROZEN)")
    p.add_argument("--skeleton", nargs=3, metavar=("ID", "TITLE", "LAYER"),
                   help="生成空白模板（打印或配合 --out 写文件）")
    p.add_argument("--new", metavar="PATH", help="将空白模板写入指定 JSON 路径")
    p.add_argument("--check", metavar="PATH", help="校验一个 Contract JSON（含 errata 输出）")
    p.add_argument("--out", metavar="PATH", help="配合 --skeleton 指定输出路径")
    args = p.parse_args(argv)

    if args.skeleton:
        cid, title, layer = args.skeleton
        return _write_skeleton(cid, title, layer, args.out or args.new)
    if args.check:
        return _check(args.check)
    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
