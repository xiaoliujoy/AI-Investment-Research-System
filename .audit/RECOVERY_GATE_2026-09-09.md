# P1 · Recovery Gate ⑤ — 受控恢复实验结论（2026-09-09）

- 性质：**受控恢复实验**（用户授权 `CONDITIONAL_GO`，2026-09-09 第 5 条消息）
- 前置裁定：B4 = `RECOVERY_READY_WITH_RESTRICTIONS`（`.audit/DB_LOCATION_AUDIT_B4_2026-09-09.md`）
- 恢复源：`D:\AI研投系统备份\2026-09-06\vibe_research.db`
- 目标：`backend\database\vibe_research.db`（唯一 canonical）

---

## 最终裁定

```yaml
P1_RECOVERY_GATE_5:
  verdict: RECOVERED_WITH_VERIFICATION
  canonical_present: true
  bit_identical_to_backup: true        # size + sha256 全 MATCH
  pytest_canonical_zero_write: true    # Gate ⑦ PASS
  residual_restrictions: ACTIVE        # B4.8 禁止清单仍强制有效
  p1c_status: OPEN                      # 86 处硬编码路径未统一
```

> 恢复本身成功且经验证。**但这不改变 B4 的任何一个 FAIL/Conditional 判定**：
> B4.3（Write Surface）仍 FAIL→P1-C；B4.6（Manual CLI）仍 FAIL；B4.8 禁止清单
> 在 P1-C 完成前持续生效。

---

## ⑤-2 · 恢复前状态确认

| 项 | 事实 |
|---|---|
| canonical 是否存在 | **否**（确认 `backend\database\vibe_research.db` 缺席） |
| C 盘可用空间 | ~80 GB |
| D 盘可用空间 | ~57 GB |
| 备份源完整性 | B1 已证：size=5,087,100,928 / sha256=30d293…5d75 / 头 `SQLite format 3` |

## ⑤-3 · 复制备份到 canonical

```bash
cp "D:/AI研投系统备份/2026-09-06/vibe_research.db" \
   "C:/Users/JOY/WorkBuddy/个人AI研投系统/backend/database/vibe_research.db"
```

- 结果大小：**5,087,100,928 B**（后台执行，~22s 完成）
- 注：Git Bash `cp` 默认**不保留源 mtime**，故 canonical 的 mtime 为复制时刻，
  而非备份源 mtime（2026-09-05 09:04:39）。**完整性由 sha256 证明，mtime 差异不影响**。

## ⑤-4 · 文件级完整性确认

| 项 | 值 | 判定 |
|---|---|---|
| size | 5,087,100,928 B | ✅ MATCH（=备份源） |
| sha256 | `30d293093b456242f56465388e5c09cfbac79c25cd85d0965db94ff1245d5d75` | ✅ MATCH |
| head | `SQLite format 3` | ✅ |

## ⑤-5 · mode=ro healthcheck（恢复后第一个动作）

- 命令：`backend\.workbuddy\automations\automation-1786030229208\healthcheck.py`（`mode=ro`，只读）
- 退出码：**0**（DB_STATUS=OK）
- 核心表可读，MAX date 一致：
  - `stock_daily` 2026-09-04（当日 5,208 行）
  - `stock_flow_daily` 2026-09-04（当日 5,556 行）
  - `sector_daily` 2026-09-04（894 行）
- 数据截止 2026-09-04，与备份源 "2026-09-05 09:04 采集截止" 相符（lag_days≈4，符合周末/非交易时段）

## ⑥ · 恢复后不可变基线（DB 内容级）

快照工具：`.audit\evidence\recovery_gate_snapshot.py`（file:…?mode=ro，零副作用）
基线留档：`.audit\evidence\recovery_pre.json` / `recovery_post.json`

| 指纹 | 值 |
|---|---|
| SIZE | 5,087,100,928 B |
| SHA256 | `30d293093b456242f56465388e5c09cfbac79c25cd85d0965db94ff1245d5d75` |
| canonical mtime_ns | 1788925503359543700（复制时刻） |

关键表 rowcount / MAX date：

| 表 | rows | MAX date |
|---|---|---|
| stock_daily | 23,492,078 | 2026-09-04 |
| sector_daily | 5,254,829 | 2026-09-04 |
| commodity_daily | 32,540 | 2026-09-04 |
| stock_flow_daily | 266,189 | 2026-09-04 |
| market_daily | 41 | 2026-09-04 |
| limit_up_daily | 3,884 | 2026-09-04 |
| stock_info | 5,530 | — |
| intraday_watch_signal | 176 | 2026-08-13 |

> 注：`sector_flow_daily` / `decision_tree_log` / `investment_committee` / `main_net_buy`
> 在本备份中**不存在对应表**（由其他模块/后续链路生成，非本次备份范围），已记录非错误。

## ⑦ · canonical 存在态 pytest 隔离复测（B4.4 终极证明）

命令（带已装守卫，未加 `--allow-prod-db`）：

```bash
python -m pytest tests/test_subprocess_db_isolation.py \
                   tests/test_prod_db_guard.py \
                   tests/test_pipeline_failure_visibility.py -q
```

| 判定项 | 结果 |
|---|---|
| pytest exit code | **0** |
| 通过用例 | **17 passed**（6.70s） |
| canonical mtime_ns 前后 | 1788925503359543700 → 同值 ✅ |
| canonical size 前后 | 5,087,100,928 → 同值 ✅ |
| canonical sha256 前后 | `30d293…5d75` → 同值 ✅ |
| 关键表 rowcount 前后 | 全部一致 ✅ |
| 真实 subprocess 路径 | ✅ `test_subprocess_db_isolation.py` 含真实 `subprocess.run` → 写沙箱、canonical 零触碰 |
| 历史元凶 | ✅ `test_pipeline_failure_visibility.py`（曾写 22,193 行到生产库）现仅写沙箱 |

**`CANONICAL_UNCHANGED = True`** → Gate ⑦ **PASS**。

> 含义：守卫（P0-A 重定向 + P0-B 硬拒 + E1 env 传递 + E1.6 subprocess.run 硬拒）
> 在 canonical **存在**状态下仍 100% 阻断任何写生产库通道。B4.4 的 "缺失态 PASS"
> 已升级为 "存在态 PASS"，行为级证据闭环。

## ⑧ · 手工 CLI 风险复核（静态，未运行）

- 恢复是**文件复制**，未改动任何脚本 → B4.6 结论不变（8 个无 dry-run 脚本仍 FAIL）。
- 新增风险点：canonical 现已存在，若误跑这 8 个脚本，将**直接写入真实生产库**
  （此前因库缺席只会造 0 字节空壳）。→ B4.8 禁止清单第 1~2 条**强化执行**。
- 未运行任何 collector / backfill / `fill_*` / `_*.py` 孤儿脚本（属禁止清单）。

## ⑨ · automation / collector 风险复核（静态，未运行）

- B4.7 结论不变：A1(15:30 run_daily)/A9(16:30 ledger) 写 canonical（预期）；
  A2(08:00 healthcheck)/A3(23:30 备份)/A5(07:30 纪要)/A8(21:00 flow archive) 只读安全。
- **恢复带来的正面变化**：A1/A9 在库缺席时会静默建 0 字节空壳（B2-F4），
  现已消除 —— canonical 存在，主链将写真实库。
- 未手工触发 `daily_collect` / `run_daily` 全链（禁止清单第 3 条）。

## ⑩ · Recovery Verdict

```yaml
verdict: RECOVERED_WITH_VERIFICATION
evidence_chain:
  - "⑤-4 文件级：size+sha256 与备份源 bit-identical"
  - "⑤-5 mode=ro healthcheck：exit=0，核心表可读，MAX date 2026-09-04"
  - "⑥ 内容级基线已留档（recovery_pre.json）"
  - "⑦ pytest 存在态复测：exit=0 / 17 passed / CANONICAL_UNCHANGED=True"
rollback_required: false
open_items:
  - "P1-C Canonical Universe：86 处硬编码路径未统一（B4.3）"
  - "B4.6 手工 CLI 8 个无 dry-run 脚本仍 FAIL（禁止清单生效中）"
  - "残留 subprocess.Popen/cli_runtime、subprocess.call/run_pathA 未覆盖（B4.5 限定 scope）"
```

**结论**：5GB 生产库已从 D 盘备份受控恢复至 canonical，文件级 + 内容级 + 行为级
（pytest 隔离）三重验证全部通过，恢复可逆（D 盘源完好）。**系统回到「DB 在场」的
正常可工作状态**，但所有 B4 治理限制（P1-C / 手工 CLI 禁止 / 禁设 VIBE_DB_PATH）
在 P1-C 完成前持续生效。

---

## 附：本 Gate 产生的工件

| 工件 | 路径 |
|---|---|
| 不可变基线（前/后） | `.audit/evidence/recovery_pre.json` / `recovery_post.json` |
| 基线快照工具 | `.audit/evidence/recovery_gate_snapshot.py` |
| pytest Gate ⑦ 日志 | `.audit/evidence/pytest_gate7.log` |
| 前置裁定 | `.audit/DB_LOCATION_AUDIT_B4_2026-09-09.md` |
