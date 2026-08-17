# Phase 1E · FROZEN / OBSERVATION + PROVENANCE MODE

> 生效时点：2026-08-17 19:30（用户正式封板）
> 性质：**Parameter Research Freeze + Decision Provenance Infrastructure 已就位**
> 本阶段目标：不追求立刻提高收益，而追求"每一个未来判断都留下完整、可复盘、可归因的证据链"。

---

## 1. 本阶段不追求什么（明确放弃）

- 不追求更高的"参与率"或"捕获这波涨幅"。
- 不为补救 8 月漏行情而调整任何生产决策参数。
- 不根据单日/单周市场结果反向塑造系统。

系统当前判断能力已被审计验证为**合格**（见 `audit_aug_report.md`：IC YES 次日胜率 71.4%、A/B 候选超额 +0.55%、被 veto 的 YES 中 80% 其实正确）。问题不在"会不会判断"，而在"判断有没有正确送达"。这正是一个观察/归因阶段该研究的对象，而非修补对象。

---

## 2. 现已具备的三层能力

| 层 | 能力 | 状态 | 交付物 |
|---|---|---|---|
| ① Evidence Provenance | 每天知道"系统当时看到了什么" | ✓ 已落地 | `flow_evidence_archive.py` + `flow_snapshots/` + `archive_manifest.jsonl`（含 FAILED 留证） |
| ② Decision Telemetry | 每天知道"系统为什么这样判断" | ◐ 设计完成，待实施 | `decision_telemetry_design.md`（8 字段 + Decision Distance + 双轴） |
| ③ Decision Attribution | 30~60 日后研究"每一层创造/消灭了多少 Alpha" | ○ 待样本 | 见 §5 体检框架 |

**关键约束**：② ③ 只解释、不决策。Telemetry 与 Attribution 不得反向修改 `run_daily / risk_guard / shadow / CIO / os2_report / flow_score / composite`。

---

## 3. Parameter Research Freeze（绝对不能做 / 可以做）

### ❌ 冻结期内禁止（无论触发原因）

| 禁止项 | 典型触发 |
|---|---|
| 改 65/80 阈值 | 看到行情上涨、错过后想"救回" |
| 改 Composite 权重 | 看到资金流入、想临时抬高资金权重 |
| 改 veto 逻辑 | 看到错过行情、想放宽否决 |
| 改 scoring formula | 看到某次误判 |
| 改主线识别 | 看到某个板块暴涨 |
| 加特例规则 | 看到某次错误 |
| 接 M4/M5 生产链路 | 想"立刻修好资金维度" |

> 核心原则：**Observation ≠ Production Decision**。若因当日结果改变规则，最终得到的不是系统研究，而是"系统根据最近一次行情不断自我解释"。

### ✅ 冻结期内允许（且鼓励）

- 数据质量监控、快照、日志、遥测
- 离线统计、错误归因
- 新假设提出、**新实验预登记（Pre-Registration）**
- 观测层脚本（只读、不回灌生产）的维护

---

## 4. 核心长期 KPI（建议成为 CIO 系统健康指标）

### 4.1 Signal Preservation Rate（信号保真率）
> IC 明确产生的有效信号，有多少最终被用户出口正确表达。

```
SPR = 正确保留(参与/谨慎) / IC YES 总数
```

IC YES=20，最终 参与8 + 谨慎7 + 错误降级NO5 → SPR=75%。
**低于阈值即提示 Decision→Delivery Gap 复发。**

### 4.2 Decision Confusion Matrix（决策传递混淆矩阵）
对象从"Prediction"升级为"Decision Transmission"：

| IC | Composite | Final | 解读 |
|---|---|---|---|
| YES | 高 | 参与 | 正确保留 |
| YES | 低 | 不交易 | **Potential Signal Loss** |
| NO | 低 | 不交易 | 正常 |
| NO | 高 | 不交易 | Decision Conflict |
| YES | 低 | 谨慎 | 正常/待验证 |

累计 30~60 天后可定量：Composite 否决权创造了多少价值、损失了多少有效信号。

---

## 5. 30~60 天系统体检（封板后唯一的解冻依据）

届时重点回答五个问题（数据源：Flow Snapshot 时序 + brain_report + memo + 真实 forward return）：

- **Q1** IC 是否真的具有稳定预测价值？
- **Q2** Composite 是否在 IC 之上提供增量信息？
- **Q3** Veto 是否提高了风险调整收益？
- **Q4** M4/M5 接入后，Capital Flow 是否真正增加信息量？
- **Q5** 整个 Decision→Delivery 链路是否还有 Signal Loss？

若五问清晰，系统从"会给投资意见的 AI"迈向"能验证自己每一层价值的研究系统"。

### 解锁前置（Release Gate，缺一不可）
1. 累积 ≥30 个干净决策日（无单日行情驱动的临时改动）
2. OBS-1A 每日快照连续、无静默缺失（manifest 可追）
3. OBS-2 Telemetry 实施并回填历史
4. 跑通 Composite 独立有效性检验（IC v.s. IC+Composite forward return 对照）
5. 用户显式 release gate APPROVED（遵循既有三平面分离：人工 Release Gate）

---

## 6. Baseline Incident 记录（留此，不再反复优化）

**Signal Loss Incident · 2026-08**

根因链（已定位，留作基线，不围绕其反复修补）：

```
真实 A 股资金(正) → stock_flow_daily
        ↓
capital_score.py 算出真实逐股资金分
        ↓
只停留在"龙头资金层"展示  ✗ 未回灌 composite 资金维度
        ↓
migration missing → 0 score → 资本维度进一步压低
        ↓
Composite < 65
        ↓
veto（resolve_decision "取最保守"）
        ↓
IC YES → Final NO
        ↓
驾驶舱显示"不交易" → 用户未收到正确风险信号
```

证据锚点：`flow_snapshot_2026-08-17.json`
- effective_weight_fraction = 0.40（M1/M4/M5 死层）
- 资本维度 effective_weight_in_composite = 0.168（名义 0.40）→ 58% 死权重
- `stock_flow_daily` 8/17 positive_ratio = 0.4531（信号在库），但 `ashare_signal_in_composite = False`

**此事故已完成定位，留作 Baseline Incident。** 修复方案见 `capital_flow_reconnection_spec.md`（仅规格，不实施）。

---

## 7. 执行顺序（钉死，勿反转）

```
P0-OBS-1    Flow Evidence Archive              ✓ 完成
P0-OBS-1A   Daily Snapshot Automation          ✓ 完成（automation-1786966060256，每日21:00）
P0-OBS-2    Decision Telemetry 设计            ✓ 设计稿完成（实施待 release gate）
P0-RESEARCH-1 Capital Flow 重接连规格          ✓ 规格书完成（实施冻结）
   ↓
累积 30~60 个干净决策日（Research Freeze 生效中）
   ↓
Composite 独立有效性检验（Q1~Q5）
   ↓
再决定 Composite 是否拥有 veto 权
   ↓
最后才讨论 65/80 阈值
```

**绝对不**为补救 8 月漏行情直接 `65→60 / 80→75`，那会把一次真实系统事故变成参数过拟合。
