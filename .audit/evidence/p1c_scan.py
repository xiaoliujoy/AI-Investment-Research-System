"""P1-C · Canonical Universe 只读扫描器 v2（不写库、不改代码）。

对 94 个含 `vibe_research.db` 字面的文件做「整文件信号检测」，判定每个文件的
DB 定位事实源与迁移类别，产出决策级 Canonical Universe Matrix。

判定维度（整文件，非仅命中行）：
  - direct_open   : 是否 `sqlite3.connect(...)` 直连
  - single_source : 是否走 `db.get_conn()` / `models.get_db()` / `database.models`
  - env_override  : 是否读 `VIBE_DB_PATH`
  - write         : 全文是否含 INSERT/UPDATE/DELETE/CREATE TABLE/REPLACE
  - ddl           : 全文是否含 CREATE TABLE / init_db
  - cwd_rel       : 是否用 `database/vibe_research.db` 这类 CWD 相对路径
  - is_test       : 是否 tests/ 或 conftest / _test 夹具
  - is_tool       : 是否 backup/healthcheck/inspect/archive 只读工具
"""
import os, re, json

ROOT = r"C:\Users\JOY\WorkBuddy\个人AI研投系统"
SCAN_DIRS = ["backend", "scripts", "trading_os", "daily-os", "quant-lab"]
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".audit", "frontend", "docs", "content", "generated-images", ".workbuddy"}

lit = re.compile(r"vibe_research\.db")
write_re = re.compile(r"\b(INSERT|UPDATE|DELETE\s+FROM|CREATE\s+TABLE|REPLACE\s+INTO|UPSERT)\b", re.I)
ddl_re = re.compile(r"\b(CREATE\s+TABLE|init_db|CREATE\s+INDEX)\b", re.I)
cwd_rel_re = re.compile(r"database[/\\]vibe_research\.db", re.I)
abs_re = re.compile(r"[a-z]:[/\\]")


def analyze(rel, text):
    low = text.lower()
    matched = [i + 1 for i, ln in enumerate(text.splitlines()) if lit.search(ln)]
    direct_open = "sqlite3.connect" in low
    single_source = any(k in low for k in
                       ("get_conn", "get_db", "import db", "import models",
                        "from database", "database.models", "db._db_path"))
    env_override = "vibe_db_path" in low
    write = bool(write_re.search(text))
    ddl = bool(ddl_re.search(text))
    cwd_rel = bool(cwd_rel_re.search(text))
    is_test = ("/tests/" in rel) or rel.endswith("conftest.py") or rel.endswith("test_integration.py")
    is_tool = any(k in low for k in ("_backup_db_to_d", "healthcheck", "_inspect", "flow_evidence_archive", "panqian_ingest"))
    has_abs = any(abs_re.search(ln) and lit.search(ln) for ln in text.splitlines())

    # 命中行是否全是注释/守卫（不含真实打开）
    matched_lines = text.splitlines()
    real_open_in_matched = any(
        lit.search(ln) and ("sqlite3.connect" in ln.lower() or "os.path.join" in ln or "__file__" in ln or "db_path" in ln.lower() or "models" in ln.lower())
        for ln in matched_lines if lit.search(ln)
    )

    # 迁移类别决策
    if is_test:
        mclass = "TEST/GUARD (excluded)"
        relevance = "TEST"
    elif rel in ("backend/db.py", "backend/database/models.py"):
        mclass = "ROOT single-source (defines DB_PATH)"
        relevance = "PROD-WRITE" if write else "PROD-READ"
    elif all(lit.search(ln) and ln.strip().startswith("#") for ln in matched_lines if lit.search(ln)) and not direct_open:
        mclass = "D-mention (no-op)"
        relevance = "COMMENT"
    elif is_tool:
        mclass = "C4-tool-read (legit points to canonical)"
        relevance = "TOOL-READ"
    elif single_source and not direct_open:
        mclass = "A/B single-source (OK, already unified)"
        relevance = "PROD-READ" if not write else "PROD-WRITE"
    elif env_override and direct_open:
        mclass = "E1-env (reads VIBE_DB_PATH; safe only if unset in prod)"
        relevance = "PROD-WRITE" if write else "PROD-READ"
    elif direct_open and write:
        mclass = "C2 WRITE (must unify)"
        relevance = "PROD-WRITE"
    elif direct_open and not write:
        mclass = "C3 READ (migratable to single source)"
        relevance = "PROD-READ"
    elif cwd_rel and write:
        mclass = "C2+C5 WRITE-cwd (fix base + unify)"
        relevance = "PROD-WRITE"
    elif cwd_rel:
        mclass = "C5 CWD-rel (fix path base)"
        relevance = "PROD-READ" if not write else "PROD-WRITE"
    elif write:
        mclass = "C2 WRITE (must unify)"
        relevance = "PROD-WRITE"
    else:
        mclass = "C3 READ-hardcode (migratable)"
        relevance = "PROD-READ"

    return {
        "rel": rel, "matched_lines": matched, "n": len(matched),
        "direct_open": direct_open, "single_source": single_source,
        "env_override": env_override, "write": write, "ddl": ddl,
        "cwd_rel": cwd_rel, "has_abs": has_abs, "is_test": is_test,
        "is_tool": is_tool, "mclass": mclass, "relevance": relevance,
    }


def main():
    rows = []
    for d in SCAN_DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for dp, dirs, files in os.walk(base):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
            for fn in files:
                if not fn.endswith((".py", ".bat", ".sh")):
                    continue
                p = os.path.join(dp, fn)
                rel = os.path.relpath(p, ROOT).replace("\\", "/")
                try:
                    with open(p, encoding="utf-8", errors="ignore") as f:
                        text = f.read()
                except Exception:
                    continue
                if lit.search(text):
                    rows.append(analyze(rel, text))

    rows.sort(key=lambda r: (r["relevance"] != "PROD-WRITE", r["mclass"], r["rel"]))
    json.dump(rows, open(os.path.join(ROOT, ".audit/evidence/p1c_matrix.json"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)

    # 聚合
    from collections import Counter
    by_class = Counter(r["mclass"] for r in rows)
    by_rel = Counter(r["relevance"] for r in rows)
    print("="*78)
    print(f"files scanned (with literal): {len(rows)}")
    print("by relevance:")
    for k in ["PROD-WRITE", "PROD-READ", "TOOL-READ", "TEST", "COMMENT"]:
        print(f"  {k:12s} {by_rel.get(k,0)}")
    print("-"*78)
    print("by migration class:")
    for k, v in sorted(by_class.items(), key=lambda x: -x[1]):
        print(f"  {k:48s} {v}")
    print("="*78)
    print("PROD-WRITE files (must unify):")
    for r in rows:
        if r["relevance"] == "PROD-WRITE":
            print(f"  {r['rel']:55s} direct={int(r['direct_open'])} cwd={int(r['cwd_rel'])} ddl={int(r['ddl'])} env={int(r['env_override'])}")
    print("-"*78)
    print("CWD-relative (fix base):")
    for r in rows:
        if r["cwd_rel"] and r["relevance"] not in ("TEST", "COMMENT"):
            print(f"  {r['rel']:55s} {r['relevance']}")


if __name__ == "__main__":
    main()
