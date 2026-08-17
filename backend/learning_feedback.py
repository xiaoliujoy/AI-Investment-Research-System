# -*- coding: utf-8 -*-
"""
learning_feedback —— L8 学习进化的【反哺引擎】。

用户架构评审的核心诉求之一：
    "Learning 也不应该最后。Learning 应该反向影响。
     例如 Learning 发现追二板胜率 30%，Execution 以后自动降低二板评分。
     这就是真正 AI：系统自己修改自己。"

本模块把 narrative_layers.monthly_pattern() 的历史统计，转成 orchestrator 可消费的
【调整信号】，实现 Learning OS ──▶ Decision OS 的唯一反向箭头：

  1) sector_bias   板块级偏置：某板块历史胜率高→加分(利好这个方向)，低→减分(收紧)。
                   需最小样本(MIN_N)，避免小样本噪声。
  2) conf_delta    对总置信度的净调整(+/-，有上下限 CAP)。
  3) pos_scale     对仓位护栏的缩放系数(<1 收紧, =1 不变)——整体胜率差时自动降仓。
  4) notes         人类可读的反哺说明，进推理链展示。
  5) applied       是否有足够样本启用(样本不足则全中性、不干预)。

守边界：反哺只调"置信度/仓位护栏"这类系统内部参数，绝不生成买卖点或图形判断。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

MIN_N = 3          # 板块级偏置的最小样本
MIN_TOTAL = 5      # 启用整体反哺的最小总样本
CAP = 12           # 总置信度净调整上限（±）
BIAS_CAP = 8       # 单板块偏置上限（±）


def _sector_bias_one(v):
    """把单个板块的胜率/盈亏转成偏置分（-BIAS_CAP..+BIAS_CAP）。"""
    n = v.get("n", 0)
    wr = v.get("win_rate")
    avg = v.get("pnl_avg")
    if n < MIN_N or wr is None:
        return 0, "样本不足"
    # 以 50% 胜率为中枢，每偏离 10pct 给 ~2.5 分，叠加盈亏方向微调
    delta = (wr - 50) / 10 * 2.5
    if avg is not None:
        delta += max(-2, min(2, avg / 5))   # 均盈亏每 5% 给 1 分，封顶 ±2
    delta = max(-BIAS_CAP, min(BIAS_CAP, round(delta, 1)))
    tag = "利好" if delta > 0 else ("收紧" if delta < 0 else "中性")
    return delta, f"{tag}(胜率{wr}%/均盈亏{avg}%/{n}笔)"


def learning_feedback():
    """产出反哺信号。无数据时返回中性、applied=False。

    两层学习反哺互补合并（OR 而非 AND）：
      · 交易级：narrative_layers.monthly_pattern() 历史胜率 → 板块偏置 + 仓位缩放
      · 预测级：learning_center.prediction_feedback() IC 方向命中率 → 置信度/仓位缩放
    任一层达到启用阈值即 applied=True 并干预；互不阻塞（此前 bug：交易样本<5 时提前
    return，把预测级回放合并也挡掉，导致 IC 命中率 33% 从未收紧仓位护栏）。
    """
    # ── Adaptive Feedback Freeze（Phase 1E / Research Freeze）──
    # 冻结时：不把「市场结果」反向写为生产参数（pos_scale/conf_delta/权重/sector_bias）。
    # 仍计算并保留 IC 方向命中率供 provenance 记录，但 applied=False 使所有消费方（orchestrator
    # 置信度、preflight 降级、committee、os2_report 权重）拿到中性信号，不污染生产决策。
    from learning_center import ADAPTIVE_FEEDBACK_ENABLED
    if not ADAPTIVE_FEEDBACK_ENABLED:
        try:
            from learning_center import prediction_feedback
            _pf = prediction_feedback()
            _pf_acc = _pf.get("accuracy")
            _pf_n = _pf.get("count", 0)
        except Exception:
            _pf_acc, _pf_n = None, 0
        return {
            "applied": False,
            "frozen": True,
            "status": "自适应反哺已冻结(Record-Only)",
            "conf_delta": 0, "pos_scale": 1.0, "sector_bias": {},
            "count": _pf_n,
            "pred_accuracy": _pf_acc,
            "notes": [f"Research Freeze：学习信号仅记录（IC 方向命中率 {_pf_acc}%，{_pf_n} 次回放），"
                      f"不回写 pos_scale/conf_delta/权重。"],
        }
    try:
        import narrative_layers as ne
        stat = ne.monthly_pattern()
    except Exception as e:
        result = {"applied": False, "status": "统计失败", "conf_delta": 0,
                  "pos_scale": 1.0, "sector_bias": {}, "notes": [repr(e)[:80]],
                  "count": 0}
        _merge_prediction_feedback(result)   # 交易统计挂了，预测级仍独立生效
        return result

    count = stat.get("count", 0)
    if count < MIN_TOTAL:
        result = {"applied": False,
                  "status": f"样本积累中({count}/{MIN_TOTAL})",
                  "conf_delta": 0, "pos_scale": 1.0, "sector_bias": {},
                  "count": count,
                  "notes": [f"交易样本 {count} 笔，达到 {MIN_TOTAL} 笔后自动启用历史胜率反哺"
                            f"（板块偏置 + 仓位缩放）。"]}
        _merge_prediction_feedback(result)   # 关键修复：交易样本不足仍合并预测级（IC 命中率独立生效）
        return result

    by_sector = stat.get("by_sector", {}) or {}
    sector_bias = {}
    notes = []
    for s, v in by_sector.items():
        d, why = _sector_bias_one(v)
        if d != 0:
            sector_bias[s] = d
            notes.append(f"「{s}」{why} → 方向偏置 {d:+.1f}")

    # 整体胜率 → 总置信度净调整 + 仓位缩放
    wr = stat.get("win_rate")
    conf_delta = 0
    pos_scale = 1.0
    if wr is not None:
        conf_delta = max(-CAP, min(CAP, round((wr - 50) / 10 * 3, 1)))
        if wr < 40:
            pos_scale = 0.7
            notes.append(f"整体胜率 {wr}% 偏低 → 仓位护栏自动收紧至 70%、总置信度 {conf_delta:+.1f}")
        elif wr < 50:
            pos_scale = 0.85
            notes.append(f"整体胜率 {wr}% 待改善 → 仓位护栏收紧至 85%、总置信度 {conf_delta:+.1f}")
        else:
            notes.append(f"整体胜率 {wr}% 良好 → 总置信度 {conf_delta:+.1f}，仓位护栏维持")

    # 采纳 narrative_layers 已提炼的迭代建议（板块最优/最差/趋势）
    for ins in stat.get("insights", []):
        notes.append(ins)

    result = {"applied": True, "status": "已启用（交易级）", "count": count,
              "win_rate": wr, "conf_delta": conf_delta, "pos_scale": pos_scale,
              "sector_bias": sector_bias, "notes": notes}

    _merge_prediction_feedback(result)   # 互补合并预测级
    return result


def _merge_prediction_feedback(result):
    """把 learning_center 的「预测回放」反哺（IC 方向命中率 → 置信度/仓位缩放）
    合并进 result。两条学习链独立，互不阻塞：预测级达标即接管 applied 与 pos_scale。"""
    try:
        from learning_center import prediction_feedback
        pf = prediction_feedback()
        result.setdefault("notes", [])
        result["pred_accuracy"] = pf.get("accuracy")
        if pf.get("applied"):
            result["notes"] = result["notes"] + pf.get("notes", [])
            result["conf_delta"] = max(-CAP, min(CAP, round(result.get("conf_delta", 0) + pf["conf_delta"], 1)))
            result["pos_scale"] = min(result.get("pos_scale", 1.0), pf.get("pos_scale", 1.0))
            result["applied"] = True
            result["status"] = ("已启用（交易级 + 预测级）"
                                if "交易级" in (result.get("status") or "")
                                else "已启用（预测级）")
            result["count"] = result.get("count", 0) + pf.get("count", 0)
        else:
            # 预测级未达阈值：仅带回 accuracy 供展示，不强制干预
            result["notes"] = result["notes"] + pf.get("notes", [])
    except Exception:
        pass
    return result


def _scale_position(position_pct: str, scale: float) -> str:
    """把 '50-80%' 这类仓位护栏按 scale 缩放，返回同格式字符串。"""
    if scale >= 0.999 or not position_pct:
        return position_pct
    import re
    nums = re.findall(r"\d+", position_pct)
    if not nums:
        return position_pct
    scaled = [str(int(round(int(x) * scale))) for x in nums]
    if len(scaled) >= 2:
        return f"{scaled[0]}-{scaled[1]}%"
    return f"{scaled[0]}%"


if __name__ == "__main__":
    import json
    print(json.dumps(learning_feedback(), ensure_ascii=False, indent=2))
