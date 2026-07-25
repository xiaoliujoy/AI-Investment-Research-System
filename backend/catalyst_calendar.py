# -*- coding: utf-8 -*-
"""
Catalyst Calendar (事件驱动日历)
================================
基于规则推算中美主要经济数据发布日，为叙事引擎提供
"证伪窗口"的具体日期。

设计原则：
  - 规则驱动：经济数据发布日有固定规律，不需要爬虫
  - 中美双轨：中国(CPI/PPI/PMI/M2/LPR/GDP) + 美国(NFP/CPI/FOMC/PMI/Jobless)
  - 零网络请求：纯日历推算，不依赖外部 API
  - 重要性分级：high/medium/low

发布日规律（实测验证）：
  中国 CPI/PPI:  每月9-10日（遇周末顺延至周一）
  中国 PMI:      每月最后一天（官方制造业PMI）
  中国 M2/社融:  每月10-15日之间
  中国 LPR:      每月20日（遇周末顺延）
  中国 GDP:      季度，1/4/7/10月的15-18日
  美国 NFP:      每月第一个周五
  美国 CPI:      通常每月10-13日（第二个周三/周四前后）
  美国 ISM PMI:  每月第一个工作日
  美国 FOMC:     每年8次，日期预先公布
  美国 Jobless:  每周四
"""
from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass, field
from typing import Optional

# ═══════════════════════════════════════════════════════
#  2026 年 FOMC 会议日历（美联储官方公布，每年1月更新）
# ═══════════════════════════════════════════════════════
FOMC_2026 = [
    dt.date(2026, 1, 28),   # Jan 27-28
    dt.date(2026, 3, 18),   # Mar 17-18
    dt.date(2026, 4, 30),   # Apr 29-30
    dt.date(2026, 6, 18),   # Jun 17-18
    dt.date(2026, 7, 30),   # Jul 29-30
    dt.date(2026, 9, 17),   # Sep 16-17
    dt.date(2026, 11, 5),   # Nov 4-5
    dt.date(2026, 12, 17),  # Dec 16-17
]

FOMC_2025 = [
    dt.date(2025, 1, 29),
    dt.date(2025, 3, 19),
    dt.date(2025, 4, 30),
    dt.date(2025, 6, 18),
    dt.date(2025, 7, 30),
    dt.date(2025, 9, 17),
    dt.date(2025, 10, 29),
    dt.date(2025, 12, 10),
]

ALL_FOMC = sorted(FOMC_2025 + FOMC_2026)


@dataclass
class Catalyst:
    """单个事件催化剂。"""
    name: str                    # "美国CPI" / "中国PMI" 等
    name_en: str                 # "US CPI" / "China PMI"
    country: str                 # "US" / "CN"
    catalyst_type: str           # cpi / pmi / nfp / fomc / lpr / m2 / gdp / jobless
    expected_date: dt.date       # 预计发布日
    days_until: int              # 距今天数（负=已过）
    importance: str              # high / medium / low
    description: str             # "美国消费者物价指数" 等
    watch_fields: list = field(default_factory=list)  # 关注字段 ["CPI同比", "核心CPI"]


def _next_business_day(d: dt.date) -> dt.date:
    """如果 d 是周末，顺延到下一个周一。"""
    while d.weekday() >= 5:  # 5=Sat, 6=Sun
        d += dt.timedelta(days=1)
    return d


def _first_friday_of_month(year: int, month: int) -> dt.date:
    """某月第一个周五。"""
    first = dt.date(year, month, 1)
    # 0=Mon ... 4=Fri
    days_until_fri = (4 - first.weekday()) % 7
    return first + dt.timedelta(days=days_until_fri)


def _first_business_day_of_month(year: int, month: int) -> dt.date:
    """某月第一个工作日。"""
    d = dt.date(year, month, 1)
    return _next_business_day(d)


def _nth_weekday_of_month(year: int, month: int, target_weekday: int, n: int) -> dt.date:
    """某月第 n 个 target_weekday（0=Mon ... 6=Sun）。"""
    first = dt.date(year, month, 1)
    days_until = (target_weekday - first.weekday()) % 7
    return first + dt.timedelta(days=days_until + 7 * (n - 1))


# ═══════════════════════════════════════════════════════
#  推算单个 catalyst 的发布日
# ═══════════════════════════════════════════════════════

def _cn_cpi_date(year: int, month: int) -> dt.date:
    """中国CPI：每月9日（遇周末顺延）。"""
    return _next_business_day(dt.date(year, month, 9))


def _cn_pmi_date(year: int, month: int) -> dt.date:
    """中国官方制造业PMI：上月数据的发布日=当月最后一天。"""
    # PMI 数据是上月的，发布在当月最后一天
    # 例如 7月发布的是 6月的数据
    if month == 12:
        return dt.date(year, month, 31)
    last_day = calendar.monthrange(year, month)[1]
    return _next_business_day(dt.date(year, month, last_day))


def _cn_m2_date(year: int, month: int) -> dt.date:
    """中国M2/社融：每月10-15日之间，取12日作为估计值。"""
    return _next_business_day(dt.date(year, month, 12))


def _cn_lpr_date(year: int, month: int) -> dt.date:
    """LPR：每月20日（遇周末顺延）。"""
    return _next_business_day(dt.date(year, month, 20))


def _cn_gdp_date(year: int, quarter: int) -> dt.date:
    """GDP：季度数据，1/4/7/10月的17日左右。"""
    month_map = {1: 1, 2: 4, 3: 7, 4: 10}
    m = month_map.get(quarter, 1)
    return _next_business_day(dt.date(year, m, 17))


def _us_nfp_date(year: int, month: int) -> dt.date:
    """美国非农就业：每月第一个周五。"""
    return _first_friday_of_month(year, month)


def _us_cpi_date(year: int, month: int) -> dt.date:
    """美国CPI：通常每月10-13日，取第二个周三作为估计值。"""
    # 第二个周三
    return _nth_weekday_of_month(year, month, 2, 2)


def _us_ism_pmi_date(year: int, month: int) -> dt.date:
    """美国ISM制造业PMI：每月第一个工作日。"""
    return _first_business_day_of_month(year, month)


# ═══════════════════════════════════════════════════════
#  生成未来 N 天内的所有 catalyst
# ═══════════════════════════════════════════════════════

def get_upcoming_catalysts(reference_date: Optional[dt.date] = None, days_ahead: int = 14) -> list[dict]:
    """
    获取未来 days_ahead 天内的所有经济数据发布日。

    Parameters
    ----------
    reference_date : date, optional
        参考日期（默认今天）
    days_ahead : int
        向前看多少天

    Returns
    -------
    list[dict]
        按日期排序的 catalyst 列表
    """
    if reference_date is None:
        reference_date = dt.date.today()

    end_date = reference_date + dt.timedelta(days=days_ahead)
    results = []

    def _add(name, name_en, country, ctype, date_obj, importance, desc, fields):
        """如果 date_obj 在窗口内，添加到 results。"""
        if date_obj < reference_date - dt.timedelta(days=1):
            return
        if date_obj > end_date + dt.timedelta(days=35):
            return
        days_until = (date_obj - reference_date).days
        results.append({
            "name": name,
            "name_en": name_en,
            "country": country,
            "catalyst_type": ctype,
            "expected_date": date_obj.isoformat(),
            "days_until": days_until,
            "importance": importance,
            "description": desc,
            "watch_fields": fields,
        })

    # 扫当月 + 下月（足够覆盖 14 天窗口）
    for m_offset in range(0, 3):
        y = reference_date.year
        mo = reference_date.month + m_offset
        while mo > 12:
            mo -= 12
            y += 1

        # ── 中国 catalysts ──
        _add("中国CPI", "CN CPI", "CN", "cpi",
             _cn_cpi_date(y, mo), "high",
             "中国消费者物价指数", ["CPI同比", "CPI环比"])

        _add("中国PPI", "CN PPI", "CN", "ppi",
             _cn_cpi_date(y, mo), "medium",
             "中国工业生产者出厂价格指数", ["PPI同比"])

        _add("中国PMI", "CN PMI", "CN", "pmi",
             _cn_pmi_date(y, mo), "high",
             "中国官方制造业PMI", ["制造业PMI", "非制造业PMI"])

        _add("中国M2/社融", "CN M2/Social Financing", "CN", "m2",
             _cn_m2_date(y, mo), "high",
             "中国货币供应量与社会融资规模", ["M2同比", "社融增量", "新增人民币贷款"])

        _add("中国LPR", "CN LPR", "CN", "lpr",
             _cn_lpr_date(y, mo), "high",
             "贷款市场报价利率", ["1年期LPR", "5年期LPR"])

        # GDP（季度）
        for q in range(1, 5):
            _add("中国GDP", "CN GDP", "CN", "gdp",
                 _cn_gdp_date(y, q), "high",
                 "中国季度GDP", ["GDP同比", "季度环比"])

        # ── 美国 catalysts ──
        _add("美国非农", "US NFP", "US", "nfp",
             _us_nfp_date(y, mo), "high",
             "美国非农就业报告", ["非农就业人数", "失业率", "平均时薪"])

        _add("美国CPI", "US CPI", "US", "cpi",
             _us_cpi_date(y, mo), "high",
             "美国消费者物价指数", ["CPI同比", "核心CPI同比"])

        _add("美国ISM PMI", "US ISM PMI", "US", "pmi",
             _us_ism_pmi_date(y, mo), "high",
             "美国ISM制造业PMI", ["制造业PMI", "新订单指数"])

    # ── 每周初请失业金（周四） ──
    d = reference_date
    while d <= end_date:
        if d.weekday() == 3:  # Thursday
            _add("美国初请失业金", "US Jobless Claims", "US", "jobless",
                 d, "medium",
                 "美国当周初请失业金人数", ["初请失业金人数", "续请失业金人数"])
        d += dt.timedelta(days=1)

    # ── FOMC 会议 ──
    for fomc_date in ALL_FOMC:
        _add("FOMC利率决议", "FOMC Rate Decision", "US", "fomc",
             fomc_date, "high",
             "美联储联邦公开市场委员会利率决议",
             ["联邦基金利率目标区间", "声明措辞变化", "点阵图(如有)"])

    # 去重 + 按日期排序 + 过滤窗口
    seen = set()
    unique = []
    for c in results:
        key = (c["name"], c["expected_date"])
        if key not in seen:
            seen.add(key)
            unique.append(c)

    filtered = [c for c in unique if -1 <= c["days_until"] <= days_ahead]
    filtered.sort(key=lambda x: (x["expected_date"], x["importance"]))
    return filtered


def _check_and_add(results, check_date, name, name_en, country, ctype,
                   expected_date, importance, description, watch_fields):
    """如果 check_date 等于 expected_date，添加到 results。"""
    if check_date == expected_date:
        reference_date = check_date - dt.timedelta(days=0)  # will be set by caller
        # days_until 计算需要 reference_date，但这里我们用 check_date 等于 expected_date
        # 所以 days_until 需要在 _make_catalyst 中计算
        results.append({
            "name": name,
            "name_en": name_en,
            "country": country,
            "catalyst_type": ctype,
            "expected_date": expected_date.isoformat(),
            "days_until": 0,  # placeholder, will be recalculated
            "importance": importance,
            "description": description,
            "watch_fields": watch_fields,
        })


def _make_catalyst(name, name_en, country, ctype, date_obj, importance, description, watch_fields, reference_date):
    """创建一个 catalyst dict。"""
    days_until = (date_obj - reference_date).days
    return {
        "name": name,
        "name_en": name_en,
        "country": country,
        "catalyst_type": ctype,
        "expected_date": date_obj.isoformat(),
        "days_until": days_until,
        "importance": importance,
        "description": description,
        "watch_fields": watch_fields,
    }


# ═══════════════════════════════════════════════════════
#  叙事模式 → catalyst 映射
# ═══════════════════════════════════════════════════════

# 每种叙事模式最相关的证伪 catalyst 类型
NARRATIVE_CATALYST_MAP = {
    "inflation_fear": ["cpi", "nfp", "pmi", "fomc"],
    "risk_off": ["fomc", "pmi", "jobless"],
    "liquidity_expansion": ["fomc", "cpi", "m2"],
    "recession_trade": ["pmi", "nfp", "gdp", "jobless"],
    "growth_selloff": ["cpi", "fomc", "nfp"],
    "commodity_supercycle": ["cpi", "pmi", "nfp"],
}


def get_falsification_catalysts(narrative_id: Optional[str], days_ahead: int = 30,
                                reference_date: Optional[dt.date] = None) -> list[dict]:
    """
    根据叙事模式，返回最相关的证伪 catalyst 列表。

    如果 narrative_id 为 None，返回所有 high importance catalyst。
    """
    all_catalysts = get_upcoming_catalysts(reference_date, days_ahead)

    if narrative_id is None:
        return [c for c in all_catalysts if c["importance"] == "high"]

    relevant_types = NARRATIVE_CATALYST_MAP.get(narrative_id, [])
    if not relevant_types:
        return all_catalysts

    # 优先返回与叙事相关的 catalyst
    relevant = [c for c in all_catalysts if c["catalyst_type"] in relevant_types]
    # 补充其他 high importance catalyst（但不重复）
    seen_types = {c["catalyst_type"] for c in relevant}
    others = [c for c in all_catalysts
              if c["importance"] == "high" and c["catalyst_type"] not in seen_types]
    return relevant + others


def format_falsification_window(narrative_id: Optional[str], days_ahead: int = 30,
                                reference_date: Optional[dt.date] = None) -> str:
    """
    生成证伪窗口的文本描述。

    返回格式：
    "下次美国CPI在7月16日（3天后），若低于预期则整个通胀叙事链失效。
     下次FOMC在7月30日（17天后），关注利率声明措辞。"
    """
    catalysts = get_falsification_catalysts(narrative_id, days_ahead, reference_date)
    if not catalysts:
        return "近期无重大经济数据发布。"

    # 取前 3 个最相关的
    parts = []
    for c in catalysts[:3]:
        d = c["days_until"]
        if d < 0:
            continue
        elif d == 0:
            timing = "今日发布"
        elif d == 1:
            timing = "明日发布"
        else:
            timing = f"{d}天后"

        date_str = c["expected_date"]
        # 格式化为 "7月16日"
        try:
            parsed = dt.datetime.fromisoformat(date_str).date()
            date_cn = f"{parsed.month}月{parsed.day}日"
        except Exception:
            date_cn = date_str

        fields = "、".join(c["watch_fields"][:2])
        parts.append(f"下次{c['name']}在{date_cn}（{timing}），关注{fields}")

    if not parts:
        return "近期无重大经济数据发布。"

    return "证伪窗口：\n" + "\n".join(parts)


# ═══════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════

def run(narrative_id: Optional[str] = None, days_ahead: int = 14) -> dict:
    """
    完整入口：返回事件日历 + 证伪窗口。

    Parameters
    ----------
    narrative_id : str, optional
        当前匹配的叙事模式 ID（如 "inflation_fear"）
    days_ahead : int
        向前看多少天

    Returns
    -------
    dict
        {
            "upcoming_catalysts": [...],
            "falsification_catalysts": [...],
            "falsification_text": "证伪窗口：...",
            "next_high_impact": {...} or None,
        }
    """
    today = dt.date.today()
    upcoming = get_upcoming_catalysts(today, days_ahead)
    falsification = get_falsification_catalysts(narrative_id, 30, today)
    falsification_text = format_falsification_window(narrative_id, 30, today)

    # 找到最近的 high importance catalyst
    next_high = None
    for c in upcoming:
        if c["importance"] == "high" and c["days_until"] >= 0:
            next_high = c
            break

    return {
        "reference_date": today.isoformat(),
        "upcoming_catalysts": upcoming,
        "falsification_catalysts": falsification,
        "falsification_text": falsification_text,
        "next_high_impact": next_high,
    }


if __name__ == "__main__":
    import json
    result = run("inflation_fear")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
