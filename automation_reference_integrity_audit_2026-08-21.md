# Phase 2.5 · Reference Integrity Audit（修正版）

> 2026-08-21 · 对 23 个 B 类（ACTIVE 且 deleted_at 非空）逐条查 runtime_state / runs / delivery_outbox。分类判据：逐条比较 last_run(ms) 与 deleted_at(ms)。

## 关键发现（修正）

1. **0 个『软删后仍被 scheduler 调度』。** 全部 23 个 B 类的 last_run 毫秒值均 **早于** 各自 deleted_at（即软删之前就停了）。UI 隐藏 = 系统已停，验证通过，不存在幽灵任务。
2. **仅 1 个 R3 异常：`automation-1786035428069` 每日八字×紫微合参简报**，`runtime_state.running=True`（僵尸会话标志未复位）。其 last_run≈08-18 仍早于 deleted_at≈08-20，故非活跃调度，仅脏标志需复位。
3. **delivery_outbox 对 B 类零引用。**
4. 17 个 R2（有历史 runs，属 provenance 应保留）、5 个 R1（无引用残留，可 ORPHAN）、1 个 R3（僵尸 running）。

## 逐条引用画像（23 行）

| id | name | running | rt_last | runs_n | 分类 | 建议状态 |
|----|------|---------|---------|--------|------|---------|
| automation-1783738779029 | 每日研投看板 | False | 2026-07-17 | 6 | R2-历史run | DEPRECATED(successor=21:00 GitHub同步) |
| automation-1784046122314 | 每日 AI 新闻推送 | False | - | 0 | R1-无引用 | ORPHAN(无引用残留) |
| automation-1784338980915 | 教学转写·自愈守护 | False | 2026-07-24 | 108 | R2-历史run | DEPRECATED(保留provenance) |
| automation-1784382766252 | 每日研投看板 | False | 2026-07-20 | 0 | R1-仅runtime残留 | DEPRECATED(successor=21:00 GitHub同步) |
| automation-1784973041017 | 美团每日自动领券 | False | 2026-08-05 | 9 | R2-历史run | DEPRECATED(保留provenance) |
| automation-1785404497715 | Checkpoint A — 系统运行健康巡检 (2026-08-15) | False | 2026-08-15 | 1 | R2-历史run | DEPRECATED(保留provenance) |
| automation-1785558807331 | 每周六周报草稿（收盘后） | False | - | 0 | R1-无引用 | ORPHAN(无引用残留) |
| automation-1785902126442 | 盘中 WatchList 09:30（动态热点·westock实时） | False | 2026-08-13 | 6 | R2-历史run | ORPHAN(无活跃successor,不恢复) |
| automation-1785902127173 | 盘中WatchList 09:35 软件开发资金第一 | False | - | 0 | R1-无引用 | ORPHAN(无活跃successor,不恢复) |
| automation-1785902127743 | 盘中WatchList 13:30 影视院线扩散 | False | 2026-08-05 | 1 | R2-历史run | ORPHAN(无活跃successor,不恢复) |
| automation-1785902128308 | 盘中WatchList 14:30 主线资金延续 | False | 2026-08-05 | 1 | R2-历史run | ORPHAN(无活跃successor,不恢复) |
| automation-1785902128913 | 盘中WatchList 10:00 软件开发龙头封板 | False | - | 0 | R1-无引用 | ORPHAN(无活跃successor,不恢复) |
| automation-1786035428069 | 每日八字×紫微合参简报 | True | 2026-08-17 | 11 | R3-僵尸(running=True) | DEPRECATED(保留provenance) |
| automation-1786090090727 | 盘中 WatchList 10:30（动态热点·westock实时） | False | 2026-08-13 | 4 | R2-历史run | ORPHAN(无活跃successor,不恢复) |
| automation-1786090090926 | 盘中 WatchList 11:30（动态热点·westock实时） | False | 2026-08-13 | 4 | R2-历史run | ORPHAN(无活跃successor,不恢复) |
| automation-1786090090995 | 盘中 WatchList 13:30（动态热点·westock实时） | False | 2026-08-12 | 3 | R2-历史run | ORPHAN(无活跃successor,不恢复) |
| automation-1786090091062 | 盘中 WatchList 14:30（动态热点·westock实时） | False | 2026-08-12 | 3 | R2-历史run | ORPHAN(无活跃successor,不恢复) |
| automation-1786415888565 | 黄金监控·三时段（08:30/12:30/20:30） | False | 2026-08-18 | 5 | R2-历史run | DEPRECATED(保留provenance) |
| automation-1786571603607 | 每日系统·中午状态重启 (12:30) | False | 2026-08-18 | 6 | R2-历史run | DEPRECATED(保留provenance) |
| automation-1786571608443 | 每日系统·晚间复盘 (21:30) | False | 2026-08-18 | 7 | R2-历史run | DEPRECATED(保留provenance) |
| automation-1786595351663 | 盘中 WatchList 输出归档（12小时保留） | False | 2026-08-13 | 9 | R2-历史run | ORPHAN(无活跃successor,不恢复) |
| automation-1786596406007 | 盘中 WatchList（多时段·westock实时） | False | 2026-08-18 | 3 | R2-历史run | ORPHAN(无活跃successor,不恢复) |
| automation-1786677039167 | 全市场动量观察·定期摄入 | False | 2026-08-16 | 1 | R2-历史run | DEPRECATED(successor=A类每日动量版) |

## successor / 业务依赖初步判断（R4，待确认）
- 每日研投看板 ×2 → 被 21:00 GitHub 同步取代 → DEPRECATED(successor)
- 全市场动量观察·定期摄入 → 被 A 类每日动量版取代 → DEPRECATED(successor)
- WatchList 全套（11 条）→ 无活跃 successor（用户决定不恢复）→ ORPHAN
- 教学转写 / 美团 / 八字紫微 / 系统午晚复盘 / 黄金监控 → 无 successor → ORPHAN（八字紫微先复位 running）

## 建议的 Phase 2 状态转换方案（待授权）
- 将 23 个 B 类 status 由 ACTIVE 改为中性非活跃（PAUSED），与 deleted_at 自洽；**不删任何 runs 记录（保留 provenance）**、**不动 cron**、**不改 14 个 ACTIVE**。
- 语义区分（记录于 Canonical Registry 文档；DB status 仅支持 ACTIVE/PAUSED，故用 PAUSED 承载）：R1→ORPHAN，R2→DEPRECATED。
- 八字紫微：先复位 `runtime_state.running=False` 再转 PAUSED。
- 该转换消除『ACTIVE+deleted_at』的治理层不一致。

## 顺序
Phase 1 Inventory Freeze: PASS → Phase 2 Reconciliation: PASS → Phase 2.5 Ref Integrity: PASS → Phase 3 Canonical Registry → Phase 4 Scheduler Refactor（最后，不动 cron 直至确认）。