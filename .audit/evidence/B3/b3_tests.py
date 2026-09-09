# -*- coding: utf-8 -*-
"""P1-B3 test isolation audit: for every test file, does it touch the canonical DB without isolation?"""
import os, re, json

ROOT = r"C:\Users\JOY\WorkBuddy\个人AI研投系统"
SKIP = ("node_modules", ".git", "__pycache__", "frontend", ".venv", "venv")

# Does the file import/invoke something that writes the canonical DB?
WRITER_IMPORTS = re.compile(
    r"\b(models\.get_db|models\.init_db|from\s+database\.models|from\s+database\s+import\s+models"
    r"|import\s+models\b|get_conn\s*\(|from\s+db\s+import|import\s+db\b"
    r"|save_market_daily|save_sector_daily|save_stock_daily|save_limit_up_daily"
    r"|write_decision_ledger|data_health|trader_log|watchlist\.manager)",
)
ISO = {
    "patch_dbpath": re.compile(r"patch\(\s*[\"']db\._DB_PATH|patch\(\s*[\"']db\.db_path|monkeypatch\.setattr\([^)]*DB_PATH|models\.DB_PATH\s*=|A\.DB_PATH\s*="),
    "tmpfile": re.compile(r"tempfile\.\w+|tmp_path|TemporaryDirectory"),
    "memory": re.compile(r":memory:"),
    "monkeypatch_any": re.compile(r"\bmonkeypatch\b|\bpatch\("),
    "autouse": re.compile(r"autouse\s*=\s*True"),
}
DML = re.compile(r"\b(INSERT\s+INTO|INSERT\s+OR|REPLACE\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|executemany|executescript)\b", re.IGNORECASE)

def walk():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP]
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)

rows = []
for path in walk():
    rel = os.path.relpath(path, ROOT).replace("\\", "/")
    base = os.path.basename(rel)
    if not (base.startswith("test_") or base.endswith("_test.py") or "/tests/" in rel or "/test/" in rel):
        continue
    try:
        src = open(path, encoding="utf-8", errors="ignore").read()
    except Exception:
        continue
    touches = bool(WRITER_IMPORTS.search(src)) or "vibe_research.db" in src or bool(re.search(r"sqlite3\.connect", src))
    iso = sorted([k for k, rx in ISO.items() if rx.search(src)])
    n_dml = len(DML.findall(src))
    n_test_funcs = len(re.findall(r"def\s+test_", src))
    rows.append({"file": rel, "touches_db": touches, "iso": iso, "dml": n_dml, "ntest": n_test_funcs})

rows.sort(key=lambda r: (not r["touches_db"], r["file"]))
json.dump(rows, open(r"C:\Users\LIU\AppData\Local\Temp\b3_tests.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

print("TOTAL test files scanned:", len(rows))
print()
print("--- GROUP 1: touches DB / has isolation ---")
for r in rows:
    if r["touches_db"] and r["iso"]:
        print(f"  [ISOLATED] {r['file']:<62} tests={r['ntest']:<3} dml={r['dml']:<3} {','.join(r['iso'])}")
print()
print("--- GROUP 2: touches DB / NO isolation  <-- RISK ---")
n = 0
for r in rows:
    if r["touches_db"] and not r["iso"]:
        print(f"  [!! NOISO ] {r['file']:<62} tests={r['ntest']:<3} dml={r['dml']}")
        n += 1
print("  count:", n)
print()
print("--- GROUP 3: no DB touch ---")
for r in rows:
    if not r["touches_db"]:
        print(f"  [  N/A   ] {r['file']:<62} tests={r['ntest']}")
