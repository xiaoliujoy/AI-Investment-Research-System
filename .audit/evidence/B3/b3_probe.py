# -*- coding: utf-8 -*-
"""P1-B3 behavioral injection probe (pytest plugin).

READONLY-safe: redirects any connection to the canonical vibe_research.db into a
throwaway sandbox file so no file is created at the canonical path, while
recording every attempted connection and every SQL statement executed.
"""
import os, sqlite3, tempfile, json, atexit, threading

ROOT = r"C:\Users\JOY\WorkBuddy\个人AI研投系统"
CANON = os.path.normpath(os.path.join(ROOT, "backend", "database", "vibe_research.db"))
SANDBOX = tempfile.mkdtemp(prefix="b3_probe_")
OUT = os.path.join(SANDBOX, "probe_log.json")

_orig_connect = sqlite3.connect
_lock = threading.Lock()
LOG = []          # {"target":..., "redirected":bool, "sql":[..], "dml":n}
_ctx = threading.local()

DML = ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE TABLE", "CREATE INDEX",
       "ALTER TABLE", "DROP TABLE", "DROP INDEX", "ATTACH", "VACUUM")


def _hooked(database, *a, **kw):
    s = str(database)
    hit = (os.path.normpath(s) == CANON) if os.sep in s else False
    if not hit and os.path.basename(s) == "vibe_research.db":
        hit = True
    target = s
    if hit:
        # never create a file at the canonical path: redirect to sandbox
        target = os.path.join(SANDBOX, "shadow.db")
    conn = _orig_connect(target, *a, **kw)
    if hit:
        import traceback
        st = traceback.extract_stack()[:-1]
        frames = [f"{os.path.basename(f.filename)}:{f.lineno}:{f.name}" for f in st[-12:]]
        cur = ""
        try:
            import pytest as _pt
            cur = os.environ.get("PYTEST_CURRENT_TEST", "")
        except Exception:
            pass
        rec = {"target": s, "redirected": True, "sql": [], "dml": 0,
               "test": cur, "frames": frames}
        with _lock:
            LOG.append(rec)
        def _trace(stmt, _rec=rec):
            _rec["sql"].append(stmt)
            u = stmt.strip().upper()
            if any(u.startswith(d) for d in DML):
                _rec["dml"] += 1
        try:
            conn.set_trace_callback(_trace)
        except Exception:
            pass
    return conn


sqlite3.connect = _hooked


def pytest_unconfigure(config):
    try:
        with _lock:
            json.dump({"sandbox": SANDBOX, "canon": CANON, "hits": LOG},
                      open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("\n\n===== B3 PROBE =====")
        print("sandbox:", SANDBOX)
        print("canonical connect attempts:", len(LOG))
        for i, r in enumerate(LOG):
            if r["dml"] == 0:
                continue
            print(f"  #{i+1} dml={r['dml']}  test={r.get('test','')}")
            print(f"      frames: {' <- '.join(r.get('frames', [])[-6:])}")
            for s in r["sql"][:3]:
                if s.strip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP")):
                    print("      SQL:", s.strip()[:100])
        print("===== END PROBE =====\n")
    except Exception as e:
        print("probe flush failed:", e)
