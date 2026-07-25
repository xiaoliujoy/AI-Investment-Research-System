# -*- coding: utf-8 -*-
"""
板块级基本面验证（验证方向 · 第③维：业绩 vs 估值）
=================================================
回答用户的核心问题：「现在的上涨，到底是业绩推动的，还是单纯估值被炒高了？」

设计边界（用户明确，2026-07-11/12）：
  - 只做到【板块/产业级】聚合，绝不输出个股财务/估值明细（个股硬过滤归用户人工）。
  - 不动 个股成交额 / ma20 / ma60（用户禁用字段）。
  - 验证方向 = 资金(L4/L5) + 基本面(本模块) + 情绪(情绪验证)。

数据源（沙箱白名单实测可达）：
  - 业绩增速：akshare stock_yjbb_em(date=最新报告期) 一次性返回全市场
    （营业总收入-同比增长 / 净利润-同比增长 / 净资产收益率 / 销售毛利率）。
  - 估值(PE)：腾讯 gtimg qt.gtimg.cn/q= 批量（f[39]=市盈率-TTM）。
  - 板块→成分：复用 decision_tree._resolve_main_members（同花顺名→东财成分股）。

输出：layer dict，供 decision_tree 渲染「基本面验证（业绩 vs 估值）」卡片 + playbook 推理链。
"""
import os
import sys
import json
import statistics
import urllib.request

_FIN_CACHE = {}  # 进程内缓存：code -> {rev_yoy, np_yoy, roe, gross, industry}


def _clean_proxy():
    for k in ("http_proxy", "https_proxy", "all_proxy", "ALL_PROXY",
              "HTTP_PROXY", "HTTPS_PROXY"):
        os.environ.pop(k, None)


def get_financials(period="20260331"):
    """一次性拉全市场业绩报表，返回 {code: {...}}。进程内缓存。"""
    global _FIN_CACHE
    if _FIN_CACHE:
        return _FIN_CACHE
    _clean_proxy()
    import akshare as ak
    df = ak.stock_yjbb_em(date=period)
    out = {}
    for _, r in df.iterrows():
        code = str(r.get("股票代码", "")).strip()
        if not code:
            continue
        def _f(x):
            try:
                v = float(x)
                if v != v:  # NaN
                    return None
                return v
            except Exception:
                return None
        out[code] = {
            "rev_yoy": _f(r.get("营业总收入-同比增长")),
            "np_yoy": _f(r.get("净利润-同比增长")),
            "roe": _f(r.get("净资产收益率")),
            "gross": _f(r.get("销售毛利率")),
            "industry": str(r.get("所处行业", "") or ""),
        }
    _FIN_CACHE = out
    return out


def _gtimg_prefix(code):
    if code.startswith("6") or code.startswith("9"):
        return "sh" + code
    if code.startswith("8") or code.startswith("4"):
        return "bj" + code
    return "sz" + code


def get_pe(codes):
    """腾讯 gtimg 批量拉市盈率（f[39]）。返回 {code: pe_float|None}。"""
    _clean_proxy()
    res = {}
    batch = [c for c in codes if c]
    for i in range(0, len(batch), 50):
        grp = batch[i:i + 50]
        q = ",".join(_gtimg_prefix(c) for c in grp)
        url = f"https://qt.gtimg.cn/q={q}"
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0",
                              "Referer": "https://gu.qq.com/"})
            raw = urllib.request.urlopen(req, timeout=20).read().decode("gbk", "ignore")
            for line in raw.strip().split(";"):
                line = line.strip()
                if not line or "=" not in line:
                    continue
                code_part, payload = line.split("=", 1)
                code = code_part.replace("v_", "").lstrip("shszbj")
                payload = payload.strip('"')
                f = payload.split("~")
                pe = None
                if len(f) > 39:
                    try:
                        pe = float(f[39])
                    except Exception:
                        pe = None
                if pe is not None and pe > 0:
                    res[code] = pe
        except Exception:
            # 单批失败不影响其他批
            continue
    return res


def _median(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return round(statistics.median(vals), 2)


def _verdict(np_yoy, pe):
    if np_yoy is None:
        return "数据不足", "缺业绩增速，无法判定业绩/估值贡献。"
    if np_yoy >= 10:
        if pe is None or pe <= 50:
            return "业绩驱动", "净利润双位数增长且估值未过热，上涨有业绩支撑。"
        return "业绩好·估值偏高", "业绩增长强，但板块 PE 已偏高，注意追高风险。"
    if np_yoy < 0:
        if pe is not None and pe >= 50:
            return "估值偏高·业绩疲软", "业绩下滑而估值高企，警惕纯炒估值、易回撤。"
        return "业绩承压", "净利润负增，低位观察，等业绩拐点。"
    return "混合/中性", "业绩温和，估值中性，需结合资金/情绪综合看。"


def _l35_evidence(l35_raw):
    """从 L3.5 的 raw 抽取「证据 / 诚实护栏」摘要（与 base_agent.l35_evidence 同源，本地内联避免重导入 brain 包）。"""
    l35_raw = l35_raw or {}
    bottlenecks = l35_raw.get("bottlenecks") or []
    candidates = l35_raw.get("candidates") or []
    downgraded = l35_raw.get("downgraded_themes") or []
    validated_sectors = set()
    validated_names = set()
    name_to_segments = {}
    top_segments = []
    for b in sorted(bottlenecks, key=lambda x: x.get("score", 0), reverse=True):
        if not b.get("fund_validated"):
            continue
        validated_sectors.add(b.get("sector"))
        nm = b.get("sector_name") or b.get("sector")
        validated_names.add(nm)
        seg = f"{nm}·{b.get('segment')}"
        name_to_segments.setdefault(nm, []).append(seg)
        top_segments.append(seg)
    candidate_gaps = {}
    for c in candidates:
        if c.get("data_gaps"):
            candidate_gaps[c.get("name")] = c.get("data_gaps")
    return {
        "validated_sectors": validated_sectors,
        "validated_names": validated_names,
        "name_to_segments": name_to_segments,
        "top_segments": top_segments[:6],
        "candidate_gaps": candidate_gaps,
        "downgraded_stocks": [d.get("stock") for d in downgraded],
        "downgraded_count": len(downgraded),
    }


def _l35_sector_validated(sec, ev):
    """容忍板块命名差异（同 base_agent.l35_sector_validated，优先用真实板块名 sector_name）。"""
    if not sec:
        return False
    sec = str(sec)
    for nm in (ev.get("validated_names") or set()):
        nm = str(nm)
        if nm and (nm == sec or nm in sec or sec in nm):
            return True
    for k in (ev.get("validated_sectors") or set()):
        k = str(k)
        if k and (k in sec or sec in k):
            return True
    return False


def layer_fundamental(focus_sectors, period="20260331", l35=None):
    """对 L4 focus 板块做板块级业绩/估值验证。返回 layer dict。

    l35（Phase 3-1）：传入 L3.5 产业链推理 raw，用于
      - 对「获产业链瓶颈验证」的板块标注基本面支撑可信度↑；
      - 继承 L3.5 诚实护栏：候选个股数据缺口（客户认证/产能未接入）绝不在基本面结论里编造；
      - 对 L3.5 已降级的蹭热点个股，明确「fundamental 不对其下结论，需复核」。
    """
    import decision_tree as dt
    ev = _l35_evidence(l35) if l35 else None
    if not focus_sectors:
        return {"status": "已接入(无主线)", "period": period,
                "sectors": [], "read": "暂无验证主线，跳过基本面验证。", "gaps": []}
    try:
        fin = get_financials(period)
    except Exception as e:
        return {"status": "待接入", "period": period, "sectors": [],
                "read": "业绩报表拉取失败，基本面验证跳过。",
                "gaps": [f"业绩报表: {repr(e)[:80]}"]}
    # 解析成分股
    all_codes = set()
    sector2codes = {}
    for sec in focus_sectors:
        mc, _ = dt._resolve_main_members([sec])
        codes = list(mc)
        sector2codes[sec] = codes
        all_codes.update(codes)
    # 批量拉 PE
    try:
        pe_map = get_pe(list(all_codes))
    except Exception:
        pe_map = {}
    sectors = []
    gaps = []
    driven = 0
    overvalued = 0
    for sec in focus_sectors:
        codes = sector2codes.get(sec, [])
        if not codes:
            gaps.append(f"{sec}：未能解析成分股（跨表缺失）")
            continue
        rev = [fin[c]["rev_yoy"] for c in codes if c in fin and fin[c]["rev_yoy"] is not None]
        npv = [fin[c]["np_yoy"] for c in codes if c in fin and fin[c]["np_yoy"] is not None]
        pes = [pe_map[c] for c in codes if c in pe_map]
        rev_med = _median(rev)
        np_med = _median(npv)
        pe_med = _median(pes)
        verdict, note = _verdict(np_med, pe_med)
        if verdict == "业绩驱动":
            driven += 1
        elif "估值偏高" in verdict:
            overvalued += 1
        sectors.append({
            "sector": sec,
            "n_stocks": len(codes),
            "rev_yoy_med": rev_med,
            "np_yoy_med": np_med,
            "pe_med": pe_med,
            "verdict": verdict,
            "note": note,
            "l35_note": (f"L3.5 产业链瓶颈已获资金验证，基本面支撑可信度较高"
                         if ev and _l35_sector_validated(sec, ev) else ""),
        })
    # 综合研判
    if sectors:
        if overvalued and not driven:
            overall = (f"验证主线中 {overvalued} 个板块呈「估值偏高」特征，"
                       f"上涨偏资金/情绪驱动、业绩未跟上，谨慎追高。")
        elif driven and not overvalued:
            overall = (f"验证主线中 {driven} 个板块为「业绩驱动」，"
                       f"上涨有基本面支撑，方向与验证共振度高。")
        elif driven and overvalued:
            overall = (f"验证主线分化：{driven} 个业绩驱动、{overvalued} 个估值偏高，"
                       f"需按板块区别对待，警惕高估值板块赶顶。")
        else:
            overall = "验证主线基本面中性，方向主要靠资金+情绪确认。"
    else:
        overall = "未解析到可验证板块。"
    read = (f"板块级基本面验证（业绩 vs 估值）：{overall}\n"
            f"（业绩增速取自 {period} 报告期；PE 为板块成分股中位市盈率，"
            f"绝对高低仅作粗略参考，深度估值分位请用 Macrotrends/Koyfin 人工核对。）")
    # ── L3.5 诚实护栏：继承数据缺口标注，绝不编造未接入数据 ──
    extra_gaps = []
    if ev:
        if ev["downgraded_count"]:
            extra_gaps.append(
                f"诚实护栏: L3.5 已将 {ev['downgraded_count']} 只蹭热点个股降级，"
                f"fundamental 不对其下结论（需产业链/人工复核）")
        if ev["candidate_gaps"]:
            allg = set()
            for g in ev["candidate_gaps"].values():
                allg.update(g)
            extra_gaps.append(
                "诚实护栏: 候选个股的" + "、".join(sorted(allg)) +
                " 等数据缺口未接入，结论中相关字段以'未知'呈现，勿编造")
    gaps = gaps + extra_gaps
    return {"status": "已接入(板块级)", "period": period,
            "sectors": sectors, "read": read,
            "l35_evidence": ev, "gaps": gaps}


if __name__ == "__main__":
    import decision_tree as dt
    tree = json.load(open(os.path.join(dt.OUT, "decision_tree.json"), encoding="utf-8"))
    l4 = tree["layers"].get("L4_consensus", {})
    focus = [r["sector"] for r in (l4.get("main_lines") or [])
             if r.get("stage") != "退潮"][:5]
    out = layer_fundamental(focus)
    print("== focus ==", focus)
    print("== read ==", out["read"])
    for s in out["sectors"]:
        print(f"  {s['sector']}: 营收同比={s['rev_yoy_med']} 净利同比={s['np_yoy_med']} "
              f"PE中位={s['pe_med']} -> {s['verdict']}")
    print("== gaps ==", out["gaps"])
