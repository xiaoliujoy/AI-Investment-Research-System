"""一句话录入 CLI：解析并写入 trade_execution（今日计划）。

用法:
    python parse_plan_cli.py "多 AU2508 760 745"
    echo "空 600519 38.5 36.2" | python parse_plan_cli.py

写库后返回 {ok,id,...}，可在纪律 UI「今日计划」查看。
解析失败(缺方向/品种)返回 ok:false 并给出已解析结构，不写库。
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plan_parser import parse_plan
from trading_discipline_engine import record_plan


def main():
    text = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    plan = parse_plan(text)
    if not plan["direction"] or not plan["symbol"]:
        print(json.dumps({"ok": False, "error": "无法解析方向或品种",
                          "parsed": plan}, ensure_ascii=False))
        sys.exit(1)
    tid = record_plan(
        plan["market"], plan["symbol"], plan["direction"],
        plan.get("reason", ""), plan.get("invalid", ""), plan.get("risk", ""),
        None, None, None, plan.get("planned_exit", ""),
    )
    out = {"ok": True, "id": tid, **plan}
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
