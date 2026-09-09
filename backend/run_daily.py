# -*- coding: utf-8 -*-
"""
每日流水线（Trading OS 日更入口）
===========================================================
把三步串成一条命令：
  step1  daily_collect.py            -> Data OS 统一采集（板块主线 + 市值回填）
  step2  decision_tree.py            -> 计算 L1-L5 + 情绪验证 + 每日方向·验证简报(L4/L5+sentiment综合)，写 decision_tree.html/json；
                                       L6 交易执行仅为边界声明(价格行为归用户人工)，系统不输出突破候选
  step2c relationship_engine.py      -> 关系/规律引擎：A股内部自动相关性+状态机，维护"今日新发现/假设"规律库
  step2d cro_agent.py                -> CRO 总裁定词：编排 Flow/Gold/Relationship/Sector 引擎，每日三问（交易/边际/规律）
  step2e narrative_engine.py         -> Narrative Engine：板块「为什么」因果链（实时新闻+产业链逻辑+情绪判定）
  step1c omi/run_omi.py           -> 期权观察层 OMI v0.1（Observation Only：仅采集/存原始链/算IV/Skew/Rank，
                                     不参与任何 IC/CIO 评分；失败仅记录，不影响主流水线）
  step3  notify/push_daily.py        -> 推送看板到企业微信/飞书/公众号（未配置渠道则自动跳过）

用法：
  python run_daily.py
  python run_daily.py --only decision   # 只跑决策树（用已有 sector_mainline.json）
  python run_daily.py --skip-step1      # 不重抓板块数据
  python run_daily.py --no-push         # 不推送看板

说明：
  - 用独立子进程调用每个脚本，单步失败不影响整体（会在日志中标记 FAIL 并继续）。
  - step1 已知同花顺偶发 403，内置 1 次重试；失败自动降级到本地 industry_map×stock_daily 聚合。
  - 运行日志写 output/run_daily.log.json + output/run_daily.log.txt。
"""
from db import get_conn, _DB_PATH
import os
import sys
import json
import argparse
import subprocess
import datetime
import time
import sqlite3

from data_freshness import build as _build_freshness

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "output")
# 优先使用 venv Python（akshare/pandas 等装在 venv 中）
_VENV_PY = "C:/Users/LIU/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
PY = _VENV_PY if os.path.exists(_VENV_PY) else sys.executable

# 步骤元组：(名称, 脚本, 重试次数, critical)
#   critical=True  → 失败即中断整条链（后续步骤不再执行，overall_ok=False）
#   critical=False → 失败仅记录并继续（不阻断，但必须在日志中可见）
#
# ── 为什么需要 critical（P0-A2, 2026-09-03）──────────────────────────────
# 旧逻辑只有 `overall_ok = overall_ok and r["ok"]`，没有 break：step2b 简报失败后
# step3 推送照跑，produce() 读到上一交易日的 brain_report.json 缓存，把旧数据当
# 新数据推送出去。2026-08-31「广度 55% 实为 08-28 值」事故的确切通道就在这里。
#
# 判据：凡是「产出或承载当日生产数据」的步骤 = critical；
#       凡是「富化/观察/分发」的步骤 = 非 critical（失败应可见，但不必停摆）。
#   step2b2 Ledger 归为 critical：Phase 1E 治理要求决策必须有 provenance，
#       没有 Ledger 记录的决策不满足审计要求，因此不允许悄悄产出。
STEPS = [
    ("step1_数据采集", "daily_collect.py", 2, True),             # Data OS：板块主线+市值回填（统一采集入口）
    ("step1b_技术回填", "tech_fill.py", 0, True),                # 本地回填 high_20d/ma/量比：确保 latest_date() 推进到最新交易日（防日期卡死）
    ("step1b2_派生表补齐", "build_derived_tables.py", 0, True),  # 本地从 stock_daily 聚合 sector_daily/market_daily/limit_up_daily；必须在 tech_fill 之后（sector_daily.cm20_count 依赖 ma20），幂等自守卫
    ("step2_八层决策树", "decision_tree.py", 0, True),
    ("step2b_决策简报(总指挥)", "run_brain_report.py", 0, True), # brain 推理链+L0叙事+决策结论
    ("step2b2_Ledger记录", "write_decision_ledger.py", 0, True), # v0.2 Phase 1B/1C：Decision Ledger 独立步骤（读既有 brain_report，run_id 幂等，不重复写）
    ("step2c_关系规律", "relationship_engine.py", 0, False),     # Relationship&Observation Engine：自动相关性+规律库
    ("step2d_CRO裁定", "cro_agent.py", 0, False),                # CRO 总裁定词：编排各引擎，每日三问（交易/边际/规律）
    ("step2e_为什么引擎", "narrative_engine.py", 0, False),      # Narrative Engine：板块「为什么」因果链（实时新闻+产业链逻辑）
    ("step2f_资金迁移", "capital_migration.py", 0, False),       # Capital Migration Engine：板块轮动+跨资产闭环+反证树，落盘每日快照
    ("step3_推送看板", "notify/push_daily.py", 0, False),        # 企业微信/飞书/公众号；无配置则自动跳过
]

# OMI 期权观察层：Observation Only，独立于评分系统，失败不影响主流水线。
# 不作为 STEPS 成员（避免单步 FAIL 翻转 overall_ok），单独在 STEPS 之后执行并记日志。
OMI_STEP = ("step1c_期权观测OMI", os.path.join("omi", "run_omi.py"))


def run_script(script, retries=0, timeout=900):
    path = os.path.join(ROOT, script)
    if not os.path.exists(path):
        return {"ok": False, "returncode": -1, "secs": 0,
                "tail": f"脚本不存在: {path}"}
    attempt = 0
    last = None
    while attempt <= retries:
        attempt += 1
        t0 = datetime.datetime.now()
        try:
            proc = subprocess.run([PY, path], cwd=ROOT,
                                  capture_output=True, text=True, timeout=timeout)
            dt = (datetime.datetime.now() - t0).total_seconds()
            out = (proc.stdout + "\n" + proc.stderr)[-2000:]
            last = {"ok": proc.returncode == 0, "returncode": proc.returncode,
                    "secs": round(dt, 1), "tail": out.strip()}
            if last["ok"] or attempt > retries:
                last["attempt"] = attempt
                return last
            print(f"  [重试 {attempt}/{retries}] {script} rc={proc.returncode}", flush=True)
        except subprocess.TimeoutExpired:
            last = {"ok": False, "returncode": -9, "secs": timeout,
                    "tail": f"TIMEOUT {timeout}s", "attempt": attempt}
            if attempt > retries:
                return last
        except Exception as e:  # noqa
            last = {"ok": False, "returncode": -2, "secs": -1,
                    "tail": repr(e), "attempt": attempt}
            if attempt > retries:
                return last
    return last


def wait_for_today_ready(max_attempts=6, backoff=20):
    """数据就绪门：step1 采集完、step1b 技术回填前，确认最新交易日 stock_daily 已写满。

    背景（2026-08-27 修复）：15:30 收盘后 TDX/akshare 当日数据有 15~60 分钟晚到窗口，
    若 step1 在 stock_daily 当日行未写满时就结束、step1b(tech_fill) 提前跑，当日 ma20 会
    是 NULL，进而 step1b2(build_derived_tables) 命中 ma20 检查、把派生表缺口永久留到次日。
    本门在 step1b 前循环探测「最新交易日 stock_daily 行数 ≥ 4000」，带有限退避重试，
    吸收数据晚到；达最大重试仍不足则放行后续步骤（派生表靠 build_derived 的延后机制自愈）。

    仅校验行数（数据是否写完），不校验 ma20——ma20 就绪由 tech_fill 负责，缺失则由
    build_derived 的非致命延后逻辑兜底，避免新上市股 ma20 合法为空导致本门死等。
    """
    db = str(_DB_PATH)
    for i in range(max_attempts):
        td, cnt = None, 0
        try:
            conn = get_conn(timeout=30)
            td = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
            if td:
                cnt = conn.execute(
                    "SELECT COUNT(*) FROM stock_daily WHERE date=?", (td,)
                ).fetchone()[0]
            conn.close()
        except Exception as e:  # noqa
            print(f"[就绪门] 查库失败（{e}），第 {i+1}/{max_attempts} 次重试", flush=True)
        if td and cnt >= 4000:
            print(f"[就绪门] 最新交易日 {td} 已采集 {cnt} 行（≥4000），数据就绪，进入技术回填。",
                  flush=True)
            return True
        print(f"[就绪门] 最新交易日 {td or '?'} 仅 {cnt} 行（<4000），等待数据写完…"
              f"（{i+1}/{max_attempts}，{backoff}s 后重试）", flush=True)
        if i < max_attempts - 1:
            time.sleep(backoff)
    print("[就绪门] 达最大重试仍 <4000 行，继续后续步骤（派生表会在 ma20 就绪后自动补齐）。",
          flush=True)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["decision"], help="只跑决策树（用已有 sector_mainline.json）")
    ap.add_argument("--skip-step1", action="store_true", help="不重抓板块数据")
    ap.add_argument("--no-push", action="store_true", help="不推送看板（跳过 step3）")
    ap.add_argument("--memo-only", action="store_true",
                    help="只写本地备忘录 HTML（push_daily --dry-run），不推送看板")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    log = {"started_at": datetime.datetime.now().isoformat(timespec="seconds"),
           "args": vars(args), "steps": []}
    overall_ok = True

    steps = STEPS
    if args.only == "decision" or args.skip_step1:
        # 只跳过外部采集 step1；step1b 是纯本地技术回填，必须保留。
        # 2026-08-10 事故：前缀匹配 startswith("step1") 把 step1b 一起跳掉 → high_20d 未回填
        # → decision_tree.latest_date() 要求「high_20d IS NOT NULL 且当日>4000行」才算完整交易日
        # → 决策树/简报日期卡死在 T-1（08-07），日报据此空算。
        steps = [s for s in STEPS if s[0] != "step1_数据采集"]
    if args.no_push or args.memo_only:
        steps = [s for s in steps if s[0] != "step3_推送看板"]

    for _idx, (name, script, retries, critical) in enumerate(steps):
        # 数据就绪门：step1 采集完、step1b 技术回填前，确认最新交易日已写满。
        # 吸收 15:30 收盘后数据晚到窗口，避免 tech_fill/build_derived 在当日 ma20 还是 NULL 时跑。
        if name == "step1b_技术回填":
            wait_for_today_ready()
        print(f"\n========== {name} ({script}){'  [CRITICAL]' if critical else ''} ==========",
              flush=True)
        r = run_script(script, retries=retries)
        r["step"] = name
        r["script"] = script
        r["critical"] = critical
        log["steps"].append(r)
        overall_ok = overall_ok and r["ok"]
        status = "OK" if r["ok"] else "FAIL"
        print(f"[{status}] {name} 耗时{r.get('secs')}s rc={r.get('returncode')} "
              f"attempt={r.get('attempt')}", flush=True)
        if r.get("tail"):
            print(r["tail"][-1000:], flush=True)

        if not r["ok"] and critical:
            # ── fail-fast（P0-A2）：关键步失败即中断 ──────────────────────
            # 后续步骤必须在「上游数据已被证明新鲜完整」的前提下才能运行。
            # 否则 step3 推送会读到上一交易日的缓存，把旧数据当新数据发出去。
            skipped = [s[0] for s in steps[_idx + 1:]]
            log["aborted_at"] = name
            log["skipped_steps"] = skipped
            print("\n" + "=" * 72, flush=True)
            print(f"❌ 关键步骤失败，中断整条流水线：{name}", flush=True)
            print(f"   rc={r.get('returncode')}  (retries={retries})", flush=True)
            if skipped:
                print(f"   已跳过后续步骤：{', '.join(skipped)}", flush=True)
            print("   原因：关键步失败后继续运行，下游会读到上一交易日的缓存数据并当作",
                  flush=True)
            print("         当日结果推送。按「宁可失败，也绝不悄悄产出错误结果」原则中断。",
                  flush=True)
            print("=" * 72, flush=True)
            break

    # === OMI 期权观察层 (Observation Only) ===
    # 独立于 IC/CIO 评分：无论成功失败，只记录观测状态，绝不翻转 overall_ok。
    # --only decision / --skip-step1 时不跑（那是快速复用缓存数据场景，不该触发外部采集）。
    if not (args.only == "decision" or args.skip_step1):
        try:
            _omi_name, _omi_script = OMI_STEP
            print(f"\n========== {_omi_name} ({_omi_script}) [Observation Only] ==========",
                  flush=True)
            _omi = run_script(_omi_script, retries=0)
            _omi["step"] = _omi_name
            log["omi"] = _omi
            print(f"[{'OK' if _omi['ok'] else 'FAIL'}] {_omi_name} "
                  f"rc={_omi.get('returncode')} #(Observation Only, 不影响主流水线)", flush=True)
            if _omi.get("tail"):
                print(_omi["tail"][-800:], flush=True)
            # 提取 "OMI 汇总 ok=N stale=N other=N total=N" 行，供一眼扫过
            _summary = None
            for _ln in (_omi.get("tail") or "").splitlines():
                if _ln.startswith("[OMI] 汇总"):
                    _summary = _ln.strip()
                    break
            if _summary:
                log["omi"]["summary"] = _summary
                print(f"\n📊 {_summary}  (Observation Only，未进入评分)", flush=True)
        except Exception as e:  # noqa
            log["omi"] = {"ok": False, "error": repr(e)}

    # --memo-only：写出本地备忘录 HTML（push_daily --dry-run，不推送）
    if args.memo_only:
        print("\n========== step3b_写备忘录HTML (--memo-only) ==========", flush=True)
        try:
            _mp = subprocess.run([PY, os.path.join(ROOT, "notify", "push_daily.py"), "--dry-run"],
                                 cwd=ROOT, capture_output=True, text=True, timeout=900)
            print((_mp.stdout + "\n" + _mp.stderr)[-1500:])
            log["memo_only"] = _mp.returncode == 0
        except Exception as e:  # noqa
            log["memo_only"] = f"ERR {repr(e)[:120]}"

    log["finished_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    log["overall_ok"] = overall_ok

    # 数据新鲜度矩阵：全数据源新鲜度检查（替代旧 date_guard）
    try:
        fr = _build_freshness(write=True)
        log["freshness"] = fr
        health = fr.get("health", "UNKNOWN")
        stale_count = fr.get("stale_count", 0)
        aging_count = fr.get("aging_count", 0)
        alerts = fr.get("alerts", [])
        # 保留 backward compat：旧日志键
        log["date_guard"] = f"freshness:{health} stal:{stale_count} aging:{aging_count}"
        if health == "HEALTHY":
            print(f"[数据新鲜度] ✅ HEALTHY (stal:{stale_count} aging:{aging_count})", flush=True)
        elif health == "WATCH":
            print(f"[数据新鲜度] ⚠️ WATCH — {aging_count} 源接近过期", flush=True)
            for a in alerts[:3]:
                print(f"  → {a}", flush=True)
        else:
            print(f"[数据新鲜度] 🔴 STALE — {stale_count} 源已过期！", flush=True)
            for a in alerts[:5]:
                print(f"  → {a}", flush=True)
    except Exception as e:
        log["date_guard"] = f"freshness ERR {repr(e)[:120]}"
        log["freshness"] = {"error": str(e)}
        print(f"[数据新鲜度] ❌ 矩阵构建失败: {e}", flush=True)

    # 自动归档 brain 报告（带日期戳，供回测追踪用）
    brain_json = os.path.join(OUT, "brain_report.json")
    if os.path.exists(brain_json):
        try:
            with open(brain_json, "r", encoding="utf-8") as f:
                _br = json.load(f)
            _td = _br.get("trade_date", datetime.date.today().isoformat())
            _archive_dir = os.path.join(OUT, "archive")
            os.makedirs(_archive_dir, exist_ok=True)
            _dst = os.path.join(_archive_dir, f"brain_report_{_td}.json")
            if not os.path.exists(_dst):
                import shutil
                shutil.copy2(brain_json, _dst)
                print(f"[归档] brain_report_{_td}.json -> archive/", flush=True)
                log["archived"] = _dst
        except Exception:
            pass  # 归档失败不影响主流程

    # 产物校验
    html = os.path.join(OUT, "decision_tree.html")
    brain_html = os.path.join(OUT, "brain_report.html")
    log["artifact"] = {
        "html": html if os.path.exists(html) else None,
        "html_mtime": (datetime.datetime.fromtimestamp(os.path.getmtime(html)).isoformat(timespec="seconds")
                       if os.path.exists(html) else None),
        "brain_html": brain_html if os.path.exists(brain_html) else None,
        "brain_html_mtime": (datetime.datetime.fromtimestamp(os.path.getmtime(brain_html)).isoformat(timespec="seconds")
                             if os.path.exists(brain_html) else None),
    }

    # 写日志
    with open(os.path.join(OUT, "run_daily.log.json"), "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT, "run_daily.log.txt"), "w", encoding="utf-8") as f:
        f.write(f"run_daily {log['started_at']} -> {log['finished_at']}  overall_ok={overall_ok}\n")
        for s in log["steps"]:
            f.write(f"  [{'OK' if s['ok'] else 'FAIL'}] {s['step']} ({s['script']}) "
                    f"{s.get('secs')}s rc={s.get('returncode')} attempt={s.get('attempt')}\n")
        f.write(f"  artifact: {log['artifact'].get('html')} mtime={log['artifact'].get('html_mtime')}\n")

    print(f"\n========== 流水线结束 overall_ok={overall_ok} ==========", flush=True)
    print(f"日志: {os.path.join(OUT, 'run_daily.log.json')}", flush=True)
    # 非 0 退出码，便于外部调度感知失败
    sys.exit(0 if overall_ok else 1)


if __name__ == "__main__":
    main()
