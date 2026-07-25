# -*- coding: utf-8 -*-
"""
brain 包内一键入口。

与 backend/run_brain_report.py 功能等价，但内聚在包内，
便于从任意位置直接调用：

    cd backend
    python -m brain.run          # 模块方式
    python brain/run.py          # 脚本方式

也可在代码中导入：

    from brain.run import main
    results, report_path = main()

输出：
    output/brain_report.json     # 完整推理链 + 决策结论
    output/brain_report.html     # 可视化决策简报
"""
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

# ---------- 确保 backend/ 在 sys.path ----------
BASE = Path(__file__).resolve().parent.parent  # backend/
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import brain  # noqa

BEIJING = timezone(timedelta(hours=8))


def main(date_str: str = None):
    """
    运行完整推理链 + 生成决策简报。

    Args:
        date_str: 可选，交易日 YYYY-MM-DD，None 则用今天。

    Returns:
        (results dict, report_html_path str)
    """
    sep = "=" * 60
    print(sep)
    print("  Trading OS · 总指挥推理链")
    print("  " + (date_str or datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")))
    print(sep)

    # ---- 1. 跑推理链 ----
    print("\n[1/2] 运行推理链 (L1→L2→L4→L3→L5→sentiment→fundamental→L6→L7→L8) ...\n")
    results = brain.run(date=date_str)

    # ---- 2. 渲染 HTML ----
    print("\n[2/2] 渲染决策简报 HTML ...")
    report_path = brain.build_report(results)

    # ---- 打印摘要 ----
    decision = results.get("decision", {})
    conf = results.get("confidence", {})
    l0 = results.get("L0", {})
    conflicts = results.get("conflicts", [])

    print(f"\n{sep}")
    print(f"  交易日: {results.get('trade_date', '?')}")
    print(f"  L0 定调: {l0.get('headline', '—')}")
    print(f"  决策: {decision.get('can_buy', '?')}  "
          f"仓位护栏: {decision.get('position_pct', '?')}%  "
          f"总置信度: {conf.get('overall', '?')}")
    print(f"  强否决: {'是' if decision.get('hard_no') else '否'}  "
          f"冲突: {len(conflicts)}处")
    print(f"  偏多票: {decision.get('bull', '?')}  "
          f"偏空票: {decision.get('bear', '?')}")
    if decision.get("reasons"):
        print(f"\n  决策依据:")
        for r in decision["reasons"]:
            print(f"    • {r}")
    print(f"\n  报告: {report_path}")
    print(sep)

    return results, report_path


if __name__ == "__main__":
    main()
