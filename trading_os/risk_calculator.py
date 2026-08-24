# -*- coding: utf-8 -*-
"""
risk_calculator.py
G1 阶段 —— 纯规则风险与手数计算器（与 MT5 运行环境完全解耦）

【输入契约】
  entry_price        : float  开仓价
  invalidation_price : float  失效价（初始止损触发位）
  direction          : str    'BUY' / 'SELL'
  risk_budget_usd    : float  单笔风险预算（默认读 risk_limits.json = 20.0）
  spec_dict          : dict   来自 xauusd_spec.json 的静态品种规格

【数学反推（物理量纲正确版，不用冗余中间式）】
  per_lot_per_point = contract_size * point          # XAUUSD = 100 * 0.01 = $1/lot/point
  stop_distance_pts = |entry - invalidation| / point
  raw_lots          = risk_budget / (stop_distance_pts * per_lot_per_point)
  calc_lots         = min(max_lot, floor(raw_lots / lot_step) * lot_step)   # 向 lot_step 下取整 + 封顶

【硬断言门禁（Hard Assertions，Machine 强制，人不能临盘绕过）】
  - InvalidStopDistanceError : stop_distance_pts < MIN_STOP_POINTS(100) 拒绝（< $1.00 黄金间距）
  - RiskBudgetExceededError : 即使按最小手(volume_min) 封顶后理论亏损仍 > budget → 拒绝
                              （成因：0.01 封顶手数 + 过宽止损，CAL-C 真问题，非计算错误）
  - SpreadTooWideError      : 当前点差 > MAX_SPREAD_POINTS(45) 拒绝

【不依赖 MT5 / 不写库 / 纯函数 + 注入时钟】
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Optional

# ---- 硬门禁常量（冻结自 risk_limits.json / PreReg §3.1） ----
MIN_STOP_POINTS = 100.0       # 最小波幅 100 points = $1.00 黄金价格间距
MAX_SPREAD_POINTS = 45.0      # 点差硬上限 45 points = $0.45
DEFAULT_MAX_LOT = 0.01        # G2 验证硬封顶（PreReg §12 CAL-C）
DEFAULT_RISK_BUDGET = 20.0    # 单笔固定物理硬顶（PreReg §12 CAL-A）


class InvalidStopDistanceError(ValueError):
    """止损距离过窄（< MIN_STOP_POINTS），拒绝开仓。"""


class RiskBudgetExceededError(ValueError):
    """即使按最小手封顶，理论最大亏损仍超预算（止损过宽），拒绝开仓。"""


class SpreadTooWideError(ValueError):
    """当前点差超 MAX_SPREAD_POINTS，拒绝开仓。"""


@dataclass
class RiskPlan:
    direction: str
    entry_price: float
    invalidation_price: float
    stop_distance_points: float
    per_lot_per_point: float
    raw_lots: float
    calculated_lots: float
    max_loss_usd: float
    risk_budget_usd: float
    spread_points: float
    within_budget: bool

    def as_dict(self) -> dict:
        return {
            "direction": self.direction,
            "entry_price": self.entry_price,
            "invalidation_price": self.invalidation_price,
            "stop_distance_points": self.stop_distance_points,
            "per_lot_per_point": self.per_lot_per_point,
            "raw_lots": self.raw_lots,
            "calculated_lots": self.calculated_lots,
            "max_loss_usd": self.max_loss_usd,
            "risk_budget_usd": self.risk_budget_usd,
            "spread_points": self.spread_points,
            "within_budget": self.within_budget,
        }


def _per_lot_per_point(spec: dict) -> float:
    """每 1 lot、价格变动 1 point 的美元损益。标准公式 contract_size × point。"""
    return float(spec["trade_contract_size"]) * float(spec["point"])


def compute_risk_plan(
    entry_price: float,
    invalidation_price: float,
    direction: str,
    risk_budget_usd: float = DEFAULT_RISK_BUDGET,
    spec_dict: Optional[dict] = None,
    spread_points: float = 0.0,
    max_lot: float = DEFAULT_MAX_LOT,
) -> RiskPlan:
    """反推手数并做硬门禁断言。纯函数，可离线单测。

    direction 仅用于记录与方向校验（机器不自产方向，方向由人提供，此处不校验方向对错）。
    """
    if direction not in ("BUY", "SELL"):
        raise ValueError(f"direction 必须是 BUY/SELL，收到 {direction!r}（机器不自产方向）")
    if spec_dict is None:
        raise ValueError("spec_dict 必填（来自 xauusd_spec.json）")

    point = float(spec_dict["point"])
    lot_step = float(spec_dict["volume_step"])
    vol_min = float(spec_dict.get("volume_min", lot_step))
    if point <= 0 or lot_step <= 0:
        raise ValueError("spec point / lot_step 非正")

    # 1. 止损距离（points）
    stop_distance_points = abs(entry_price - invalidation_price) / point
    if stop_distance_points < MIN_STOP_POINTS:
        raise InvalidStopDistanceError(
            f"止损距离 {stop_distance_points:.1f}pt < 下限 {MIN_STOP_POINTS:.0f}pt "
            f"（${stop_distance_points * point:.2f} < ${MIN_STOP_POINTS * point:.2f}），拒绝开仓"
        )

    # 2. 点差硬拦截
    if spread_points > MAX_SPREAD_POINTS:
        raise SpreadTooWideError(
            f"当前点差 {spread_points:.1f}pt > 上限 {MAX_SPREAD_POINTS:.0f}pt，拒绝开仓"
        )

    # 3. 单位损益
    per_lot = _per_lot_per_point(spec_dict)

    # 4. 反推原始手数
    raw_lots = risk_budget_usd / (stop_distance_points * per_lot)

    # 5. 向 lot_step 下取整 + 封顶 max_lot（CAL-C：0.01 是封顶非定值）
    floored = math.floor(raw_lots / lot_step) * lot_step
    calculated_lots = min(max_lot, floored)
    calculated_lots = max(calculated_lots, 0.0)

    # 6. 理论最大亏损（按计算手数触及时）
    max_loss_usd = calculated_lots * per_lot * stop_distance_points

    # 7. 预算溢出判定：即使按最小手（vol_min，通常=0.01）封顶仍超预算 → 拒绝
    #    成因是封顶手数 + 过宽止损，不是计算错（CAL-C 真问题）
    min_lot_loss = vol_min * per_lot * stop_distance_points
    if min_lot_loss > risk_budget_usd + 1e-9:
        raise RiskBudgetExceededError(
            f"即使按最小手 {vol_min} 封顶，理论亏损 ${min_lot_loss:.2f} 仍超预算 "
            f"${risk_budget_usd:.2f}（止损过宽 {stop_distance_points:.0f}pt），拒绝开仓"
        )

    within_budget = max_loss_usd <= risk_budget_usd + 1e-9
    return RiskPlan(
        direction=direction,
        entry_price=entry_price,
        invalidation_price=invalidation_price,
        stop_distance_points=stop_distance_points,
        per_lot_per_point=per_lot,
        raw_lots=raw_lots,
        calculated_lots=calculated_lots,
        max_loss_usd=max_loss_usd,
        risk_budget_usd=risk_budget_usd,
        spread_points=spread_points,
        within_budget=within_budget,
    )
