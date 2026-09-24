# -*- coding: utf-8 -*-
"""
submit_close.py
G2 人工辅助 —— 平仓意图录入 + 平仓监听循环（独立通道，不改已冻结的 poll_loop）。

【为什么单独一套】
  mt5_bridge.poll_loop 只监听 order_intent.json（开仓），不监听平仓。
  平仓需要 exit_price + realized_pnl_usd，这两个数只能来自 MT5 终端的真实
  平仓回报，由你（人）读取后录入。本模块提供：
    1. submit_close_cli()  —— 交互录入平仓意图，写 close_intent.json
    2. close_loop()        —— 监听 close_intent.json，消费后调
                              AttributionSink.close_position() 落库 + 回写
                              execution_result_close.json，并回调熔断器。

【契约边界】
  - 机器不计算盈亏、不读终端。人负责把终端的真实平仓价与已实现盈亏填进来。
  - 机器只做：归因计算（MFE/MAE/R 倍数，E1 量纲）+ 落库 + 驱动熔断闭环。
  - 不开 G3：本模块仍要求人工逐笔录入，无任何自动信号触发。

运行（两个独立终端）：
  终端A（开仓 Bridge，已有）： 见 PreReg SOP 步骤2
  终端B（平仓监听）：          python trading_os/submit_close.py --serve --mode mock
  终端C（录入平仓）：          python trading_os/submit_close.py

【G01 存储边界（2026-09-24）】
  `--serve` 旧实现无模式声明即构造 `AttributionSink`（默认连 canonical 生产库 + DDL + commit），
  是 G01 的**第二个入口**。现已要求 `--mode {mock,test}` 显式声明：
  缺失 → UNKNOWN → 拒绝并 exit 2；MOCK/TEST 只允许 `:memory:`。
  归因库路径不再有"默认生产库"常量：DEFAULT_DB 已删除。
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from circuit_breaker import CircuitBreaker
from attribution_sink import AttributionSink
import storage_policy

DATA_DIR = os.path.join(_HERE, "data")
CLOSE_INTENT_PATH = os.path.join(DATA_DIR, "close_intent.json")
CLOSE_RESULT_PATH = os.path.join(DATA_DIR, "execution_result_close.json")
EXEC_RESULT_PATH = os.path.join(DATA_DIR, "execution_result.json")
# ⚠️ G01：已删除 DEFAULT_DB（原为 canonical 生产库路径常量）。
#    归因存储目标由 storage_policy 按 --mode 裁决，MOCK/TEST 只允许 ':memory:'。


def _prompt(msg: str) -> str:
    try:
        return input(msg).strip()
    except (EOFError, KeyboardInterrupt):
        print("\n[ABORT] 已取消")
        sys.exit(130)


def _last_filled_order_id() -> str:
    """从 execution_result.json 读取最近一笔 FILLED 订单的 order_id 作为默认。"""
    if not os.path.exists(EXEC_RESULT_PATH):
        return ""
    try:
        with open(EXEC_RESULT_PATH, "r", encoding="utf-8") as f:
            res = json.load(f)
        if res.get("status") == "FILLED" and res.get("order_id"):
            return str(res["order_id"])
    except Exception:
        pass
    return ""


def submit_close_cli() -> None:
    """交互录入平仓意图。order_id 默认带出最近一笔开仓成交号，避免手抄出错。"""
    default_oid = _last_filled_order_id()
    if default_oid:
        print(f"[提示] 检测到最近开仓成交号：{default_oid}（直接回车沿用）")
        order_id = _prompt(f"平仓订单 order_id [{default_oid}]: ").strip() or default_oid
    else:
        order_id = _prompt("平仓订单 order_id (无开仓记录，请手动填): ").strip()
    if not order_id:
        print("[FAIL] order_id 不能为空")
        sys.exit(1)
    try:
        exit_price = float(_prompt("平仓价 (exit_price，取自 MT5 终端真实回报): "))
        realized_pnl = float(_prompt("已实现盈亏 USD (realized_pnl_usd，取自 MT5 终端): "))
    except ValueError:
        print("[FAIL] 平仓价 / 盈亏必须是数字")
        sys.exit(1)
    exit_reason = _prompt("平仓原因 [MANUAL/SL/TP/SIGNAL] (默认 MANUAL): ").strip() or "MANUAL"

    intent = {
        "order_id": order_id,
        "exit_price": exit_price,
        "realized_pnl_usd": realized_pnl,
        "exit_reason": exit_reason,
    }
    with open(CLOSE_INTENT_PATH, "w", encoding="utf-8") as f:
        json.dump(intent, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] 已写入 {CLOSE_INTENT_PATH}")
    print(f"     平仓监听循环（--serve）将消费并落库 xau_execution_attribution。")


def close_loop(
    circuit_breaker: CircuitBreaker,
    attribution_sink: AttributionSink,
    interval: float = 0.5,
    max_iterations: int | None = None,
) -> None:
    """监听 close_intent.json（I/O 层，不进单测）。"""
    iterations = 0
    while True:
        if os.path.exists(CLOSE_INTENT_PATH):
            try:
                with open(CLOSE_INTENT_PATH, "r", encoding="utf-8") as f:
                    intent = json.load(f)
                row = attribution_sink.close_position(
                    order_id=intent["order_id"],
                    exit_price=float(intent["exit_price"]),
                    exit_reason=intent.get("exit_reason", "MANUAL"),
                    realized_pnl_usd=float(intent["realized_pnl_usd"]),
                    circuit_breaker=circuit_breaker,
                )
                with open(CLOSE_RESULT_PATH, "w", encoding="utf-8") as f:
                    json.dump({"status": "CLOSED", **row}, f, ensure_ascii=False, indent=2)
                print(f"[CLOSE] order_id={row['order_id']} realized_r={row['realized_r']} "
                      f"mfe_r={row['mfe_r']} giveback_r={row['giveback_r']} 已落库")
            except Exception as e:
                with open(CLOSE_RESULT_PATH, "w", encoding="utf-8") as f:
                    json.dump({"status": "ERROR", "reason": str(e)}, f, ensure_ascii=False, indent=2)
                print(f"[CLOSE-ERROR] {e}")
            try:
                os.remove(CLOSE_INTENT_PATH)
            except OSError:
                pass

        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            break
        time.sleep(interval)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", action="store_true", help="启动平仓监听循环（消费 close_intent.json）")
    ap.add_argument("--mode", choices=["mock", "test"], default=None,
                    help="--serve 必填：存储模式。缺失 → UNKNOWN → 拒绝并 exit 2（G01 fail-closed）")
    ap.add_argument("--db", default=None,
                    help="归因 SQLite 路径（MOCK/TEST 只允许 ':memory:'；不传即 ':memory:'）")
    args = ap.parse_args()

    if args.serve:
        # ── G01：先裁决模式与目标，再构造 sink ──
        mode = storage_policy.resolve_mode(mock=False, mode_arg=args.mode)
        try:
            target = storage_policy.resolve_db_target(mode, args.db)
        except storage_policy.StoragePolicyError as e:
            print(f"[FAIL] 存储边界拒绝（G01）：{e}")
            print("       提示：--serve 必须显式 --mode {mock,test}；MOCK/TEST 只允许 ':memory:'。")
            sys.exit(2)

        cb = CircuitBreaker()
        sink = AttributionSink(db_target=target)   # 构造期零 I/O
        sink.open()                                 # 连接由策略层签发
        print(f"[close_loop] 已启动，监听 {CLOSE_INTENT_PATH} ... (Ctrl+C 停止)")
        try:
            close_loop(cb, sink, interval=0.5)
        except KeyboardInterrupt:
            print("\n[close_loop] 已停止")
            sink.close()
    else:
        submit_close_cli()


if __name__ == "__main__":
    main()
