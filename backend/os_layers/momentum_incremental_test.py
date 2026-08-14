"""
momentum_incremental_test.py - P2：Momentum 增量信息检验（Incremental Information Test）

====================================================================
目的（用户 2026-08-14 定调）
====================================================================
不是简单比 A/B 的年化收益（样本太少），而是检验：

    Momentum（A × Tilt）是否对「未来收益」有稳定预测关系？

即回答：
  Q1. A 很高 + Tilt 显著为负  → 未来 1~4 周趋势恶化概率？
  Q2. A 很低 + Tilt 显著为正  → 未来是否更容易趋势修复？
  Q3. A 高 + Tilt 高           → 是否真正的强势延续？
  Q4. A 高 + Tilt 低           → 是否「长周期强、短周期掉速」的典型衰减？

用二维框架（长期趋势 × 短期动量）分组，比较各组的前向收益分布：

            短期动量 ↑          短期动量 ↓
长期趋势 ↑   强趋势延续          趋势衰减
长期趋势 ↓   趋势修复            弱势延续

====================================================================
当前状态：骨架占位（不可运行的正式检验）
====================================================================
- 数据底座 momentum_timeseries.jsonl 刚开始积累（≥20 周度/日度快照才够统计意义）。
- ft_ret_1w / ft_ret_2w / ft_ret_4w 目前全为 None，需接入价格序列回填后才能算前向收益。
- 本脚本现仅做：加载底座 → 报告当前数据充分度 → 打印「待做检验」的设计，不做任何结论。
- 接入价格序列的 TODO 见 _fill_forward_returns()。

====================================================================
用法
====================================================================
  python momentum_incremental_test.py
  数据足够 + 回填后，会自动跑 Incremental Information Test 并输出各象限前向收益。
"""

import os
import json
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.abspath(os.path.join(HERE, "..", "output"))
TIMESERIES_PATH = os.path.join(OUTPUT_DIR, "momentum_timeseries.jsonl")

# 二维框架阈值（研究用，后续用历史分布重标定）
A_STRONG = 60.0          # 长期趋势强：Model A 综合排名 ≥ 60
TILT_HIGH = 5.0          # 短期动量大：Tilt ≥ +5
TILT_LOW = -5.0          # 短期动量小：Tilt ≤ -5
MIN_SNAPSHOTS = 20       # 启动正式检验的最低快照数（用户建议 20~30）


def load_panel():
    """把 jsonl 底座摊平成 (date, ticker) 长表。"""
    if not os.path.exists(TIMESERIES_PATH):
        return []
    panel = []
    with open(TIMESERIES_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            snap = json.loads(line)
            d = snap["date"]
            for r in snap["rows"]:
                panel.append({
                    "date": d,
                    "ticker": r.get("ticker"),
                    "cat2": r.get("cat2"),
                    "compA": r.get("compA"),
                    "compB": r.get("compB"),
                    "tilt": r.get("tilt"),
                    "ft_ret_1w": r.get("ft_ret_1w"),
                    "ft_ret_2w": r.get("ft_ret_2w"),
                    "ft_ret_4w": r.get("ft_ret_4w"),
                })
    return panel


def classify_quadrant(rec):
    """返回 (长期趋势, 短期动量) 二维标签。"""
    a = rec.get("compA")
    t = rec.get("tilt")
    if a is None or t is None:
        return None
    long_term = "强" if a >= A_STRONG else "弱"
    if t >= TILT_HIGH:
        short_term = "↑"
    elif t <= TILT_LOW:
        short_term = "↓"
    else:
        short_term = "→"
    return (long_term, short_term)


def _fill_forward_returns(panel):
    """TODO(P2 数据接入)：把 ft_ret_1w/2w/4w 从价格序列回填。

    候选数据源（按系统既有）：
      - 通达信本地 / backend/database TDX 行情（需 ETF 代码映射）
      - akshare / 东财（沙箱需直连，代理可能阻断）
    回填后，每个 (date, ticker) 的 ft_ret_kw = 自该 data_date 起未来 k 周收益率。
    未接入前，本函数原样返回（ft_ret 仍为 None）。
    """
    return panel


def readiness_report(panel):
    snaps = sorted({r["date"] for r in panel})
    n = len(panel)
    filled = sum(1 for r in panel if r.get("ft_ret_4w") is not None)
    print("== 数据充分度 ==")
    print("  快照数：%d（启动正式检验需 ≥ %d）" % (len(snaps), MIN_SNAPSHOTS))
    print("  面板样本：(date,ticker) 共 %d 条" % n)
    print("  前向收益已回填：%d 条（当前应=0，待接价格序列）" % filled)
    print("  快照日期：%s ~ %s" % (snaps[0] if snaps else "-", snaps[-1] if snaps else "-"))
    ok = len(snaps) >= MIN_SNAPSHOTS and filled > 0
    return ok


def run_test(panel):
    """正式 Incremental Information Test（数据就绪后由 main 调用）。"""
    quad = defaultdict(list)
    for r in panel:
        if r.get("ft_ret_4w") is None:
            continue
        q = classify_quadrant(r)
        if q is None:
            continue
        quad[q].append(r["ft_ret_4w"])
    print("\n== 各象限 4 周前向收益（均值 / 样本数）==")
    for lt in ("强", "弱"):
        for st in ("↑", "→", "↓"):
            vals = quad.get((lt, st), [])
            if vals:
                print("  长期%s 短期%s：均值 %.3f%%  n=%d" % (lt, st, sum(vals)/len(vals)*100, len(vals)))
    # TODO: 加 t 检验 / 命中率 / 与「仅 A」基准的增量对比
    print("\n（完整检验：t 检验、命中率、与仅-Model-A 基准的增量对比，待数据就绪后补全）")


def main():
    print("[P2] Momentum Incremental Information Test（骨架占位）")
    panel = load_panel()
    if not panel:
        print("  底座为空，请先运行 market_momentum.py 积累快照。")
        return
    ready = readiness_report(panel)
    if not ready:
        print("\n结论：数据尚未就绪，暂不跑检验。")
        print("  下一步：① 让每日自动化积累快照（目标 ≥ %d）② 接价格序列回填 ft_ret_*。" % MIN_SNAPSHOTS)
        print("  设计已就位：A×Tilt 二维框架（强趋势延续 / 趋势衰减 / 趋势修复 / 弱势延续）。")
        return
    panel = _fill_forward_returns(panel)
    run_test(panel)


if __name__ == "__main__":
    main()
