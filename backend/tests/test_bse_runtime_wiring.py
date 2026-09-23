# -*- coding: utf-8 -*-
"""Step 4B runtime-wiring contract tests (独立审计裁定 9 缺口闭合验证).

不限于纯函数，覆盖生产接线合同：
  (a) provider 原始 codes 原样进入 _audit_ingest（raw != accepted, rejected 有意义）
  (b) accepted 集合 == 实际写库行数
  (c) 中间页异常 → 不写库 + RuntimeError（禁止部分提交）
  (d) 审计日志写失败可观测（strict=True 抛 AUDIT_LOG_WRITE_FAILED）
  (e) drift fail → 不 commit
  (f) daily/flow 审计记录可区分（job/table/run_id）
  (g) written 反映本次运行（committed_rows == attempted）
  (h) 空 provider → FAIL-LOUD
  (i) 部分重跑不掩盖旧数据（整日期替换语义）

均使用临时 sqlite（monkeypatch get_conn）+ monkeypatch _fetch_page / _write_bse_audit_log。
不触碰生产 DB / universe.py / schema / UPSERT / daily_collect。
"""
import sqlite3

import pytest

import fill_daily_quotes as fdq
import fill_stock_flow as fsf


# ── 样本数据（raw=4, accepted=3, rejected=1）──
DAILY_FULL = [
    {"code": "600000", "name": "浦发", "close": 10.0, "pct": 1.0, "high": 10.2,
     "low": 9.8, "open": 9.9, "vol_hand": 1000, "amount_yuan": 1e8, "mcap_yuan": 1e10,
     "fcap_yuan": 5e9, "turnover": 1.0},
    {"code": "000001", "name": "平安", "close": 12.0, "pct": 0.5, "high": 12.2,
     "low": 11.8, "open": 11.9, "vol_hand": 2000, "amount_yuan": 2e8, "mcap_yuan": 2e10,
     "fcap_yuan": 1e10, "turnover": 1.2},
    {"code": "920001", "name": "北交所A", "close": 20.0, "pct": 2.0, "high": 20.5,
     "low": 19.5, "open": 19.8, "vol_hand": 300, "amount_yuan": 3e7, "mcap_yuan": 3e9,
     "fcap_yuan": 2e9, "turnover": 3.0},
    {"code": "830001", "name": "非BSE", "close": 5.0, "pct": -1.0, "high": 5.2,
     "low": 4.8, "open": 5.0, "vol_hand": 100, "amount_yuan": 1e6, "mcap_yuan": 1e8,
     "fcap_yuan": 1e8, "turnover": 0.5},
]

FLOW_FULL = [
    {"code": "600000", "name": "浦发", "main": 1.0, "super_l": 0.5, "large": 0.3, "medium": 0.1, "small": 0.1},
    {"code": "000001", "name": "平安", "main": 2.0, "super_l": 1.0, "large": 0.5, "medium": 0.2, "small": 0.3},
    {"code": "920001", "name": "北交所A", "main": 0.3, "super_l": 0.2, "large": 0.05, "medium": 0.02, "small": 0.03},
    {"code": "830001", "name": "非BSE", "main": 0.05, "super_l": 0.0, "large": 0.0, "medium": 0.02, "small": 0.03},
]


def _make_temp_db(tmp_path):
    path = tmp_path / "test_bse_wiring.db"
    con = sqlite3.connect(str(path))
    con.execute("""CREATE TABLE stock_daily (
        date TEXT, code TEXT, name TEXT, open REAL, high REAL, low REAL, close REAL,
        volume REAL, amount REAL, change_pct REAL, turnover_rate REAL,
        market_cap REAL, float_cap REAL, created_at REAL,
        PRIMARY KEY (date, code))""")
    con.execute("""CREATE TABLE stock_flow_daily (
        date TEXT, code TEXT, name TEXT, main_net_buy REAL, super_large_net_buy REAL,
        large_net_buy REAL, medium_net_buy REAL, small_net_buy REAL, source TEXT,
        confidence REAL, PRIMARY KEY (date, code))""")
    con.commit()
    con.close()
    return str(path)


def _patch_get_conn(monkeypatch, db_path):
    def fake(*a, **k):
        con = sqlite3.connect(db_path, timeout=30)
        con.execute("PRAGMA busy_timeout=30000")
        return con
    monkeypatch.setattr(fdq, "get_conn", fake)
    monkeypatch.setattr(fsf, "get_conn", fake)


def _patch_audit_log(monkeypatch):
    captured = []
    def fake(rec, strict=False):
        captured.append((rec, strict))
    monkeypatch.setattr(fdq, "_write_bse_audit_log", fake)
    monkeypatch.setattr(fsf, "_write_bse_audit_log", fake)
    return captured


def _patch_fetch_daily(monkeypatch, pages, total):
    it = {"i": 0}
    def fake(pn):
        idx = min(it["i"], len(pages) - 1)
        it["i"] += 1
        return pages[idx], (total if pn == 1 else None)
    monkeypatch.setattr(fdq, "_fetch_page", fake)


def _patch_fetch_flow(monkeypatch, pages, total):
    it = {"i": 0}
    def fake(pn):
        idx = min(it["i"], len(pages) - 1)
        it["i"] += 1
        return pages[idx], (total if pn == 1 else None)
    monkeypatch.setattr(fsf, "_fetch_page", fake)


def _snapshot(db, table, date):
    """目标日期全量快照（逐行 + 逐列，按 code 排序），用于证明「数据逐行完全不变」。"""
    con = sqlite3.connect(db)
    rows = con.execute(f"SELECT * FROM {table} WHERE date=? ORDER BY code", (date,)).fetchall()
    con.close()
    return rows


# ── (a) raw audit counts (raw != accepted, rejected 有意义) ──
def test_fdq_raw_audit_counts(tmp_path, monkeypatch):
    db = _make_temp_db(tmp_path)
    _patch_get_conn(monkeypatch, db)
    cap = _patch_audit_log(monkeypatch)
    _patch_fetch_daily(monkeypatch, [DAILY_FULL], total=4)
    fdq.main()
    rec = cap[-1][0]
    assert rec["verdict"] == "PASS"
    assert rec["raw"] == 4
    assert rec["accepted"] == 3
    assert rec["rejected"] == 1
    assert rec["raw"] != rec["accepted"]   # 关键：审计基于过滤前原始集合
    con = sqlite3.connect(db)
    n = con.execute("SELECT count(*) FROM stock_daily WHERE date=?", (rec["date"],)).fetchone()[0]
    con.close()
    assert n == 3                          # (b) accepted == 写库行数


def test_fsf_raw_audit_counts(tmp_path, monkeypatch):
    db = _make_temp_db(tmp_path)
    _patch_get_conn(monkeypatch, db)
    cap = _patch_audit_log(monkeypatch)
    _patch_fetch_flow(monkeypatch, [FLOW_FULL], total=4)
    res = fsf.fill(date="2026-09-10")
    rec = cap[-1][0]
    assert rec["verdict"] == "PASS"
    assert rec["raw"] == 4 and rec["accepted"] == 3 and rec["rejected"] == 1
    assert rec["raw"] != rec["accepted"]
    assert res["committed_rows"] == 3      # (g) written 反映本次运行
    assert res["db_total_after_commit"] == 3
    con = sqlite3.connect(db)
    n = con.execute("SELECT count(*) FROM stock_flow_daily WHERE date=?", ("2026-09-10",)).fetchone()[0]
    con.close()
    assert n == 3


# ── (h) empty provider → FAIL-LOUD，未写库 ──
def test_fdq_empty_snapshot(tmp_path, monkeypatch):
    db = _make_temp_db(tmp_path)
    _patch_get_conn(monkeypatch, db)
    cap = _patch_audit_log(monkeypatch)
    _patch_fetch_daily(monkeypatch, [[]], total=0)
    with pytest.raises(RuntimeError, match="PROVIDER_EMPTY_SNAPSHOT"):
        fdq.main()
    assert cap[-1][0]["reason"] == "provider_empty_snapshot"
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM stock_daily").fetchone()[0] == 0
    con.close()


def test_fsf_empty_snapshot(tmp_path, monkeypatch):
    db = _make_temp_db(tmp_path)
    _patch_get_conn(monkeypatch, db)
    cap = _patch_audit_log(monkeypatch)
    _patch_fetch_flow(monkeypatch, [[]], total=0)
    with pytest.raises(RuntimeError, match="PROVIDER_EMPTY_SNAPSHOT"):
        fsf.fill(date="2026-09-10")
    assert cap[-1][0]["reason"] == "provider_empty_snapshot"
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM stock_flow_daily").fetchone()[0] == 0
    con.close()


# ── pagination incomplete（空中间页不再被当作正常结束）──
def test_fdq_pagination_incomplete(tmp_path, monkeypatch):
    monkeypatch.setattr(fdq, "PZ", 2)
    db = _make_temp_db(tmp_path)
    _patch_get_conn(monkeypatch, db)
    cap = _patch_audit_log(monkeypatch)
    _patch_fetch_daily(monkeypatch, [DAILY_FULL[:2], []], total=4)
    with pytest.raises(RuntimeError, match="PAGINATION_INCOMPLETE"):
        fdq.main()
    assert cap[-1][0]["reason"] == "pagination_incomplete"
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM stock_daily").fetchone()[0] == 0
    con.close()


def test_fsf_pagination_incomplete(tmp_path, monkeypatch):
    monkeypatch.setattr(fsf, "PZ", 2)
    db = _make_temp_db(tmp_path)
    _patch_get_conn(monkeypatch, db)
    cap = _patch_audit_log(monkeypatch)
    _patch_fetch_flow(monkeypatch, [FLOW_FULL[:2], []], total=4)
    with pytest.raises(RuntimeError, match="PAGINATION_INCOMPLETE"):
        fsf.fill(date="2026-09-10")
    assert cap[-1][0]["reason"] == "pagination_incomplete"
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM stock_flow_daily").fetchone()[0] == 0
    con.close()


# ── (c) mid-page exception → 不写库 + RuntimeError ──
def test_fdq_midpage_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(fdq, "PZ", 2)
    db = _make_temp_db(tmp_path)
    _patch_get_conn(monkeypatch, db)
    cap = _patch_audit_log(monkeypatch)
    def fake(pn):
        if pn == 1:
            return DAILY_FULL[:2], 4
        raise RuntimeError("network boom")
    monkeypatch.setattr(fdq, "_fetch_page", fake)
    with pytest.raises(RuntimeError, match="PAGE_FETCH_FAILED"):
        fdq.main()
    assert cap[-1][0]["reason"] == "page_fetch_failed"
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM stock_daily").fetchone()[0] == 0
    con.close()


def test_fsf_midpage_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(fsf, "PZ", 2)
    db = _make_temp_db(tmp_path)
    _patch_get_conn(monkeypatch, db)
    cap = _patch_audit_log(monkeypatch)
    def fake(pn):
        if pn == 1:
            return FLOW_FULL[:2], 4
        raise RuntimeError("network boom")
    monkeypatch.setattr(fsf, "_fetch_page", fake)
    with pytest.raises(RuntimeError, match="PAGE_FETCH_FAILED"):
        fsf.fill(date="2026-09-10")
    assert cap[-1][0]["reason"] == "page_fetch_failed"
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM stock_flow_daily").fetchone()[0] == 0
    con.close()


# ── (e) drift fail → 不 commit ──
def test_fdq_drift_fail(tmp_path, monkeypatch):
    db = _make_temp_db(tmp_path)
    _patch_get_conn(monkeypatch, db)
    cap = _patch_audit_log(monkeypatch)
    _patch_fetch_daily(monkeypatch, [DAILY_FULL], total=4)
    monkeypatch.setattr(fdq, "_prev_day_bse_count", lambda con, date, table="stock_daily": 10)
    with pytest.raises(RuntimeError, match="BSE drift FAIL_LOUD"):
        fdq.main()
    assert cap[-1][0]["verdict"] == "FAIL"
    assert cap[-1][0]["reason"] == "drift"
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM stock_daily").fetchone()[0] == 0
    con.close()


def test_fsf_drift_fail(tmp_path, monkeypatch):
    db = _make_temp_db(tmp_path)
    _patch_get_conn(monkeypatch, db)
    cap = _patch_audit_log(monkeypatch)
    _patch_fetch_flow(monkeypatch, [FLOW_FULL], total=4)
    monkeypatch.setattr(fsf, "_prev_day_bse_count", lambda con, date, table="stock_flow_daily": 10)
    with pytest.raises(RuntimeError, match="BSE drift FAIL_LOUD"):
        fsf.fill(date="2026-09-10")
    assert cap[-1][0]["verdict"] == "FAIL"
    assert cap[-1][0]["reason"] == "drift"
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM stock_flow_daily").fetchone()[0] == 0
    con.close()


# ── (d) audit log write failure observable (strict) ──
def test_audit_log_strict_failure(tmp_path, monkeypatch):
    # 用一个已存在的「文件」冒充目录父节点，使 makedirs 必然失败（Windows 下根目录路径可能被建出）
    blocker = tmp_path / "blocker_file"
    blocker.write_text("x")
    monkeypatch.setattr(fdq, "_AUDIT_LOG", str(blocker / "audit.jsonl"))
    rec = {"date": "2026-09-10", "job": "fill_daily_quotes", "table": "stock_daily",
           "run_id": "x", "timestamp": 1.0, "verdict": "PASS"}
    with pytest.raises(RuntimeError, match="AUDIT_LOG_WRITE_FAILED"):
        fdq._write_bse_audit_log(rec, strict=True)
    # strict=False：不抛，仅告警（非阻塞）
    assert fdq._write_bse_audit_log(rec, strict=False) is None


# ── (f) daily/flow 审计记录可区分 ──
def test_job_table_distinguishable(tmp_path, monkeypatch):
    db = _make_temp_db(tmp_path)
    _patch_get_conn(monkeypatch, db)
    cap = _patch_audit_log(monkeypatch)
    _patch_fetch_daily(monkeypatch, [DAILY_FULL], total=4)
    _patch_fetch_flow(monkeypatch, [FLOW_FULL], total=4)
    fdq.main()
    fsf.fill(date="2026-09-10")
    jobs = {(r["job"], r["table"]) for r, _ in cap}
    assert ("fill_daily_quotes", "stock_daily") in jobs
    assert ("fill_stock_flow", "stock_flow_daily") in jobs
    assert all(r.get("run_id") for r, _ in cap)


# ── (i) partial rerun doesn't mask old data（整日期替换语义）──
def test_fsf_partial_rerun_no_mask(tmp_path, monkeypatch):
    db = _make_temp_db(tmp_path)
    con = sqlite3.connect(db)
    for code in ("600000", "000001", "920001"):
        con.execute("INSERT INTO stock_flow_daily (date,code,name,main_net_buy,source,confidence) "
                    "VALUES (?,?,?,?,?,?)", ("2026-09-10", code, code, 1.0, "old", 1.0))
    con.commit(); con.close()
    _patch_get_conn(monkeypatch, db)
    cap = _patch_audit_log(monkeypatch)
    # 本次只成功抓到 1 只 canonical（920001）+ 1 只被拒（830001），total=2 视为完整
    _patch_fetch_flow(monkeypatch, [FLOW_FULL[2:4]], total=2)
    monkeypatch.setattr(fsf, "_prev_day_bse_count", lambda con, date, table="stock_flow_daily": 0)
    res = fsf.fill(date="2026-09-10")
    assert res["committed_rows"] == 1
    assert res["db_total_after_commit"] == 1
    con = sqlite3.connect(db)
    codes = [r[0] for r in con.execute(
        "SELECT code FROM stock_flow_daily WHERE date=?", ("2026-09-10",)).fetchall()]
    con.close()
    assert codes == ["920001"]   # 旧 600000/000001 已被整日期替换清除，不被掩盖


def test_fdq_partial_rerun_no_mask(tmp_path, monkeypatch):
    db = _make_temp_db(tmp_path)
    con = sqlite3.connect(db)
    for code in ("600000", "000001", "920001"):
        con.execute("INSERT INTO stock_daily (date,code,name,close,created_at) VALUES (?,?,?,?,?)",
                    ("2026-09-10", code, code, 1.0, 1.0))
    con.commit(); con.close()
    _patch_get_conn(monkeypatch, db)
    cap = _patch_audit_log(monkeypatch)
    _patch_fetch_daily(monkeypatch, [DAILY_FULL[2:4]], total=2)
    monkeypatch.setattr(fdq, "_prev_day_bse_count", lambda con, date, table="stock_daily": 0)
    monkeypatch.setattr("sys.argv", ["fill_daily_quotes.py", "2026-09-10"])
    fdq.main()
    con = sqlite3.connect(db)
    codes = sorted(r[0] for r in con.execute(
        "SELECT code FROM stock_daily WHERE date=?", ("2026-09-10",)).fetchall())
    con.close()
    # NOT IN delete 保留 920001、删除 stale 非候选集（600000/000001）
    assert codes == ["920001"]


# ── (gap_3 + blocker#1) close=None 代码：accepted 但不可写，且旧行不得残留 ──
def test_fdq_close_none_reduces_writeable(tmp_path, monkeypatch):
    db = _make_temp_db(tmp_path)
    _patch_get_conn(monkeypatch, db)
    cap = _patch_audit_log(monkeypatch)
    rows = [dict(r) for r in DAILY_FULL]
    rows[0]["close"] = None  # 600000 本次返回但收盘价为空
    _patch_fetch_daily(monkeypatch, [rows], total=4)
    monkeypatch.setattr("sys.argv", ["fill_daily_quotes.py", "2026-09-10"])
    fdq.main()
    rec = cap[-1][0]
    assert rec["accepted"] == 3        # 代码资格仍接受 600000
    assert rec["writeable"] == 2       # 但可写仅 2（600000 close=None 排除）
    con = sqlite3.connect(db)
    n = con.execute("SELECT count(*) FROM stock_daily WHERE date=?", ("2026-09-10",)).fetchone()[0]
    con.close()
    assert n == 2                       # 实际写入 = writeable，非 accepted（gap_3 闭合）


def test_fdq_close_none_stale_mask(tmp_path, monkeypatch):
    # 同日旧数据：600000 已有完整行；本次 600000 close=None → 旧行必须被删除，不得残留掩盖
    db = _make_temp_db(tmp_path)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO stock_daily (date,code,name,close,created_at) VALUES (?,?,?,?,?)",
                ("2026-09-10", "600000", "浦发", 1.0, 1.0))
    con.commit(); con.close()
    _patch_get_conn(monkeypatch, db)
    cap = _patch_audit_log(monkeypatch)
    rows = [dict(r) for r in DAILY_FULL]
    rows[0]["close"] = None
    _patch_fetch_daily(monkeypatch, [rows], total=4)
    monkeypatch.setattr("sys.argv", ["fill_daily_quotes.py", "2026-09-10"])
    fdq.main()
    con = sqlite3.connect(db)
    codes = [r[0] for r in con.execute(
        "SELECT code FROM stock_daily WHERE date=?", ("2026-09-10",)).fetchall()]
    con.close()
    assert "600000" not in codes            # 旧行已删，未被掩盖（blocker#1 闭合）
    assert sorted(codes) == ["000001", "920001"]


# ── L1 · Single Writer（CIO 裁定 Q1-A'，2026-09-14）──
# canary 模式现在**必须**持有合法 session 租约（`backend/ingest_lock.py`）。
# 本 fixture 提供合规租约，使下方 4 个 canary 测试继续验证原断言，
# 同时覆盖"带租约的 canary 路径"这一新增前置条件。
# 租约路径重定向到 tmp_path ⇒ 绝不触碰 backend/output/ 与生产库。
@pytest.fixture
def canary_lease(tmp_path, monkeypatch):
    import ingest_lock
    monkeypatch.setenv("STEP5C_LEASE_PATH", str(tmp_path / "STEP5C_SESSION.lease"))
    monkeypatch.delenv("STEP5C_SESSION_ID", raising=False)
    sid = ingest_lock.acquire(owner="pytest")
    monkeypatch.setenv("STEP5C_SESSION_ID", sid)
    yield sid
    try:
        ingest_lock.release(sid)
    except ingest_lock.LeaseError:
        pass


# ── (blocker#2) Canary 写前 preflight：审计设施不可用 → 不进入 DB mutation ──
def _raise_on_strict(rec, strict=False):
    if strict:
        raise RuntimeError("AUDIT_LOG_WRITE_FAILED (simulated)")


def test_fdq_canary_preflight_blocks_when_audit_down(tmp_path, monkeypatch, canary_lease):
    # 先种 sentinel：目标日期已有一行旧数据，且其 code 不在本次 provider 集合内。
    # 若实现退化为「DELETE 先于 INTENT」，DELETE 会删掉 sentinel → 本测试必红。
    # 空表起步无法区分这种退化（独立复审 residual #2）。
    monkeypatch.setenv("BSE_INGEST_CANARY", "1")
    db = _make_temp_db(tmp_path)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO stock_daily (date,code,name,close,created_at) VALUES (?,?,?,?,?)",
                ("2026-09-10", "600519", "贵州茅台", 1688.0, 1.0))
    con.commit(); con.close()
    _patch_get_conn(monkeypatch, db)
    monkeypatch.setattr(fdq, "_write_bse_audit_log", _raise_on_strict)
    _patch_fetch_daily(monkeypatch, [DAILY_FULL], total=4)
    monkeypatch.setattr("sys.argv", ["fill_daily_quotes.py", "2026-09-10"])
    before = _snapshot(db, "stock_daily", "2026-09-10")
    with pytest.raises(RuntimeError, match="AUDIT_LOG_WRITE_FAILED"):
        fdq.main()
    after = _snapshot(db, "stock_daily", "2026-09-10")
    assert after == before                       # 逐行逐列完全不变（INTENT 先于 DELETE）
    assert [r[1] for r in after] == ["600519"]   # 仅 sentinel，无任何 mutation


def test_fsf_canary_preflight_blocks_when_audit_down(tmp_path, monkeypatch, canary_lease):
    monkeypatch.setenv("BSE_INGEST_CANARY", "1")
    db = _make_temp_db(tmp_path)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO stock_flow_daily (date,code,name,main_net_buy,source,confidence) "
                "VALUES (?,?,?,?,?,?)", ("2026-09-10", "600519", "贵州茅台", 9.9, "old", 1.0))
    con.commit(); con.close()
    _patch_get_conn(monkeypatch, db)
    monkeypatch.setattr(fsf, "_write_bse_audit_log", _raise_on_strict)
    _patch_fetch_flow(monkeypatch, [FLOW_FULL], total=4)
    before = _snapshot(db, "stock_flow_daily", "2026-09-10")
    with pytest.raises(RuntimeError, match="AUDIT_LOG_WRITE_FAILED"):
        fsf.fill(date="2026-09-10")
    after = _snapshot(db, "stock_flow_daily", "2026-09-10")
    assert after == before
    assert [r[1] for r in after] == ["600519"]


def test_fdq_canary_intent_then_pass(tmp_path, monkeypatch, canary_lease):
    monkeypatch.setenv("BSE_INGEST_CANARY", "1")
    db = _make_temp_db(tmp_path)
    _patch_get_conn(monkeypatch, db)
    cap = _patch_audit_log(monkeypatch)
    _patch_fetch_daily(monkeypatch, [DAILY_FULL], total=4)
    fdq.main()
    verdicts = [r["verdict"] for r, _ in cap]
    assert "INTENT" in verdicts
    assert "PASS" in verdicts


def test_fsf_canary_intent_then_pass(tmp_path, monkeypatch, canary_lease):
    monkeypatch.setenv("BSE_INGEST_CANARY", "1")
    db = _make_temp_db(tmp_path)
    _patch_get_conn(monkeypatch, db)
    cap = _patch_audit_log(monkeypatch)
    _patch_fetch_flow(monkeypatch, [FLOW_FULL], total=4)
    fsf.fill(date="2026-09-10")
    verdicts = [r["verdict"] for r, _ in cap]
    assert "INTENT" in verdicts
    assert "PASS" in verdicts


# ── (Step 4D residual #3) WRITE_INTEGRITY_FAIL：commit 前检测 → ROLLBACK，原数据完整恢复 ──
# 故意制造 read-back mismatch：provider 返回重复 code（分页重叠/脏数据）→ UPSERT 迭代次数
# (=writeable) > 去重后实际落库行数 → 事务内 read-back 不符。断言三件事同时成立：
#   ① WRITE_INTEGRITY_FAIL 被抛出 ② 原数据逐行完整恢复（回滚） ③ 无 PASS 审计记录。
def test_fdq_write_integrity_fail_rolls_back(tmp_path, monkeypatch):
    db = _make_temp_db(tmp_path)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO stock_daily (date,code,name,close,created_at) VALUES (?,?,?,?,?)",
                ("2026-09-10", "600519", "贵州茅台", 1688.0, 1.0))
    con.commit(); con.close()
    _patch_get_conn(monkeypatch, db)
    cap = _patch_audit_log(monkeypatch)
    dup = [dict(DAILY_FULL[1]), dict(DAILY_FULL[1]), dict(DAILY_FULL[2])]  # 000001×2 + 920001
    _patch_fetch_daily(monkeypatch, [dup], total=3)
    monkeypatch.setattr("sys.argv", ["fill_daily_quotes.py", "2026-09-10"])
    before = _snapshot(db, "stock_daily", "2026-09-10")
    with pytest.raises(RuntimeError, match="WRITE_INTEGRITY_FAIL"):
        fdq.main()
    after = _snapshot(db, "stock_daily", "2026-09-10")
    assert after == before                                       # ② 回滚：原数据完整恢复
    assert [r[1] for r in after] == ["600519"]
    assert not any(r["verdict"] == "PASS" for r, _ in cap)       # ③ 无 PASS 审计
    assert any(r["verdict"] == "FAIL" and r.get("reason") == "write_integrity_fail"
               for r, _ in cap)                                  # ① 有 FAIL 审计（rolled_back）


def test_fsf_write_integrity_fail_rolls_back(tmp_path, monkeypatch):
    db = _make_temp_db(tmp_path)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO stock_flow_daily (date,code,name,main_net_buy,source,confidence) "
                "VALUES (?,?,?,?,?,?)", ("2026-09-10", "600519", "贵州茅台", 9.9, "old", 1.0))
    con.commit(); con.close()
    _patch_get_conn(monkeypatch, db)
    cap = _patch_audit_log(monkeypatch)
    dup = [dict(FLOW_FULL[1]), dict(FLOW_FULL[1]), dict(FLOW_FULL[2])]  # 000001×2 + 920001
    _patch_fetch_flow(monkeypatch, [dup], total=3)
    before = _snapshot(db, "stock_flow_daily", "2026-09-10")
    with pytest.raises(RuntimeError, match="WRITE_INTEGRITY_FAIL"):
        fsf.fill(date="2026-09-10")
    after = _snapshot(db, "stock_flow_daily", "2026-09-10")
    assert after == before
    assert [r[1] for r in after] == ["600519"]
    assert not any(r["verdict"] == "PASS" for r, _ in cap)
    assert any(r["verdict"] == "FAIL" and r.get("reason") == "write_integrity_fail"
               for r, _ in cap)
