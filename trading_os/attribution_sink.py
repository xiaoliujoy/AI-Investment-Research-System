# -*- coding: utf-8 -*-
"""
attribution_sink.py
G2 阶段 —— 实时归因汇聚器（与 MT5 运行环境解耦，纯逻辑 + 可注入存储）

【职责】
  对处于 IN_POSITION 的订单，以 Tick 采样更新 MFE / MAE，
  平仓时计算 R 倍数体系（E1 量纲），将交易级执行归因落库，
  并回调 CircuitBreaker.record_trade() 驱动连亏/日亏熔断闭环。

【量纲体系（冻结自 PreReg §3.0 E1）】
  1R            = plan.max_loss_usd  （初始失效位理论损失绝对额）
  Realized_R    = Realized_PnL / 1R
  MFE_R         = Max_Favorable_PnL / 1R
  MAE_R         = |Max_Adverse_PnL| / 1R
  Giveback_R    = MFE_R - Realized_R

【存储边界（CAL-D 治理决策）】
  现有 outcome_attribution 表是"研究级归因"（research/decision/execution/financial
  四段 outcome + 四类 error + luck），与 G2 的"交易级执行归因"语义不同、字段不同。
  本模块落地【选项 A】：独立建表 xau_execution_attribution，物理隔离，
  不碰现有 outcome_attribution schema，符合生产/观察三平面分离。
  表名可配置（ATTRIBUTION_TABLE 常量 / 构造参数），若后续改 B/C 只改此处。

【设计】
  - 纯逻辑，不依赖 MT5、不依赖真实时钟（now 注入）。
  - 存储连接可注入（默认 sqlite3 文件路径，单测用 :memory:）。
  - 不写任何生产库表以外的数据。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

# 独立归因表名（CAL-D 选项 A）
ATTRIBUTION_TABLE = "xau_execution_attribution"

# DDL：若不存在则建（防御式，不破坏现有表）
_DDL = f"""
CREATE TABLE IF NOT EXISTS {ATTRIBUTION_TABLE} (
    order_id          TEXT PRIMARY KEY,
    symbol            TEXT,
    direction         TEXT,
    entry_price       REAL,
    sl_price          REAL,
    exit_price        REAL,
    exit_reason       TEXT,
    requested_lots    REAL,
    filled_lots       REAL,
    fill_price        REAL,
    spread_points     REAL,
    slippage_points   REAL,
    max_loss_usd      REAL,
    realized_pnl_usd  REAL,
    mfe_price         REAL,
    mae_price         REAL,
    mfe_usd           REAL,
    mae_usd           REAL,
    mfe_r             REAL,
    mae_r             REAL,
    realized_r        REAL,
    giveback_r        REAL,
    open_ts           TEXT,
    close_ts          TEXT,
    notes             TEXT
)
"""


@dataclass
class PositionState:
    order_id: str
    symbol: str
    direction: str
    entry_price: float
    sl_price: float
    requested_lots: float
    filled_lots: float
    fill_price: float
    spread_points: float
    slippage_points: float
    max_loss_usd: float            # = 1R
    open_ts: str
    # 运行时极值（不落库，仅用于平仓时计算）
    mfe_price: float = 0.0
    mae_price: float = 0.0
    _opened: bool = True


class AttributionSink:
    def __init__(self, db_path: str = "backend/database/vibe_research.db", table: str = ATTRIBUTION_TABLE):
        self.table = table
        # check_same_thread=False：G2 守护在后台线程消费平仓并落库，连接须跨线程
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(_DDL.replace(ATTRIBUTION_TABLE, self.table))
        self._conn.commit()
        self._positions: Dict[str, PositionState] = {}

    # ---- 开仓登记 ----
    def open_position(
        self,
        order_id: str,
        symbol: str,
        direction: str,
        entry_price: float,
        sl_price: float,
        requested_lots: float,
        filled_lots: float,
        fill_price: float,
        max_loss_usd: float,
        spread_points: float = 0.0,
        slippage_points: float = 0.0,
        open_ts: str = "",
    ) -> PositionState:
        if direction == "BUY":
            mfe_price, mae_price = fill_price, fill_price
        else:  # SELL
            mfe_price, mae_price = fill_price, fill_price
        ps = PositionState(
            order_id=order_id, symbol=symbol, direction=direction,
            entry_price=entry_price, sl_price=sl_price,
            requested_lots=requested_lots, filled_lots=filled_lots,
            fill_price=fill_price, spread_points=spread_points,
            slippage_points=slippage_points, max_loss_usd=max_loss_usd,
            open_ts=open_ts, mfe_price=mfe_price, mae_price=mae_price,
        )
        self._positions[order_id] = ps
        return ps

    # ---- Tick 采样 ----
    def sample_tick(self, order_id: str, price: float) -> None:
        ps = self._positions.get(order_id)
        if ps is None:
            return
        if ps.direction == "BUY":
            ps.mfe_price = max(ps.mfe_price, price)   # 有利 = 价更高
            ps.mae_price = min(ps.mae_price, price)   # 不利 = 价更低
        else:  # SELL
            ps.mfe_price = min(ps.mfe_price, price)   # 有利 = 价更低
            ps.mae_price = max(ps.mae_price, price)   # 不利 = 价更高

    # ---- 平仓结算 + 落库 + 回调熔断器 ----
    def close_position(
        self,
        order_id: str,
        exit_price: float,
        exit_reason: str,
        realized_pnl_usd: float,
        circuit_breaker=None,
        close_ts: str = "",
    ) -> Dict[str, Any]:
        ps = self._positions.get(order_id)
        if ps is None:
            raise KeyError(f"order_id={order_id} 未开仓登记，无法平仓归因")

        one_r = ps.max_loss_usd if ps.max_loss_usd > 0 else 1.0

        # 方向相关的最大有利/不利美元损益（基于极值价）
        if ps.direction == "BUY":
            mfe_usd = (ps.mfe_price - ps.fill_price) * ps.filled_lots * 100.0
            mae_usd = (ps.mae_price - ps.fill_price) * ps.filled_lots * 100.0
        else:
            mfe_usd = (ps.fill_price - ps.mfe_price) * ps.filled_lots * 100.0
            mae_usd = (ps.fill_price - ps.mae_price) * ps.filled_lots * 100.0
        mae_usd = abs(mae_usd)

        # E1 量纲体系
        mfe_r = mfe_usd / one_r
        mae_r = mae_usd / one_r
        realized_r = realized_pnl_usd / one_r
        giveback_r = mfe_r - realized_r

        row = {
            "order_id": order_id,
            "symbol": ps.symbol,
            "direction": ps.direction,
            "entry_price": ps.entry_price,
            "sl_price": ps.sl_price,
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "requested_lots": ps.requested_lots,
            "filled_lots": ps.filled_lots,
            "fill_price": ps.fill_price,
            "spread_points": ps.spread_points,
            "slippage_points": ps.slippage_points,
            "max_loss_usd": ps.max_loss_usd,
            "realized_pnl_usd": realized_pnl_usd,
            "mfe_price": ps.mfe_price,
            "mae_price": ps.mae_price,
            "mfe_usd": round(mfe_usd, 4),
            "mae_usd": round(mae_usd, 4),
            "mfe_r": round(mfe_r, 4),
            "mae_r": round(mae_r, 4),
            "realized_r": round(realized_r, 4),
            "giveback_r": round(giveback_r, 4),
            "open_ts": ps.open_ts,
            "close_ts": close_ts,
            "notes": "",
        }
        cols = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        self._conn.execute(
            f"INSERT OR REPLACE INTO {self.table} ({cols}) VALUES ({placeholders})",
            tuple(row.values()),
        )
        self._conn.commit()

        # 驱动熔断器闭环（G2 关键回调）
        if circuit_breaker is not None:
            circuit_breaker.record_trade(realized_pnl_usd)

        del self._positions[order_id]
        return row

    # ---- 查询（单测/调试用） ----
    def get_record(self, order_id: str) -> Optional[Dict[str, Any]]:
        cur = self._conn.execute(f"SELECT * FROM {self.table} WHERE order_id=?", (order_id,))
        col_names = [d[0] for d in cur.description]
        row = cur.fetchone()
        return dict(zip(col_names, row)) if row else None

    def close(self) -> None:
        self._conn.close()
