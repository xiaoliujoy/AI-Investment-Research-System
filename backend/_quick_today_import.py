"""快速导入今天 TDX数据。只读每个.day文件最后一条记录，定位日期=20260714则导入。"""
import sqlite3
import struct
import time
from pathlib import Path

TDX = Path("C:/new_tdx64/vipdoc")
DB = Path("database/vibe_research.db")
TARGET = 20260714

def get_short_code(fname: str) -> str:
    for p in ["sh", "sz", "bj"]:
        if fname.startswith(p):
            return fname[len(p):].replace(".day", "")
    return ""

def read_last_record(filepath: Path):
    """读取最后32字节，匹配日期返回(date,open,high,low,close,amount,volume)"""
    try:
        sz = filepath.stat().st_size
        if sz < 32:
            return None
        with open(filepath, "rb") as f:
            f.seek(sz - 32)
            record = f.read(32)
        date = struct.unpack_from("<I", record, 0)[0]
        if date != TARGET:
            return None
        return (
            date,
            struct.unpack_from("<I", record, 4)[0] / 100.0,
            struct.unpack_from("<I", record, 8)[0] / 100.0,
            struct.unpack_from("<I", record, 12)[0] / 100.0,
            struct.unpack_from("<I", record, 16)[0] / 100.0,
            struct.unpack_from("<f", record, 20)[0],   # amount(元)
            struct.unpack_from("<I", record, 24)[0],   # volume(手)
        )
    except:
        return None

def main():
    t0 = time.time()
    all_files = []
    for mkt in ["sh", "sz", "bj"]:
        for sub in ["lday", "eday"]:
            p = TDX / mkt / sub
            if p.exists():
                all_files.extend(p.glob("*.day"))
    print(f"扫描 {len(all_files)} 个 .day 文件...")

    records = []  # [(short_code, date, open, high, low, close, amount, volume, name), ...]
    scanned = 0
    for fp in all_files:
        rec = read_last_record(fp)
        if rec:
            code = get_short_code(fp.name)
            if code:
                records.append((code, *rec, ""))
        scanned += 1
        if scanned % 2000 == 0:
            print(f"  {scanned}/{len(all_files)} → 命中 {len(records)}")

    print(f"命中 {len(records)} 条，耗时 {time.time()-t0:.1f}s")
    if not records:
        print("未找到今日数据！")
        return

    conn = sqlite3.connect(str(DB))
    c = conn.cursor()

    # 删旧 + 查 name
    c.execute("DELETE FROM stock_daily WHERE date = ?", ("20260714",))
    c.execute("DELETE FROM stock_daily WHERE date = ?", ("2026-07-14",))
    
    # 构建 name lookup
    code_names = {}
    for (code, name) in c.execute("SELECT code, name FROM stock_info"):
        code_names[code] = name

    batch = []
    for short_code, date, op, hi, lo, cl, amt, vol, _ in records:
        date_str = f"{date//10000:04d}-{(date//100)%100:02d}-{date%100:02d}"  # 20260714 → 2026-07-14
        name = code_names.get(short_code, short_code)
        batch.append((
            date_str, short_code, name, "",  # 0-3
            op, hi, lo, cl,                   # 4-7
            float(vol), float(amt),            # 8-9  volume, amount
            None, None,                       # 10-11 change_pct, turnover
            None, None,                       # 12-13 market_cap, float_cap
            None, None, None, None,           # 14-17 ma5/10/20/60
            None, None, None,                 # 18-20 high_20d/low_20d/is_new_high
            None, None, None,                 # 21-23 volume_ratio, main_net_buy, created_at
        ))
        if len(batch) >= 5000:
            sql = "INSERT OR REPLACE INTO stock_daily VALUES (" + ",".join(["?"]*24) + ")"
            c.executemany(sql, batch)
            batch = []
    if batch:
        sql = "INSERT OR REPLACE INTO stock_daily VALUES (" + ",".join(["?"]*24) + ")"
        c.executemany(sql, batch)

    conn.commit()
    c.execute("SELECT COUNT(*) FROM stock_daily WHERE date=?", ("2026-07-14",))
    print(f"DB 2026-07-14 共 {c.fetchone()[0]} 条，总耗时 {time.time()-t0:.1f}s ✅")
    conn.close()

if __name__ == "__main__":
    main()
