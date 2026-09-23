# -*- coding: utf-8 -*-
"""
fill_daily_quotes.py — 个股日线东财兜底抓取（Data OS）

背景：
  stock_daily 个股日线历史上由 tdx_daily_import.py 从通达信 vipdoc 导入。
  沙箱/无通达信环境无 vipdoc，tdx_daily_import 直接跳过 → 新交易日个股行情进不来。
  本脚本用东财 push2delay 批量快照接口兜底，把指定交易日全 A 股 OHLCV+市值+换手
  抓回并 upsert 进 stock_daily，使日报/决策层在沙箱也能跑通。

数据源：push2delay.eastmoney.com/api/qt/clist/get
  字段：f12=代码 f14=名称 f2=最新价(收盘) f3=涨跌幅% f15=最高 f16=最低 f17=今开
        f5=成交量(手) f6=成交额(元) f20=总市值(元) f21=流通市值(元) f8=换手率(%)
  注：①主域 push2 被沙箱代理拦截，改用 push2delay 可直连；
      ②用 urllib 显式无代理 opener 强制不走系统死代理（同 fill_stock_flow）。

用法：
  python fill_daily_quotes.py                 # 抓今天
  python fill_daily_quotes.py 2026-07-21     # 抓指定交易日

说明：
  - 分页步长固定 100（push2delay 强制上限）。
  - amount 单位统一为亿元（÷1e8），volume 单位股（手×100），与既有 stock_daily 一致。
  - UPSERT（ON CONFLICT DO UPDATE）只更新价格/市值列，保留 high_20d 等技术列（tech_fill 回填）。
  - 北交所(920 新代码)经 `m:0+t:81` 可覆盖；Step 4(R2) 写入前用 **920-only ingestion predicate**
    过滤，拒绝 83/87/874/875/899 等非当前 BSE 上市代码，并落
    raw/accepted/rejected/by_exchange 审计日志 + 漂移门（详见模块底部 helpers）。
"""
from __future__ import annotations
from db import get_conn, _DB_PATH
from universe import is_stock, market_of
from ingest_lock import require_lease   # L1 Single Writer · session lease（CIO 裁定 Q1-A'）

import os
import sys
import time
import json
import uuid
import sqlite3
import urllib.request
import urllib.parse
import datetime
from pathlib import Path

DB = str(_DB_PATH)
PZ = 100
TIMEOUT = 20
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://quote.eastmoney.com/",
}
SOURCE = "eastmoney_push2"

_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _clear_proxy():
    for k in ("http_proxy", "https_proxy", "all_proxy",
              "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
              "no_proxy", "NO_PROXY"):
        os.environ.pop(k, None)


def _fetch_page(pn: int):
    """拉一页当日快照 → (list[dict(f12,f14,f2,f3,f15,f16,f17,f5,f6,f20,f21,f8)], provider_total|None)。

    provider_total 取自 EastMoney `data.total`，供 Step 4B 分页完整性 FAIL-LOUD 校验
    （抓取数 < 报告总数 → 异常终止/缺页，禁止部分提交）。
    """
    fs = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81"  # 沪A/深A/科创/创业/北交所(920)
    fields = "f12,f14,f2,f3,f15,f16,f17,f5,f6,f20,f21,f8"
    url = (f"https://push2delay.eastmoney.com/api/qt/clist/get"
           f"?pn={pn}&pz={PZ}&po=1&np=1&fltt=2&invt=2&fid=f3"
           f"&fs={urllib.parse.quote(fs)}&fields={fields}")
    req = urllib.request.Request(url, headers=HEADERS)
    raw = _NO_PROXY_OPENER.open(req, timeout=TIMEOUT).read().decode("utf-8", "ignore")
    j = json.loads(raw)
    data = j.get("data") or {}
    diff = data.get("diff") or []
    total = data.get("total")
    out = []
    for it in diff:
        code = (it.get("f12") or "").strip()
        if not code:
            continue
        out.append({
            "code": code,
            "name": (it.get("f14") or "").strip(),
            "close": _f(it.get("f2")),
            "pct": _f(it.get("f3")),
            "high": _f(it.get("f15")),
            "low": _f(it.get("f16")),
            "open": _f(it.get("f17")),
            "vol_hand": _f(it.get("f5")),     # 手
            "amount_yuan": _f(it.get("f6")),  # 元
            "mcap_yuan": _f(it.get("f20")),   # 元
            "fcap_yuan": _f(it.get("f21")),   # 元
            "turnover": _f(it.get("f8")),     # %
        })
    return out, total


def _f(v):
    try:
        if v is None or v == "-":
            return None
        return float(v)
    except Exception:
        return None


# ── Step 4 (Governance R2, 2026-09-11) · BSE 920-only ingestion predicate ──
# provider-ingestion 层针对「当前行情数据」的更严格资格门；
# **不是**对 universe.py / C10 的重新定义（universe.py 不动）。
# 依据：北交所存量上市股票自 2025-10-09 全面切换 920 代码；
# 83/87 为 NEEQ 挂牌及历史 BSE 旧代码混合、874/875 为 NEEQ 挂牌，均不得作当前 BSE 上市成员。
BSE_PREFIX = "920"
# 漂移层相对阈值（%）：成员数量用相对规则，绝不硬编码绝对成员数（对齐 U1）。
BSE_DRIFT_MAX_PCT = 20.0
_AUDIT_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "bse_ingest_audit.jsonl")


def _is_canonical_quote_code(code: str) -> bool:
    """当前行情可写入 Canonical Universe 的资格门（BSE=920-only）。

    沪市/深市：沿用现有 universe.is_stock 契约（含其已知局限，如 39x 指数误归深市）。
    北交所：本次明确限定 920 前缀，拒绝 83/87/874/875/899。
    """
    code = (code or "").strip()
    if not code:
        return False  # 空/空白代码不得误判为某交易所股票（防 universe 静默重定义）
    code = code.zfill(6)
    market = market_of(code)
    if market in ("沪市", "深市"):
        return is_stock(code)
    if code.startswith(BSE_PREFIX):
        return True
    return False


def _audit_ingest(raw_codes):
    """Provider-ingestion 计数审计（R2 §4）。

    返回 {raw, accepted, rejected, by_exchange}；
    资格层 FAIL-LOUD：accepted 中若有被 market_of 判为北交所但非 920 前缀者 → predicate 回归，立即抛错。
    """
    raw = [c.strip().zfill(6) for c in raw_codes]
    accepted, rejected = [], []
    by_ex = {"SSE": 0, "SZSE": 0, "BSE": 0}
    for c in raw:
        if _is_canonical_quote_code(c):
            accepted.append(c)
            ex = {"沪市": "SSE", "深市": "SZSE", "北交所": "BSE"}.get(market_of(c))
            if ex:
                by_ex[ex] += 1
        else:
            rejected.append(c)
    bse_non_920 = [c for c in accepted if market_of(c) == "北交所" and not c.startswith(BSE_PREFIX)]
    if bse_non_920:
        raise RuntimeError(
            f"BSE ingestion qualification FAIL_LOUD: {len(bse_non_920)} accepted codes "
            f"classified 北交所 but not {BSE_PREFIX}-prefixed (e.g. {bse_non_920[:5]})"
        )
    return {"raw": len(raw), "accepted": len(accepted), "rejected": len(rejected), "by_exchange": by_ex}


def _bse_drift_check(today_bse: int, prev_bse: int):
    """漂移层：今日 accepted BSE 数 vs 上一交易日（相对规则）。

    返回 ("ok"|"baseline"|"fail", msg)。prev==0 视为基线未建立（首填/回填首日），不阻断。
    """
    if prev_bse == 0:
        return "baseline", f"prev_bse={prev_bse} (no baseline yet)"
    delta = (today_bse - prev_bse) / prev_bse * 100.0
    if abs(delta) > BSE_DRIFT_MAX_PCT:
        return "fail", f"today={today_bse} prev={prev_bse} delta_pct={delta:.1f} > {BSE_DRIFT_MAX_PCT}"
    return "ok", f"today={today_bse} prev={prev_bse} delta_pct={delta:.1f}"


def _prev_day_bse_count(con, date: str, table: str = "stock_daily") -> int:
    row = con.execute(f"SELECT max(date) FROM {table} WHERE date < ?", (date,)).fetchone()
    if not row or not row[0]:
        return 0
    prev = row[0]
    return con.execute(
        f"SELECT count(*) FROM {table} WHERE date=? AND code LIKE '920%'", (prev,)
    ).fetchone()[0]


def _make_run_id() -> str:
    """每次运行唯一 id，用于关联审计记录（daily/flow 同日期可靠区分）。"""
    return uuid.uuid4().hex[:16]


def _audit_record(job, table, source, date, run_id, audit, *, verdict,
                 reason=None, drift_status=None, prev_bse=None, delta_msg=None,
                 rows_written=None, write_status=None, commit_status=None,
                 provider_total=None, fetched=None, error=None,
                 writeable=None, db_total_after_commit=None):
    """构造一条完整审计记录（含漂移门与写库结果，供 Step 5A Canary 追溯）。

    关键：raw/accepted/rejected 来自**过滤前**的 provider 原始集合（见 main 调用 _audit_ingest 的位置），
    因此 rejected 非零才有治理意义（R2 §3）。
    """
    rec = {
        "date": date,
        "job": job,
        "table": table,
        "source": source,
        "run_id": run_id,
        "timestamp": time.time(),
        "verdict": verdict,
    }
    if audit is not None:
        rec["raw"] = audit["raw"]
        rec["accepted"] = audit["accepted"]
        rec["rejected"] = audit["rejected"]
        rec["by_exchange"] = audit["by_exchange"]
    if reason is not None:
        rec["reason"] = reason
    if drift_status is not None:
        rec["drift_status"] = drift_status
    if prev_bse is not None:
        rec["prev_bse"] = prev_bse
    if delta_msg is not None:
        rec["delta_msg"] = delta_msg
    if rows_written is not None:
        rec["rows_written"] = rows_written
    if write_status is not None:
        rec["write_status"] = write_status
    if commit_status is not None:
        rec["commit_status"] = commit_status
    if provider_total is not None:
        rec["provider_total"] = provider_total
    if fetched is not None:
        rec["fetched"] = fetched
    if writeable is not None:
        rec["writeable"] = writeable
    if db_total_after_commit is not None:
        rec["db_total_after_commit"] = db_total_after_commit
    if error is not None:
        rec["error"] = error
    return rec


def _write_bse_audit_log(record: dict, strict: bool = False):
    """落盘审计日志（完整记录：raw/accepted/rejected + 漂移门 + 写库结果）。

    strict=True（Canary/治理模式）：日志写失败 → 抛 RuntimeError("AUDIT_LOG_WRITE_FAILED")，
    使日志失败可观测、可阻断。默认 strict=False：写失败仅告警到 stderr，不阻断主流程
    （生产环境日志非关键路径，但必须可见，杜绝静默吞掉）。
    """
    try:
        os.makedirs(os.path.dirname(_AUDIT_LOG), exist_ok=True)
        with open(_AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        if strict:
            raise RuntimeError(f"AUDIT_LOG_WRITE_FAILED: {e}")
        print(f"[WARN] BSE audit log write failed (non-fatal): {e}", file=sys.stderr)


def main():
    _clear_proxy()
    target = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().isoformat()
    print(f"[fill_daily_quotes] target_date={target}")
    # L1 · Single Writer（CIO 裁定 Q1-A' 2026-09-14）：Canary 模式下必须有合法 session 租约。
    # 非 canary（15:30 daily_collect 调度）→ 本调用立即返回 None，零行为变更。
    # 必须位于任何 get_conn()/网络取数**之前**（fail-closed：无租约即不进入 DB mutation）。
    require_lease("fill_daily_quotes")
    run_id = _make_run_id()
    # Step 4C · Canary 模式（env 开关；默认生产=False 非阻塞）：True 时所有审计日志 strict，
    # 且写前 preflight 保证审计设施不可用时不进入 DB mutation。
    _audit_strict = (os.environ.get("BSE_INGEST_CANARY") == "1")

    # ── Step 4B(1): 拉全量 + 捕获 provider 报告总数（分页完整性校验）──
    all_rows = []
    provider_total = None
    pn = 1
    while True:
        try:
            page, total = _fetch_page(pn)
        except Exception as e:
            _write_bse_audit_log(_audit_record("fill_daily_quotes", "stock_daily", SOURCE,
                                target, run_id, None, verdict="FAIL",
                                reason="page_fetch_failed", error=str(e)), strict=_audit_strict)
            raise RuntimeError(f"[fill_daily_quotes] PAGE_FETCH_FAILED at pn={pn}: {e}")
        if provider_total is None and total is not None:
            provider_total = total
        if not page:
            break
        all_rows.extend(page)
        if provider_total is not None and len(all_rows) >= provider_total:
            break
        if len(page) < PZ:
            break
        pn += 1
        time.sleep(0.08)
    print(f"[fill_daily_quotes] 抓到 {len(all_rows)} 只 (provider_total={provider_total})")

    # ── Step 4B(2): 审计必须基于 provider 原始集合（过滤前）──
    raw_codes = [r["code"] for r in all_rows]
    try:
        audit = _audit_ingest(raw_codes)   # 资格层 FAIL-LOUD（raw 含 83/87/874/875/920 混合）
    except RuntimeError as e:
        _write_bse_audit_log(_audit_record("fill_daily_quotes", "stock_daily", SOURCE,
                            target, run_id, None, verdict="FAIL",
                            reason="qualification_fail_loud", error=str(e)), strict=_audit_strict)
        raise

    # 空快照 = provider 降级，必须 FAIL-LOUD（A 股快照不可能为空）
    if len(all_rows) == 0:
        _write_bse_audit_log(_audit_record("fill_daily_quotes", "stock_daily", SOURCE,
                            target, run_id, audit, verdict="FAIL",
                            reason="provider_empty_snapshot", provider_total=provider_total),
                            strict=_audit_strict)
        raise RuntimeError("[fill_daily_quotes] PROVIDER_EMPTY_SNAPSHOT: 0 rows fetched")

    # 分页完整性：抓取数 < provider 报告总数 → 异常终止/缺页，禁止部分提交
    if provider_total is not None and len(all_rows) < provider_total:
        _write_bse_audit_log(_audit_record("fill_daily_quotes", "stock_daily", SOURCE,
                            target, run_id, audit, verdict="FAIL",
                            reason="pagination_incomplete",
                            provider_total=provider_total, fetched=len(all_rows)), strict=_audit_strict)
        raise RuntimeError(f"[fill_daily_quotes] PAGINATION_INCOMPLETE: "
                           f"fetched {len(all_rows)} < provider_total {provider_total}")

    print(f"[fill_daily_quotes] audit raw={audit['raw']} accepted={audit['accepted']} "
          f"rejected={audit['rejected']} by_ex={audit['by_exchange']}")

    # ── 过滤（写入候选集 = audit.accepted 集合，仅按代码资格）──
    filtered = []
    for it in all_rows:
        code = it["code"].strip().zfill(6)
        if not _is_canonical_quote_code(code):
            continue
        it = dict(it)
        it["code"] = code
        filtered.append(it)

    con = get_conn()
    cur = con.cursor()
    prev_bse = _prev_day_bse_count(con, target, "stock_daily")
    status, msg = _bse_drift_check(audit["by_exchange"]["BSE"], prev_bse)
    if status == "fail":
        _write_bse_audit_log(_audit_record("fill_daily_quotes", "stock_daily", SOURCE,
                            target, run_id, audit, verdict="FAIL", reason="drift",
                            drift_status="fail", prev_bse=prev_bse, delta_msg=msg),
                            strict=_audit_strict)
        con.close()
        raise RuntimeError(f"[fill_daily_quotes] BSE drift FAIL_LOUD: {msg}")
    elif status == "baseline":
        print(f"[fill_daily_quotes] BSE baseline not established (prev={prev_bse}); skip drift check")

    # 真正可写集合 = 候选集内 close 有效者。close=None 的代码本次不写，必须排除出白名单，
    # 否则其旧行被保留又不被覆盖 → 旧数据掩盖本次缺失（审计 P1 Blocker #1）。
    writeable = [it for it in filtered if it["close"] is not None]
    wcodes = [it["code"] for it in writeable]

    # ── Step 4C · Canary 写前 strict preflight（审计设施不可用时阻断 DB mutation）──
    # 必须在首个 DB 写（DELETE）之前；_audit_strict=True 时日志写失败即抛错，mutation 不发生。
    _write_bse_audit_log(_audit_record("fill_daily_quotes", "stock_daily", SOURCE,
                        target, run_id, audit, verdict="INTENT", reason="canary_preflight",
                        drift_status=status, prev_bse=prev_bse,
                        writeable=len(wcodes),
                        provider_total=provider_total, fetched=len(all_rows)),
                    strict=_audit_strict)

    # 全日期替换语义（保留 tech_fill 已回填的技术列）：删除该 date 下不在「可写集合」内的既有行，
    # 杜绝历史非 Canonical 代码（如 83/87）残留、或旧完整数据掩盖本次部分/无效抓取（审计 P1）。
    if wcodes:
        _ph = ",".join("?" * len(wcodes))
        cur.execute(f"DELETE FROM stock_daily WHERE date=? AND code NOT IN ({_ph})",
                    (target, *wcodes))
    else:
        cur.execute("DELETE FROM stock_daily WHERE date=?", (target,))

    cnt = 0
    for it in writeable:
        vol = it["vol_hand"] * 100 if it["vol_hand"] is not None else None
        amount = it["amount_yuan"] / 1e8 if it["amount_yuan"] is not None else None
        mcap = it["mcap_yuan"] / 1e8 if it["mcap_yuan"] is not None else None
        fcap = it["fcap_yuan"] / 1e8 if it["fcap_yuan"] is not None else None
        # UPSERT：保留 high_20d 等技术列（由 tech_fill 回填），冲突时只更新价格/市值
        cur.execute(
            """INSERT INTO stock_daily
               (date,code,name,open,high,low,close,volume,amount,change_pct,
                turnover_rate,market_cap,float_cap,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(date,code) DO UPDATE SET
                 name=excluded.name, open=excluded.open, high=excluded.high,
                 low=excluded.low, close=excluded.close, volume=excluded.volume,
                 amount=excluded.amount, change_pct=excluded.change_pct,
                 turnover_rate=excluded.turnover_rate,
                 market_cap=excluded.market_cap, float_cap=excluded.float_cap""",
            (target, it["code"], it["name"], it["open"], it["high"], it["low"],
             it["close"], vol, amount, it["pct"], it["turnover"], mcap, fcap,
             time.time()),
        )
        cnt += 1

    # ── Step 4D · 写库完整性自检在 commit「之前」：事务内 read-back（同一连接可见未提交写入）。
    # mismatch → ROLLBACK（异常数据不进入 canonical DB）+ WRITE_INTEGRITY_FAIL，使其成为真正的
    # write gate 而非 post-commit alarm（独立复审 #3，2026-09-11）。──
    db_total_in_txn = con.execute(
        "SELECT count(*) FROM stock_daily WHERE date=?", (target,)).fetchone()[0]
    if cnt != db_total_in_txn:
        con.rollback()
        con.close()
        try:
            _write_bse_audit_log(_audit_record("fill_daily_quotes", "stock_daily", SOURCE,
                                target, run_id, audit, verdict="FAIL",
                                reason="write_integrity_fail", drift_status=status,
                                prev_bse=prev_bse, writeable=len(wcodes), rows_written=cnt,
                                write_status="rolled_back", commit_status="rollback",
                                provider_total=provider_total, fetched=len(all_rows),
                                db_total_after_commit=db_total_in_txn), strict=_audit_strict)
        except RuntimeError:
            pass  # 审计设施失败不得掩盖主错误 WRITE_INTEGRITY_FAIL
        raise RuntimeError(f"[fill_daily_quotes] WRITE_INTEGRITY_FAIL: "
                           f"written={cnt} != db_total_in_txn={db_total_in_txn} (rolled back)")

    con.commit()
    con.close()
    db_total_after_commit = db_total_in_txn
    print(f"[fill_daily_quotes] upserted {cnt} 行（可写 {len(wcodes)} / 候选 {len(filtered)}）")

    # ── Step 4B(4): 最终审计记录（含漂移门 + 写库结果，供 Canary 追溯）──
    _write_bse_audit_log(_audit_record("fill_daily_quotes", "stock_daily", SOURCE,
                        target, run_id, audit, verdict="PASS",
                        drift_status=status, prev_bse=prev_bse,
                        writeable=len(wcodes),
                        rows_written=cnt, write_status="committed",
                        commit_status="ok", provider_total=provider_total,
                        fetched=len(all_rows), db_total_after_commit=db_total_after_commit),
                    strict=_audit_strict)
    return cnt


if __name__ == "__main__":
    main()
