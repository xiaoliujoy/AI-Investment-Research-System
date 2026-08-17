# P0-OBS-2 · Decision / Delivery Telemetry 设计稿

> 属于 **Signal Loss Incident · 2026-08** 的观测层修复第二阶段。
> 状态：**设计稿（DESIGN ONLY）**。本文件不落地任何生产代码，不改动 run_daily / risk_guard / shadow / CIO / os2_report。
> 实施须走 release gate，且应在 P0-OBS-1A 积累 ≥ 若干干净样本之后。

---

## 0. 要解决什么

2026-08 事故的本质：**系统内部判断对了，但用户收到的决策错了**（Decision → Delivery Gap）。
根因之一是最终「不交易」是一个**语义坍缩的输出**——它同时掩盖了：

- IC 其实看多（YES）
- Composite 只差 2 分没过线（63 vs 65）
- 资本维度因数据断接被压低（DEGRADED）

用户看到「不交易」，无法区分「系统判断市场不可做」与「系统判断可参与、但证据链不完整」。
本设计让系统**自己解释「我为什么得出这个决定」**，把语义损失显性化。

核心原则（来自用户 2026-08-17）：

> Telemetry 负责解释与审计，**不负责改变决策**。

---

## 1. 每日 Telemetry 记录的 8 个字段

每个交易日产生一份 `decision_telemetry_YYYY-MM-DD.json`，落入 `backend/output/archive/decision_telemetry/`。

| # | 字段 | 含义 | 来源（现有产物） |
|---|---|---|---|
| 1 | `ic_view` | IC 的投资观点 BULL / NEUTRAL / BEAR | brain_report `decision` 综合；或 L1/L2/L3 方向聚合 |
| 2 | `ic_can_buy` | IC 是否允许参与 YES / NO | brain_report `decision.can_buy` |
| 3 | `composite_score` | 综合评分（0~100） | memo 驾驶舱「综合评分」/ os2_report 输出 |
| 4 | `decision_distance` | 距参与阈值多远（见 §2） | composite_score − 阈值 |
| 5 | `veto_reason` | 谁否决了（见 §3） | 重建 resolve_decision 链路 |
| 6 | `veto_magnitude` | 否决强度（见 §3） | 失败的分差 / 风险分超出量 |
| 7 | `evidence_quality` | 当前证据质量 HIGH / MEDIUM / LOW | flow_snapshot `data_health` + migration status |
| 8 | `final_decision` | 最终用户出口 可以买 / 谨慎参与 / 不交易 | memo 驾驶舱「今日裁决」 |

**关键**：这 8 个字段全部可由**现有产物离线重建**（brain_report + flow_snapshot + memo HTML），
无需改动任何生产逻辑即可先回填历史 → 这正是它应优先于「改裁决器」的原因。

---

## 2. Decision Distance（决策距离）

把「分数」翻译成「距离」：

```
distance_to_participate = composite_score − 65     # 参与门槛
distance_to_strong      = composite_score − 80     # 强参与门槛
```

展示示例：

| composite | 距参与线 | 含义 |
|---|---|---|
| 82 | +17 | 条件充分 |
| 73 | +8 | 条件较好 |
| 65 | 0 | 临界 |
| 64 | −1 | 极接近 |
| 59 | −6 | 尚不足 |
| 42 | −23 | 明显不足 |

这样用户每天看到的不是二元「买/不买」，而是「系统认为距离参与条件还有多远」。
`63 → 65` 与 `35 → 65` 现在都显示「不交易」，信息损失巨大；Decision Distance 修复了这一点。

---

## 3. veto_reason + veto_magnitude

重建链路：`IC.can_buy → composite_score → score_ladder → resolve_decision → final_decision`。

枚举：

| veto_reason | 含义 | magnitude 定义 |
|---|---|---|
| `NONE` | 无否决，IC 与最终一致 | — |
| `COMPOSITE_SCORE` | IC=YES 但 composite < 65 | `65 − composite_score`（分差） |
| `RISK_VETO` | L7 综合风险 ≥ 70 强否决 | `L7 − 70` |
| `DATA_STALE` | 证据健康度 DEGRADED 且触发降级 | 关联 flow_snapshot `effective_weight_fraction` |
| `SAFETY_GUARD` | 系统安检否决 | — |

示例（2026-08-06）：
```
IC View:       BULL
IC Can Buy:    YES
Composite:     63
Threshold:     65
Distance:      -2
Veto:          COMPOSITE_SCORE
Magnitude:     2
Evidence:      LOW
Final:         NO
```
这比单纯「不交易」是两个完全不同的信息系统。

---

## 4. 双轴（Investment View × Evidence Quality）—— 解释层，非决策层

```
               Evidence Quality
               HIGH        MEDIUM       LOW
Investment
View  BULL     可以参与    谨慎参与    看多但暂不扩大风险
      NEUTRAL  等待        等待        等待（证据弱，勿过度解读）
      BEAR     回避        回避        谨慎（证据弱，勿过度解读）
```

**架构边界（铁律）**：双轴用于**解释与展示**，绝不能自动映射成 BUY 指令。
否则我们又重新制造一个隐藏的决策闸门。Telemetry 永远是链路末端的「解释器」，
不是「决策者」。

---

## 5. Signal Preservation Rate（信号保真率）—— 本阶段核心 KPI

定义（直接度量这次事故）：

```
Signal Preservation Rate =
  IC 产生的有效信号中，最终被用户出口正确表达的比例
```

示例：
```
IC YES = 10
最终：参与 6 / 谨慎参与 2 / 不交易 2
→ SPR = 80%

IC YES = 10
最终：参与 0 / 谨慎参与 2 / 不交易 8
→ SPR = 20%
```

这比「预测准确率」更能监测 Decision → Delivery Gap。
修复 M4/M5 后，SPR 应从当前低位回升——这是验证修复有效性的首要指标。

---

## 6. Decision Loss Matrix（决策损失矩阵）

每日归档，积累 30~60 天后可回答「Composite 否决权创造了多少价值 / 损失了多少信号」：

| IC | Composite | Final | 实际结果 | 归类 |
|---|---|---|---|---|
| YES | 高 | 参与 | 正确 | 正常命中 |
| YES | 低 | 不交易 | 上涨 | **Potential Signal Loss** |
| NO | 低 | 不交易 | 下跌 | 正常规避 |
| NO | 高 | 不交易 | — | **Decision Conflict**（需查） |
| YES | 低 | 谨慎参与 | — | 部分表达（待验证） |

`Potential Signal Loss` 的累计计数，就是这次事故的量级化。

---

## 7. 系统架构位置

```
Evidence (市场/资金/产业/宏观数据)
   ↓
IC / Analytical View (brain_report)
   ↓
Decision Engine (resolve_decision)
   ↓
Decision Telemetry  ←── 本设计（解释 + 审计，不改决策）
   ↓
User Presentation (驾驶舱 / 公众号 memo)
```

Telemetry 位于 Decision Engine 与 Presentation 之间，是**旁路观测**，不回写 Engine。

---

## 8. 实施边界（冻结项）

- 不改动 65 / 80 阈值
- 不改动 Composite 权重
- 不接入 M4/M5 生产链路
- 不修改 resolve_decision 的否决逻辑（先观测，后决定是否调整）
- 所有产出仅落 `archive/decision_telemetry/`，不进生产链

## 9. 下一步

1. 先用离线脚本回填 8/4~8/17 的 telemetry（验证 8 字段可全从现有产物重建）。
2. 在驾驶舱渲染层增加 Decision Distance + veto_reason + 双轴（仍走观察/草稿，不落地生产）。
3. 待 P0-OBS-1A 积累 ≥ 30 个干净样本，再评估是否进入 P0-RESEARCH-1 实施与 Composite 角色重审。
