# -*- coding: utf-8 -*-
"""P1-B3 scan v2: indirect write surface via models.get_db()/db.get_conn()/sqlite3.connect."""
import os, re, json

ROOT = r"C:\Users\JOY\WorkBuddy\个人AI研投系统"
SKIP = ("node_modules", ".git", "__pycache__", "frontend", ".venv", "venv")

DML_RE = re.compile(r"\b(INSERT\s+INTO|INSERT\s+OR|REPLACE\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|executemany|executescript)\b", re.IGNORECASE)
DDL_RE = re.compile(r"\b(CREATE\s+TABLE|CREATE\s+INDEX|ALTER\s+TABLE|DROP\s+TABLE)\b", re.IGNORECASE)

# indirect connectors
CONN_PATTERNS = {
    "models.get_db": re.compile(r"models\.get_db\s*\(|from\s+database\.models\s+import[^;\n]*\bget_db\b|from\s+database\s+import\s+models"),
    "db.get_conn": re.compile(r"\bget_conn\s*\(|from\s+db\s+import"),
    "raw_sqlite3_connect": re.compile(r"sqlite3\.connect\s*\("),
    "models.init_db": re.compile(r"models\.init_db|init_db\s*\("),
    "models_DB_PATH": re.compile(r"models\.DB_PATH|DB_PATH"),
}

def walk():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP]
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)

rows = []
for path in walk():
    try:
        src = open(path, encoding="utf-8", errors="ignore").read()
    except Exception:
        continue
    rel = os.path.relpath(path, ROOT).replace("\\", "/")
    conns = sorted([k for k, rx in CONN_PATTERNS.items() if rx.search(src)])
    if not conns:
        continue
    dml = len(DML_RE.findall(src))
    ddl = len(DDL_RE.findall(src))
    # isolation
    iso = []
    if re.search(r":memory:", src): iso.append("memory")
    if re.search(r"\btmp_path\b", src): iso.append("tmp_path")
    if re.search(r"\bmonkeypatch\b", src): iso.append("monkeypatch")
    if re.search(r"tempfile\.(mkdtemp|TemporaryDirectory)", src): iso.append("tmpdir")
    if re.search(r"autouse\s*=\s*True", src): iso.append("autouse")
    is_test = bool(re.search(r"(^|/)tests?/|(^|/)test_|_test\.py$", rel))
    rows.append({"file": rel, "conn": conns, "dml": dml, "ddl": ddl, "iso": iso, "is_test": is_test})

json.dump(rows, open(r"C:\Users\LIU\AppData\Local\Temp\b3_scan2.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

print("TOTAL files with any DB connector:", len(rows))
print()
print("=== TEST files that touch DB (is_test) ===")
for r in sorted([r for r in rows if r["is_test"]], key=lambda x: -x["dml"]):
    print(f"  {r['file']:<62} dml={r['dml']:<4} ddl={r['ddl']:<3} conn={','.join(r['conn']):<40} iso={','.join(r['iso']) or '*** NONE ***'}")
print()
print("=== NON-test files: indirect write via models.get_db (no explicit db path string) ===")
cnt = 0
for r in sorted([r for r in rows if not r["is_test"] and r["dml"] > 0 and "models.get_db" in r["conn"]], key=lambda x: -x["dml"]):
    has_path = "vibe_research.db" in open(os.path.join(ROOT, r["file"].replace('/', os.sep)), encoding="utf-8", errors="ignore").read()
    print(f"  {r['file']:<62} dml={r['dml']:<4} ddl={r['ddl']:<3} explicit_path={has_path}")
    cnt += 1
print("  count:", cnt)
