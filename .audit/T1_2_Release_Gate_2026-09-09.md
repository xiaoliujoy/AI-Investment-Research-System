# T1 #2 独立 Release Gate（2026-09-09）

> 待审对象：`t1-2-release`。可信基线已由 `df4ac04` 更新为 **`origin/main = 277c44b`**（Silent Failure Hardening 已发布）。
> 本次**不使用**旧 Ledger 的 `df4ac04 → 3a17308` 拓扑。

## ⚠️ 关键变更：候选 commit 从 `3a17308` 改为 `074e467`

Gate A 首查即发现原候选不可用，必须重建：

| 问题 | 原 `3a17308` | 处理 |
|---|---|---|
| 拓扑 | `parent = df4ac04`，与 `277c44b` 是**同源兄弟**（`3a17308..277c44b = 1` → 分歧） | 重挂到 `277c44b` |
| 若直接 push | **非 fast-forward，会丢掉 `277c44b`**（回滚刚发布的护栏） | — |
| Diff 越界 | 对 `277c44b` 的 diff 含 `test_data_health_fail_closed.py` **删除 171 行** | 重挂后消失 |
| 完整性 | **漏了 T1#2 回归测试**（原始 `6679c02` 含 fix + test 两文件） | 从备份补回 |

重建后候选：**`074e467`**（`parent = 277c44b`，含 `investment_committee.py` 修复 + `test_investment_committee_sentiment_contract.py`）。

## Gate A：拓扑与边界 — PASS

```
t1-2-release 链：074e467 → 277c44b → df4ac04
parent(074e467)        = 277c44b          ✅
277c44b..074e467 count = 1                ✅
074e467..277c44b count = 0（无分歧）      ✅
fast-forward           = YES              ✅
```
Deferred 污染检查（是否为 074e467 祖先）：`13380b1 / c53d8c4 / d053363 / dca2e60 / 6679c02 / 975db51` → **全部 absent ✅**

## Gate B：Diff 精确性 — PASS（附一处需裁定）

```
git diff --stat 277c44b 074e467
 backend/committee/investment_committee.py          |   2 +-      ← 生产修改：1 插 1 删
 backend/tests/test_investment_committee_sentiment_contract.py | 205 +++  ← 新增测试
 2 files changed, 206 insertions(+), 1 deletion(-)
```
生产代码唯一改动（`investment_committee.py:243`）：
```diff
-    if _dir(results, "sentiment") in ("退潮", "冰点"):
+    if _dir(results, "sentiment") == "bearish":
```
- 无配置 / DB / 文档 / 其他生产代码混入 ✅
- **需裁定**：新增测试文件是否与「没有测试混入」冲突。说明：原始 `6679c02` **本就含此测试**，且它是 Gate C 的验证资产；若要求纯修复可再重建（但会丢失 Gate C 断言能力）。

## Gate C：语义回归 — PASS

| 验证项 | 结果 |
|---|---|
| ① `direction == "bearish"` 强否决生效 | ✅ Case1（4 真实历史漏判日 07-16/07-20/08-06/08-21 → NO + hard_no 含"情绪退潮/冰点"） |
| ② 原 `退潮/冰点` 不再错误触发 / 防过度修复 | ✅ Case2（仅英文 `bearish` 触发；`neutral_bearish != "bearish"`） |
| ③ 正常 bullish / neutral 未被误伤 | ✅ Case3（4 目标 YES→NO，其余 **58 样本 100% 不变**） |
| ④ 现有相关测试无 regression | ✅ `test_data_health_fail_closed.py` **3 passed**；`test_pure.py + test_fixes.py` **16 passed** |

```
tests/test_investment_committee_sentiment_contract.py  → 4 passed in 3.84s
tests/test_data_health_fail_closed.py                  → 3 passed in 2.09s
tests/test_pure.py tests/test_fixes.py                 → 16 passed in 12.00s
```
- 枚举契约 Case4 ✅（direction 必须是合法英文枚举）

## Gate D：Working Tree — PASS

```
git status --short = [ ?? .audit/ ]     ← 唯一脏项，未跟踪，不进 commit
```
- commit 内容仅 2 个目标文件，**无 `.audit`、无 daily-sync 混入** ✅
- 工作树 `:243` 确认 = `if _dir(results, "sentiment") == "bearish":` ✅

**过程中修复的一个既有损伤**：`backend/tests/` 整个目录在磁盘上消失（SIGTERM 中断的 reset 所致，blob 均在对象库、未丢数据）。因 git index 与 target 一致而跳过重写 → 删除 index 后 `reset --hard` 全量恢复，**17 个文件全部回归**。

## ⚠️ 附带发现（非本次事故造成，不影响本 Gate）

生产 DB **不在本工作树**：`backend/vibe_research.db` 为 **0 字节占位**（mtime `2026-07-11`，早于今日恢复两个月 → **未被本次操作触碰**）；`backend/database/` 无 db 文件；项目内**无任何 >50MB 文件**。
即 memory 记载的 5GB 库 `backend/database/vibe_research.db` 本就不在此树（迁移未带来或存于别处）。**既有缺口，需另行确认 DB 实际位置。**

## Gate E：Release Candidate

```yaml
T1_2_RELEASE_GATE:
  base: 277c44b
  candidate: 074e467
  topology: PASS
  diff_boundary: PASS
  semantic_regression: PASS
  working_tree: PASS
  deferred_contamination: NONE
  status: RELEASED
  released_at: "2026-09-09 00:2x"
  push: "277c44b..074e467  t1-2-release -> main  (fast-forward, exit 0)"
  ls_remote_verify: "074e4670dc7eb9043556a59137fc69fd771a9ea1  refs/heads/main"
  local_align: "main=074e467, origin/main=074e467, ahead=0/behind=0"
  note: >
    候选由 3a17308 重建为 074e467（重挂 277c44b + 补回 T1#2 回归测试）。
    已于用户授权后完成 push，仅 1 commit 入库。
```

## 发布完成（等授权后执行）

```
Gate PASS ✅ → 报告 ✅ → 用户授权 ✅ → git push origin t1-2-release:main ✅
             → ls-remote 验证 origin/main == 074e467 ✅
             → Release Ledger：T1 #2 = RELEASED ✅
```

远程发布链（自上而下）：
```
074e467  T1 #2  fix(committee): sentiment bearish hard veto  ← 本次
277c44b  Silent Failure Hardening: data-health fail-closed guard
df4ac04  fix: fail closed when data health module is unavailable
```
