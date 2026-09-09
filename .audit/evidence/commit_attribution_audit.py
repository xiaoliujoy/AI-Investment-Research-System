# -*- coding: utf-8 -*-
"""Commit Attribution Audit —— 只读（READONLY）。

把工作树 74 条改动逐 **文件**、逐 **hunk** 映射到两个目标 commit：
    Commit 1  HISTORICAL : P1-B3·E1 / P1-B3·P0-A·P0-B / P1-B3·B3-F8 / 历史 P0-B
    Commit 2  C7 + C10   : 本轮 DB 消费者迁移 / Universe 单点收敛

目的：找出 **MIXED** 文件（同一文件内混有历史轮次 hunk 与本轮 hunk），
      避免按文件路径拆分时把两个轮次混进同一个 commit。

本脚本只调用 `git diff` 读取，**不修改任何文件、不 staging、不 commit**。

用法：
    python .audit/evidence/commit_attribution_audit.py
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# 特征模式
# ---------------------------------------------------------------------------
HIST_PAT = re.compile(
    r'VIBE_DB_PATH'                 # P1-B3·E1 环境传递
    r'|allow-prod-db'               # P1-B3·P0-A/P0-B 放行开关
    r'|生产库隔离守卫'
    r'|P0-A|P0-B|P1-B3'
    r'|_no_subprocess'              # P1-B3·B3-F8 子进程打桩
    r'|FAULT-INJECT: subprocess'
    r'|monkeypatch\.setenv|mp\.setenv'
    r'|sandbox'
)

C7_PAT = re.compile(
    r'from db import get_conn'
    r'|get_conn\('
    r'|str\(_DB_PATH\)'
    r'|sqlite3\.connect'
    r'|^[+-]\s*(DB|DB_PATH|OUT_DB|db)\s*='
    r'|import sqlite3'
    r'|db_conn\('
)

C10_PAT = re.compile(
    r'from universe import'
    r'|\bis_stock\b|\bmarket_of\b'
    r'|_gtimg_prefix|_ts_code'
    r'|get_prefix|disclosure'
    r'|BJ_PREFIXES'
    r'|北交所'                       # 文档漂移修正
)

HUNK_SPLIT = re.compile(r'^@@ ', re.M)


def classify(body: str):
    """返回一个 hunk 的归属集合。"""
    tags = set()
    if HIST_PAT.search(body):
        tags.add('HISTORICAL')
    if C7_PAT.search(body):
        tags.add('C7')
    if C10_PAT.search(body):
        tags.add('C10')
    return tags or {'UNKNOWN'}


def main():
    out = subprocess.run(
        ['git', 'diff', 'HEAD', '--name-only', '--', 'backend/'],
        cwd=REPO, capture_output=True, text=True)
    files = [f for f in out.stdout.split('\n') if f.strip() and f.endswith('.py')]

    # untracked（不出现在 git diff 里，单独处理）
    st = subprocess.run(['git', 'status', '--short'],
                        cwd=REPO, capture_output=True, text=True).stdout
    untracked = [l[3:].strip() for l in st.split('\n') if l.startswith('??')]

    rows = []
    for f in files:
        d = subprocess.run(['git', 'diff', 'HEAD', '-U3', '--', f],
                           cwd=REPO, capture_output=True, text=True).stdout
        parts = HUNK_SPLIT.split(d)
        # parts[0] 是 diff header，之后每个是 hunk
        hunks = []
        for p in parts[1:]:
            body = '\n'.join(
                ln for ln in p.split('\n') if ln[:1] in '+-' and not ln.startswith('+++')
                and not ln.startswith('---'))
            hunks.append(classify(body))
        if not hunks:
            continue
        all_tags = set()
        for h in hunks:
            all_tags |= h
        if 'HISTORICAL' in all_tags and (all_tags & {'C7', 'C10'}):
            verdict = 'MIXED'
        elif 'HISTORICAL' in all_tags:
            verdict = 'HISTORICAL'
        elif all_tags & {'C7', 'C10'}:
            verdict = 'C7+C10' if len(all_tags & {'C7', 'C10'}) > 1 else \
                      ('C7' if 'C7' in all_tags else 'C10')
        else:
            verdict = 'UNKNOWN'
        rows.append((f, verdict, sorted(all_tags), len(hunks), hunks))

    # 输出
    print('=' * 78)
    print('COMMIT ATTRIBUTION AUDIT (READONLY)')
    print('=' * 78)
    print(f'\nmodified .py 文件数: {len(rows)}\n')

    print('---- 文件级归属 ----')
    for f, verdict, tags, nh, _ in sorted(rows, key=lambda r: (r[1], r[0])):
        print(f'  {verdict:<10} {f}   (hunks={nh}, tags={",".join(tags)})')

    mixed = [r for r in rows if r[1] == 'MIXED']
    print(f'\n---- MIXED 文件（需 hunk 级拆分）: {len(mixed)} ----')
    for f, _, tags, nh, hunks in mixed:
        print(f'\n  {f}')
        for i, h in enumerate(hunks, 1):
            print(f'      hunk {i}: {",".join(h)}')

    hist = [r[0] for r in rows if r[1] == 'HISTORICAL']
    c7 = [r[0] for r in rows if r[1] == 'C7']
    c10 = [r[0] for r in rows if r[1] == 'C10']
    c7c10 = [r[0] for r in rows if r[1] == 'C7+C10']
    unk = [r[0] for r in rows if r[1] == 'UNKNOWN']

    print('\n---- 汇总 ----')
    print(f'  COMMIT1 HISTORICAL (文件级纯历史): {len(hist)}')
    for f in hist:
        print(f'      {f}')
    print(f'  COMMIT2 纯 C7     : {len(c7)}')
    print(f'  COMMIT2 纯 C10    : {len(c10)}')
    for f in c10:
        print(f'      {f}')
    print(f'  COMMIT2 C7+C10   : {len(c7c10)} (文件内既有 DB 迁移又有 Universe 收敛)')
    print(f'  MIXED (需拆分)    : {len(mixed)}')
    for f, *_ in mixed:
        print(f'      {f}')
    print(f'  UNKNOWN           : {len(unk)}')
    for f in unk:
        print(f'      {f}')

    print('\n---- UNTRACKED（新文件，归属需人工判定）----')
    for u in untracked:
        print(f'      {u}')

    print('\n[READONLY] 未 staging、未 commit。')


if __name__ == '__main__':
    main()
