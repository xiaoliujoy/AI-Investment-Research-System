"""Recovery Gate ⑤ · ⑥/⑦ 不可变基线快照工具（只读，mode=ro）。

用法：
    python recovery_gate_snapshot.py [out.json]
产物：
    - 打印 canonical 文件指纹（size/mtime_ns/sha256）+ 关键表 rowcount/maxdate
    - 若给 out.json，另写结构化快照供前后比对
注意：全程 file:...?mode=ro，绝不打开可写连接，零副作用。
"""
import sqlite3, os, json, hashlib, sys

CANON = r"C:\Users\JOY\WorkBuddy\个人AI研投系统\backend\database\vibe_research.db"

# 决策相关关键表（Gate ⑦ 要求「关键表 rowcount 前后完全一致」）
KEY_TABLES = [
    "stock_daily", "sector_daily", "commodity_daily", "stock_flow_daily",
    "market_daily", "limit_up_daily", "stock_info", "sector_flow_daily",
    "decision_tree_log", "investment_committee", "main_net_buy",
    "intraday_watch_signal",
]


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def main():
    st = os.stat(CANON)
    size = st.st_size
    mtime_ns = st.st_mtime_ns
    sha = sha256_file(CANON)

    uri = "file:" + CANON.replace("\\", "/") + "?mode=ro"
    c = sqlite3.connect(uri, uri=True)  # 必须 uri=True 才能解析 file: URI
    cur = c.cursor()
    counts, maxdates = {}, {}
    for t in KEY_TABLES:
        try:
            counts[t] = cur.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
        except Exception as e:
            counts[t] = f"ERR:{e}"
            continue
        try:
            cols = [d[1] for d in cur.execute(f"PRAGMA table_info('{t}')").fetchall()]
            if "date" in cols:
                maxdates[t] = cur.execute(f"SELECT MAX(date) FROM '{t}'").fetchone()[0]
        except Exception:
            pass
    c.close()

    snap = {"size": size, "mtime_ns": mtime_ns, "sha256": sha,
            "rowcounts": counts, "maxdate": maxdates}
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w") as f:
            json.dump(snap, f, indent=2)

    print("=" * 64)
    print(f"CANONICAL: {CANON}")
    print(f"SIZE:      {size}")
    print(f"MTIME_NS:  {mtime_ns}")
    print(f"SHA256:    {sha}")
    print("-" * 64)
    for t in KEY_TABLES:
        if t in counts:
            md = maxdates.get(t)
            print(f"{t:22s} rows={counts[t]}" + (f"  maxdate={md}" if md is not None else ""))
    print("=" * 64)


if __name__ == "__main__":
    main()
