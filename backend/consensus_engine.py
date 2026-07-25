# -*- coding: utf-8 -*-
"""
第四层 · 资金共识生命周期判定引擎（量化 + 规则树）
=================================================
输入：sector_mainline.json 的 `sectors`（全 90 行业完整指标）
      - 资金：net_now / net_3d / net_5d / net_10d（新浪，亿元，当日/3/5/10日累计净额）
      - 价格：chg_pct（板块涨跌幅）、close_vs_high25（价处25日高点%）、price_mom5/10（动量）
      - 量能：amount_today / amount_ma20（同花顺，成交额及20日均值）
输出：每个行业的 7 阶段生命周期定位 + 共识强度(0-100) + 可读判定理由
      及全市场 stage 分布汇总。

生命周期（consensus_cycle.md）：
  事件 → 讨论 → 资金流入 → 赚钱效应 → 一致性 → 高潮 → 退潮

设计原则：
  - 纯本地计算（无外部网络），可每日自动跑。
  - 「AI 判定」= 五维量化打分 + 可解释规则树（透明、可回溯，非黑箱）。
"""
import json, os, math


def _f(x):
    try:
        if x is None or x == "":
            return None
        return float(x)
    except Exception:
        return None


def _clip(v, lo, hi):
    return max(lo, min(hi, v))


def _pct_rank(v, arr):
    """v 在 arr 中的百分位（0-100），用于横截面相对强度"""
    if v is None or not arr:
        return None
    below = sum(1 for x in arr if x < v)
    return round(below / len(arr) * 100, 1)


# 各阶段对应的「共识进度」刻度（仅用于排序展示，非风险）
STAGE_SCORE = {
    "事件": 5, "讨论": 15, "资金流入": 35, "赚钱效应": 55,
    "一致性": 75, "高潮": 92, "退潮": 80,
}


def compute_consensus(sectors):
    """对全行业列表做生命周期判定，返回带判定结果的列表（按共识强度降序）。"""
    nets = [_f(s.get("net_now")) for s in sectors]
    nets_valid = [v for v in nets if v is not None]

    out = []
    for s in sectors:
        net_now = _f(s.get("net_now"))
        net_3d = _f(s.get("net_3d"))
        net_5d = _f(s.get("net_5d"))
        net_10d = _f(s.get("net_10d"))
        chg = _f(s.get("chg_pct"))
        amt_t = _f(s.get("amount_today"))
        amt_ma20 = _f(s.get("amount_ma20"))
        cvh = _f(s.get("close_vs_high25"))
        mom5 = _f(s.get("price_mom5"))

        # ---- 五维量化 ----
        fund_strength = _pct_rank(net_now, nets_valid)          # 资金强度（横截面百分位）
        # 资金趋势/加速：当日净额 vs 近5日日均（封顶避免 net_5d≈0 时爆炸）
        if net_5d is not None and net_5d > 0 and net_now is not None:
            fund_accel = net_now / (net_5d / 5) if (net_5d / 5) > 0 else (1.2 if net_now > 0 else 0.0)
        elif net_now is not None and net_now > 0:
            fund_accel = 1.2
        else:
            fund_accel = 0.0
        fund_accel = min(max(fund_accel, 0.0), 3.0)
        # 量能趋势：当日成交额 / 20日均
        vol_trend = (amt_t / amt_ma20) if (amt_t and amt_ma20) else None
        # 赚钱效应：板块当日涨跌幅
        profit = chg
        # 价格位置：处25日高点百分比
        price_pos = cvh

        # ---- 规则树：映射到 7 阶段 ----
        stage = None
        risk = False
        outflow_today = (net_now is not None and net_now < 0)
        if net_now is None:
            stage = "讨论"
        elif outflow_today and (net_5d is None or net_5d <= 0):
            # 当日与近5日双转负 → 真退潮（资金撤离）
            stage = "退潮"
            risk = True
        elif outflow_today:
            # 当日净流出但5日仍为正 → 分歧/兑现，需价格确认才算退潮
            risk = True
            if (chg or 0) < 0 or (cvh or 1) < 0.90:
                stage = "退潮"
            elif (chg or 0) > 0 and (vol_trend or 1) >= 1.12 and (cvh or 0) >= 0.92:
                stage = "一致性"
            elif (chg or 0) > 0 and (vol_trend or 1) >= 1.05:
                stage = "赚钱效应"
            elif (vol_trend or 1) >= 1.0:
                stage = "资金流入"
            else:
                stage = "讨论"
        else:
            vt = vol_trend if vol_trend is not None else 1.0
            acc = fund_accel
            fstr = fund_strength if fund_strength is not None else 50
            # 高潮：多信号共振、全面发酵
            if (fstr >= 70 and acc >= 1.2 and vt >= 1.25
                    and (chg or 0) >= 3 and (cvh or 0) >= 0.97):
                stage = "高潮"
                risk = True
            # 一致性：资金持续、量能放大、价格抬升、市场形成一致预期
            elif (net_5d is not None and net_5d > 0 and vt >= 1.12
                  and (chg or 0) > 0 and (cvh or 0) >= 0.92):
                stage = "一致性"
            # 赚钱效应：板块开始涨、出现赚钱样本
            elif (chg or 0) > 0 and vt >= 1.05:
                stage = "赚钱效应"
            # 资金流入：主力开始进场，量能刚启动
            elif vt >= 1.0 or acc >= 1.0:
                stage = "资金流入"
            else:
                stage = "讨论"

        # ---- 共识强度（0-100，用于排序；退潮压低）----
        vol_c = _clip((_f(vol_trend) - 0.8) / 0.6 * 100, 0, 100) if vol_trend else 0
        chg_c = _clip((chg or 0) * 10 + 50, 0, 100)
        price_c = _clip(((cvh or 0.8) - 0.8) / 0.2 * 100, 0, 100) if cvh else 40
        strength = (0.40 * (fund_strength or 0)
                    + 0.20 * vol_c
                    + 0.20 * chg_c
                    + 0.20 * price_c)
        if stage == "退潮":
            strength = min(strength, 60)
        strength = round(strength, 1)

        # ---- 可读判定理由 ----
        reasons = []
        if net_now is not None:
            reasons.append(f"净流入{net_now:+.1f}亿(强度P{fund_strength})")
        if net_5d is not None:
            reasons.append(f"5日累计{net_5d:+.1f}亿")
        if vol_trend is not None:
            reasons.append(f"成交额/20日均={vol_trend:.2f}x")
        if chg is not None:
            reasons.append(f"板块{chg:+.1f}%")
        if cvh is not None:
            reasons.append(f"价处25日高{cvh*100:.0f}%")
        if stage == "退潮":
            reasons.append("⚠ 资金撤离(当日/5日净流出)")
        elif stage == "高潮":
            reasons.append("⚠ 多信号共振，警惕散户涌入/赶顶")
        elif outflow_today:
            reasons.append("⚠ 当日净流出(分歧/兑现，未确认退潮)")

        out.append({
            "sector": s.get("sector"),
            "stage": stage,
            "stage_score": STAGE_SCORE.get(stage, 0),
            "consensus_strength": strength,
            "risk": risk,
            "fund_accel": round(fund_accel, 3),
            "net_now": net_now,
            "net_5d": net_5d,
            "net_10d": net_10d,
            "chg_pct": chg,
            "amount_today": amt_t,
            "amount_ma20": amt_ma20,
            "vol_trend": round(vol_trend, 3) if vol_trend else None,
            "close_vs_high25": cvh,
            "reason": " ｜ ".join(reasons),
        })

    out.sort(key=lambda x: x["consensus_strength"], reverse=True)

    # 早期观察：处于「资金流入/讨论」且加速明显的板块（潜在新主线）
    early = [r for r in out if r["stage"] in ("资金流入", "讨论")]
    early.sort(key=lambda x: (x["fund_accel"] or 0), reverse=True)
    early_watch = early[:8]

    # stage 分布
    from collections import Counter
    dist = Counter(r["stage"] for r in out)
    return out, dict(dist), early_watch


def consensus_for_layers(json_path, top_n=15):
    """供 decision_tree 调用的入口：返回 L4 层结构。"""
    d = json.load(open(json_path, encoding="utf-8"))
    sectors = d.get("sectors", [])
    if not sectors:
        return {"status": "待接入", "note": "sector_mainline.json 缺 sectors 字段，先重跑 build_sector_mainline.py"}
    ranked, dist, early = compute_consensus(sectors)
    return {
        "status": "已接入(量化+规则树)",
        "trade_date": d.get("trade_date"),
        "sector_count": d.get("sector_count"),
        "stage_distribution": dist,
        "main_lines": ranked[:top_n],
        "early_watch": early,
    }


if __name__ == "__main__":
    BASE = os.path.dirname(os.path.abspath(__file__))
    OUT = os.path.join(BASE, "output")
    p = os.path.join(OUT, "sector_mainline.json")
    res, dist, early = compute_consensus(json.load(open(p, encoding="utf-8")).get("sectors", []))
    json.dump(res, open(os.path.join(OUT, "sector_consensus.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"行业数={len(res)}  阶段分布={dist}\n")
    print(f"{'板块':<6}{'阶段':<6}{'强度':>6}  理由")
    print("-" * 90)
    for r in res[:20]:
        print(f"{r['sector']:<6}{r['stage']:<6}{r['consensus_strength']:>6}  {r['reason']}")
    print("\n--- 早期观察(潜在新主线) ---")
    for r in early:
        print(f"  {r['sector']:<6} 加速={r['fund_accel']} 净流入={r['net_now']} 成交额比={r['vol_trend']}")
