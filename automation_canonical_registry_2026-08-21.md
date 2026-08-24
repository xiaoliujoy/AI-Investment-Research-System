# Phase 3 · Canonical Registry（14 个活跃任务）

> 2026-08-21 · 冻结基线：仅 `status=ACTIVE AND deleted_at IS NULL` 的 14 个任务。
> 核心不变量：**One Day, One Canonical Production Run** —— 15:30 Daily Close Production 是当日研究生产的唯一事实源；其余任务只能引用/丰富/归档/发布，不得重新生产。

## 分层
- **Production**：真正产生研究数据与结论（Health Check / Daily Close / Decision Log / Weekly Note / Weekly Cognition）
- **Evidence**：补充、验证、归档证据（UST / Momentum / Flow Enrichment / Archive）
- **Publication**：同步 GitHub / memo（Pre-Market Brief / GitHub Push）
- **Governance**：检查点、备份、审计（Checkpoint B/C / Local Backup）

## 生产链时序（交易日）
```
08:00 Health Check (Gate)
08:00 UST Observer   08:45 Momentum
        |
15:30 Daily Close Production  ── CANONICAL MEMO
        |
16:30 Decision Log (FROZEN)  ──┐
18:30 Flow Evidence (ENRICH)  ──┘
        |
21:00 Finalize & Archive  +  GitHub Push (消费15:30 memo)
```

## 逐条条目（14）

### Pre-Market Brief
- **task_id**: `automation-1784175362588`
- **legacy_name**: 盘前纪要每日自动抓取
- **schedule**: FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=7;BYMINUTE=30
- **layer**: Publication/Input
- **input**: output/panqian_queue/ (.txt/.url)
- **output**: panqian_feed.json + 盘前备忘录 HTML
- **dependency**: 无
- **side_effect**: 写 feed、移动队列到 archive
- **status**: ACTIVE
- **备注**: 盘前人工复制粘贴素材，非生产链

### Daily Publication (GitHub)
- **task_id**: `automation-1785037277644`
- **legacy_name**: 每日研投日报自动同步GitHub
- **schedule**: FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=21;BYMINUTE=0
- **layer**: Publication
- **input**: 当日 memo（应消费15:30产物）
- **output**: git commit + push
- **dependency**: Daily Close Production (应消费其 memo)
- **side_effect**: git 提交推送
- **status**: ACTIVE
- **备注**: ⚠ 当前重跑 daily_collect+run_daily（Phase4 改只 push）

### Daily Close Production
- **task_id**: `automation-1785399819081`
- **legacy_name**: 交易日自动更新数据并生成研报(15:30)
- **schedule**: FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=15;BYMINUTE=30
- **layer**: Production
- **input**: 各数据源(TDX/东财等)
- **output**: 当日 memo + asset_intelligence_history 落库 + collect.log.json
- **dependency**: 无（生产链入口）
- **side_effect**: 更新 stock_daily 等表、生成研报、写 asset intelligence
- **status**: ACTIVE
- **备注**: ★ CANONICAL PRODUCTION BOUNDARY：当日研究生产唯一事实源

### Checkpoint B
- **task_id**: `automation-1785409809893`
- **legacy_name**: Checkpoint B — 初步研究审查 (2026-09-30)
- **schedule**: 2026-09-30T15:30:00
- **layer**: Governance
- **input**: validation_report.json
- **output**: 初步研究审查结论
- **dependency**: 无
- **side_effect**: 审查
- **status**: ACTIVE
- **备注**: 一次性 2026-09-30

### Checkpoint C
- **task_id**: `automation-1785409841264`
- **legacy_name**: Checkpoint C — 统计显著性审查 (2026-12-31)
- **schedule**: 2026-12-31T15:30:00
- **layer**: Governance
- **input**: validation_report.json
- **output**: 统计显著性审查结论
- **dependency**: 无
- **side_effect**: 审查
- **status**: ACTIVE
- **备注**: 一次性 2026-12-31

### Weekly Research Note
- **task_id**: `automation-1785409881241`
- **legacy_name**: Weekly Trading OS Research Note（每周五，含跨市场观察 v2）
- **schedule**: FREQ=WEEKLY;BYDAY=FR;BYHOUR=20;BYMINUTE=0
- **layer**: Production/Research
- **input**: validation_report.json
- **output**: Markdown 研究日志 6 节
- **dependency**: 无
- **side_effect**: 产文章
- **status**: ACTIVE
- **备注**: 对外/研究产出

### Decision Log Build
- **task_id**: `automation-1785538694105`
- **legacy_name**: 每日 Decision Log 草稿（收盘后）
- **schedule**: FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=16;BYMINUTE=30
- **layer**: Production
- **input**: 当日市场数据
- **output**: Decision Log 草稿 (action=WAIT, sector_view 预填)
- **dependency**: Daily Close Production (消费15:30产物)
- **side_effect**: 建库，不生成文章
- **status**: ACTIVE
- **备注**: ★ FROZEN at 16:30，防 look-ahead

### Weekly Cognition Update
- **task_id**: `automation-1785559618604`
- **legacy_name**: 每周六周度认知更新草稿
- **schedule**: FREQ=WEEKLY;BYDAY=SA;BYHOUR=9;BYMINUTE=0
- **layer**: Production/Knowledge
- **input**: 当周数据
- **output**: 周度认知更新草稿（建库）
- **dependency**: 无
- **side_effect**: 建库
- **status**: ACTIVE
- **备注**: 内部知识库更新（周六）

### Flow Evidence Enrichment
- **task_id**: `automation-1785896623311`
- **legacy_name**: 每日 westock 板块资金流交叉验证
- **schedule**: FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=18;BYMINUTE=30
- **layer**: Evidence
- **input**: westock 板块资金流 (mcp)
- **output**: 写入 Decision Log 的 westock_cross_check 列
- **dependency**: Decision Log Build (16:30草稿)
- **side_effect**: 只 enrichment，不改原始 decision
- **status**: ACTIVE
- **备注**: 18:30 仅补充证据

### Data Health Check
- **task_id**: `automation-1786030229208`
- **legacy_name**: 盘前数据健康巡检（交易日 08:00）
- **schedule**: FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=8;BYMINUTE=0
- **layer**: Production/Gate
- **input**: 主库 vibe_research.db 关键表最新交易日
- **output**: 健康巡检报告（仅汇报）
- **dependency**: 无（盘前链 Gate）
- **side_effect**: 只读、只汇报
- **status**: ACTIVE
- **备注**: 决定当日数据能否进生产链

### Local DB Backup
- **task_id**: `automation-1786033017776`
- **legacy_name**: 数据库本地备份（周日 23:30 → D:）
- **schedule**: FREQ=WEEKLY;BYDAY=SU;BYHOUR=23;BYMINUTE=30
- **layer**: Governance
- **input**: 主库 db 文件
- **output**: D://AI研投系统备份//
- **dependency**: 无
- **side_effect**: 拷贝备份
- **status**: ACTIVE
- **备注**: 第二道保险

### Global Momentum Refresh
- **task_id**: `1786677039167`
- **legacy_name**: 全市场动量·每日自动获取与重算
- **schedule**: FREQ=DAILY;BYHOUR=8;BYMINUTE=45
- **layer**: Evidence
- **input**: TheMarketMemo/tradecat Google Sheet (xlsx)
- **output**: momentum_latest.json + 轮动信号
- **dependency**: 无
- **side_effect**: 落盘观察信号，不碰生产
- **status**: ACTIVE
- **备注**: 外部信号交叉验证

### Daily Finalize & Archive
- **task_id**: `automation-1786966060256`
- **legacy_name**: Flow Evidence Archive · 每日快照
- **schedule**: FREQ=DAILY;BYHOUR=21;BYMINUTE=0
- **layer**: Evidence/Archive
- **input**: flow_report 等
- **output**: flow_snapshot_YYYY-MM-DD.json
- **dependency**: 无
- **side_effect**: 落盘快照，不碰生产
- **status**: ACTIVE
- **备注**: 观测层归档

### UST Yield Observer
- **task_id**: `automation-1787098043035`
- **legacy_name**: US Treasury Yield Observer · 每日美债观察
- **schedule**: FREQ=DAILY;BYHOUR=8;BYMINUTE=0
- **layer**: Evidence
- **input**: 美国财政部官网收益率曲线
- **output**: ust_yield_snapshot_YYYY-MM-DD.json + manifest
- **dependency**: 无
- **side_effect**: 落盘快照，不碰生产
- **status**: ACTIVE
- **备注**: 纯观察层

## Phase 4 Scheduler Refactor（待确认，尚未执行）
- 21:00 改为只 Archive + Git Push（消费 15:30 产物，不再 `daily_collect`）
- 08:00 与 08:10 错峰（Health Check / UST Observer）
- 周度两任务改名以明确语义（Registry 已建立 canonical↔legacy 映射，改名不影响 provenance）

## 状态
- Phase 1 Inventory Freeze: PASS
- Phase 2 Reconciliation: PASS
- Phase 2.5 Ref Integrity: PASS
- Phase 2 状态清洗: DONE（23→PAUSED, 0 矛盾, 14 活跃未动）
- Phase 3 Canonical Registry: DONE（本文档）
- Phase 4 Scheduler Refactor: DONE (2026-08-21)
## Phase 4 执行记录 (2026-08-21)
- 美债观察 rrule 08:00→08:10 错峰（automation-1787098043035）。
- GitHub 同步 automation-1785037277644 prompt 改为只 `git commit`+`push`，不再 `daily_run.bat` 重跑 daily_collect/run_daily；固化「15:30 当日研究生产唯一事实源」不变量。验证读回：prompt 已无 daily_run.bat、含 git push、含「绝不补跑」。
- 周度两任务改名**暂缓**（按用户指示：先在 Registry 建立 canonical↔legacy 映射，待冻结后再决定 UI name 是否同步）。
- 创建一次性运行验证检查点 automation-1787353921130（2026-08-25 22:00），自动核对 15:30 生产一次、21:00 只归档发布一次。
- 全链路 Phase 1→4 完成：14 活跃=冻结基线；23 矛盾已 PAUSED（0 矛盾）；治理层不一致消除；核心不变量=One Day, One Canonical Production Run。
