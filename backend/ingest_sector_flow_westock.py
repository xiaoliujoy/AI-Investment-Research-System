"""方案A落地：westock 板块资金流作定主线交叉验证源，写入 Decision Log 草稿。

双段式（不接活管道）：
  段1(取数): 对话层/automation 用 mcp__westock-mcp__data_sector mode=ranking 取数，
             提取 fundflow.plate/concept 的 top/bottom 写成 output/westock_fundflow_{date}.json。
  段2(本脚本): 读 JSON -> 写 sector_flow_westock(新表,不动 sector_daily)
             -> 计算 westock concept.top 与 sector_daily TOP 的交叉验证
             -> 写入 research_decision_log.westock_cross_check 列(今日草稿)

字段单位（见 JSON unit_note）：
  cje/zllr/zllc/zljlr/zljlr_d5/zljlr_d20 单位=万元；change_pct=zdf(%)。
  westock 亿元 = 万元 / 10000；sector_daily.net_amount 已是亿元。

用法：
  python ingest_sector_flow_westock.py --json output/westock_fundflow_20260804.json
  python ingest_sector_flow_westock.py --date 2026-08-04   # 默认读 output/westock_fundflow_{date}.json
"""

from db import get_conn as db_conn, _DB_PATH

import argparse
import json
import os
import sqlite3
import sys

DB = str(_DB_PATH)
HERE = os.path.dirname(__file__)


def norm(s: str) -> str:
    """板块名归一：去空白、去易差异后缀，便于跨源对齐。"""
    s = s.strip()
    for rep in ["概念", "Ⅱ", "II", "（", "）", "(", ")"]:
        s = s.replace(rep, "")
    return s


def get_conn():
    return db_conn()


def ensure_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sector_flow_westock (
            date          TEXT NOT NULL,
            src           TEXT NOT NULL,
            rank_type     TEXT NOT NULL,
            code          TEXT NOT NULL,
            name          TEXT,
            change_pct    REAL,
            amount_wan    REAL,
            main_in_wan   REAL,
            main_out_wan  REAL,
            net_amount_wan REAL,
            net_d5_wan    REAL,
            net_d20_wan   REAL,
            leader_code   TEXT,
            leader_name   TEXT,
            PRIMARY KEY (date, src, rank_type, code)
        )
        """
    )
    conn.commit()


def ensure_cross_check_col(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(research_decision_log)")]
    if "westock_cross_check" not in cols:
        conn.execute("ALTER TABLE research_decision_log ADD COLUMN westock_cross_check TEXT")
        conn.commit()


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def ingest(conn, data):
    date = data["date"]
    rows = []
    for src in ("plate", "concept"):
        for rk in ("top", "bottom"):
            for b in data.get(src, {}).get(rk, []):
                rows.append(
                    (
                        date, src, rk, b["code"], b.get("name"), b.get("zdf"),
                        b.get("cje"), b.get("zllr"), b.get("zllc"), b.get("zljlr"),
                        b.get("zljlr_d5"), b.get("zljlr_d20"),
                        b.get("lzg_code"), b.get("lzg_name"),
                    )
                )
    conn.executemany(
        """
        INSERT OR REPLACE INTO sector_flow_westock
        (date,src,rank_type,code,name,change_pct,amount_wan,main_in_wan,
         main_out_wan,net_amount_wan,net_d5_wan,net_d20_wan,leader_code,leader_name)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def load_sector_daily(conn, date):
    cur = conn.execute(
        "SELECT sector_name, net_amount, change_pct, amount, leader_name "
        "FROM sector_daily WHERE date=?",
        (date,),
    )
    return {
        n: {"net": net, "chg": chg, "amount": amt, "leader": leader}
        for n, net, chg, amt, leader in cur.fetchall()
    }


def align(name, sdict):
    """跨源板块名对齐，按 精确 > 归一精确 > 子串 三级优先。

    子串轮必须择优，不能先到先得：dict 遍历顺序由 SQL 决定，短名会抢占长名。
    实例（2026-08-10）：westock「半导体设备概念」归一为「半导体设备」，遍历时先撞上
    sector_daily「半导体」（"半导体" in "半导体设备" 成立）即返回，导致 +52.13亿 被错配到
    -29.79亿、误报为方向分歧；而真正对应的「半导体设备」(+36.88亿) 就在同一张表里。
    择优规则：归一名长度与目标最接近者优先，长度差相同则取更长者（更具体的板块）。
    """
    if name in sdict:
        return name
    na = norm(name)
    if not na:
        return None
    for sname in sdict:  # 第二轮：归一化后精确相等
        if norm(sname) == na:
            return sname
    cands = []  # 第三轮：子串包含，择优而非先到先得
    for sname in sdict:
        nb = norm(sname)
        if nb and (na in nb or nb in na):
            cands.append((abs(len(nb) - len(na)), -len(nb), sname))
    if cands:
        cands.sort()
        return cands[0][2]
    return None


# 量级偏离阈值：两源净流入绝对值之比 > 该倍数时，认为"名字对上了但口径/成分不同"，
# 该条对齐只算弱证据，不得当作交叉验证通过。典型案例：
# 2026-08-05 concept「芯片概念」352.52亿 被名称匹配到 sector_daily「AI芯片」15.41亿（22.9x）。
MAG_RATIO_LIMIT = 3.0

# 错配阈值：偏离超过该倍数时，名称匹配本身就是假的（不是同一个东西），
# 必须判为「错配 mismatch」而非「方向分歧 divergent」，并从 aligned 中剔除。
# 理由：方向一致性只有在两源量级可比时才有意义；量级差两个数量级以上说明对齐无效，
# 让它产出 divergent 会重演 08-05 的污染模式——把"没有对应板块"污染成"两源结论分歧"。
# 典型案例：2026-08-13 concept「算力租赁」+46.44亿 被子串匹配到行业板块「租赁」-0.07亿（663x），
# 本地实际并无「算力租赁」板块（最近的「算力概念」概念范围不同），正解是判未对齐。
# 阈值取 20x 的依据：3~20x 区间是同一主题下的口径/成分差异（如 08-12 半导体 3.3x），
# 方向一致仍有弱参考价值；>20x 的历史案例全部为名称错配。
MISMATCH_RATIO_LIMIT = 20.0


def mag_ratio(w_yi, s_yi):
    """返回两源净流入绝对值的偏离倍数；任一为 0/None 时返回 None（不可判）。"""
    if s_yi is None or w_yi is None:
        return None
    a, b = abs(w_yi), abs(s_yi)
    if a < 1e-9 or b < 1e-9:
        return None
    return max(a, b) / min(a, b)


def mag_ok(ratio):
    """None(不可判) 视作不通过强证据，但单列出来，不算分歧。"""
    return ratio is not None and ratio <= MAG_RATIO_LIMIT


def is_mismatch(ratio):
    """量级偏离到不可能是同一板块 -> 名称对齐无效，按未对齐处理，不产生分歧结论。"""
    return ratio is not None and ratio > MISMATCH_RATIO_LIMIT


def _load_westock_rank(conn, date, src, rank_type):
    """从入库表取 westock 某源某排行的板块列表（行业/概念均可）。"""
    cur = conn.execute(
        "SELECT name, net_amount_wan, net_d5_wan, net_d20_wan, change_pct "
        "FROM sector_flow_westock WHERE date=? AND src=? AND rank_type=?",
        (date, src, rank_type),
    )
    return [
        {
            "name": n,
            "net_yi": round((net or 0) / 10000.0, 2),
            "d5_yi": round((d5 or 0) / 10000.0, 2),
            "d20_yi": round((d20 or 0) / 10000.0, 2),
            "chg": chg,
        }
        for n, net, d5, d20, chg in cur.fetchall()
    ]


def _align_rank_to_sector(wlist, sdict):
    """把 westock 某排行（top/bottom）与 sector_daily 对齐，返回 (aligned, divergent, suspect, mismatched)。

    对齐防护沿用既有 align / mag_ratio / is_mismatch：
      - 量级偏离 > MISMATCH_RATIO_LIMIT 倍 → 名称错配，按未对齐剔除，不产分歧结论；
      - 量级偏离 > MAG_RATIO_LIMIT 但 <= MISMATCH 倍 → 弱证据（方向一致不算强证据）。
    """
    aligned, divergent, suspect, mismatched = [], [], [], []
    for w in wlist:
        sname = align(w["name"], sdict)
        if sname:
            snet = sdict[sname]["net"]
            same = (w["net_yi"] >= 0) == (snet is not None and snet >= 0)
            ratio = mag_ratio(w["net_yi"], snet)
            if is_mismatch(ratio):
                mismatched.append({
                    "w_name": w["name"], "s_name": sname,
                    "w_net_yi": w["net_yi"], "s_net_yi": snet,
                    "mag_ratio": round(ratio, 2),
                })
                continue
            ok = mag_ok(ratio)
            aligned.append({
                "w_name": w["name"], "s_name": sname,
                "w_net_yi": w["net_yi"], "s_net_yi": snet,
                "same_dir": same,
                "mag_ratio": round(ratio, 2) if ratio is not None else None,
                "mag_ok": ok,
            })
            if not same:
                divergent.append(w["name"])
            if not ok:
                suspect.append({
                    "w_name": w["name"], "s_name": sname,
                    "mag_ratio": round(ratio, 2) if ratio is not None else None,
                })
    return aligned, divergent, suspect, mismatched


def build_cross_check(conn, data, sdict):
    """构造 westock plate（行业板块）与 sector_daily（行业板块）的交叉验证 JSON。

    口径修正（2026-08-22）：
      - 交叉验证主体从 concept.top（概念板块）切换为 plate.top / plate.bottom（行业板块），
        与 sector_daily 同为行业口径，可比性成立，消除每日恒 unaligned 假警报。
      - concept 侧为概念板块噪音，与行业板块天然不可比，降级为"参考"不进入一致性判定分母。
      - 对齐防护（align / mag_ratio / MISMATCH_RATIO_LIMIT）全部保留。
    """
    date = data["date"]
    # westock plate.top（行业板块净流入端） + plate.bottom（行业板块净流出端）
    wtop = _load_westock_rank(conn, date, "plate", "top")
    wbottom = _load_westock_rank(conn, date, "plate", "bottom")
    # sector_daily TOP10 by net_amount（行业板块，与 plate 同口径）
    stop = sorted(
        [(n, v["net"], v["chg"]) for n, v in sdict.items() if v["net"] is not None],
        key=lambda x: x[1], reverse=True,
    )[:10]
    stop = [{"name": n, "net_yi": round(net, 2), "chg": chg} for n, net, chg in stop]

    # 对齐：top 与 bottom 分别对齐（bottom 反向验证，方向判定也随之反向）
    aligned_top, divergent_top, suspect_top, mismatched_top = _align_rank_to_sector(wtop, sdict)
    aligned_bot, divergent_bot, suspect_bot, mismatched_bot = _align_rank_to_sector(wbottom, sdict)

    # bottom 侧：westock 净流出（net_yi<0）对齐 sector_daily 净流出（net<0）才算同向；
    # 这里 aligned_bot 的 same_dir 是按"同号"算的，净流出端同号即同向（均流出），语义正确。
    aligned = aligned_top + aligned_bot
    divergent = divergent_top + divergent_bot
    suspect_alignment = suspect_top + suspect_bot
    mismatched = mismatched_top + mismatched_bot

    # 一致性判定
    # 关键区分：对照基准缺失(no_baseline) != 两源分歧(divergent)。
    # sector_daily 当日无数据时不得判 divergent，否则把"数据没来"污染成"结论分歧"。
    note = None
    if not sdict:
        consistency = "no_baseline"
        note = f"sector_daily 当日({date})无数据，无法交叉验证；westock 侧已入库，待 daily_collect 补数后重跑。"
    elif not aligned:
        consistency = "unaligned"
        note = "sector_daily 有数据但 westock plate 行业板块全部未对齐（命名口径差异或量级错配），非方向分歧。"
    elif all(a["same_dir"] for a in aligned):
        consistency = "consistent"
    else:
        consistency = "partial"
    strong = [a for a in aligned if a["mag_ok"]]
    out = {
        "date": date,
        "westock_plate_top": wtop,
        "westock_plate_bottom": wbottom,
        "sector_daily_top10": stop,
        "aligned": aligned,
        "consistency": consistency,
        "divergent": divergent,
        # 强证据 = 方向一致 且 量级偏离 <= MAG_RATIO_LIMIT 倍
        "strong_evidence_count": sum(1 for a in strong if a["same_dir"]),
        "suspect_alignment": suspect_alignment,
        "mismatched": mismatched,
        "mag_ratio_limit": MAG_RATIO_LIMIT,
        "mismatch_ratio_limit": MISMATCH_RATIO_LIMIT,
        # concept 侧为概念板块噪音，不参与判定（仅记录供参考）
        "concept_side_note": (
            "concept（概念板块）与 sector_daily（行业板块）口径不可比，"
            "已降级为参考噪音，不进入一致性判定分母；定主线以 plate 侧为准。"
        ),
    }
    if mismatched:
        mnames = "、".join(f"{m['w_name']}↔{m['s_name']}({m['mag_ratio']}x)" for m in mismatched)
        mwarn = (f"量级偏离>{MISMATCH_RATIO_LIMIT:g}x 判为名称错配 {len(mismatched)} 项：{mnames}；"
                 f"已按未对齐剔除，不计入方向分歧。")
        note = f"{note} {mwarn}" if note else mwarn
    if suspect_alignment:
        names = "、".join(f"{s['w_name']}↔{s['s_name']}({s['mag_ratio']}x)" for s in suspect_alignment)
        warn = f"量级偏离>{MAG_RATIO_LIMIT}x 的对齐 {len(suspect_alignment)} 项：{names}；名称匹配上但口径/成分不同，方向一致性不作为强证据。"
        note = f"{note} {warn}" if note else warn
    if note:
        out["note"] = note
    return out


def update_decision_log(conn, cross):
    date = cross["date"]
    exists = conn.execute(
        "SELECT 1 FROM research_decision_log WHERE date=?", (date,)
    ).fetchone()
    if not exists:
        print(f"[SKIP] 今日({date})无 Decision Log 草稿，跳过 westock_cross_check 写入（仅入库）。")
        return False
    conn.execute(
        "UPDATE research_decision_log SET westock_cross_check=? WHERE date=?",
        (json.dumps(cross, ensure_ascii=False), date),
    )
    conn.commit()
    print(f"[OK] 已写 westock_cross_check 到 Decision Log 草稿 {date}（一致性={cross['consistency']}）")
    return True


def compare_report(data, sdict):
    lines = []
    matched_plate = []
    unmatched = []
    mismatched = []
    concept_raw = []  # 概念板块噪音，不参与任何对齐尝试
    for src in ("plate", "concept"):
        for rk in ("top", "bottom"):
            for b in data.get(src, {}).get(rk, []):
                wname = b.get("name")
                w_net_yi = (b.get("zljlr") or 0) / 10000.0
                if src == "concept":
                    # 概念板块与行业板块口径不可比，不尝试对齐，仅作为噪音记录
                    concept_raw.append((src, rk, wname, w_net_yi))
                    continue
                sname = align(wname, sdict)
                if sname:
                    sv = sdict[sname]
                    same = (w_net_yi >= 0) == (sv["net"] is not None and sv["net"] >= 0)
                    ratio = mag_ratio(w_net_yi, sv["net"])
                    # 极端偏离 = 名称错配，归入未对齐，不得计入一致率分母也不算分歧
                    if is_mismatch(ratio):
                        mismatched.append((src, rk, wname, sname, w_net_yi, sv["net"], ratio))
                        unmatched.append((src, rk, wname, w_net_yi))
                        continue
                    matched_plate.append((src, rk, wname, sname, w_net_yi, sv["net"], same, ratio))
                else:
                    unmatched.append((src, rk, wname, w_net_yi))
    lines.append(f"# 板块资金流对照报告  {data['date']}\n")
    if not sdict:
        lines.append(f"> ⚠️ sector_daily 当日无数据，本报告仅为 westock 单源快照，**未做交叉验证**。\n")
    lines.append(f"- westock 样本(plate): {len(matched_plate)+len(unmatched)}；plate 对齐命中: {len(matched_plate)}")
    # 主判定口径 = plate 侧（行业板块，与 sector_daily 同口径可比）
    if matched_plate:
        same = sum(1 for m in matched_plate if m[6])
        strong = sum(1 for m in matched_plate if m[6] and mag_ok(m[7]))
        lines.append(f"- **方向一致率（plate 侧主口径）**: {same}/{len(matched_plate)} = {same/len(matched_plate)*100:.0f}%")
        lines.append(
            f"- **强证据**(方向一致 且 量级偏离≤{MAG_RATIO_LIMIT:g}x): {strong}/{len(matched_plate)}"
        )
        lines.append("")
        lines.append("## plate 侧（行业板块，口径可比，主看这一栏）")
        lines.append("| westock | 类型 | westock净流入(亿) | sector_daily净流入(亿) | 量级比 | 一致 |")
        lines.append("|---|---|---|---|---|---|")
        for src, rk, wn, sn, wn_yi, sn_yi, same, ratio in matched_plate:
            rtxt = f"{ratio:.1f}x" if ratio is not None else "n/a"
            if not mag_ok(ratio):
                rtxt = f"⚠️{rtxt}"
            flag = "✅" if same else "❌"
            if same and not mag_ok(ratio):
                flag = "🟡"  # 方向一致但量级不可比：弱证据
            lines.append(
                f"| {wn} | {src}/{rk} | {wn_yi:.2f} | {sn_yi if sn_yi is not None else 'NULL'} | {rtxt} | {flag} |"
            )
        suspects = [m for m in matched_plate if not mag_ok(m[7])]
        if suspects:
            lines.append(
                f"\n> 🟡 量级偏离>{MAG_RATIO_LIMIT:g}x 共 {len(suspects)} 项："
                + "、".join(f"{m[2]}↔{m[3]}" for m in suspects)
                + "。名称匹配上但两源口径/成分不同，**方向一致不算交叉验证通过**。"
            )
    if mismatched:
        lines.append(
            f"\n> ⛔ 名称错配（量级偏离>{MISMATCH_RATIO_LIMIT:g}x，已按未对齐剔除，不算分歧）共 {len(mismatched)} 项："
            + "、".join(f"{m[2]}↔{m[3]}({m[6]:.0f}x：{m[4]:.2f}亿 vs {m[5]}亿)" for m in mismatched)
        )
    if unmatched:
        lines.append("\n## 未对齐（plate 侧，概念板块不在此列）")
        for src, rk, wn, wn_yi in unmatched:
            lines.append(f"- [{src}/{rk}] {wn} ({wn_yi:.2f}亿)")
    if concept_raw:
        lines.append("\n## 概念板块（噪音参考，不参与交叉验证）")
        lines.append("| westock | 类型 | westock净流入(亿) |")
        lines.append("|---|---|---|")
        for src, rk, wn, wn_yi in concept_raw:
            lines.append(f"| {wn} | {src}/{rk} | {wn_yi:.2f} |")
        lines.append(
            "\n> ℹ️ concept 为概念板块，与 sector_daily 行业板块口径不可比，不尝试对齐，仅供人工参考，不计入方向一致率分母、不污染未对齐清单。"
        )
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    if args.json:
        jpath = args.json
    else:
        date = args.date or __import__("datetime").date.today().isoformat()
        jpath = os.path.join(HERE, "output", f"westock_fundflow_{date}.json")
    if not os.path.exists(jpath):
        print(f"[ERR] JSON 不存在: {jpath}", file=sys.stderr)
        sys.exit(1)

    data = load_json(jpath)
    date = data.get("date", args.date)
    conn = get_conn()
    ensure_table(conn)
    ensure_cross_check_col(conn)
    n = ingest(conn, data)
    sdict = load_sector_daily(conn, date)
    print(f"[OK] 写入 sector_flow_westock {n} 行 ({date})")

    report = compare_report(data, sdict)
    print(report)

    cross = build_cross_check(conn, data, sdict)
    update_decision_log(conn, cross)
    conn.close()

    out = os.path.join(HERE, "output", f"compare_westock_vs_sector_{date}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[OK] 对照报告: {out}")


if __name__ == "__main__":
    main()
