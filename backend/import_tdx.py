"""通达信历史数据导入脚本 (优化版)。"""

from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

TDX_PATH = Path(r"C:\new_tdx64\vipdoc")

MARKET_DIRS = {
    "sh": {"name": "上海", "prefix": "sh"},
    "sz": {"name": "深圳", "prefix": "sz"},
    "bj": {"name": "北京", "prefix": "bj"},
}

DATA_DIRS = ["lday", "eday"]


def read_tdx_day_file(filepath: Path) -> list[dict]:
    """读取单个 TDX .day 文件。"""
    records = []
    
    try:
        with open(filepath, "rb") as f:
            data = f.read()
    except Exception:
        return records
    
    record_size = 32
    num_records = len(data) // record_size
    
    for i in range(num_records):
        offset = i * record_size
        record = data[offset:offset + record_size]
        
        if len(record) < 32:
            break
        
        try:
            date_int = struct.unpack("<I", record[0:4])[0]
            open_raw = struct.unpack("<I", record[4:8])[0]
            high_raw = struct.unpack("<I", record[8:12])[0]
            low_raw = struct.unpack("<I", record[12:16])[0]
            close_raw = struct.unpack("<I", record[16:20])[0]
            amount = struct.unpack("<f", record[20:24])[0]
            volume = struct.unpack("<I", record[24:28])[0]
        except struct.error:
            continue
        
        year = date_int // 10000
        month = (date_int % 10000) // 100
        day = date_int % 100
        
        if year < 1990 or year > 2030:
            continue
        if month < 1 or month > 12 or day < 1 or day > 31:
            continue
        
        records.append((
            f"{year}-{month:02d}-{day:02d}",
            open_raw / 100.0,
            high_raw / 100.0,
            low_raw / 100.0,
            close_raw / 100.0,
            volume,
            amount,
        ))
    
    return records


def get_stock_code_from_filename(filename: str) -> Optional[str]:
    name = filename.replace(".day", "")
    for prefix in ["sh", "sz", "bj"]:
        if name.startswith(prefix):
            return name[len(prefix):]
    return None


def import_market_data(
    market: str,
    start_date: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    from database import models
    
    market_info = MARKET_DIRS.get(market)
    if not market_info:
        return {"files": 0, "records": 0, "skipped": 0}
    
    market_name = market_info["name"]
    market_path = TDX_PATH / market
    
    if not market_path.exists():
        return {"files": 0, "records": 0, "skipped": 0}
    
    all_files = []
    for data_dir in DATA_DIRS:
        dir_path = market_path / data_dir
        if dir_path.exists():
            files = list(dir_path.glob("*.day"))
            all_files.extend(files)
    
    if not all_files:
        print(f"No .day files found for {market_name}")
        return {"files": 0, "records": 0, "skipped": 0}
    
    print(f"Importing {market_name} ({market})... {len(all_files)} files")
    
    total_records = 0
    files_processed = 0
    batch = []
    batch_size = 5000
    
    for filepath in all_files:
        code = get_stock_code_from_filename(filepath.name)
        if not code:
            continue
        
        records = read_tdx_day_file(filepath)
        
        if not records:
            continue
        
        if start_date:
            records = [r for r in records if r[0] >= start_date]
        
        if not records:
            continue
        
        for rec in records:
            batch.append((rec[0], code, "", rec[1], rec[2], rec[3], rec[4], rec[5], rec[6] / 1e8 if rec[6] else 0))
        
        files_processed += 1
        total_records += len(records)
        
        # 批量写入
        if len(batch) >= batch_size:
            if not dry_run:
                _write_batch(batch)
            batch = []
        
        if files_processed % 500 == 0:
            print(f"  {files_processed}/{len(all_files)} files, {total_records} records")
    
    # 写入剩余数据
    if batch and not dry_run:
        _write_batch(batch)
    
    print(f"  Done: {files_processed} files, {total_records} records")
    
    return {"files": files_processed, "records": total_records, "skipped": 0}


def _write_batch(batch: list):
    """批量写入数据库。"""
    from database import models
    
    conn = models.get_db()
    now = time.time()
    
    conn.executemany("""
        INSERT OR REPLACE INTO stock_daily 
        (date, code, name, open, high, low, close, volume, amount, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [(b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7], b[8], now) for b in batch])
    
    conn.commit()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="通达信历史数据导入 (优化版)")
    parser.add_argument("--market", type=str, help="市场代码 (sh/sz/bj)")
    parser.add_argument("--start", type=str, help="起始日期 (YYYYMMDD)")
    parser.add_argument("--dry-run", action="store_true", help="只统计不导入")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("通达信历史数据导入 (优化版)")
    print("=" * 60)
    
    start_time = time.time()
    
    if args.market:
        results = {args.market: import_market_data(args.market, args.start, args.dry_run)}
    else:
        results = {}
        for market in ["sh", "sz", "bj"]:
            results[market] = import_market_data(market, args.start, args.dry_run)
    
    elapsed = time.time() - start_time
    
    print("\\n" + "=" * 60)
    print("导入完成!")
    print("=" * 60)
    
    total_files = sum(r["files"] for r in results.values())
    total_records = sum(r["records"] for r in results.values())
    
    print(f"总文件数: {total_files}")
    print(f"总记录数: {total_records}")
    print(f"耗时: {elapsed:.1f}秒")


if __name__ == "__main__":
    main()
