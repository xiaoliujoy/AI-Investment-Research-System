# -*- coding: utf-8 -*-
"""
submit_intent.py
G2 人工辅助 —— 开仓意图交互录入。

【定位】
  你（人）负责判断方向与价位；脚本负责把判断转成机器可消费的
  order_intent.json，并复用 compute_risk_plan 反推手数，避免手填 lots
  触发 mt5_bridge 的防篡改拒绝（TamperedIntentRejected）。

【不做什么】
  - 不连 MT5、不下单、不写生产库。只写 trading_os/data/order_intent.json。
  - 不自产方向。方向必须由你输入 BUY/SELL。
  - 不绕过硬门禁。若止损过窄/止损过宽/点差超限，compute_risk_plan 会
    直接抛错，脚本打印原因后退出，不写意图文件。

运行：
  python trading_os/submit_intent.py
依赖：trading_os/data/xauusd_spec.json（先跑 probe_xauusd_spec.py 生成）
"""
from __future__ import annotations
import json
import os
import sys

# 允许以脚本直接运行（cwd=项目根）或模块导入两种情况
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from risk_calculator import compute_risk_plan, DEFAULT_RISK_BUDGET

DATA_DIR = os.path.join(_HERE, "data")
SPEC_PATH = os.path.join(DATA_DIR, "xauusd_spec.json")
INTENT_PATH = os.path.join(DATA_DIR, "order_intent.json")


def _load_spec() -> dict:
    if not os.path.exists(SPEC_PATH):
        print(f"[FAIL] 找不到规格文件 {SPEC_PATH}")
        print("       请先运行：python trading_os/probe_xauusd_spec.py")
        sys.exit(2)
    with open(SPEC_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _prompt(msg: str) -> str:
    try:
        return input(msg).strip()
    except (EOFError, KeyboardInterrupt):
        print("\n[ABORT] 已取消")
        sys.exit(130)


def main() -> None:
    spec = _load_spec()
    print(f"[submit_intent] 规格来源 = {spec.get('source')} （XAUUSD）")
    print(f"[submit_intent] 单笔风险预算 = ${DEFAULT_RISK_BUDGET:.2f}（固定硬顶，CAL-A）")
    print("-------------------------------------------------------------")

    direction = _prompt("方向 [BUY/SELL]: ").upper()
    if direction not in ("BUY", "SELL"):
        print("[FAIL] 方向必须是 BUY 或 SELL")
        sys.exit(1)

    try:
        entry = float(_prompt("入场价 (entry_price): "))
        invalidation = float(_prompt("失效价 / 初始止损位 (invalidation_price): "))
    except ValueError:
        print("[FAIL] 价格必须是数字")
        sys.exit(1)

    # 复用 G1 计算器反推手数 + 硬门禁断言（窄止损/宽止损/点差 会在此拦截）
    try:
        plan = compute_risk_plan(
            entry_price=entry,
            invalidation_price=invalidation,
            direction=direction,
            risk_budget_usd=DEFAULT_RISK_BUDGET,
            spec_dict=spec,
        )
    except Exception as e:
        print(f"\n[REJECTED] 风险验算未通过，未写入意图文件：")
        print(f"           {e}")
        sys.exit(1)

    intent = {
        "symbol": "XAUUSD",
        "direction": direction,
        "entry_price": entry,
        "invalidation_price": invalidation,
        "lots": plan.calculated_lots,
    }

    print("\n--- 意图预览（机器将按此反推手数，与你的 lots 比对防篡改）---")
    print(f"  方向            : {direction}")
    print(f"  入场价          : {entry}")
    print(f"  失效价          : {invalidation}")
    print(f"  止损距离        : {plan.stop_distance_points:.1f} pt")
    print(f"  反推手数        : {plan.calculated_lots} lot（封顶 0.01）")
    print(f"  理论最大亏损    : ${plan.max_loss_usd:.2f}（≤ ${DEFAULT_RISK_BUDGET:.2f}）")
    print(f"  点值口径        : ${plan.per_lot_per_point:.2f}/lot/pt")

    # 二次确认，避免误触下单
    ok = _prompt("\n确认写入 order_intent.json 并提交 Bridge 执行？[y/N]: ").lower()
    if ok != "y":
        print("[ABORT] 未确认，意图未写入")
        sys.exit(0)

    with open(INTENT_PATH, "w", encoding="utf-8") as f:
        json.dump(intent, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] 已写入 {INTENT_PATH}")
    print(f"     Bridge（poll_loop）将在下一个轮询周期读取并下发真实 0.01 手订单。")


if __name__ == "__main__":
    main()
