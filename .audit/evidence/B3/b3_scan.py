# -*- coding: utf-8 -*-
"""P1-B3 Write Surface static scanner. READONLY: only reads source files."""
import os, re, json, sys

ROOT = r"C:\Users\JOY\WorkBuddy\个人AI研投系统"
SKIP = ("node_modules", ".git", "__pycache__", "frontend", ".venv", "venv")

WRITE_RE = re.compile(
    r"\b(INSERT\s+INTO|INSERT\s+OR|UPDATE\s+\w+\s+SET|DELETE\s+FROM|REPLACE\s+INTO"
    r"|CREATE\s+TABLE|CREATE\s+INDEX|CREATE\s+VIEW|DROP\s+TABLE|DROP\s+INDEX"
    r"|ALTER\s+TABLE|ATTACH\s+DATABASE|VACUUM|PRAGMA\s+journal_mode"
    r"|executemany|executescript|\.to_sql\()",
    re.IGNORECASE,
)
DDL_RE = re.compile(r"\b(CREATE\s+TABLE|CREATE\s+INDEX|ALTER\s+TABLE|DROP\s+TABLE)\b", re.IGNORECASE)
DML_RE = re.compile(r"\b(INSERT\s+INTO|INSERT\s+OR|REPLACE\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|executemany)\b", re.IGNORECASE)
DBREF_RE = re.compile(r"vibe_research\.db")

# isolation markers inside a file
ISO_MARKERS = {
    "tmp_path": re.compile(r"\btmp_path\b"),
    "memory_db": re.compile(r":memory:"),
    "monkeypatch": re.compile(r"\bmonkeypatch\b"),
    "tmp_dir": re.compile(r"tempfile\.mkdtemp|TemporaryDirectory|mkstemp"),
    "patch_dbpath": re.compile(r"(monkeypatch|patch|setattr).*(DB_PATH|db_path|_DB_PATH)|DB_PATH\s*=\s*tmp"),
    "autouse_fixture": re.compile(r"autouse\s*=\s*True"),
    "sqlite_backup": re.compile(r"shutil\.copy2?\s*\(|backup\("),
}

def walk():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP]
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)

results = []
noref_write = []
for path in walk():
    try:
        src = open(path, encoding="utf-8", errors="ignore").read()
    except Exception:
        continue
    rel = os.path.relpath(path, ROOT).replace("\\", "/")
    if not DBREF_RE.search(src):
        continue
    wm = WRITE_RE.findall(src)
    if not wm:
        continue
    ddl = len(DDL_RE.findall(src))
    dml = len(DML_RE.findall(src))
    iso = sorted([k for k, rx in ISO_MARKERS.items() if rx.search(src)])
    has_initdb = bool(re.search(r"def\s+init_db|from\s+database\.models\s+import|models\.init_db", src))
    results.append({
        "file": rel,
        "write_hits": len(wm),
        "ddl": ddl,
        "dml": dml,
        "has_initdb": has_initdb,
        "isolation": iso,
        "is_test": bool(re.search(r"(^|/)tests?/|^test_|_test\.py$", rel)) or "/test" in rel.lower(),
        "is_automation": ".workbuddy/automations" in rel,
        "loc": src.count("\n") + 1,
    })

results.sort(key=lambda r: (-r["dml"], -r["ddl"]))
json.dump(results, open(r"C:\Users\LIU\AppData\Local\Temp\b3_scan.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

print("TOTAL files referencing vibe_research.db AND containing write SQL:", len(results))
print("  of which dml>0:", sum(1 for r in results if r["dml"] > 0))
print("  of which ddl>0:", sum(1 for r in results if r["ddl"] > 0))
print("  of which BOTH  :", sum(1 for r in results if r["dml"] > 0 and r["ddl"] > 0))
print()
print("=== TEST files (write surface) ===")
for r in results:
    if r["is_test"]:
        print(f"  {r['file']:<70} dml={r['dml']:<4} ddl={r['ddl']:<3} iso={','.join(r['isolation']) or 'NONE'}")
print()
print("=== NON-TEST files with BOTH ddl+dml (self-schema writers) ===")
for r in results:
    if not r["is_test"] and r["ddl"] > 0 and r["dml"] > 0:
        print(f"  {r['file']:<70} dml={r['dml']:<4} ddl={r['ddl']:<3} initdb={r['has_initdb']}")
