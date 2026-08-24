# -*- coding: utf-8 -*-
"""
circuit_breaker.py
G1 阶段 —— 行为熔断器与状态机（与 MT5 运行环境完全解耦）

【状态枚举】
  IDLE         : 正常，可开仓
  COOLDOWN     : 连亏触发冷却，锁定至 unlock_ts
  DAILY_HALTED : 日亏达上限，锁定至次日 00:00（本地时区）
  IN_POSITION  : 已有持仓（可选状态，G1 仅占位，G2 接 MT5 时填充）

【断路规则（冻结自 PreReg §12）】
  - 连续亏损 K=2 笔（30min 滑动窗口内） → COOLDOWN，锁定 cooldown_minutes=120
  - 当日累计已实现亏损 ≥ daily_loss_halt_usd=60.0（3R） → DAILY_HALTED，锁至次日
  - can_submit_order() -> (bool, str) 开仓前前置门禁

【设计】
  - 纯状态机，不写库、不依赖 MT5。
  - 时钟注入（now 可传入 datetime），单测确定性。
  - 日亏累计按"交易日"重置：跨日（date 变化）自动清零。
"""
from __future__ import annotations
import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Tuple, Optional


class CBState(str, Enum):
    IDLE = "IDLE"
    COOLDOWN = "COOLDOWN"
    DAILY_HALTED = "DAILY_HALTED"
    IN_POSITION = "IN_POSITION"


# 冻结默认参数（与 risk_limits.json 一致）
DEFAULT_K_LOSS = 2
DEFAULT_WINDOW_MIN = 30          # 连亏滑动窗口（分钟）
DEFAULT_COOLDOWN_MIN = 120
DEFAULT_DAILY_HALT_USD = 60.0
DEFAULT_MAX_OPEN_RISK_USD = 60.0


@dataclass
class TradeResult:
    ts: datetime.datetime
    realized_pnl_usd: float
    is_loss: bool


class CircuitBreaker:
    def __init__(
        self,
        k_loss: int = DEFAULT_K_LOSS,
        window_min: int = DEFAULT_WINDOW_MIN,
        cooldown_min: int = DEFAULT_COOLDOWN_MIN,
        daily_halt_usd: float = DEFAULT_DAILY_HALT_USD,
        max_open_risk_usd: float = DEFAULT_MAX_OPEN_RISK_USD,
        now: Optional[datetime.datetime] = None,
    ):
        self.k_loss = k_loss
        self.window_min = window_min
        self.cooldown_min = cooldown_min
        self.daily_halt_usd = daily_halt_usd
        self.max_open_risk_usd = max_open_risk_usd

        self._now = now or datetime.datetime.now()
        self.state = CBState.IDLE
        self.cooldown_unlock_ts: Optional[datetime.datetime] = None
        self.daily_halt_unlock_date: Optional[datetime.date] = None
        self.daily_loss_usd = 0.0
        self._daily_date: Optional[datetime.date] = self._now.date()
        self._recent_results: List[TradeResult] = []  # 近期交易（用于连亏窗口）
        self._consecutive_losses = 0

    # ---- 时钟工具 ----
    def _advance_clock(self, now: datetime.datetime) -> None:
        """外部推进时钟时调用，处理跨日重置与冷却解锁。"""
        self._now = now
        # 跨日：日亏清零 + 解除日停
        if now.date() != self._daily_date:
            self._daily_date = now.date()
            self.daily_loss_usd = 0.0
            self.daily_halt_unlock_date = None
            if self.state == CBState.DAILY_HALTED:
                self.state = CBState.IDLE
        # 冷却到期
        if self.state == CBState.COOLDOWN and self.cooldown_unlock_ts and now >= self.cooldown_unlock_ts:
            self.state = CBState.IDLE
            self.cooldown_unlock_ts = None

    # ---- 核心门禁 ----
    def can_submit_order(self, now: Optional[datetime.datetime] = None) -> Tuple[bool, str]:
        if now is not None:
            self._advance_clock(now)
        if self.state == CBState.COOLDOWN:
            remain = (self.cooldown_unlock_ts - self._now).total_seconds() / 60.0
            return False, f"COOLDOWN 锁定中，剩余 {remain:.1f} 分钟"
        if self.state == CBState.DAILY_HALTED:
            return False, f"DAILY_HALTED 锁定至 {self.daily_halt_unlock_date} 次日"
        if self.state == CBState.IN_POSITION:
            return False, "IN_POSITION 已有持仓（G1 占位，G2 接 MT5 后细化）"
        return True, "IDLE 允许开仓"

    # ---- 事件录入 ----
    def record_trade(self, realized_pnl_usd: float, now: Optional[datetime.datetime] = None) -> None:
        """录入一笔已平仓交易结果，更新连亏窗口与日亏累计，可能触发断路。"""
        if now is not None:
            self._advance_clock(now)
        ts = self._now
        is_loss = realized_pnl_usd < 0

        # 日亏累计
        if realized_pnl_usd < 0:
            self.daily_loss_usd += abs(realized_pnl_usd)
        if self.daily_loss_usd >= self.daily_halt_usd - 1e-9 and self.state != CBState.DAILY_HALTED:
            self.state = CBState.DAILY_HALTED
            self.daily_halt_unlock_date = ts.date()
            return

        # 连亏滑动窗口（仅统计亏损笔）
        self._recent_results.append(TradeResult(ts=ts, realized_pnl_usd=realized_pnl_usd, is_loss=is_loss))
        cutoff = ts - datetime.timedelta(minutes=self.window_min)
        self._recent_results = [r for r in self._recent_results if r.ts >= cutoff]

        # 统计窗口内"连续"亏损笔数（从最近的交易往前数，遇盈则断）
        consecutive = 0
        for r in reversed(self._recent_results):
            if r.is_loss:
                consecutive += 1
            else:
                break
        self._consecutive_losses = consecutive

        if consecutive >= self.k_loss and self.state == CBState.IDLE:
            self.state = CBState.COOLDOWN
            self.cooldown_unlock_ts = ts + datetime.timedelta(minutes=self.cooldown_min)

    def set_in_position(self, flag: bool, now: Optional[datetime.datetime] = None) -> None:
        """G1 占位：标记是否持仓。仅当 IDLE/IN_POSITION 间切换，不覆盖断路态。"""
        if now is not None:
            self._advance_clock(now)
        if flag and self.state in (CBState.IDLE,):
            self.state = CBState.IN_POSITION
        elif not flag and self.state == CBState.IN_POSITION:
            self.state = CBState.IDLE

    def snapshot(self) -> dict:
        return {
            "state": self.state.value,
            "daily_loss_usd": round(self.daily_loss_usd, 4),
            "consecutive_losses": self._consecutive_losses,
            "cooldown_unlock_ts": self.cooldown_unlock_ts.isoformat() if self.cooldown_unlock_ts else None,
            "daily_halt_unlock_date": self.daily_halt_unlock_date.isoformat() if self.daily_halt_unlock_date else None,
        }

    @property
    def consecutive_losses(self) -> int:
        """公开只读：当前连亏笔数（窗口内从最近一笔往前数的连续亏损）。"""
        return self._consecutive_losses
