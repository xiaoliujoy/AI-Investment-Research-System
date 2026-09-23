# -*- coding: utf-8 -*-
"""
fill_stock_flow —— 个股资金流数据源（Data OS，独立表）

背景：stock_daily 的 main_net_buy 列由 TDX 导入而来，TDX 不提供主力净流入
      → 该列恒为 NULL（实测 2026-07-17 填充 0/9326）。用户的红线要求：
      「龙头资金」必须可观测（板块 → 龙头 → 资金 → 图形 第四环）。
      故建立独立表 stock_flow_daily，与价格数据（stock_daily）分离。

数据源：push2delay.eastmoney.com/api/qt/clist/get
        字段：f62=主力净流入 f66=超大单 f72=大单 f78=中单 f84=小单（净额，单位：元）。
        **关键**：①主域 push2.eastmoney.com 被沙箱代理(127.0.0.1:7890)拦截
        （RemoteDisconnected），改用 delayed 子域 push2delay 可直连/经代理均通；
        ②akshare 自带 requests 死代理会 ProxyError，故用 urllib 直连 +
        显式空 ProxyHandler opener 强制不走系统代理。

设计要点：
  - 分页拉全 A 股（沪A/深A/科创/创业/北交所920），fs 拼接。
  - 元 ÷1e8 → 亿元（与 amount / market_cap 同单位）。
  - INSERT OR REPLACE 写独立表（不 UPDATE stock_daily，避免数据层幻觉）。
  - source='eastmoney_push2'，confidence 默认 1.0（网络可达即高可信）。
  - 北交所(920 新代码)经 `m:0+t:81` 可覆盖；Step 4(R2) 写入前用 **920-only ingestion predicate**
    过滤，拒绝 83/87/874/875/899 等非当前 BSE 上市代码，并落
    raw/accepted/rejected/by_exchange 审计日志 + 漂移门（详见模块底部 helpers）。
"""
from __future__ import annotations
from db import get_conn, _DB_PATH
from universe import is_stock, market_of
from ingest_lock import require_lease   # L1 Single Writer · session lease（CIO 裁定 Q1-A'）

import os
import sqlite3
import sys
import time
import uuid
import urllib.request
import urllib.parse
import json
from pathlib import Path

DB = str(_DB_PATH)
# 注意：push2delay 子域无视 pz 参数、强制每页最多 100 条（实测 pz=1000 仍只回 100）。
# 故分页步长固定 100，循环翻页直到不足 100 条为止（全 A 约 5540 只 → ~56 页）。
PZ = 100           # 每页条数（push2delay 实际上限）
TIMEOUT = 20
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://quote.eastmoney.com/",
}
SOURCE = "eastmoney_push2"


# 显式无代理 opener：Windows 上 getproxies() 会读注册表代理（127.0.0.1:7890 死代理），
# 仅清 env 变量不够，必须在 _fetch_page 内显式用空 ProxyHandler 的 opener 强制直连。
# 注意：只在本模块内显式使用，不 install_opener 全局，避免影响同进程其他采集器的代理设置。
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _clear_proxy():
    """清掉所有代理环境变量（防御性；真正强制直连靠 _fetch_page 内的 _NO_PROXY_OPENER）。"""
    for k in ("http_proxy", "https_proxy", "all_proxy",
              "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
              "no_proxy", "NO_PROXY"):
        os.environ.pop(k, None)


def _fetch_page(pn: int):
    """拉一页个股资金流排名 → (list[{code,name,main,super_l,large,medium,small}], provider_total|None)（亿元）。

    provider_total 取自 EastMoney `data.total`，供 Step 4B 分页完整性 FAIL-LOUD 校验。
    """
    fs = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81"  # 沪A/深A/科创/创业/北交所(920)
    fields = "f12,f14,f62,f66,f72,f78,f84"
    url = (f"https://push2delay.eastmoney.com/api/qt/clist/get"
           f"?pn={pn}&pz={PZ}&po=1&np=1&fltt=2&invt=2&fid=f62"
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
        try:
            main = float(it.get("f62") or 0) / 1e8
            super_l = float(it.get("f66") or 0) / 1e8
            large = float(it.get("f72") or 0) / 1e8
            medium = float(it.get("f78") or 0) / 1e8
            small = float(it.get("f84") or 0) / 1e8
        except (ValueError, TypeError):
            main = super_l = large = medium = small = 0.0
        out.append({
            "code": code, "name": it.get("f14") or "",
            "main": round(main, 4), "super_l": round(super_l, 4),
            "large": round(large, 4), "medium": round(medium, 4),
            "small": round(small, 4),
        })
    return out, total


# ── Step 4 (Governance R2, 2026-09-11) · BSE 920-only ingestion predicate ──
# 与 fill_daily_quotes.py 同款治理门；provider-ingestion 层针对「当前行情数据」的更严格资格门；
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


def _prev_day_bse_count(con, date: str, table: str = "stock_flow_daily") -> int:
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

    关键：raw/accepted/rejected 来自**过滤前**的 provider 原始集合（见 fill 调用 _audit_ingest 的位置），
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


def fill(date=None, verbose=True):
    """回填指定交易日（默认最新）的个股资金流。返回统计 dict。"""
    _clear_proxy()
    # L1 · Single Writer（CIO 裁定 Q1-A' 2026-09-14）：Canary 模式下必须有合法 session 租约。
    # 非 canary（15:30 daily_collect 调度）→ 立即返回 None，零行为变更。
    # 必须位于 get_conn() **之前**（fail-closed：无租约即不连库、不写）。
    require_lease("fill_stock_flow")
    c = get_conn(timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    if date is None:
        row = c.execute("SELECT max(date) FROM stock_daily").fetchone()
        date = row[0] if row and row[0] else None
    if not date:
        c.close()
        return {"date": None, "error": "no date"}

    run_id = _make_run_id()
    # Step 4C · Canary 模式（env 开关；默认生产=False 非阻塞）：True 时所有审计日志 strict，
    # 且写前 preflight 保证审计设施不可用时不进入 DB mutation。
    _audit_strict = (os.environ.get("BSE_INGEST_CANARY") == "1")

    # ── Step 4B(1): 拉全量 + 捕获 provider 报告总数（分页完整性校验）──
    all_rows = []
    provider_total = None
    pn = 1
    while True:
        page = None
        for attempt in range(3):
            try:
                page, total = _fetch_page(pn)
                break
            except Exception:
                if attempt < 2:
                    time.sleep(1.0)
                else:
                    # 3 次重试后仍失败 → 禁止部分提交，FAIL-LOUD（审计 P1）
                    _write_bse_audit_log(_audit_record(
                        "fill_stock_flow", "stock_flow_daily", SOURCE, date, run_id,
                        None, verdict="FAIL", reason="page_fetch_failed",
                        provider_total=provider_total, fetched=len(all_rows)), strict=_audit_strict)
                    c.close()
                    raise RuntimeError(
                        f"[stock_flow] PAGE_FETCH_FAILED after 3 retries at pn={pn} "
                        f"(fetched {len(all_rows)} of provider_total {provider_total})")
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
        time.sleep(0.25)
    print(f"[stock_flow] 抓到 {len(all_rows)} 条 (provider_total={provider_total})")

    # ── Step 4B(2): 审计必须基于 provider 原始集合（过滤前）──
    raw_codes = [r["code"] for r in all_rows]
    try:
        audit = _audit_ingest(raw_codes)   # 资格层 FAIL-LOUD（raw 含 83/87/874/875/920 混合）
    except RuntimeError as e:
        _write_bse_audit_log(_audit_record(
            "fill_stock_flow", "stock_flow_daily", SOURCE, date, run_id, None,
            verdict="FAIL", reason="qualification_fail_loud", error=str(e),
            provider_total=provider_total, fetched=len(all_rows)), strict=_audit_strict)
        c.close()
        raise

    # 空快照 = provider 降级，必须 FAIL-LOUD（A 股快照不可能为空）
    if len(all_rows) == 0:
        _write_bse_audit_log(_audit_record(
            "fill_stock_flow", "stock_flow_daily", SOURCE, date, run_id, audit,
            verdict="FAIL", reason="provider_empty_snapshot",
            provider_total=provider_total), strict=_audit_strict)
        c.close()
        raise RuntimeError("[stock_flow] PROVIDER_EMPTY_SNAPSHOT: 0 rows fetched")

    # 分页完整性：抓取数 < provider 报告总数 → 异常终止/缺页，禁止部分提交
    if provider_total is not None and len(all_rows) < provider_total:
        _write_bse_audit_log(_audit_record(
            "fill_stock_flow", "stock_flow_daily", SOURCE, date, run_id, audit,
            verdict="FAIL", reason="pagination_incomplete",
            provider_total=provider_total, fetched=len(all_rows)), strict=_audit_strict)
        c.close()
        raise RuntimeError(f"[stock_flow] PAGINATION_INCOMPLETE: "
                           f"fetched {len(all_rows)} < provider_total {provider_total}")

    # ── 过滤（写入候选集 = audit.accepted 集合，仅按代码资格）──
    filtered = []
    for r in all_rows:
        code = r["code"].strip().zfill(6)
        if not _is_canonical_quote_code(code):
            continue
        rr = dict(r)
        rr["code"] = code
        filtered.append(rr)
    attempted = len(filtered)
    writeable = attempted   # stock_flow_daily 无 close 等价跳过，候选即可写
    print(f"[stock_flow] audit raw={audit['raw']} accepted={audit['accepted']} "
          f"rejected={audit['rejected']} by_ex={audit['by_exchange']}")

    prev_bse = _prev_day_bse_count(c, date, "stock_flow_daily")
    status, msg = _bse_drift_check(audit["by_exchange"]["BSE"], prev_bse)
    if status == "fail":
        _write_bse_audit_log(_audit_record(
            "fill_stock_flow", "stock_flow_daily", SOURCE, date, run_id, audit,
            verdict="FAIL", reason="drift", drift_status="fail",
            prev_bse=prev_bse, delta_msg=msg), strict=_audit_strict)
        c.close()
        raise RuntimeError(f"[stock_flow] BSE drift FAIL_LOUD: {msg}")
    elif status == "baseline":
        print(f"[stock_flow] BSE baseline not established (prev={prev_bse}); skip drift check")

    # ── Step 4C · Canary 写前 strict preflight（审计设施不可用时阻断 DB mutation）──
    _write_bse_audit_log(_audit_record(
        "fill_stock_flow", "stock_flow_daily", SOURCE, date, run_id, audit,
        verdict="INTENT", reason="canary_preflight", drift_status=status,
        prev_bse=prev_bse, writeable=writeable,
        provider_total=provider_total, fetched=len(all_rows)), strict=_audit_strict)

    # 全日期替换语义：先删该 date 既有行，再写入候选集，
    # 杜绝「旧完整数据掩盖本次部分抓取 / 历史非 Canonical 代码回填后残留」（审计 P1 / 测试(i)）。
    # stock_flow_daily 完全由本脚本所有，无 tech_fill 等技术列，可直接整日期替换。
    c.execute("DELETE FROM stock_flow_daily WHERE date=?", (date,))

    rows = [(
        date, r["code"], r["name"], r["main"], r["super_l"], r["large"],
        r["medium"], r["small"], SOURCE, 1.0,
    ) for r in filtered]
    c.executemany(
        "INSERT OR REPLACE INTO stock_flow_daily "
        "(date, code, name, main_net_buy, super_large_net_buy, large_net_buy, "
        " medium_net_buy, small_net_buy, source, confidence) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)

    # ── Step 4D · 写库完整性自检在 commit「之前」：事务内 read-back（同一连接可见未提交写入）。
    # mismatch → ROLLBACK（异常数据不进入 canonical DB）+ WRITE_INTEGRITY_FAIL（独立复审 #3）。──
    db_total_in_txn = c.execute(
        "SELECT count(*) FROM stock_flow_daily WHERE date=?", (date,)).fetchone()[0]
    if writeable != db_total_in_txn:
        c.rollback()
        c.close()
        try:
            _write_bse_audit_log(_audit_record(
                "fill_stock_flow", "stock_flow_daily", SOURCE, date, run_id, audit,
                verdict="FAIL", reason="write_integrity_fail", drift_status=status,
                prev_bse=prev_bse, writeable=writeable, rows_written=writeable,
                write_status="rolled_back", commit_status="rollback",
                provider_total=provider_total, fetched=len(all_rows),
                db_total_after_commit=db_total_in_txn), strict=_audit_strict)
        except RuntimeError:
            pass  # 审计设施失败不得掩盖主错误 WRITE_INTEGRITY_FAIL
        raise RuntimeError(f"[stock_flow] WRITE_INTEGRITY_FAIL: "
                           f"written={writeable} != db_total_in_txn={db_total_in_txn} (rolled back)")

    c.commit()
    c.close()
    db_total_after_commit = db_total_in_txn
    committed = writeable
    if verbose:
        print(f"[stock_flow] 交易日={date} 候选 {attempted} 条写入 stock_flow_daily，"
              f"db_total(当日) {db_total_after_commit} 只（亿元）。")

    # ── Step 4B(4): 最终审计记录（含漂移门 + 写库结果，供 Canary 追溯）──
    _write_bse_audit_log(_audit_record(
        "fill_stock_flow", "stock_flow_daily", SOURCE, date, run_id, audit,
        verdict="PASS", drift_status=status, prev_bse=prev_bse,
        writeable=writeable,
        rows_written=committed, write_status="committed", commit_status="ok",
        provider_total=provider_total, fetched=len(all_rows),
        db_total_after_commit=db_total_after_commit), strict=_audit_strict)

    return {
        "date": date,
        "fetched": len(all_rows),
        "written": db_total_after_commit,           # 兼容旧字段
        "provider_raw": audit["raw"],
        "accepted": audit["accepted"],
        "rejected": audit["rejected"],
        "attempted_rows": attempted,
        "committed_rows": committed,
        "db_total_after_commit": db_total_after_commit,
        "provider_total": provider_total,
        "verdict": "PASS",
    }


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else None
    fill(d)
