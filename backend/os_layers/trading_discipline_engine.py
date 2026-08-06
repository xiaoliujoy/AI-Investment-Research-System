#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Trading Discipline Engine —— Decision Execution Layer（决策执行层）

定位（与架构冻结的关系，见 docs/trader_os_v0.1_architecture_freeze.md）：
  本模块是 Trader OS 的「Coach Agent」具体化，即用户所称的
  「计划交易，交易计划 / Trading Discipline Engine / Decision Execution Layer」。
  它不预测市场、不产出买卖建议、不写 CIO（§1.1 永久冻结）。
  它只做一件事：监督「你有没有成为那个你想成为的人」——
  即你的决策系统和执行系统是否一致。

三阶段闭环（用户设计，2026-08-05）：
  Plan   (交易前) → 写交易计划，落位 trade_execution 的 E3 字段
  Trade  (交易中) → 只记录「有没有按计划」，不记录「赚没赚钱」
  Review (交易后) → 决策质量/执行质量/情绪管理 三星评分 + 复盘三问

核心新指标（用户提出）：
  信念兑现率 Belief Fulfillment Rate
  = 被市场证明方向正确、且真正持有兑现的交易 / 被市场证明方向正确的交易
  衡量「分析能力」与「信念兑现能力」的缺口，正是用户「70对/20兑现」洞察的工程化。

架构冻结合规：
  §1.1  Trader OS 永不做：不产买卖建议、不改 Layer1、不写 CIO、不盘中推送。
        本引擎只读写私有表 trader_reflection / trader_review 与 trade_execution(E3)，
        决策心理档案为「用户口述、AI 记录」，AI 不做任何心理诊断/人格标签/自动干预。
  §11   Capture > Analysis：Plan 录入 ≤60 秒，先拥有数据再分析。

用法：
  # 记录一条交易计划（Plan 阶段，≤60s）
  python trading_discipline_engine.py plan \
      --market MT5 --symbol XAUUSD --direction BUY \
      --hypothesis "日线下降趋势线突破，高低点结构改变" \
      --invalid "跌破3990 说明趋势判断错误" \
      --risk "最大接受亏损 X 元" \
      --signal A --scenario A --hold4h y --exit "3990 止损，4236 为目标"

  # 交易后回填（Trade→Review 衔接）
  python trading_discipline_engine.py executed <id> <exit_price> [exit_trigger] [exit_decision_state]
  python trading_discipline_engine.py skipped <id>

  # 录入复盘（Review 阶段）
  python trading_discipline_engine.py review <id> \
      --dq 5 --eq 3 --em 2 \
      --judgment y --execution n \
      --fear "4050 浮亏时害怕，提前平仓" \
      --improve "下次浮亏达痛阈前，机械按失效位持仓" \
      --deviation execution

  # 录入反思 / 心理档案（用户口述，AI 记录，非诊断）
  python trading_discipline_engine.py reflect \
      --date 2026-08-05 --title "黄金错过交易：从机会焦虑到系统复利" \
      --category trade_review --body-file docs/trading_coach/_tmp_gold.txt

  # 生成每日交易执行三问
  python trading_discipline_engine.py check <id>

  # 计算信念兑现率（基于 mt5_raw/trade_path.csv）
  python trading_discipline_engine.py belief --csv mt5_raw/trade_path.csv
"""
import argparse
import csv
import os
import sqlite3
import statistics
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "..", "database", "vibe_research.db")
REFLECTION_MD = os.path.join(HERE, "..", "..", "docs", "trading_coach", "reflections.md")

# 平仓层认知映射（与 trader_log.py 保持一致；自我报告，非诊断）
ET_MAP = {"a": "target", "b": "structure_break", "c": "time_exit",
          "d": "emotion_exit", "e": "protect_profit", "f": "other"}
EDS_MAP = {"a": "wrong_exit", "b": "pain_threshold", "c": "weak_exit",
           "d": "disoriented", "e": "other"}
SC_MAP = {"a": "A", "b": "B", "c": "C", "d": "D"}
SG_MAP = {"a": "A", "b": "B", "c": "C"}


def _con():
    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys=OFF")
    return con


def init():
    """建表：trader_reflection / trader_review；确保 trade_execution 存在。"""
    # 复用 trader_log 的 schema 初始化（含 E3 列迁移）
    import importlib.util
    spec = importlib.util.spec_from_file_location("trader_log", os.path.join(HERE, "..", "trader_log.py"))
    tl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tl)
    tl.init()

    con = _con()
    # 补列：risk_plan（最大可承受亏损，原引擎只打印没存）
    try:
        con.execute("ALTER TABLE trade_execution ADD COLUMN risk_plan TEXT")
    except sqlite3.OperationalError:
        pass  # 已存在
    # 盘中执行三问的持久化（原引擎只生成 prompt，不落库）
    con.execute("""
    CREATE TABLE IF NOT EXISTS trader_checkin (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id        INTEGER,
        rdate           TEXT NOT NULL,
        q1_logic_broken INTEGER,     -- 价格破坏原始逻辑? 1/0
        q1_note         TEXT,        -- 若破坏，记录什么破坏了逻辑
        q2_reason       TEXT,        -- A逻辑改变/B浮亏难受/C怕失去利润
        q3_pattern      TEXT,        -- 是否在重复过去模式
        note            TEXT,
        created_at      TEXT DEFAULT (datetime('now'))
    )
    """)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS trader_reflection (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        rdate       TEXT NOT NULL,
        title       TEXT NOT NULL,
        category    TEXT NOT NULL,   -- trade_review / psych_profile / insight
        body        TEXT NOT NULL,
        tags        TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS trader_review (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id        INTEGER,          -- 关联 trade_execution.id（可为 NULL=纯复盘）
        rdate           TEXT NOT NULL,
        decision_quality    INTEGER,      -- 决策质量 ★ 1-5
        execution_quality   INTEGER,      -- 执行质量 ★ 1-5
        emotion_management   INTEGER,      -- 情绪管理 ★ 1-5
        judgment_correct    INTEGER,      -- 判断正确? 1/0
        execution_correct   INTEGER,      -- 执行正确? 1/0
        fear_trigger        TEXT,         -- 什么时候产生恐惧
        improvement         TEXT,         -- 下一次如何处理
        deviation_reason    TEXT,         -- execution(执行偏离)/information(信息变化)/none
        close_reason        TEXT,         -- 平仓归因 A逻辑错误/B目标达成/C风险调整/D情绪退出
        created_at          TEXT DEFAULT (datetime('now'))
    );
    """)
    # 补列：close_reason（平仓归因枚举，Belief Execution Engine 新增）
    try:
        con.execute("ALTER TABLE trader_review ADD COLUMN close_reason TEXT")
    except sqlite3.OperationalError:
        pass  # 已存在
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# Plan 阶段（交易前）—— 落位 trade_execution 的 E3 字段，驱动 0%→100% 覆盖
# ---------------------------------------------------------------------------
def record_plan(market_type, symbol, direction, hypothesis, invalid_condition,
                risk_plan, signal_grade=None, expected_scenario=None,
                willing_hold_4h=None, planned_exit=None):
    """写入一条交易计划。exec_status='planned'，待 executed/skipped 回填。
    返回新计划 id。设计目标 ≤60s：参数化录入，无交互阻塞。"""
    con = _con()
    cur = con.execute(
        """INSERT INTO trade_execution
           (trade_date, market_type, symbol, direction, exec_status, planned,
            reason, signal_grade, expected_scenario, invalid_condition,
            risk_plan, willing_hold_4h, planned_exit, source)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (date.today().isoformat(), market_type.upper(), symbol, direction.upper(),
         "planned", 1, hypothesis,
         SG_MAP.get((signal_grade or "").lower()),
         SC_MAP.get((expected_scenario or "").lower()),
         invalid_condition, risk_plan,
         (1 if willing_hold_4h in ("y", "Y", True) else
          (0 if willing_hold_4h in ("n", "N", False) else None)),
         planned_exit, "discipline_plan"),
    )
    tid = cur.lastrowid
    con.commit()
    con.close()
    print("✅ 计划已记录 #%d  %s %s %s" % (tid, market_type.upper(), direction.upper(), symbol))
    print("   假设: %s" % hypothesis)
    print("   失效: %s" % invalid_condition)
    print("   风险: %s" % risk_plan)
    return tid


def record_checkin(tid, q1_logic_broken, q1_note="", q2_reason="", q3_pattern="", note=""):
    """盘中执行三问的持久化。只记录，不评价、不诊断（§1.1）。"""
    con = _con()
    con.execute(
        """INSERT INTO trader_checkin
           (trade_id, rdate, q1_logic_broken, q1_note, q2_reason, q3_pattern, note)
           VALUES (?,?,?,?,?,?,?)""",
        (int(tid) if tid else None, date.today().isoformat(),
         1 if q1_logic_broken in ("y", "Y", True) else 0,
         q1_note, q2_reason, q3_pattern, note),
    )
    con.commit()
    con.close()
    print("✅ 盘中三问已记录（计划 #%s）" % (tid or "—"))


def mark_executed(tid, exit_price, exit_trigger="", exit_decision_state=""):
    con = _con()
    con.execute(
        """UPDATE trade_execution
           SET exec_status='executed', exit_price=?, exit_trigger=?, exit_decision_state=?
           WHERE id=?""",
        (float(exit_price), ET_MAP.get((exit_trigger or "").lower()),
         EDS_MAP.get((exit_decision_state or "").lower()), int(tid)),
    )
    con.commit()
    con.close()
    print("✅ #%d 已执行，平仓 @%s" % (int(tid), exit_price))


def mark_skipped(tid):
    con = _con()
    con.execute("UPDATE trade_execution SET exec_status='skipped' WHERE id=?", (int(tid),))
    con.commit()
    con.close()
    print("✅ #%d 标记 skipped（计划未执行）" % int(tid))


# ---------------------------------------------------------------------------
# Trade 阶段（交易中）—— 每日三问，只问「有没有偏离计划」
# ---------------------------------------------------------------------------
def daily_check_prompt(tid):
    """生成每日交易执行三问（用户设计）。AI 只问，不评价、不诊断。"""
    con = _con()
    row = con.execute(
        "SELECT market_type, symbol, direction, reason, invalid_condition, planned_exit "
        "FROM trade_execution WHERE id=?", (int(tid),)
    ).fetchone()
    con.close()
    if not row:
        print("计划 #%s 不存在" % tid)
        return
    mt, sym, dr, hyp, inv, pe = row
    q = f"""
══════════════════════════════════════════
  交易执行三问 · 计划 #{tid}  {mt} {dr} {sym or ''}
══════════════════════════════════════════
  原始逻辑：{hyp or '（未填）'}
  失效条件：{inv or '（未填）'}
  退出计划：{pe or '（未填）'}

  Q1  当前价格变化是否破坏原始逻辑？
      否 → 继续，不动。
      是 → 记录什么破坏了逻辑，不靠感觉。

  Q2  我现在想平仓，是因为：
      A. 逻辑改变（对应 Q1=是）
      B. 浮亏难受
      C. 害怕失去利润
      若选 B / C → 记录，不执行。这是恐惧，不是信号。

  Q3  我是否正在重复过去模式？
      例如：连续三次小止损 → 提醒自己
      「你可能正在用短期波动否定长期判断。」
══════════════════════════════════════════
"""
    print(q)
    return q


# ---------------------------------------------------------------------------
# Review 阶段（交易后）—— 三星评分 + 复盘三问，评价「决策质量」非「赚亏」
# ---------------------------------------------------------------------------
def record_review(tid, decision_quality, execution_quality, emotion_management,
                  judgment_correct, execution_correct, fear_trigger="",
                  improvement="", deviation_reason="none", close_reason=""):
    con = _con()
    con.execute(
        """INSERT INTO trader_review
           (trade_id, rdate, decision_quality, execution_quality, emotion_management,
            judgment_correct, execution_correct, fear_trigger, improvement, deviation_reason,
            close_reason)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (int(tid) if tid else None, date.today().isoformat(),
         decision_quality, execution_quality, emotion_management,
         1 if judgment_correct in ("y", "Y", True) else 0,
         1 if execution_correct in ("y", "Y", True) else 0,
         fear_trigger, improvement, deviation_reason,
         (close_reason or "").upper()[:1] or None),
    )
    con.commit()
    con.close()
    print("✅ 复盘已记录：决策★%d 执行★%d 情绪★%d 平仓归因=%s" %
          (decision_quality, execution_quality, emotion_management, close_reason or "—"))


# ---------------------------------------------------------------------------
# 交易逻辑放弃率 Thesis Abandonment Rate —— Belief Execution Engine 核心新增指标
# ---------------------------------------------------------------------------
def thesis_abandonment_rate():
    """交易逻辑放弃率 = 情绪类退出(D) / 方向正确交易。

    按市场分组（join trade_execution 取 market_type）：
    - 股票 / MT5：方向正确 = trader_review.judgment_correct=1（用户事后判定方向对），分母可靠
    - 期货：MFE 近似使"方向正确"分母不可靠 → 同时给出 D占比 = D / 总复盘 作为近似版

    设计原则（诚实 NULL > 伪精确）：期货 TAR 标 approximate，仅 D占比 作参考。
    返回 {by_market:{MARKET:{n,dir_correct,d,tar,d_share}}, total:{...}}
    """
    con = _con()
    rows = con.execute(
        """SELECT t.market_type, r.judgment_correct, r.close_reason
           FROM trader_review r
           JOIN trade_execution t ON r.trade_id = t.id
           WHERE r.trade_id IS NOT NULL"""
    ).fetchall()
    con.close()
    markets = {}
    for mt, jc, cr in rows:
        m = markets.setdefault(mt, {"n": 0, "dir_correct": 0, "d": 0})
        m["n"] += 1
        if jc == 1:
            m["dir_correct"] += 1
        if (cr or "").upper() == "D":
            m["d"] += 1
    out = {"by_market": {}, "total": None}
    tot = {"n": 0, "dir_correct": 0, "d": 0}
    for mt, m in markets.items():
        tar = (m["d"] / m["dir_correct"]) if m["dir_correct"] else None
        d_share = (m["d"] / m["n"]) if m["n"] else None
        out["by_market"][mt] = {"n": m["n"], "dir_correct": m["dir_correct"], "d": m["d"],
                                "tar": tar, "d_share": d_share}
        tot["n"] += m["n"]; tot["dir_correct"] += m["dir_correct"]; tot["d"] += m["d"]
    if tot["dir_correct"]:
        out["total"] = {"n": tot["n"], "dir_correct": tot["dir_correct"], "d": tot["d"],
                        "tar": tot["d"] / tot["dir_correct"],
                        "d_share": tot["d"] / tot["n"] if tot["n"] else None}
    return out


# ---------------------------------------------------------------------------
# 反思 / 交易心理档案 —— 用户口述，AI 记录（非诊断、非人格标签）
# ---------------------------------------------------------------------------
def record_reflection(rdate, title, category, body, tags=None):
    """记录用户口述的反思或心理档案条目。AI 原样保存，不做任何分析/诊断。"""
    con = _con()
    cur = con.execute(
        "INSERT INTO trader_reflection (rdate, title, category, body, tags) VALUES (?,?,?,?,?)",
        (rdate, title, category, body, tags),
    )
    rid = cur.lastrowid
    con.commit()
    con.close()
    _append_md(rdate, title, category, body)
    print("✅ 反思已记录 #%d  分类=%s  标题=%s" % (rid, category, title))
    return rid


def _append_md(rdate, title, category, body):
    os.makedirs(os.path.dirname(REFLECTION_MD), exist_ok=True)
    block = "\n## %s · %s  [%s]\n\n%s\n\n---\n" % (rdate, title, category, body)
    with open(REFLECTION_MD, "a", encoding="utf-8") as f:
        f.write(block)
    print("   ↳ 已镜像至 %s" % REFLECTION_MD)


def list_reflections(limit=20):
    con = _con()
    rows = con.execute(
        "SELECT id, rdate, title, category FROM trader_reflection ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    con.close()
    if not rows:
        print("（暂无反思记录）")
        return
    print("\n反思/心理档案（最近 %d 条）:" % len(rows))
    for r in rows:
        print("  #%d %s  [%s]  %s" % (r[0], r[1], r[2], r[3]))


def get_today_plan():
    """返回今日未执行的计划（供轻量入口盘中展示）。无则 None。"""
    con = _con()
    row = con.execute(
        "SELECT id, market_type, symbol, direction, reason, invalid_condition, "
        "risk_plan, planned_exit, willing_hold_4h, signal_grade "
        "FROM trade_execution WHERE trade_date=? AND exec_status='planned' "
        "ORDER BY id DESC LIMIT 1",
        (date.today().isoformat(),),
    ).fetchone()
    con.close()
    if not row:
        return None
    keys = ["id", "market_type", "symbol", "direction", "reason", "invalid_condition",
            "risk_plan", "planned_exit", "willing_hold_4h", "signal_grade"]
    return dict(zip(keys, row))


def get_history(limit=15):
    """聚合最近计划/复盘/反思，供轻量入口「我的数据」展示。"""
    con = _con()
    plans = con.execute(
        "SELECT id, trade_date, market_type, symbol, direction, exec_status "
        "FROM trade_execution ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    reviews = con.execute(
        "SELECT id, trade_id, rdate, decision_quality, execution_quality, "
        "emotion_management, deviation_reason FROM trader_review ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    reflections = con.execute(
        "SELECT id, rdate, title, category FROM trader_reflection ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    con.close()
    return {"plans": plans, "reviews": reviews, "reflections": reflections}


# ---------------------------------------------------------------------------
# 信念兑现率 Belief Fulfillment Rate —— 把「70对/20兑现」假设变成真实数字
# ---------------------------------------------------------------------------
def belief_fulfillment_rate(csv_path):
    """基于 trade_path.csv（mt5_raw）计算：
      方向正确   = mfe_usd > 0（市场曾在你入场方向给过有利波动，证明你没看错）
      信念兑现   = 方向正确 且 mfe_capture_ratio >= 0.5（你真的拿到了至少一半的机会）
      信念兑现率 = 信念兑现 / 方向正确
    这是「分析能力」与「信念兑现能力」的缺口量化，正是用户核心洞察的工程化。
    """
    if not os.path.exists(csv_path):
        print("❌ 找不到 %s" % csv_path)
        return
    rows = []
    with open(csv_path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                r["mfe_usd"] = float(r.get("mfe_usd") or 0)
                r["mfe_capture_ratio"] = float(r.get("mfe_capture_ratio") or 0)
                r["pnl"] = float(r.get("pnl") or 0)
                r["pol"] = float(r.get("pol") or 0)
                rows.append(r)
            except ValueError:
                continue
    total = len(rows)
    if total == 0:
        print("❌ 无数据")
        return
    direction_correct = [r for r in rows if r["mfe_usd"] > 0]
    belief_fulfilled = [r for r in direction_correct if r["mfe_capture_ratio"] >= 0.5]
    n_dc = len(direction_correct)
    n_bf = len(belief_fulfilled)

    direction_acc = n_dc / total
    bfr = n_bf / n_dc if n_dc else 0.0

    # 方向正确但被「出场管理」吃掉的笔数（path_archetype=C）
    mismanaged = [r for r in direction_correct if r.get("path_archetype") == "C_exit_management"]
    # 方向正确但 POL（盈利机会损失率）>1 的笔数：不仅没拿到，还倒吐
    pol_leak = [r for r in direction_correct if r["pol"] > 1]
    # 方向正确交易留在桌上的总机会（MFE 未被捕获部分）
    left_on_table = sum(r["mfe_usd"] * (1 - max(r["mfe_capture_ratio"], 0)) for r in direction_correct)

    print("\n════════════════════════════════════════════════════")
    print("  信念兑现率 · 基于 %s" % os.path.basename(csv_path))
    print("════════════════════════════════════════════════════")
    print("  总交易笔数          : %d" % total)
    print("  方向被市场证明正确  : %d  (方向正确率 %.1f%%)" % (n_dc, direction_acc * 100))
    print("  其中真正信念兑现    : %d  (capture ≥ 0.5)" % n_bf)
    print("  ────────────────────────────────────────────")
    print("  ★ 信念兑现率        : %.1f%%" % (bfr * 100))
    print("  方向正确但未兑现    : %d 笔 (你看了对，却没拿到)" % (n_dc - n_bf))
    print("    其中出场管理失当  : %d 笔 (path_archetype=C)" % len(mismanaged))
    print("    其中机会转负收益  : %d 笔 (POL>1，浮盈倒吐)" % len(pol_leak))
    print("  方向正确交易留在桌上: %.2f USD（未被捕获的 MFE）" % left_on_table)
    print("════════════════════════════════════════════════════")
    print("  解读：信念兑现率越低，说明漏损在『执行/持有』而非『分析』。")
    print("  若方向正确率很高但信念兑现率低 → 你的瓶颈是执行层，不是判断层。")
    return {
        "total": total, "direction_correct": n_dc, "direction_accuracy": direction_acc,
        "belief_fulfilled": n_bf, "belief_fulfillment_rate": bfr,
        "left_on_table_usd": left_on_table,
    }


# ---------------------------------------------------------------------------
# 执行智能四分类 + 三个核心指标（用户 2026-08-06 提议，Execution Intelligence）
# ---------------------------------------------------------------------------
def abcd_analysis(csv_path):
    """把交易按「方向正确性 × 结果」拆成四类，并算三个执行智能指标：
      A 方向错，正常止损      (mfe_usd <= 0)
      B 方向对，正常盈利      (mfe>0 且 capture >= 0.5)
      C 方向对，提前退出(小赚) (mfe>0, capture<0.5, pnl>=0)
      D 方向对，盈利后倒亏    (mfe>0, capture<0.5, pnl<0)
    三个指标：
      Thesis Survival Rate 交易逻辑存活率 = 方向正确率
      Profit Capture Ratio  利润捕获率     = 方向正确交易 capture 中位
      Premature Exit Rate   提前退出率     = (C+D)/方向正确
    返回 dict（供轻量入口仪表盘常驻展示）。
    """
    if not os.path.exists(csv_path):
        print("❌ 找不到 %s" % csv_path)
        return None
    rows = []
    with open(csv_path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                r["mfe"] = float(r.get("mfe_usd") or 0)
                r["pnl"] = float(r.get("pnl") or 0)
                r["cap"] = float(r.get("mfe_capture_ratio") or 0)
                rows.append(r)
            except ValueError:
                continue
    total = len(rows)
    if total == 0:
        print("❌ 无数据")
        return None
    A = [r for r in rows if r["mfe"] <= 0]
    dc = [r for r in rows if r["mfe"] > 0]
    B = [r for r in dc if r["cap"] >= 0.5]
    rest = [r for r in dc if r["cap"] < 0.5]
    D = [r for r in rest if r["pnl"] < 0]
    C = [r for r in rest if r["pnl"] >= 0]
    caps_dc = [r["cap"] for r in dc]
    left_C = sum(r["mfe"] * (1 - max(r["cap"], 0)) for r in C)
    mfe_D = sum(r["mfe"] for r in D)
    pnl_D = sum(r["pnl"] for r in D)
    out = {
        "total": total,
        "A": len(A), "B": len(B), "C": len(C), "D": len(D),
        "direction_correct": len(dc),
        "thesis_survival_rate": len(dc) / total,
        "cd_rate": (len(C) + len(D)) / total,
        "premature_exit_rate": (len(C) + len(D)) / len(dc) if dc else 0,
        "capture_median_dc": statistics.median(caps_dc) if caps_dc else 0,
        "left_on_table_C_usd": left_C,
        "mfe_created_D_usd": mfe_D,
        "net_D_usd": pnl_D,
        "evaporated_D_usd": mfe_D - pnl_D,
        "belief_fulfilled": len(B),
        "belief_target_40_need": int(0.40 * len(dc)) - len(B),
    }
    print("\n══════════════════════════════════════════════════")
    print("  执行智能四分类 · 基于 %s" % os.path.basename(csv_path))
    print("══════════════════════════════════════════════════")
    print("  A 方向错正常止损    : %3d  (%.1f%%)" % (len(A), len(A)/total*100))
    print("  B 方向对正常盈利    : %3d  (%.1f%%)" % (len(B), len(B)/total*100))
    print("  C 方向对提前退出    : %3d  (%.1f%%)" % (len(C), len(C)/total*100))
    print("  D 方向对盈利后倒亏  : %3d  (%.1f%%)" % (len(D), len(D)/total*100))
    print("  ────────────────────────────────────────────────")
    print("  ★ C+D 合计          : %3d  (%.1f%%)  ← 假设>80%% 已验证" % (len(C)+len(D), (len(C)+len(D))/total*100))
    print("  逻辑存活率          : %.1f%%" % (len(dc)/total*100))
    print("  利润捕获率(中位)    : %.2f" % out["capture_median_dc"])
    print("  提前退出率          : %.1f%%" % (out["premature_exit_rate"]*100))
    print("  D 类浮盈蒸发        : %.0f USD (创 %.0f → 实 %.0f)" % (out["evaporated_D_usd"], mfe_D, pnl_D))
    print("══════════════════════════════════════════════════")
    return out


# ---------------------------------------------------------------------------
def main():
    if not os.path.exists(DB):
        print("DB 不存在:", DB)
        return
    init()
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("plan")
    p.add_argument("--market", required=True)
    p.add_argument("--symbol", required=True)
    p.add_argument("--direction", required=True)
    p.add_argument("--hypothesis", required=True)
    p.add_argument("--invalid", required=True)
    p.add_argument("--risk", required=True)
    p.add_argument("--signal", default="")
    p.add_argument("--scenario", default="")
    p.add_argument("--hold4h", default="")
    p.add_argument("--exit", default="")

    e = sub.add_parser("executed")
    e.add_argument("tid"); e.add_argument("price"); e.add_argument("trigger", nargs="?", default="")
    e.add_argument("eds", nargs="?", default="")

    s = sub.add_parser("skipped"); s.add_argument("tid")

    c = sub.add_parser("check"); c.add_argument("tid")

    rv = sub.add_parser("review"); rv.add_argument("tid")
    rv.add_argument("--dq", type=int, required=True)
    rv.add_argument("--eq", type=int, required=True)
    rv.add_argument("--em", type=int, required=True)
    rv.add_argument("--judgment", default="y")
    rv.add_argument("--execution", default="y")
    rv.add_argument("--fear", default="")
    rv.add_argument("--improve", default="")
    rv.add_argument("--deviation", default="none")

    rf = sub.add_parser("reflect")
    rf.add_argument("--date", required=True)
    rf.add_argument("--title", required=True)
    rf.add_argument("--category", required=True)
    rf.add_argument("--body", default="")
    rf.add_argument("--body-file", default="")
    rf.add_argument("--tags", default="")

    sub.add_parser("list")

    bf = sub.add_parser("belief"); bf.add_argument("--csv", required=True)
    ab = sub.add_parser("abcd"); ab.add_argument("--csv", required=True)

    args = ap.parse_args()
    if args.cmd == "plan":
        record_plan(args.market, args.symbol, args.direction, args.hypothesis,
                     args.invalid, args.risk, args.signal, args.scenario, args.hold4h, args.exit)
    elif args.cmd == "executed":
        mark_executed(args.tid, args.price, args.trigger, args.eds)
    elif args.cmd == "skipped":
        mark_skipped(args.tid)
    elif args.cmd == "check":
        daily_check_prompt(args.tid)
    elif args.cmd == "review":
        record_review(args.tid, args.dq, args.eq, args.em, args.judgment,
                      args.execution, args.fear, args.improve, args.deviation)
    elif args.cmd == "reflect":
        body = args.body
        if args.body_file:
            with open(args.body_file, encoding="utf-8") as fh:
                body = fh.read()
        record_reflection(args.date, args.title, args.category, body, args.tags)
    elif args.cmd == "list":
        list_reflections()
    elif args.cmd == "belief":
        belief_fulfillment_rate(args.csv)
    elif args.cmd == "abcd":
        abcd_analysis(args.csv)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
