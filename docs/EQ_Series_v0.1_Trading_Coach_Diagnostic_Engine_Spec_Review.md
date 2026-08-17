# Trading Coach Diagnostic Engine v0.1 — Specification Review

> 写 `coach_diagnostics.py` 之前的**最小治理闸门**：把"研究变量 → 稳定测量"这一步定义严谨，防止 Diagnostic 悄悄滑向 Rule。

- 文档类型：**Diagnostic Layer 实现规格评审（翻译层 / 非统计研究）**
- 状态：**OBSERVATION / DESIGN**（设计态，仅描述，不跑新统计）
- 日期：2026-08-16
- 上游设计：`docs/EQ_Series_v0.1_Trading_Coach_Diagnostic_Mapping.md`（已按 3 修正点收口）
- 证据底座：`RC-EQ1-PREREG-v0.1` / `RC-EQ1R-PREREG-v0.1` / `RC-EQ1M-PREREG-v0.1`
- 既有 Coach：`docs/trading_coach/Trading_Coach_v0.2_设计.md`、`docs/trading_coach_prd_v0.1.md`

---

## 0. 边界（铁律，先读）

本引擎是 **Research → Diagnostic 单向翻译的最终落地代码**，不是统计研究、不是分类器、不是规则。

```
Research (EQ 已验证观察，方向+量级)
   │  validated observation
   ▼
Diagnostic Engine v0.1（本文档；只读测量结果）
   │  repeated evidence（跨多笔/多样本一致）
   ▼
Potential Rule（Phase D，须独立样本重复验证）
```

- **仅消费** EQ 系列的已验证观察；**不重算、不回写**任何研究冻结参数（`k=2 / W=48 / IAE_WIN=10 / seed / N_BOOT / N_PERM / 路径定义`）。
- **不接入**生产（`run_daily` / `risk_guard` / `shadow`）。
- **不做**任何"一次相关性 → Coach 标签 → 交易规则"的链路。

---

## 1. 一句话目标

> **把 EQ-1 / EQ-1R / EQ-1M 已验证的研究变量，稳定地测量到每一笔交易上——只测量，不分类、不解释、不决策。**

Coach 由此开始能问"这笔交易失败在 Timing / Exposure / Opportunity / Profit Capture 哪一步"，而不是只看 P&L 一个数字。

---

## 2. 输入（只读，不重算 EQ）

| 项 | 值 |
| --- | --- |
| 源文件 | `backend/output/research_contracts/eq1m_observation_v0_1.json` |
| 读取键 | `per_trade`（210 行） |
| 不读取 | 任何统计字段 / 路径系数 / bootstrap / permutation（那些是 Research 层结论，本引擎不重算） |
| 字段 schema（已确认） | `trade_id`(样本中为 null)、`direction`、`etd_bars`、`etd_minutes`、`IAE_usd`、`Giveback_usd`、`Giveback_late_usd`、`MFE_usd`、`MAE_usd`、`PnL_usd`、`initial_risk_usd`、`mfe_peak_idx`、`duration_bars`、`overlap`、`exit_reason`、`sl_present` |

- `trade_id` 在样本中为 null → 引擎用 **1-based `trade_index`** 兜底标识，并保留 `source_trade_id`（若非空）。
- 缺字段的交易 → 该维度置 null，不报错、不推断。

---

## 3. 输出 schema

### 3.1 每笔交易（测量态，非分类态）

```json
{
  "trade_index": 1,
  "source_trade_id": null,
  "direction": "BUY",
  "timing": {
    "etd_bars": 7.0,
    "etd_percentile": 62.0
  },
  "exposure": {
    "iae_usd": 1.97,
    "iae_percentile": 41.0
  },
  "opportunity": {
    "mfe_usd": 42.8,
    "mfe_percentile": 55.0
  },
  "profit_capture": {
    "giveback_usd": 41.83,
    "giveback_percentile": 70.0,
    "capture_efficiency": 0.023,
    "capture_percentile": 38.0
  },
  "diagnostic_label": null,
  "diagnostic_facts": {
    "opportunity_available": true,
    "giveback_occurred": true,
    "giveback_to_mfe_ratio": 0.977
  },
  "diagnostic_fact_strings": [
    "ETD = 7.0 bars",
    "IAE = $1.97",
    "MFE = $42.8 (opportunity available)",
    "Giveback = $41.83",
    "Capture Efficiency = 2.3%",
    "Giveback/MFE = 97.7%"
  ]
}
```

- `*_percentile`：**样本内描述性百分位**（该值在 210 笔中的排名位置），**仅描述分布，明确标注无交易决策含义**。
- `diagnostic_label`：**恒为 `null`**（v0.1 不分类）。
- `diagnostic_facts` 中的布尔均为**符号检查（sign-check）**：`opportunity_available = (MFE > 0)`、`giveback_occurred = (Giveback > 0)`；**不含任何 cutoff**。`giveback_to_mfe_ratio` 为事实数值（MFE<=0 时为 null）。
- `diagnostic_fact_strings`：仅把上述事实转成**中性陈述**，不出现"应该…/太晚/太早"等解释。

### 3.2 Trading DNA（仅分布 / 描述）

```json
{
  "n": 210,
  "distributions": {
    "etd_bars":      {"median": ..., "p25": ..., "p75": ...},
    "iae_usd":       {"median": ..., "p25": ..., "p75": ...},
    "mfe_usd":       {"median": ..., "p25": ..., "p75": ...},
    "giveback_usd":  {"median": ..., "p25": ..., "p75": ...},
    "capture_efficiency": {"median": ..., "p25": ..., "p75": ..., "n_valid": ...}
  },
  "exit_reason_distribution": {"manual": ..., "sl": ..., "tp": ...},
  "direction_distribution":   {"BUY": ..., "SELL": ...}
}
```

- **不做**"你的最大问题是…"式定性结论。任何行为定性须 Phase C/D 的重复证据，不在此层产生。

---

## 4. v0.1 只做 5 件事

1. **读** `eq1m_observation_v0_1.json` 的 `per_trade`；不重算 EQ。
2. **每笔生成四维原始诊断**：`etd_bars` / `iae_usd` / `mfe_usd` / `giveback_usd` / `capture_efficiency`（MFE<=0→null）。
3. **生成诊断事实**：仅报告数值（ETD / IAE / MFE / Giveback / Capture）；只告诉发生了什么。
4. **结构化 Diagnosis（事实型）**：符号检查布尔 + 事实比率 + 中性陈述串；不进入解释层。
5. **Trading DNA（仅分布/描述）**：N、各维 median/P25/P75、exit_reason 分布；不做定性结论。

---

## 5. D4 数学边界（必锁，不可绕过）

```python
def capture_efficiency(mfe_usd, giveback_usd):
    if mfe_usd is None or mfe_usd <= 0:
        return None                      # 无定义：避免 0/0 与极小 MFE 极端值
    return (mfe_usd - giveback_usd) / mfe_usd
```

- 保留三原始字段 `MFE_usd` / `Giveback_usd` / `capture_efficiency`，**不折叠为单一效率指标**（低 Capture 与低 Opportunity 是不同问题，须分别可观测）。
- `capture_percentile` 仅在 `capture_efficiency` 非 null 时计算，基于有效样本。

---

## 6. 允许的 / 禁止的（v0.1）

| 类别 | 允许 | 禁止 |
| --- | --- | --- |
| 输出形态 | 连续原始值、样本内描述性百分位（标注无决策含义）、`diagnostic_label=null`、DNA 描述统计 | 分类标签（Early/Late/High/Low）、cutoff、分位阈值规则 |
| 统计 | 样本内百分位、median/P25/P75（纯描述） | 新假设检验、bootstrap/permutation、参数优化、相关性重算 |
| 解释 | 中性事实陈述（"Giveback/MFE = 97.7%"） | "你止盈太晚""时机偏早"等解释性结论 |
| 规则 | — | 任何交易信号 / 执行规则 / 仓位建议 |
| 生产 | — | 接入 `run_daily` / `risk_guard` / `shadow`；回写研究冻结参数 |
| 研究参数 | 只读消费 EQ 结论 | 改动 `k=2 / W=48 / IAE_WIN=10 / seed / N_BOOT / N_PERM / 路径定义` |

---

## 7. 与 Mapping 3 修正点的对应（可追溯）

| Mapping 修正点 | 本规格落实位置 |
| --- | --- |
| ① D1/D2/D4 标签未真正定义 → v0.1 不分类 | §3.1 `diagnostic_label=null`、§3.1 仅连续值+百分位、§6 禁止分类/cutoff |
| ② D4 数学边界 MFE<=0→null + 三原始字段 | §5 锁定 `capture_efficiency` 边界、§3.1 保留三字段 |
| ③ "IAE 独立诊断价值"措辞收紧 | Mapping §2/§4 D2 已改；本引擎不在任何输出中使用"独立诊断价值"做强结论，仅消费 EQ-1R 的"关系不能简单由 initial risk 尺度解释" |

---

## 8. 验证计划

1. `python -m py_compile backend/os_layers/coach_diagnostics.py` → 编译通过。
2. 运行引擎 → 读 210 笔、`diagnostic_label` 全程为 null、无 cutoff、无异常。
3. D4 边界自检：统计 `capture_efficiency is None` 的笔数（应等于 MFE<=0 的笔数），打印核对。
4. DNA 自检：N=210，各分布 median/P25/P75 有限、合理。
5. 输出落盘 `backend/output/coach_diagnostics_v0_1.json`。

---

## 9. 决策规则（收口）

- 本引擎是**测量翻译**，不是统计声称，**不需要 Pre-Registration / Gate 0**（那些是 Research 层方法学闭环的护栏，已在 EQ-1M 收口）。
- 但须以 **OBSERVATION / DESIGN** 状态收口：运行成功后，在本文档 §10 记录"已实现并跑通 210 笔，测量态校验通过"，不推导任何交易结论、不产信号。
- 若运行发现 Mapping/规格矛盾（如字段缺失、边界歧义），**回 Mapping 修订并独立记录**，不静默改引擎逻辑。

---

## 10. 下一步

- 本文档评审通过后 → 实现 `backend/os_layers/coach_diagnostics.py`（**Trading Coach Diagnostic Engine v0.1**）。
- 跑通既有 210 笔 → 产出首批诊断 JSON + DNA 观察摘要。
- 之后进入 Phase C（长期 Coach：真实交易 → 自动采集 → EQ Diagnostics → Trading DNA → 行为反馈）。
- 规则化（Phase D）须独立样本重复验证后才考虑；严禁 premature optimization。
- 这是整个系统从"研究发现"到"个人能力测量"的第一次真正连接。

## 11. Closure（2026-08-16，用户定调收口）

- **状态**：B.1 已实现并跑通，收口为 **OBSERVATION / DESIGN**。
- **验证结果**：读 `eq1m_observation_v0_1.json` per_trade 210 笔；`diagnostic_label` 全程 null；D4 边界自检 MFE<=0(96) == capture_efficiency null(96)；cutoff=0；无分类、无规则、未接入生产。
- **原则性状态（用户定调）**：**Measurement Validated, Behavioral Interpretation Pending**（测量系统已验证，行为结论暂缓）。
- 210 笔历史样本证明 Engine 能工作，但**不能证明 Trading DNA 已稳定**；行为定性须 Phase C/D 的跨时间/跨市场重复证据。
- 下一步进入 **Phase B.2：把 Diagnostic Engine 接入真实交易数据流（Observation-only，自动测量不自动干预）**。严禁从此跨入 Interpretation / Rule。
