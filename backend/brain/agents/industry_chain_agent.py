# -*- coding: utf-8 -*-
"""
L3.5 产业链推理 Agent —— Serenity 式「供应链瓶颈」研究（确定性，无 LLM 打分）

定位（用户架构决议）：
  - 这是 L3.5 研究层，不是决策层。它只做「研究 / 排序 / 推理」，不买卖。
  - 热点起点直接吃盘前纪要热榜（panqian_feed.hot_list_top）+ L4 资金主线（sector_mainline 净流入 Top）。
  - 对热点做产业链拆解（复用 narrative_engine.INDUSTRY_CHAIN），再用硬编码 A 股瓶颈映射
    CHAIN_BOTTLENECK 找「低供应商数 / 长验证 / 扩产难 / 认证严 / 纯度高」的瓶颈环节。
  - 输出：chain_map（板块→环节）、bottlenecks（按信号+资金验证打分排序）、
    candidates（靠近瓶颈的个股候选，带证据与数据缺口）、downgraded_themes（蹭热点降级）。
  - 诚实护栏：候选的「客户认证 / 产能」等若无数据源，显式标 data_gap，绝不编造。

数据来源（全部本地，确定性）：
  - output/panqian_feed.json  （盘前纪要热榜 + 叙事 feed）
  - output/sector_mainline.json（L4 资金主线，净流入 Top）
  - narrative_engine.INDUSTRY_CHAIN（~20 板块产业链逻辑）
  - CHAIN_BOTTLENECK（本文件内置：板块→瓶颈环节+受益子行业关键词）
"""
import os
import sys
import json

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from .base_agent import make_result
try:
    from narrative_engine import INDUSTRY_CHAIN
except Exception:  # noqa
    INDUSTRY_CHAIN = {}

OUTPUT = os.path.join(BASE, "output")


# ───────────────────────────────────────────────────────────
#  板块 → 瓶颈环节 + 受益子行业关键词（A 股适配，确定性映射）
#  受益人关键词同时含「子行业术语」与少量高辨识个股片段，用于与盘前热榜匹配。
#  缺映射的板块 → 标 data_gap（无结构化瓶颈映射），不编造。
# ───────────────────────────────────────────────────────────
CHAIN_BOTTLENECK = {
    "半导体": [
        {"segment": "半导体设备(光刻/刻蚀/薄膜沉积)", "reason": "低供应商数+长验证周期+扩产难，国产替代紧迫",
         "beneficiaries": ["设备", "光刻", "刻蚀", "薄膜", "中微", "北方华创", "拓荆", "盛美", "华海清科", "芯源"]},
        {"segment": "先进封装(CoWoS/2.5D/CPO)", "reason": "AI 算力硬瓶颈，产能稀缺、良率爬坡慢",
         "beneficiaries": ["封测", "先进封装", "长电", "通富", "盛合晶微", "CoWoS"]},
        {"segment": "半导体材料(光刻胶/电子气体/靶材/抛光液)", "reason": "纯度要求极高+客户认证严格",
         "beneficiaries": ["材料", "光刻胶", "电子气体", "靶材", "彤程", "华特", "雅克", "鼎龙", "安集"]},
        {"segment": "存储(DRAM/NAND/HBM)", "reason": "周期反转+AI 拉动 HBM 紧缺",
         "beneficiaries": ["存储", "佰维", "兆易", "北京君正", "长江存储", "长鑫"]},
    ],
    "CPO": [
        {"segment": "光模块/光芯片(硅光/1.6T)", "reason": "带宽容量的硬瓶颈，硅光良率爬坡慢",
         "beneficiaries": ["光模块", "光芯片", "硅光", "中际旭创", "新易盛", "天孚", "源杰", "光迅"]},
    ],
    "通信设备": [
        {"segment": "高速交换机/CPO 交换机芯片", "reason": "AI 集群组网瓶颈，ASIC 稀缺",
         "beneficiaries": ["交换机", "紫光", "锐捷", "盛科", "中兴"]},
        {"segment": "光模块", "reason": "同 CPO 算力前置",
         "beneficiaries": ["光模块", "中际旭创", "新易盛", "华工", "光迅"]},
    ],
    "元件": [
        {"segment": "PCB/覆铜板(高速 CCL)", "reason": "AI 服务器用量倍增+产能紧张",
         "beneficiaries": ["PCB", "覆铜板", "CCL", "沪电", "胜宏", "生益", "深南", "华正"]},
        {"segment": "被动元件(MLCC/电感)", "reason": "量价齐升，高端依赖进口替代",
         "beneficiaries": ["MLCC", "电感", "风华", "三环", "顺络", "达利"]},
    ],
    "消费电子": [
        {"segment": "AI 手机供应链(射频/光学/结构件/电池)", "reason": "换机周期+AI 增量价值量",
         "beneficiaries": ["AI手机", "射频", "光学", "结构件", "信维", "光弘", "蓝思", "领益", "东山"]},
        {"segment": "折叠/铰链/转轴", "reason": "创新增量部件",
         "beneficiaries": ["铰链", "转轴", "精研", "科森"]},
    ],
    "机器人": [
        {"segment": "减速器(谐波/RV)", "reason": "精度壁垒+产能稀缺，人形用量大",
         "beneficiaries": ["减速器", "谐波", "RV", "绿的", "双环", "中大力德", "丰立"]},
        {"segment": "行星滚柱丝杠", "reason": "人形机器人线性执行器核心，工艺难",
         "beneficiaries": ["丝杠", "恒立", "贝斯特", "秦川", "北特"]},
        {"segment": "传感器/灵巧手/执行器", "reason": "感知与执行瓶颈",
         "beneficiaries": ["传感器", "灵巧手", "执行器", "柯力", "鸣志", "昊志"]},
    ],
    "医药": [
        {"segment": "创新药(出海 BD/ADC)", "reason": "全球竞争力+医保/商保倾斜，估值底背离",
         "beneficiaries": ["创新药", "ADC", "百济", "信达", "恒瑞", "科伦", "君实", "荣昌"]},
        {"segment": "CXO(研发外包)", "reason": "创新药研发弹性外溢",
         "beneficiaries": ["CXO", "药明", "康龙", "泰格", "昭衍", "美迪西"]},
        {"segment": "实验动物(食蟹猴)", "reason": "供给紧缺，价格突破 20 万",
         "beneficiaries": ["实验猴", "昭衍", "药康", "南模"]},
    ],
    "电力设备": [
        {"segment": "变压器/特高压设备", "reason": "电网投资瓶颈，海外订单外溢",
         "beneficiaries": ["变压器", "特高压", "特变", "金盘", "思源", "许继", "平高"]},
        {"segment": "储能(PCS/电池系统)", "reason": "新能源消纳刚需",
         "beneficiaries": ["储能", "PCS", "阳光", "宁德", "亿纬"]},
    ],
    "汽车": [
        {"segment": "智能驾驶(域控/激光雷达/线控)", "reason": "渗透率提升，价值量跃升",
         "beneficiaries": ["智驾", "域控", "激光雷达", "德赛", "伯特利", "禾赛", "华阳"]},
        {"segment": "零部件出海", "reason": "整车出海带动",
         "beneficiaries": ["零部件", "拓普", "旭升", "爱柯迪", "新泉"]},
    ],
    "工业金属": [
        {"segment": "铜(电解铜/铜箔)", "reason": "供给扰动+电网/AI 数据中心用铜",
         "beneficiaries": ["铜", "铜箔", "紫金", "洛阳钼业", "西部矿业", "铜陵"]},
    ],
    "有色金属": [
        {"segment": "铜/锂/钴镍", "reason": "全球供需+美元周期共同定价",
         "beneficiaries": ["铜", "锂", "天齐", "赣锋", "华友", "中矿"]},
    ],
    "计算机": [
        {"segment": "AI 应用/信创软件", "reason": "大模型落地+国产化",
         "beneficiaries": ["AI应用", "信创", "软件", "金山", "用友", "寒武纪", "海光"]},
    ],
    "人工智能": [
        {"segment": "算力芯片/大模型", "reason": "AI 主线总括，算力为基",
         "beneficiaries": ["算力", "芯片", "大模型", "寒武纪", "海光", "昇腾"]},
    ],
}


def _norm_name(s):
    if not s:
        return ""
    return str(s).replace("Ａ", "A").replace("Ｂ", "B").strip()


def _load_sector_mainline(top=10):
    """读 L4 资金主线（净流入 Top），返回 [{sector, net}]。
    兼容 sector_mainline.json 的 top10_net_inflow / sectors / main_lines 多种结构。"""
    try:
        p = os.path.join(OUTPUT, "sector_mainline.json")
        if not os.path.exists(p):
            return []
        d = json.load(open(p, encoding="utf-8"))
        src = (d.get("top10_net_inflow") or d.get("main_lines")
               or d.get("sectors") or [])
        if not isinstance(src, list):
            return []
        out = []
        for it in src:
            if not isinstance(it, dict):
                continue
            sec = it.get("sector") or it.get("name")
            if not sec:
                continue
            net = (it.get("net_now") or it.get("net_inflow") or it.get("net_today")
                   or it.get("net_5d") or 0)
            out.append({"sector": _norm_name(sec), "net": net})
        out.sort(key=lambda x: (x["net"] or 0), reverse=True)
        return out[:top]
    except Exception:  # noqa
        return []


def _load_panqian():
    """读盘前纪要 feed。返回 dict 或 None。"""
    try:
        p = os.path.join(OUTPUT, "panqian_feed.json")
        if not os.path.exists(p):
            return None
        return json.load(open(p, encoding="utf-8"))
    except Exception:  # noqa
        return None


def _hot_stocks(pq):
    """汇总盘前纪要热榜 + 叙事 related_stocks，返回去重个股名列表。
    注意：panqian_feed.json 的 hot_list_top 位于 cro_feed 之下。"""
    stocks = []
    if not pq:
        return stocks
    hl = (pq.get("hot_list_top")
          or (pq.get("cro_feed") or {}).get("hot_list_top") or [])
    for hl0 in hl:
        for s in (hl0.get("stock") or []):
            stocks.append(_norm_name(s))
    for nf in (pq.get("narrative_feed") or []):
        for s in (nf.get("related_stocks") or []):
            stocks.append(_norm_name(s))
    # 去重保序
    seen, uniq = set(), []
    for s in stocks:
        if s and s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def _theme_for_text(text):
    """用 INDUSTRY_CHAIN 关键词把一段文字归到某板块（返回 key 或 None）。"""
    if not text:
        return None
    t = str(text)
    best, best_n = None, 0
    for key, info in INDUSTRY_CHAIN.items():
        n = sum(1 for kw in info.get("keywords", []) if kw and kw in t)
        if n > best_n:
            best, best_n = key, n
    return best if best_n > 0 else None


def run(ctx=None):
    """L3.5 产业链推理。ctx 可选（用于读取 L4 主线）。"""
    pq = _load_panqian()
    sm = _load_sector_mainline(top=10)
    sm_sectors = {_norm_name(s["sector"]) for s in sm}
    hot = _hot_stocks(pq)

    gaps = []
    if pq is None:
        gaps.append("盘前纪要 feed 未生成（panqian_feed.json 缺失）→ 热点起点仅用 L4 资金主线")
    if not sm:
        gaps.append("sector_mainline.json 缺失 → 资金验证不可用")

    # ── 1. 汇总热点主题（板块集合）──
    # 来源 A：L4 资金主线板块
    themes = {}  # sector_key -> {"sources": set(), "sector_name": str}
    for s in sm:
        sec = _norm_name(s["sector"])
        # 在 INDUSTRY_CHAIN 里按板块名命中
        key = sec if sec in INDUSTRY_CHAIN else _theme_for_text(sec)
        if key:
            themes.setdefault(key, {"sources": set(), "sector_name": sec})
            themes[key]["sources"].add("L4资金主线")

    # 来源 B：盘前纪要热榜个股 + 叙事 → 关键词归板块
    if pq:
        for s in hot:
            key = _theme_for_text(s)
            if key:
                th = themes.setdefault(key, {"sources": set(), "sector_name": key})
                th["sources"].add("盘前热榜")
        for nf in (pq.get("narrative_feed") or []):
            txt = nf.get("text") or nf.get("name") or nf.get("theme") or ""
            key = _theme_for_text(txt)
            if key:
                th = themes.setdefault(key, {"sources": set(), "sector_name": key})
                th["sources"].add("盘前叙事")

    # ── 2. 对每个热点板块做产业链拆解 + 瓶颈打分 ──
    bottlenecks = []
    chain_map = {}
    for key, info in themes.items():
        chain = CHAIN_BOTTLENECK.get(key)
        if not chain:
            gaps.append(f"{key}：无结构化瓶颈映射（数据缺口）")
            # 仍记录产业链逻辑（若有）
            ic = INDUSTRY_CHAIN.get(key, {})
            chain_map[key] = [ic.get("logic", "（无内置产业链逻辑）")[:60]]
            continue
        chain_map[key] = [b["segment"] for b in chain]
        for b in chain:
            # 信号强度：几个独立热点源指向该板块
            src_n = len(info["sources"])
            # 资金验证：板块在 L4 净流入 Top，或热榜个股命中共益人关键词
            fund_ok = key in sm_sectors
            matched_stocks = [s for s in hot if any(kw and kw in s for kw in b["beneficiaries"])]
            if matched_stocks:
                fund_ok = True
            # 打分（确定性，0-100）
            score = 40 + 20 * min(src_n, 3)
            if fund_ok:
                score += 20
            if matched_stocks:
                score += 10
            score = min(100, score)
            bottlenecks.append({
                "sector": key,
                "sector_name": info["sector_name"],
                "segment": b["segment"],
                "reason": b["reason"],
                "score": score,
                "sources": sorted(info["sources"]),
                "fund_validated": fund_ok,
                "candidates": matched_stocks,
                "beneficiary_hints": b["beneficiaries"],
                "data_gaps": ["客户认证:未接入数据源", "产能利用率:未接入数据源"],
            })

    # ── 3. 候选汇总（去重，按最快瓶颈 score 排序）──
    cand_map = {}
    for bn in bottlenecks:
        for st in bn["candidates"]:
            c = cand_map.setdefault(st, {"name": st, "bottlenecks": [], "evidence": set()})
            c["bottlenecks"].append(bn["segment"])
            c["evidence"].add("盘前热榜")
            if bn["fund_validated"]:
                c["evidence"].add("资金验证")
    candidates = []
    for nm, c in cand_map.items():
        candidates.append({
            "name": nm,
            "bottlenecks": c["bottlenecks"],
            "evidence": sorted(c["evidence"]),
            "data_gaps": ["客户认证:未接入数据源", "产能/订单:未接入数据源"],
        })
    candidates.sort(key=lambda x: len(x["bottlenecks"]), reverse=True)

    # ── 4. 蹭热点降级：盘前热榜提及、但未匹配任何结构化瓶颈、且无资金验证支撑的个股 ──
    # 注意：用「候选集合」判定支撑，而非对个股名做行业关键词匹配——个股名（如昭衍新药）
    # 几乎不会命中 INDUSTRY_CHAIN 的行业关键词，否则会把已匹配瓶颈的个股误判降级。
    cand_stocks = {c["name"] for c in candidates}
    downgraded = []
    for s in hot:
        if s in cand_stocks:
            continue  # 已匹配产业链瓶颈，保留
        # 次级豁免：个股名命中某「获 L4 资金验证」板块的关键词
        key = _theme_for_text(s)
        if key and key in sm_sectors:
            continue  # 所属板块获资金验证
        downgraded.append({
            "stock": s,
            "reason": "盘前热榜提及，但未匹配结构化产业链瓶颈、且无 L4 资金验证支撑，疑似蹭热点，需人工/基本面层复核",
        })
    if hot and not cand_stocks:
        gaps.append("beneficiary 关键词库为人工内置、覆盖有限（如部分真实 CXO/封测龙头未列入）→ 降级仅代表'未自动匹配'，需基本面层复核")

    # ── 5. 方向信号（研究层，非硬否决）──
    validated = [b for b in bottlenecks if b["fund_validated"]]
    if len(validated) >= 2:
        stage = "neutral_bullish"
    elif bottlenecks:
        stage = "neutral"
    else:
        stage = "neutral"
    conf = 72 if (pq and sm) else 50

    narrative = (f"产业链推理：识别 {len(bottlenecks)} 个瓶颈环节（{len(validated)} 个获资金验证）/ "
                 f"{len(candidates)} 个候选 / {len(downgraded)} 个蹭热点降级")
    risk = "蹭热点降级主题需等资金或产业链证据再介入。" if downgraded else ""

    raw = {
        "hotspot_themes": {k: sorted(v["sources"]) for k, v in themes.items()},
        "chain_map": chain_map,
        "bottlenecks": sorted(bottlenecks, key=lambda x: x["score"], reverse=True),
        "candidates": candidates,
        "downgraded_themes": downgraded,
        "gaps": gaps,
    }
    res = make_result(
        "L3_5", "产业链推理", stage, narrative, raw=raw,
        signal={
            "direction": stage,
            "bottlenecks_count": len(bottlenecks),
            "validated_count": len(validated),
            "top_bottlenecks": [b["segment"] for b in sorted(bottlenecks, key=lambda x: x["score"], reverse=True)[:5]],
            "candidates_count": len(candidates),
            "downgraded_count": len(downgraded),
        },
        confidence=conf, risk_note=risk,
        upstream=f"接 L4(主线 {len(sm)}) + 盘前纪要热榜({len(hot)} 股)",
        gaps=gaps,
    )
    if ctx is not None:
        try:
            ctx.put("L3_5", res.to_dict())
        except Exception:  # noqa
            pass

    # 持久化（供 CIO / 前端复用）
    try:
        rep = {
            "generated_at": (ctx.generated_at if ctx else ""),
            "trade_date": (ctx.trade_date if ctx else ""),
            "layer": "L3_5",
            "stage": stage,
            "narrative": narrative,
            "raw": raw,
        }
        with open(os.path.join(OUTPUT, "industry_chain_report.json"), "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2, default=str)
    except Exception:  # noqa
        pass
    return res
