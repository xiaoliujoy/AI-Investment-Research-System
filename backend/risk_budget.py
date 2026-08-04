# backend/risk_budget.py
"""
Risk Budget Engine — score_to_budget() 纯函数（Phase 1.9B）

将 Risk Temperature (regime_history.risk_score, 0-100) 映射为连续风险预算：
    equity / gold / bond / cash

设计依据：docs/risk_budget_framework_v1.0.md (v1.1)

核心规则（用户 2026-08-04 拍板）：
  - 非线性防御曲线（高分不追高、低位才降仓）
  - 正常模式：黄金恒 15%、现金恒 5%，债券 = 1 - 股 - 15% - 5%
  - 战略权益底 Strategic Equity Floor = 30%（日常不可破）
  - Crisis Protocol（score < 30）：独立危机协议，股 20% / 金 25% / 债 45% / 现 10%

不碰 Layer1 评分模型、不读 DB（纯函数，便于回测与单测）。
"""
from typing import Dict, Tuple

# 正常模式固定防御配比
NORMAL_GOLD = 0.15
NORMAL_CASH = 0.05
# 危机协议配比（score < 30）
CRISIS_EQUITY = 0.20
CRISIS_GOLD = 0.25
CRISIS_CASH = 0.10

# 战略权益底（日常不可破）
STRATEGIC_EQUITY_FLOOR = 0.30


def score_to_budget(score: float) -> Dict[str, float]:
    """将 0-100 的 Risk Temperature 映射为资产预算。

    返回：{equity, gold, bond, cash, mode}
      mode ∈ {'normal', 'crisis'}
    各权重合计 = 1.0
    """
    if score is None:
        score = 50.0
    score = max(0.0, min(100.0, float(score)))

    # Crisis Protocol：仅极端系统性风险（<30）触发
    if score < 30:
        equity = CRISIS_EQUITY
        gold = CRISIS_GOLD
        cash = CRISIS_CASH
        mode = 'crisis'
    else:
        # 非线性防御曲线（正常模式）
        if score >= 80:
            equity = 0.70
        elif score >= 65:
            equity = 0.65
        elif score >= 50:
            equity = 0.55
        elif score >= 40:
            equity = 0.40
        else:  # 30 <= score < 40 → 贴战略底
            equity = STRATEGIC_EQUITY_FLOOR
        gold = NORMAL_GOLD
        cash = NORMAL_CASH
        mode = 'normal'

    bond = round(1.0 - equity - gold - cash, 6)
    # 数值保护：债券不为负
    if bond < 0:
        bond = 0.0
        # 重新分配：从现金扣（理论不会发生，因曲线已对齐）
        cash = max(0.0, 1.0 - equity - gold)

    return {
        'equity': equity,
        'gold': gold,
        'bond': bond,
        'cash': cash,
        'mode': mode,
    }


def budget_to_text(b: Dict[str, float], score: float) -> str:
    """生成可读证据字符串，供 Decision Record 使用。"""
    eq = int(round(b['equity'] * 100))
    if b['mode'] == 'crisis':
        return (f"Risk Temperature={score:.0f} < 30 → Crisis Protocol："
                f"股{eq}% / 金{int(b['gold']*100)}% / 债{int(b['bond']*100)}% / 现{int(b['cash']*100)}%"
                f"（极端系统性风险，突破战略底）")
    floor_note = "（贴战略权益底 30%）" if b['equity'] == STRATEGIC_EQUITY_FLOOR else ""
    return (f"Risk Temperature={score:.0f} → 股{eq}% / 金{int(b['gold']*100)}% / 债{int(b['bond']*100)}% / 现{int(b['cash']*100)}%{floor_note}")


if __name__ == '__main__':
    print("=== score_to_budget 映射表自检 ===")
    for s in [90, 70, 55, 45, 35, 25, 10]:
        b = score_to_budget(s)
        print(f"  score={s:>3}  eq={b['equity']:.0%}  gold={b['gold']:.0%}  bond={b['bond']:.0%}  cash={b['cash']:.0%}  mode={b['mode']}")
