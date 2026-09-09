# -*- coding: utf-8 -*-
"""P1-B3 injection #2: redirect canonical DB to a pre-seeded sandbox DB that has
the FULL production schema, then run the suite and observe which tables receive writes.

Zero risk: nothing is ever written to the canonical path.
"""
import os, sqlite3, json

ROOT = r"C:\Users\JOY\WorkBuddy\个人AI研投系统"
CANON = os.path.normpath(os.path.join(ROOT, "backend", "database", "vibe_research.db"))
SANDBOX_DB = os.environ["B3_SANDBOX_DB"]          # pre-seeded with production schema
OUT = os.environ.get("B3_OUT", os.path.join(os.path.dirname(SANDBOX_DB), "probe2.json"))

_orig_connect = sqlite3.connect
_hits = []


def _hooked(database, *a, **kw):
    s = str(database)
    hit = (os.path.normpath(s) == CANON) or (os.path.basename(s) == "vibe_research.db")
    if hit:
        _hits.append(s)
        return _orig_connect(SANDBOX_DB, *a, **kw)
    return _orig_connect(database, *a, **kw)


sqlite3.connect = _hooked


def pytest_unconfigure(config):
    # inventory the sandbox DB after the run
    c = _orig_connect(SANDBOX_DB)
    ts = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    res = {}
    for t in ts:
        if t.startswith("sqlite_"):
            continue
        try:
            n = c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        except Exception:
            n = "ERR"
        res[t] = n
    c.close()
    json.dump({"sandbox": SANDBOX_DB, "canonical_connect_attempts": len(_hits), "tables": res},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n\n===== B3 INJECTION #2 =====")
    print("canonical connect attempts:", len(_hits))
    print("sandbox tables with rows > 0 (i.e. what the suite WOULD write to prod):")
    for t, n in res.items():
        if isinstance(n, int) and n > 0:
            print(f"   {t:<40} {n}")
    print("===== END =====\n")
