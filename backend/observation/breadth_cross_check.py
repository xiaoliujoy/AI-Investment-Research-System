# -*- coding: utf-8 -*-
"""
breadth_cross_check.py  —  观察层 · G2 市场宽度口径对齐诊断

目的（来自 docs/themarketmemo_os_gap.md G2）：
  核对我们 market_daily 现有的「涨跌家数宽度」(advance-decline breadth)
  与 TheMarketMemo 的「收盘价高于 MA20/50/200 百分比」(MA-position breadth)
  是否为同一口径；若不同，在观察层补一份 TMM 口径做交叉验证。

治理边界（强制）：
  - 本脚本仅 READ 生产表、WRITE 到 output/ 日志，绝不修改任何生产表/生产评分。
  - MA20/50/200 仅用于「全市场指数级宽度聚合」，非个股硬筛。
    用户红线「禁 amount/ma20/ma60 个股过滤」针对的是个股候选筛选，本用法属 G2 已注明的合规例外。
  - 当前系统处于 Phase 1E 冻结 + 8 周纪律期：本脚本不新增任何生产指标、不改风控、不优化分数。

用法：
  python breadth_cross_check.py [--date YYYY-MM-DD] [--window 750]
"""

from db import get_conn, _DB_PATH

import argparse
import json
import os
import sqlite3
from datetime import date

import pandas as pd

DB = str(_DB_PATH)
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "output")

# TheMarketMemo 市场宽度阈值（来自 docs/themarketmemo_kb.md §B）
TMM_TOP = 85.0     # 短期顶 / 长期顶：20&50 或 50&200 同达 >=85%
TMM_BOTTOM = 15.0  # 短期底 / 长期底：同达 <=15%
TMM_BULL_LINE = 50.0  # 200日宽度 >50 牛 / <50 熊


def load_active_close(cur, max_date):
    """取最新交易日仍在交易的股票收盘价序列（避免退市股污染全市场宽度）。"""
    cur.execute("SELECT code FROM stock_daily WHERE date=?", (max_date,))
    active = [r[0] for r in cur.fetchall()]
    print(f"[i] active codes on {max_date}: {len(active)}")
    # 批量取这些 code 的 (date, code, close)
    ph = ",".join("?" * len(active))
    cur.execute(
        f"SELECT date, code, close FROM stock_daily WHERE code IN ({ph}) ORDER BY code, date",
        active,
    )
    rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["date", "code", "close"])
    return df, active


def compute_ma_breadth(df, active, window):
    """每只股票本地算 MA20/50/200，按日聚合「收盘价>MA 的百分比」。"""
    df["date"] = pd.to_datetime(df["date"])
    all_dates = sorted(df["date"].unique())
    cut = all_dates[-window] if len(all_dates) >= window else all_dates[0]
    df = df[df["date"] >= cut]
    # pivot: index=date, columns=code, values=close
    wide = df.pivot(index="date", columns="code", values="close").sort_index()
    res = pd.DataFrame(index=wide.index)
    for n, col in [(20, "b20"), (50, "b50"), (200, "b200")]:
        ma = wide.rolling(n, min_periods=n).mean()
        above = (wide > ma)
        # 百分比：当日有 MA 的股票里，收盘价>MA 的占比
        eligible = ma.notna().sum(axis=1)
        cnt_above = above[ma.notna()].sum(axis=1)
        eligible_safe = eligible.where(eligible > 0)  # 0 -> NaN，避免除零
        res[col] = (cnt_above / eligible_safe * 100)
    res["eligible20"] = wide.rolling(20, min_periods=20).mean().notna().sum(axis=1)
    res["eligible50"] = wide.rolling(50, min_periods=50).mean().notna().sum(axis=1)
    res["eligible200"] = wide.rolling(200, min_periods=200).mean().notna().sum(axis=1)
    return res


def load_ad_breadth(cur):
    """现有 market_daily 涨跌家数宽度：up/(up+down+flat)*100。"""
    cur.execute(
        "SELECT date, up_count, down_count, flat_count FROM market_daily "
        "WHERE up_count IS NOT NULL ORDER BY date"
    )
    rows = cur.fetchall()
    d = pd.DataFrame(rows, columns=["date", "up", "down", "flat"])
    d["date"] = pd.to_datetime(d["date"])
    tot = d["up"] + d["down"] + d["flat"]
    d["ad_breadth"] = (d["up"] / tot * 100).where(tot > 0)
    return d.set_index("date")[["ad_breadth"]]


def tmm_signals(row):
    """把 TMM 阈值翻成信号文本。"""
    b20, b50, b200 = row["b20"], row["b50"], row["b200"]
    sigs = []
    if pd.notna(b20) and pd.notna(b50):
        if b20 >= TMM_TOP and b50 >= TMM_TOP:
            sigs.append("短期超买(20&50>=85%)")
        elif b20 <= TMM_BOTTOM and b50 <= TMM_BOTTOM:
            sigs.append("短期超卖(20&50<=15%)")
    if pd.notna(b50) and pd.notna(b200):
        if b50 >= TMM_TOP and b200 >= TMM_TOP:
            sigs.append("长期超买(50&200>=85%)")
        elif b50 <= TMM_BOTTOM and b200 <= TMM_BOTTOM:
            sigs.append("长期超卖(50&200<=15%)")
    if pd.notna(b200):
        sigs.append("牛市" if b200 > TMM_BULL_LINE else "熊市")
    return " / ".join(sigs) if sigs else "中性"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="截止日期 YYYY-MM-DD，默认最新")
    ap.add_argument("--window", type=int, default=750, help="MA 计算回看交易日数")
    args = ap.parse_args()

    con = get_conn()
    cur = con.cursor()
    max_date = args.date or cur.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
    print(f"[i] target date = {max_date}, window = {args.window}")

    df, active = load_active_close(cur, max_date)
    ma = compute_ma_breadth(df, active, args.window)
    ad = load_ad_breadth(cur)
    con.close()

    # 合并两口径
    merged = ma.join(ad, how="inner").dropna(subset=["b20", "ad_breadth"])
    merged = merged.sort_index()

    latest = merged.iloc[-1]
    latest_date = merged.index[-1].strftime("%Y-%m-%d")

    # 相关性（仅在两口径都有的重叠窗口上计算）
    corr = merged[["b20", "b50", "b200", "ad_breadth"]].corr()
    overlap_n = int(merged["ad_breadth"].notna().sum())
    overlap_min = merged["ad_breadth"].notna()
    overlap_min = merged.index[overlap_min][0].strftime("%Y-%m-%d") if overlap_min.any() else "NA"
    overlap_max = merged.index[merged["ad_breadth"].notna()][-1].strftime("%Y-%m-%d") if overlap_min != "NA" else "NA"

    # TMM 信号
    signal = tmm_signals(latest)

    # 末 N 日对比表
    tail = merged.tail(10).iloc[::-1]
    tail_rows = []
    for idx, r in tail.iterrows():
        tail_rows.append(
            f"| {idx.strftime('%Y-%m-%d')} | {r['ad_breadth']:.1f} | {r['b20']:.1f} | "
            f"{r['b50']:.1f} | {r['b200']:.1f} | {tmm_signals(r)} |"
        )

    # 牛熊状态（200日宽度）— 用 MA 位置宽度全部有效历史，不依赖 AD 宽度短历史
    b200_valid = ma["b200"].dropna()
    bull_days = int((b200_valid > TMM_BULL_LINE).sum())
    bear_days = int((b200_valid <= TMM_BULL_LINE).sum())
    b200_start = b200_valid.index.min().strftime("%Y-%m-%d")
    b200_end = b200_valid.index.max().strftime("%Y-%m-%d")

    # 涨跌家数宽度历史深度（数据完整性发现）
    ad_first = merged["ad_breadth"].notna()
    ad_hist_start = merged.index[ad_first][0].strftime("%Y-%m-%d") if ad_first.any() else "NA"
    ad_hist_n = overlap_n

    report = f"""# G2 市场宽度口径对齐诊断 · {latest_date}

> 观察层诊断，只读生产、不写生产。治理边界见脚本头注释（Phase 1E 冻结 + 8 周纪律期）。
> TMM 阈值：短期顶/底=20&50 同达 ≥85%/≤15%；长期顶/底=50&200 同达；200日>50 牛 / <50 熊。

## 一、两种宽度口径定义对比

| 口径 | 定义 | 来源 | 数据列 |
|---|---|---|---|
| 现有（涨跌家数） | 上涨家数 / (上涨+下跌+平) ×100% | 我们 market_daily | up/down/flat_count |
| TheMarketMemo（MA 位置） | 收盘价高于 MA20/50/200 的股票占比 | themarketmemo.com/marketbreadth | 本地算（stock_daily.close） |

**结论：两口径定义不同，是互补关系，非冗余。** 涨跌家数宽度对单日情绪敏感；MA 位置宽度对趋势/regime 更稳。

## 二、最新读数（{latest_date}）

| 指标 | 数值 | TMM 语义 |
|---|---|---|
| 现有 涨跌家数宽度 | {latest['ad_breadth']:.1f}% | 单日情绪 |
| TMM 20日宽度 | {latest['b20']:.1f}% | 短期 |
| TMM 50日宽度 | {latest['b50']:.1f}% | 中期 |
| TMM 200日宽度 | {latest['b200']:.1f}% | 长期/牛熊 |
| **TMM 综合信号** | {signal} | — |

样本：MA20/50/200 合格股票数 = {int(latest.get('eligible20',0))}/{int(latest.get('eligible50',0))}/{int(latest.get('eligible200',0))}（全市场活跃 {len(active)} 只）

## 三、近 10 日两口径对照

| 日期 | 涨跌家数% | MA20% | MA50% | MA200% | TMM 信号 |
|---|---|---|---|---|---|
{chr(10).join(tail_rows)}

## 四、相关性矩阵（重叠窗口 {overlap_n} 交易日，{overlap_min}~{overlap_max}）

| | 涨跌家数 | MA20 | MA50 | MA200 |
|---|---|---|---|---|
| 涨跌家数 | 1.000 | {corr.loc['ad_breadth','b20']:.3f} | {corr.loc['ad_breadth','b50']:.3f} | {corr.loc['ad_breadth','b200']:.3f} |
| MA20 | {corr.loc['b20','ad_breadth']:.3f} | 1.000 | {corr.loc['b20','b50']:.3f} | {corr.loc['b20','b200']:.3f} |
| MA50 | {corr.loc['b50','ad_breadth']:.3f} | {corr.loc['b50','b20']:.3f} | 1.000 | {corr.loc['b50','b200']:.3f} |
| MA200 | {corr.loc['b200','ad_breadth']:.3f} | {corr.loc['b200','b20']:.3f} | {corr.loc['b200','b50']:.3f} | 1.000 |

解读：涨跌家数 vs MA20 通常高相关（同反映短期）；vs MA200 相关性偏低（MA200 捕捉长周期 regime，涨跌家数捕捉单日）。这正是保留两口径的价值。
⚠️ 注意：两口径重叠窗口仅 {overlap_n} 交易日（{overlap_min} 起），样本过浅，相关系数仅供参考、不可用于统计推断。

## 五、牛熊状态（200日宽度，MA 位置口径全部有效历史）

- 有效历史：{b200_start} ~ {b200_end}（{bull_days + bear_days} 交易日）
- 牛市天数（>50%）：{bull_days} / 熊市天数（≤50%）：{bear_days}
- 当前 200日宽度 {latest['b200']:.1f}% → {('牛市' if latest['b200']>TMM_BULL_LINE else '熊市')}

## 六、数据完整性发现（G2 关键产出）

- ⚠️ **现有涨跌家数宽度历史极浅**：`market_daily.up_count` 仅 {ad_hist_n} 个交易日（{ad_hist_start} 起）有数据，回补前无法作为长期 regime 参照。
- ✅ **MA 位置宽度历史深厚**：TMM 口径（本地算）自 {b200_start} 起连续有效（{bull_days + bear_days} 交易日），可作耐久 regime 量尺。
- 建议：① 若要把涨跌家数宽度当长期指标，需回补 `market_daily` 历史（属数据工程，非生产参数改动）；② 在此之前，以 MA 位置宽度为主 regime 量尺、AD 宽度为短期情绪辅助；③ 二者定义不同，互补而非替代。

## 七、治理结论

- ✅ 观察层隔离验证通过：本脚本独立读取 stock_daily / market_daily，输出到 output/，未触碰任何生产表或生产评分。
- ✅ 两口径差异与历史深度差异已量化，可作为观察层交叉验证项。建议后续每日随观察链输出本表，不进入生产决策。
- ⚠️ 不变更生产：不把 TMM 宽度接生产评分、不改风控阈值、不新增评分指标（8 周纪律期）。
"""
    os.makedirs(OUT_DIR, exist_ok=True)
    out_md = os.path.join(OUT_DIR, f"breadth_cross_check_{latest_date}.md")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(report)

    # 机器可读 sidecar
    out_json = os.path.join(OUT_DIR, f"breadth_cross_check_{latest_date}.json")
    payload = {
        "date": latest_date,
        "active_codes": len(active),
        "ad_breadth": round(float(latest["ad_breadth"]), 2),
        "tmm": {
            "b20": round(float(latest["b20"]), 2),
            "b50": round(float(latest["b50"]), 2),
            "b200": round(float(latest["b200"]), 2),
            "signal": signal,
        },
        "corr_ad_vs_ma200": round(float(corr.loc["ad_breadth", "b200"]), 3),
        "b200_valid_range": f"{b200_start}~{b200_end}",
        "bull_days_b200hist": bull_days,
        "bear_days_b200hist": bear_days,
        "ad_breadth_history": f"{ad_hist_start} ({ad_hist_n} sessions)",
        "overlap_window": f"{overlap_min}~{overlap_max} ({overlap_n} sessions)",
        "observation_only": True,
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[ok] wrote {out_md}")
    print(f"[ok] wrote {out_json}")
    print(f"[summary] {latest_date} | 涨跌家数 {latest['ad_breadth']:.1f}% | "
          f"MA20 {latest['b20']:.1f}% MA50 {latest['b50']:.1f}% MA200 {latest['b200']:.1f}% | {signal}")
    return payload


if __name__ == "__main__":
    main()
