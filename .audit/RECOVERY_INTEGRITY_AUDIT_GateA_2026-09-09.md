# Recovery Integrity Audit · Gate A —— 全量 Git Ref / Reachability / Orphan Commit Inventory

> 时间：2026-09-09 · 审计对象：`.git` 损坏与重建后的仓库完整性
> **执行模式：READONLY**（仅 `show-ref` / `for-each-ref` / `fsck --unreachable --dangling` / `cat-file` / `rev-list` / `count-objects`）
> **未执行**：checkout / reset / merge / push / 改文件 / 写 DB / gc / prune / reflog expire

## 核心问题
> `origin/main = 074e467` 是否已重建一条**完整、可解释、不遗漏已发布护栏**的生产链？

**结论：是。可信度由 ~95% 上调至 ~98%。**

## 1. Commit ancestry audit — PASS

```
rev-list --parents --all
074e4670dc7eb9043556a59137fc69fd771a9ea1  277c44b577a1b389cc7ab74e0effcd9062e22d32
277c44b577a1b389cc7ab74e0effcd9062e22d32  df4ac04d99d41a4f38c5f9fb014513aca70236de
df4ac04d99d41a4f38c5f9fb014513aca70236de                       ← shallow 边界（无父，正常）
```
| commit | parent | 对象 | tree |
|---|---|---|---|
| `074e467` | `277c44b` ✅ | readable ✅ | readable ✅ |
| `277c44b` | `df4ac04` ✅ | readable ✅ | readable ✅ |
| `df4ac04` | —（shallow） | readable ✅ | readable ✅ |

可达 commit 数 = **3**（恰为发布链，无多余、无缺漏）。

## 2. Lost / orphan commit inventory

### 2.1 已丢失（对象不可用，本地不可恢复）— 确认
| commit | 状态 |
|---|---|
| `975db51` (SF-013 guard 原始) | gone（已被 `277c44b` 取代） |
| `6679c02` (T1#2 原始) | gone（已被 `074e467` 取代） |
| `13380b1` / `c53d8c4` / `d053363` / `dca2e60` | gone（deferred / daily-sync，内容已在 RECOVERY 备份） |

### 2.2 仍存在但不可达的孤儿 — 已盘清，**无生产代码价值**
| 对象 | 类型 | 身份 | 价值判定 |
|---|---|---|---|
| `3a17308` | commit | 废弃的 T1#2 候选（挂在 df4ac04），被 `t1-2-release@{2}`/`HEAD@{4}` reflog 引用 | 无。**无 ref 指向、不会被 push**；内容已由 `074e467` 取代 |
| `03d0a32` | commit | 被 SIGTERM 打断的 **`git stash` index commit**（message `index on main: dca2e60 …`） | **不可恢复**：parent `dca2e60` 已丢，其 tree `3120ac00` 亦不可读 |
| `038330` | tree | `backend/notify/` 子树快照 | 无唯一价值（同批文件在 `df4ac04` 中同样存在） |
| `01b4a3` (6.9KB) / `02733d` (79KB) / `03d6c9` (16.6KB) | blob | 生成产物（`02733d` = 2025 交易结果统计 JSON） | 无，非生产代码 |

`git stash list` = 空；`refs/stash` 不存在 → **stash 从未真正建立，无可恢复内容**。

## 3. Branch / ref inventory — PASS

```
show-ref（5 个 ref，全部有效解析，无 broken ref）
074e467…  refs/heads/main
074e467…  refs/heads/t1-2-release
074e467…  refs/remotes/origin/main
277c44b…  refs/heads/guard-release
df4ac04…  refs/tags/pre-guard-cherrypick
```
- 本地/远程一致：`main == origin/main == 074e467`，ahead 0 / behind 0。
- **冗余分支（可清理，本次未动）**：`guard-release`（=277c44b，已是 main 祖先）、`t1-2-release`（== main）。

## 4. Tag / ref integrity — PASS
- 仅 1 个 tag：`pre-guard-cherrypick` → `df4ac04`，`type=commit`，解析正常。
- 无悬空/损坏 tag。

## 5. Reachability / fsck audit — PASS
- `git fsck --full` → **exit 0**（无 missing / broken 对象）。
- `count-objects -v`：in-pack 604、loose 20、packs 1、**garbage 0**、size-pack ~10.2MB。
- unreachable/dangling 仅为第 2.2 节已盘清的 5 个对象。

## 6. Release Ledger ↔ Git 实际状态核对 — PASS

| Ledger 项 | Git 实际 | 一致 |
|---|---|---|
| `origin/main = 074e467` | `ls-remote` = `074e4670dc7eb9043556a59137fc69fd771a9ea1` | ✅ |
| T1 #2 = RELEASED | 已 push（1 commit ff），本地 main 对齐 | ✅ |
| SF-013 = `277c44b` | `277c44b` 在链上，为 `074e467` 之父 | ✅ |
| `975db51 → 277c44b` | 原对象 gone，重建后为 `277c44b` | ✅ |
| `6679c02 → 074e467` | 原对象 gone，重建后为 `074e467` | ✅ |
| `3a17308` 废弃 | 孤儿、不可达 | ✅ |
| `backend/tests/` 已恢复 | 17 文件在位 | ✅ |
| daily-sync 未恢复 | `c53d8c4/d053363/dca2e60` gone，内容在 RECOVERY 备份 | ✅（已知待办） |

## 7. T1/T3 已发布变更完整性 — PASS
| 发布 | 内容 | 核验 |
|---|---|---|
| `df4ac04` | T3 生产修改（data health fail-closed） | 含 `backend/data_health.py` ✅ |
| `277c44b` | SF-013 护栏 `test_data_health_fail_closed.py` | 存在，**9136 bytes** ✅ |
| `074e467` | T1#2 修复 + 回归测试 | `:243` = `if _dir(results, "sentiment") == "bearish":` ✅；`test_investment_committee_sentiment_contract.py` 存在 ✅ |

## 8. 形态事实与残余不确定性

1. **仓库为 shallow**（`.git/shallow` = `df4ac04`）：本地仅有 `df4ac04` 之后历史，**更早历史仅存于 GitHub**。
   → 不影响发布链；如需完整本地历史，可 `git fetch --unshallow`（需网络，本次未执行）。
2. **孤儿对象已全部盘清**，无一含唯一生产代码。
3. **冗余分支** 2 个（清理属可选 housekeeping，不影响完整性）。
4 残余 ~2% 不确定性来源：shallow 截断（远程有完整历史兜底）+ 孤儿对象（已逐个定性）。

## 9. 建议后续（均**未在本次执行**，READONLY）
- [ ] 可选：`git fetch --unshallow` 恢复完整本地历史。
- [ ] 可选：删除冗余分支 `guard-release`、`t1-2-release`（均已并入/为祖先）。
- [ ] 可选：`git gc --prune=now` 清理孤儿（`3a17308` / stash 残留 / 3 个 blob + 1 tree）——建议保留至确认无需回退后再做。
- [ ] P1（独立开）：**DB Location & Runtime Dependency Audit**（5GB 生产库实际位置与运行时连接目标）。
