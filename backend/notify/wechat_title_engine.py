# -*- coding: utf-8 -*-
"""公众号标题引擎 v1.0 —— 把「盘后归档文件」升级为「次日交易决策工具」
================================================================

设计定位（用户 2026-08-15 定稿）：
  原日报标题「投资决策备忘录 2026-08-13」本质是文件名，不是内容标题。
  它告诉读者"这是什么、哪一天"，却没回答"我为什么现在要打开它"。
  本引擎把标题从「日期驱动」改为「明日决策驱动」：
    - 标题完全不放日期（订阅号已有发布时间，正文首屏已有完整日期）
    - 核心判断前置，栏目名「投资决策备忘录」退居品牌后缀
    - 五类标题按优先级轮换，避免连续空仓导致读者疲劳

五类标题与优先级（高→低）：
  矛盾型 > 决策型 > 风险型 > 主线型 > 机会型
  - 矛盾型仅在存在「具体、可指名的看多表象」时触发（板块大额净流入 / 外围走强 /
    上涨家数过半），且标题必须点出该表象。无具体表象则降级到决策型，避免标题党。
  - 决策型为默认主选（任何一天都可用）。
  - 风险/主线/机会型作为备选标题，丰富维度。

输出：
  output/wechat_meta_{trade_date}.json   主标题 + 2~3 备选 + 摘要 + 类型
  output/wechat_title_log.jsonl         每次生成追加一行（日期/类型/标题），
                                         供用户事后从公众号后台手填打开率，闭环迭代。

依赖：纯读取 memo 对象，不修改任何决策/风控/Shadow 逻辑。
调用入口：emit_wechat_meta(memo)（守卫式，失败不影响日报）。
"""
import os
import sys
import json
import datetime

# 把 backend/ 加入 path，保证作为独立脚本也能 import os2_report
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

BRAND = "投资决策备忘录"

# 裁决等级数值（本地复刻，避免依赖 os2_report 私有 _LEVEL）
_LEVEL = {"YES": 2, "CAUTION": 1, "NO": 0}


def _t(phrase):
    """给标题短语追加品牌后缀。"""
    return f"{phrase}｜{BRAND}"


def _md(trade_date):
    """2026-08-14 → 8月14日（摘要用，标题不放日期）。"""
    if not trade_date:
        return ""
    try:
        d = datetime.date.fromisoformat(trade_date)
        return f"{d.month}月{d.day}日"
    except Exception:
        return trade_date


# ═══════════════════════════════════════════════════════
#  上下文提取（从 memo + decision 抽字段，全部防御式）
# ═══════════════════════════════════════════════════════
def extract_context(memo, decision, score):
    """从实时 memo 与安全裁决结果中抽出一个纯 dict 上下文，供模板填充。"""
    ctx = {
        "trade_date": getattr(memo, "trade_date", ""),
        "final": decision.get("final", "NO"),
        "composite": decision.get("composite", 0),
        "position": decision.get("position", ""),
        "ic_can_buy": decision.get("ic_can_buy", ""),
        "ic_level": decision.get("ic_level", ""),
        "pf_passed": decision.get("pf_passed", 0),
        "pf_total": decision.get("pf_total", 0),
        "market_state": decision.get("market_state", ""),
        "main_sector": "",
        "main_sector_stars": 0,
        "risk_biggest": "",
        "inflow_sectors": [],
        "capital_one_liner": "",
        "external_up": False,
        "rise_ratio": None,
        "retreat_count": None,
        "south_net_yi": None,
        "cross_asset_name": "",
        "watch_count": 0,
    }

    # 主线第一候选
    mls = getattr(memo, "main_lines", None) or []
    if mls:
        m0 = mls[0]
        ctx["main_sector"] = getattr(m0, "sector", "") or ""
        ctx["main_sector_stars"] = getattr(m0, "star_rating", 0) or 0

    # 最大风险
    rk = getattr(memo, "risk", None)
    if rk is not None:
        ctx["risk_biggest"] = getattr(rk, "biggest_risk", "") or ""

    # 资金迁移：轮动 in_top（板块净流入榜）
    mig = getattr(memo, "migration", None) or {}
    rot_in = ((mig.get("rotation") or {})).get("in_top", []) or []
    names = []
    for r in rot_in:
        if isinstance(r, dict):
            nm = r.get("sector") or r.get("name") or ""
        elif isinstance(r, str):
            nm = r
        else:
            nm = ""
        if nm:
            names.append(nm)
    ctx["inflow_sectors"] = names[:3]

    # 资金一句话
    cf = getattr(memo, "capital_flow", None)
    if cf is not None:
        ctx["capital_one_liner"] = getattr(cf, "one_liner", None) or ""
        ctx["south_net_yi"] = getattr(cf, "south_net_yi", None)

    # 外围市场（全球看板是否有上涨）
    gx = getattr(memo, "global_market", None)
    board = getattr(gx, "board", None) or [] if gx is not None else []
    ctx["external_up"] = any((b.get("change_pct") or 0) > 0 for b in board)

    # 市场结构（上涨占比 / 退潮板块数，可选）
    ms = getattr(memo, "market_structure", None) or {}
    rr = ms.get("rise_ratio") or ms.get("up_pct")
    ctx["rise_ratio"] = rr
    ctx["retreat_count"] = ms.get("retreat_count") or ms.get("down_sector_count")

    # 跨资产机会名（黄金等），仅取首个非空名
    ca = mig.get("cross_asset") or {}
    for k in ("黄金", "gold", "GOLD", "原油", "商品"):
        if k in ca and ca[k]:
            ctx["cross_asset_name"] = k
            break
    if not ctx["cross_asset_name"] and isinstance(ca, dict) and ca:
        # 退而求其次：用任意非空的跨资产键名
        for k, v in ca.items():
            if v:
                ctx["cross_asset_name"] = k
                break

    # 盯盘清单条数
    al = getattr(memo, "action_list", None) or []
    ctx["watch_count"] = len(al)

    return ctx


# ═══════════════════════════════════════════════════════
#  矛盾型检测（核心差异化，必须有具体看多表象）
# ═══════════════════════════════════════════════════════
def detect_contradiction(ctx):
    """返回 (矛盾型标题, 表象描述) 或 (None, "")。

    仅当最终裁决为 NO/CAUTION（保守）且存在具体看多表象时触发，
    且标题点出该表象。避免把「系统日常保守」包装成「矛盾」。
    """
    final = ctx["final"]
    # 矛盾型仅当系统「否决」看多表象时成立（最终裁决=NO）。CAUTION 是谨慎认同，
    # 并非否决，建议仓位 50-80% 本身即参与，不构成标题级认知冲突。
    # 例：8.20 IC=YES + 上涨76% + 最终CAUTION(仓位50-80%) → 不触发，走决策型。
    if final != "NO":
        return None, ""
    if _LEVEL.get(final, 0) >= 2:
        return None, ""

    # 看多氛围闸门：IC 偏多 或 上涨家数过半，否则板块流入只是防御轮动/
    # 避险切换，外围微涨只是噪音，不构成「看多表象」，触发矛盾型=标题党。
    # 例：8.18 IC=NO + 上涨36% + 资金从半导体切向银行/种植业(防守) → 不触发。
    ic_bullish = ctx["ic_can_buy"] in ("YES", "CAUTION")
    breadth_bullish = ctx["rise_ratio"] is not None and ctx["rise_ratio"] > 0.5
    if not (ic_bullish or breadth_bullish):
        return None, ""

    # 优先级：板块净流入 > 委员会看多 > 外围走强 > 上涨家数过半
    if ctx["inflow_sectors"]:
        sec = ctx["inflow_sectors"][0]
        return _t(f"{sec}资金回流，为什么系统仍裁定不交易"), f"{sec}资金回流"
    if ctx["ic_can_buy"] == "YES":
        return _t("委员会投票看多，为什么系统仍裁定不交易"), "IC 投票看多"
    if ctx["external_up"]:
        return _t("外围市场走强，为什么系统仍建议观望"), "外围走强"
    if ctx["rise_ratio"] is not None and ctx["rise_ratio"] > 0.5:
        return _t("上涨家数过半，为什么系统仍建议观望"), "上涨家数过半"
    return None, ""


# ═══════════════════════════════════════════════════════
#  各类型标题构建
# ═══════════════════════════════════════════════════════
def _decision_title(ctx):
    final = ctx["final"]
    if final == "NO":
        return _t("明日操作：维持空仓观望，等待主线确认")
    if final == "CAUTION":
        sec = ctx["main_sector"]
        if sec:
            return _t(f"明日操作：轻仓谨慎参与，聚焦{sec}")
        return _t("明日操作：轻仓谨慎参与，严控仓位")
    # YES
    sec = ctx["main_sector"]
    if sec:
        return _t(f"明日操作：逐步提高风险暴露，聚焦{sec}")
    return _t("明日操作：逐步提高风险暴露")


def _risk_title(ctx):
    if ctx["retreat_count"] is not None:
        return _t(f"{ctx['retreat_count']}个板块退潮，明日重点看主线能否接力")
    if ctx["rise_ratio"] is not None and ctx["rise_ratio"] < 0.5:
        pct = int(round(ctx["rise_ratio"] * 100))
        return _t(f"上涨家数仅{pct}%，市场仍处偏弱防守周期")
    if ctx["risk_biggest"]:
        # risk_biggest 在生产环境是一整句（含「——」解释），不能直接拼进标题
        _rb = ctx["risk_biggest"].split("——")[0].split("。")[0].strip()
        # 源数据 bug 防护：rise_ratio>=0.5 时「上涨家数仅X%」应为「上涨家数X%」
        if ctx["rise_ratio"] is not None and ctx["rise_ratio"] >= 0.5:
            _rb = _rb.replace("上涨家数仅", "上涨家数")
        if not _rb:
            _rb = "风险"
        return _t(f"最大风险：{_rb}，明日重点看风险释放")
    return _t("当前宜防守，明日重点看信号确认")


def _mainline_title(ctx):
    if ctx["inflow_sectors"]:
        return _t(f"{ctx['inflow_sectors'][0]}资金回流，明日能否确认主线")
    if ctx["main_sector"]:
        return _t(f"{ctx['main_sector']}成焦点，明日能否确认持续性")
    return None


def _opportunity_title(ctx):
    if ctx["cross_asset_name"]:
        return _t(f"{ctx['cross_asset_name']}出现异动，明日重点观察能否延续")
    return None


def _build_summary(ctx, contradiction=False):
    md = _md(ctx["trade_date"])
    verdict_txt = {"NO": "维持空仓防守", "CAUTION": "谨慎参与", "YES": "发出进攻信号"}.get(ctx["final"], "审慎应对")
    if contradiction and ctx["inflow_sectors"]:
        # 矛盾型：现象=看多表象（板块回流），与主标题呼应
        phen = f"{ctx['inflow_sectors'][0]}板块大额回流但持续性待验证"
    elif ctx["retreat_count"] is not None:
        # 非矛盾型：现象=风险数据，与决策/风险型标题呼应，避免「标题说退潮、摘要说回流」
        parts = [f"全市场{ctx['retreat_count']}个板块退潮"]
        if ctx["rise_ratio"] is not None:
            pct = int(round(ctx["rise_ratio"] * 100))
            # rise_ratio>=0.5 是普涨，不能叫「仅」
            word = "上涨家数" if ctx["rise_ratio"] >= 0.5 else "上涨家数仅"
            parts.append(f"{word}{pct}%")
        phen = "，".join(parts)
    elif ctx["rise_ratio"] is not None and ctx["rise_ratio"] < 0.5:
        pct = int(round(ctx["rise_ratio"] * 100))
        phen = f"上涨家数仅{pct}%，市场偏弱"
    elif ctx["risk_biggest"]:
        phen = f"最大风险为{ctx['risk_biggest']}"
    else:
        phen = ctx["market_state"] or "市场信号中性"
    wc = ctx.get("watch_count") or 0
    watch = f"{wc}个盯盘信号" if wc else "明日关键观察点"
    return f"{md}盘后更新。综合评分{ctx['composite']}分，系统{verdict_txt}，{phen}，明日重点看{watch}。"


# ═══════════════════════════════════════════════════════
#  总装
# ═══════════════════════════════════════════════════════
def build_titles(ctx):
    """按优先级生成 主标题 + 备选 + 摘要 + 类型。返回 dict。"""
    contradiction, surface = detect_contradiction(ctx)
    is_contradiction = bool(contradiction)

    decision_t = _decision_title(ctx)
    risk_t = _risk_title(ctx)
    mainline_t = _mainline_title(ctx)
    opp_t = _opportunity_title(ctx)

    if is_contradiction:
        main_title = contradiction
        title_type = "矛盾型"
    else:
        main_title = decision_t
        title_type = "决策型"

    # 备选：决策型 + 其它可用类型，去重，最多 3 条，且不等于主标题
    backups = []
    for t in [decision_t, risk_t, mainline_t, opp_t]:
        if not t or t == main_title:
            continue
        if t not in backups:
            backups.append(t)
        if len(backups) >= 3:
            break

    return {
        "main_title": main_title,
        "backup_titles": backups,
        "summary": _build_summary(ctx, contradiction=is_contradiction),
        "title_type": title_type,
        "surface_signal": surface,
        "report_date": ctx["trade_date"],
    }


def generate_wechat_meta(memo, decision, score):
    """从 memo + 安全裁决结果生成完整 meta。"""
    ctx = extract_context(memo, decision, score)
    return build_titles(ctx)


# ═══════════════════════════════════════════════════════
#  落地：写 json + 追加日志 + 打印
# ═══════════════════════════════════════════════════════
def emit_wechat_meta(memo):
    """守卫式入口：计算裁决→生成 meta→落盘+打印。任何异常都不应阻断日报。"""
    from os2_report import compute_weighted_score, resolve_decision

    score = compute_weighted_score(memo)
    decision = resolve_decision(memo, score)
    meta = generate_wechat_meta(memo, decision, score)

    out_dir = os.path.join(_ROOT, "output")
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, f"wechat_meta_{memo.trade_date}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # 留痕日志（供事后填打开率，闭环迭代）
    log_path = os.path.join(out_dir, "wechat_title_log.jsonl")
    log_row = {
        "date": memo.trade_date,
        "title_type": meta["title_type"],
        "main_title": meta["main_title"],
        "backup_titles": meta["backup_titles"],
        "open_rate": None,   # 用户从公众号后台手填
        "read_rate": None,
        "share_rate": None,
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_row, ensure_ascii=False) + "\n")

    print("─── 公众号标题引擎 v1.0 ───")
    print(f"[类型] {meta['title_type']}" + (f"  表象：{meta['surface_signal']}" if meta['surface_signal'] else ""))
    print(f"[主标题] {meta['main_title']}")
    for i, b in enumerate(meta["backup_titles"], 1):
        print(f"[备选{i}] {b}")
    print(f"[摘要] {meta['summary']}")
    print(f"[落盘] {json_path}")
    return meta


# ═══════════════════════════════════════════════════════
#  自检：用 mock 上下文复现 2026-08-14，验证与用户示例一致
# ═══════════════════════════════════════════════════════
def self_test():
    # 复现 8.14：综合 63 分、IC 偏多(YES)但最终裁决 NO、通信净流入、52 板块退潮
    ctx = {
        "trade_date": "2026-08-14",
        "final": "NO",
        "composite": 63,
        "position": "0%（空仓）",
        "ic_can_buy": "YES",
        "ic_level": "YES",
        "pf_passed": 4,
        "pf_total": 7,
        "market_state": "偏弱防守",
        "main_sector": "通信设备",
        "main_sector_stars": 4,
        "risk_biggest": "主线无持续性",
        "inflow_sectors": ["通信设备", "半导体"],
        "capital_one_liner": "",
        "external_up": False,
        "rise_ratio": 0.46,
        "retreat_count": 52,
        "south_net_yi": -13,
        "cross_asset_name": "黄金",
        "watch_count": 5,
    }
    meta = build_titles(ctx)
    print("════ 自检 · 2026-08-14 场景 ════")
    print(f"类型   : {meta['title_type']}")
    print(f"主标题 : {meta['main_title']}")
    for i, b in enumerate(meta["backup_titles"], 1):
        print(f"备选{i} : {b}")
    print(f"摘要   : {meta['summary']}")

    # 断言关键期望
    assert meta["title_type"] == "矛盾型", meta["title_type"]
    assert "通信设备资金回流，为什么系统仍裁定不交易" in meta["main_title"], meta["main_title"]
    assert any("维持空仓观望" in b for b in meta["backup_titles"]), meta["backup_titles"]
    assert any("52个板块退潮" in b for b in meta["backup_titles"]), meta["backup_titles"]
    assert "8月14日盘后更新" in meta["summary"], meta["summary"]
    assert "综合评分63分" in meta["summary"], meta["summary"]
    print("\n✅ 自检通过：复现 8.14 示例（主标题/备选/摘要 与预期一致）")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true", help="运行内置自检（无需 produce / 网络）")
    args = ap.parse_args()
    if args.selftest:
        self_test()
        sys.exit(0)
    # 实时运行：需要完整 brain 流水线（用户生产环境使用）
    try:
        from brain.cio_agent import produce
        memo = produce()
        emit_wechat_meta(memo)
    except Exception as e:  # 沙箱/无网络环境下退回自检，保证模块可验证
        print(f"[warn] 实时运行失败（{e}），退回自检模式：")
        self_test()
