#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
盘中 WatchList 输出自动归档脚本。
策略：backend/output 下的 intraday_*.json 快照只保留 12 小时，旧的移入 archive/intraday_watch/；
_raw_*.json 临时文件只保留 2 小时，旧的直接删除。

用法：
    python backend/archive_watchlist_outputs.py [--dry-run]
"""
import argparse
import os
import shutil
import time
from datetime import datetime, timedelta

ROOT = r'C:\Users\JOY\WorkBuddy\个人AI研投系统'
SRC_DIR = os.path.join(ROOT, 'backend', 'output')
ARCHIVE_DIR = os.path.join(ROOT, 'archive', 'intraday_watch')

# 保留窗口
KEEP_INTRADAY_HOURS = 12
KEEP_RAW_HOURS = 2


def parse_args():
    p = argparse.ArgumentParser(description='Archive old intraday watchlist outputs')
    p.add_argument('--dry-run', action='store_true', help='只打印不移动/删除')
    return p.parse_args()


def ensure_dir(path):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def age_hours(path):
    return (time.time() - os.path.getmtime(path)) / 3600.0


def safe_move(src, dst, dry_run=False):
    if dry_run:
        return True
    ensure_dir(os.path.dirname(dst))
    # 防重名：若目标已存在，追加序号
    if os.path.exists(dst):
        base, ext = os.path.splitext(dst)
        n = 1
        while True:
            candidate = f'{base}_{n}{ext}'
            if not os.path.exists(candidate):
                dst = candidate
                break
            n += 1
    shutil.move(src, dst)
    return True


def main():
    args = parse_args()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f'[{now}] archive_watchlist_outputs start (dry_run={args.dry_run})')

    moved, skipped_move, deleted_raw, skipped_raw = [], [], [], []

    # 1) intraday_*.json：>12h 归档
    for f in sorted(glob_paths(SRC_DIR, 'intraday_*.json')):
        h = age_hours(f)
        base = os.path.basename(f)
        if h > KEEP_INTRADAY_HOURS:
            dst = os.path.join(ARCHIVE_DIR, base)
            if safe_move(f, dst, dry_run=args.dry_run):
                moved.append((base, round(h, 1)))
        else:
            skipped_move.append((base, round(h, 1)))

    # 2) _raw_*.json：>2h 删除
    for f in sorted(glob_paths(SRC_DIR, '_raw_*.json')):
        h = age_hours(f)
        base = os.path.basename(f)
        if h > KEEP_RAW_HOURS:
            if not args.dry_run:
                os.remove(f)
            deleted_raw.append((base, round(h, 1)))
        else:
            skipped_raw.append((base, round(h, 1)))

    print(f'  intraday archived: {len(moved)}')
    for base, h in moved:
        print(f'    + {base} (age={h}h)')
    print(f'  intraday kept (<={KEEP_INTRADAY_HOURS}h): {len(skipped_move)}')
    for base, h in skipped_move:
        print(f'    = {base} (age={h}h)')
    print(f'  raw deleted: {len(deleted_raw)}')
    for base, h in deleted_raw:
        print(f'    - {base} (age={h}h)')
    print(f'  raw kept (<={KEEP_RAW_HOURS}h): {len(skipped_raw)}')
    for base, h in skipped_raw:
        print(f'    = {base} (age={h}h)')
    print('done')


def glob_paths(directory, pattern):
    return [os.path.join(directory, p) for p in os.listdir(directory)
            if os.path.isfile(os.path.join(directory, p)) and match_pattern(p, pattern)]


def match_pattern(name, pattern):
    # 极简通配：只处理 *.json 前缀匹配
    if pattern == 'intraday_*.json':
        return name.startswith('intraday_') and name.endswith('.json')
    if pattern == '_raw_*.json':
        return name.startswith('_raw_') and name.endswith('.json')
    return False


if __name__ == '__main__':
    main()
