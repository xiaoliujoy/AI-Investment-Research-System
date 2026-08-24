# Automation Registry Audit（修正版）

> 2026-08-21 · Phase 1 Inventory Freeze + Phase 2 Reconciliation（只读，未改动任何 Scheduler / 未删除任何记录）

## 0. 总览

- 底层 `automations` 表总行数：**38**
- **A 类 真实活跃（ACTIVE 且 deleted_at 空）：14** ← UI 当前显示的全部，与 list 接口一致
- **B 类 矛盾状态（ACTIVE 且 deleted_at 非空）：23** ← 治理层状态机不一致（重点清洗对象）
- **C 类 软删残留（deleted_at 非空、非 ACTIVE）：1**
- D 类 其他：0
- **id 命名前缀不统一**：带 `automation-` 前缀 37 个，不带 1 个（如 `1786677039167` 与 `automation-1786677039167` 是两个不同 id，并非重复主键）

## 1. A 类 · VALID ACTIVE（14 个，真实运行）

|   |
| - |

\#

|   |
| - |

id

|   |
| - |

name

|   |
| - |

schedule

|   |
| - |

被引用

|   |
| - |

1

|   |
| - |

automation-1784175362588

|   |
| - |

盘前纪要每日自动抓取

|   |
| - |

FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=7;BYMINUTE=30

|   |
| - |

是

|   |
| - |

2

|   |
| - |

automation-1785037277644

|   |
| - |

每日研投日报自动同步GitHub

|   |
| - |

FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=21;BYMINUTE=0

|   |
| - |

是

|   |
| - |

3

|   |
| - |

automation-1785399819081

|   |
| - |

交易日自动更新数据并生成研报(15:30)

|   |
| - |

FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=15;BYMINUTE=30

|   |
| - |

是

|   |
| - |

4

|   |
| - |

automation-1785409809893

|   |
| - |

Checkpoint B — 初步研究审查 (2026-09-30)

|   |
| - |

2026-09-30T15:30:00

|   |
| - |

否

|   |
| - |

5

|   |
| - |

automation-1785409841264

|   |
| - |

Checkpoint C — 统计显著性审查 (2026-12-31)

|   |
| - |

2026-12-31T15:30:00

|   |
| - |

否

|   |
| - |

6

|   |
| - |

automation-1785409881241

|   |
| - |

Weekly Trading OS Research Note（每周五，含跨市场观察 v2）

|   |
| - |

FREQ=WEEKLY;BYDAY=FR;BYHOUR=20;BYMINUTE=0

|   |
| - |

是

|   |
| - |

7

|   |
| - |

automation-1785538694105

|   |
| - |

每日 Decision Log 草稿（收盘后）

|   |
| - |

FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=16;BYMINUTE=30

|   |
| - |

是

|   |
| - |

8

|   |
| - |

automation-1785559618604

|   |
| - |

每周六周度认知更新草稿

|   |
| - |

FREQ=WEEKLY;BYDAY=SA;BYHOUR=9;BYMINUTE=0

|   |
| - |

是

|   |
| - |

9

|   |
| - |

automation-1785896623311

|   |
| - |

每日 westock 板块资金流交叉验证

|   |
| - |

FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=18;BYMINUTE=30

|   |
| - |

是

|   |
| - |

10

|   |
| - |

automation-1786030229208

|   |
| - |

盘前数据健康巡检（交易日 08:00）

|   |
| - |

FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=8;BYMINUTE=0

|   |
| - |

是

|   |
| - |

11

|   |
| - |

automation-1786033017776

|   |
| - |

数据库本地备份（周日 23:30 → D:）

|   |
| - |

FREQ=WEEKLY;BYDAY=SU;BYHOUR=23;BYMINUTE=30

|   |
| - |

是

|   |
| - |

12

|   |
| - |

1786677039167

|   |
| - |

全市场动量·每日自动获取与重算

|   |
| - |

FREQ=DAILY;BYHOUR=8;BYMINUTE=45

|   |
| - |

是

|   |
| - |

13

|   |
| - |

automation-1786966060256

|   |
| - |

Flow Evidence Archive · 每日快照

|   |
| - |

FREQ=DAILY;BYHOUR=21;BYMINUTE=0

|   |
| - |

是

|   |
| - |

14

|   |
| - |

automation-1787098043035

|   |
| - |

US Treasury Yield Observer · 每日美债观察

|   |
| - |

FREQ=DAILY;BYHOUR=8;BYMINUTE=0

|   |
| - |

是

## 2. B 类 · CONTRADICTORY（ACTIVE 但已软删，状态机不一致）

> 这 23 条是「乱」的主要来源：UI 已隐藏，但 status 仍写 ACTIVE，且部分在 runtime_state/runs 中仍有引用。

|   |
| - |

id

|   |
| - |

name

|   |
| - |

deleted_at

|   |
| - |

被 scheduler 引用

|   |
| - |

automation-1783738779029

|   |
| - |

每日研投看板

|   |
| - |

1784382760346

|   |
| - |

是

|   |
| - |

automation-1784046122314

|   |
| - |

每日 AI 新闻推送

|   |
| - |

1784046148775

|   |
| - |

否

|   |
| - |

automation-1784338980915

|   |
| - |

教学转写·自愈守护

|   |
| - |

1785977812767

|   |
| - |

是

|   |
| - |

automation-1784382766252

|   |
| - |

每日研投看板

|   |
| - |

1784551874521

|   |
| - |

是

|   |
| - |

automation-1784973041017

|   |
| - |

美团每日自动领券

|   |
| - |

1785977812919

|   |
| - |

是

|   |
| - |

automation-1785404497715

|   |
| - |

Checkpoint A — 系统运行健康巡检 (2026-08-15)

|   |
| - |

1787093711173

|   |
| - |

是

|   |
| - |

automation-1785558807331

|   |
| - |

每周六周报草稿（收盘后）

|   |
| - |

1785559608834

|   |
| - |

否

|   |
| - |

automation-1785902126442

|   |
| - |

盘中 WatchList 09:30（动态热点·westock实时）

|   |
| - |

1786596529051

|   |
| - |

是

|   |
| - |

automation-1785902127173

|   |
| - |

盘中WatchList 09:35 软件开发资金第一

|   |
| - |

1785977813290

|   |
| - |

否

|   |
| - |

automation-1785902127743

|   |
| - |

盘中WatchList 13:30 影视院线扩散

|   |
| - |

1785977813229

|   |
| - |

是

|   |
| - |

automation-1785902128308

|   |
| - |

盘中WatchList 14:30 主线资金延续

|   |
| - |

1785977813136

|   |
| - |

是

|   |
| - |

automation-1785902128913

|   |
| - |

盘中WatchList 10:00 软件开发龙头封板

|   |
| - |

1785977813080

|   |
| - |

否

|   |
| - |

automation-1786035428069

|   |
| - |

每日八字×紫微合参简报

|   |
| - |

1787093717577

|   |
| - |

是

|   |
| - |

automation-1786090090727

|   |
| - |

盘中 WatchList 10:30（动态热点·westock实时）

|   |
| - |

1786596411778

|   |
| - |

是

|   |
| - |

automation-1786090090926

|   |
| - |

盘中 WatchList 11:30（动态热点·westock实时）

|   |
| - |

1786596411912

|   |
| - |

是

|   |
| - |

automation-1786090090995

|   |
| - |

盘中 WatchList 13:30（动态热点·westock实时）

|   |
| - |

1786596412155

|   |
| - |

是

|   |
| - |

automation-1786090091062

|   |
| - |

盘中 WatchList 14:30（动态热点·westock实时）

|   |
| - |

1786596412058

|   |
| - |

是

|   |
| - |

automation-1786415888565

|   |
| - |

黄金监控·三时段（08:30/12:30/20:30）

|   |
| - |

1787093711484

|   |
| - |

是

|   |
| - |

automation-1786571603607

|   |
| - |

每日系统·中午状态重启 (12:30)

|   |
| - |

1787093538129

|   |
| - |

是

|   |
| - |

automation-1786571608443

|   |
| - |

每日系统·晚间复盘 (21:30)

|   |
| - |

1787093537829

|   |
| - |

是

|   |
| - |

automation-1786595351663

|   |
| - |

盘中 WatchList 输出归档（12小时保留）

|   |
| - |

1786633789736

|   |
| - |

是

|   |
| - |

automation-1786596406007

|   |
| - |

盘中 WatchList（多时段·westock实时）

|   |
| - |

1787093711306

|   |
| - |

是

|   |
| - |

automation-1786677039167

|   |
| - |

全市场动量观察·定期摄入

|   |
| - |

1787093711009

|   |
| - |

是

## 3. C 类 · SOFT-DELETED（已软删、非 ACTIVE）

- automation-1784256915504 | 教学视频·增量整理（逐章讲解） | status=PAUSED | deleted_at=1785977812986

## 4. id 命名一致性（非数据损坏）

- 带前缀 `automation-`：37 个；不带前缀：1 个。
- 示例：`1786677039167`（全市场动量·每日版，A 类活跃）与 `automation-1786677039167`（全市场动量观察·定期摄入，B 类已软删）是两个不同 id，曾误判为重复主键，经核验**无重复主键、无数据损坏**，仅为命名前缀不统一（低优先整洁项）。

## 5. 盘中 WatchList 系列

- automation-1785902126442 | 盘中 WatchList 09:30（动态热点·westock实时） | 矛盾(ACTIVE+deleted) | 引用=是
- automation-1785902127173 | 盘中WatchList 09:35 软件开发资金第一 | 矛盾(ACTIVE+deleted) | 引用=否
- automation-1785902127743 | 盘中WatchList 13:30 影视院线扩散 | 矛盾(ACTIVE+deleted) | 引用=是
- automation-1785902128308 | 盘中WatchList 14:30 主线资金延续 | 矛盾(ACTIVE+deleted) | 引用=是
- automation-1785902128913 | 盘中WatchList 10:00 软件开发龙头封板 | 矛盾(ACTIVE+deleted) | 引用=否
- automation-1786090090727 | 盘中 WatchList 10:30（动态热点·westock实时） | 矛盾(ACTIVE+deleted) | 引用=是
- automation-1786090090926 | 盘中 WatchList 11:30（动态热点·westock实时） | 矛盾(ACTIVE+deleted) | 引用=是
- automation-1786090090995 | 盘中 WatchList 13:30（动态热点·westock实时） | 矛盾(ACTIVE+deleted) | 引用=是
- automation-1786090091062 | 盘中 WatchList 14:30（动态热点·westock实时） | 矛盾(ACTIVE+deleted) | 引用=是
- automation-1786595351663 | 盘中 WatchList 输出归档（12小时保留） | 矛盾(ACTIVE+deleted) | 引用=是
- automation-1786596406007 | 盘中 WatchList（多时段·westock实时） | 矛盾(ACTIVE+deleted) | 引用=是

> 全部停用/软删，当前无盘中实时监控在跑（符合「不要恢复」的判断）。

## 6. Phase 2 Reconciliation 结论

- 真实运行集锁定为 14 个，与 UI 一致。
- 23 条矛盾状态（ACTIVE+deleted_at）需清洗为一致状态（DEPRECATED/ORPHAN），消除治理层不一致；其中被引用的应优先处理。
- 无重复主键、无数据损坏；id 前缀不统一为低优先整洁项。
- 盘中 WatchList 已全部停用，保持空窗。

## 7. 下一步（待确认后执行，先不碰 cron）

- Phase 3 Canonical Registry：为 14 个真实任务定义 task_id/schedule/input/output/dependency/side_effect。
- Phase 2 状态清洗：将 B 类 23 条 status 由 ACTIVE 改为一致的非活跃状态（不动 cron、不删数据）。
- Phase 4 Scheduler Refactor（需确认）：21:00 改为只 Archive+Git Push（消费 15:30 产物，不再 daily_collect）；08:00 与 08:10 错峰；周度两任务改名明确语义。
