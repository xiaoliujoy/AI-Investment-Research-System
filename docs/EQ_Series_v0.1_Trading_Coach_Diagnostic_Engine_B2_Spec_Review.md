# Trading Coach Diagnostic Engine v0.1 — Phase B.2 Specification Review

> 把 Diagnostic Engine **接入真实交易数据流** 之前的**最小治理闸门**。B.2 的目标是"自动测量、不自动干预"——严防火墙从 Observation 滑向 Interpretation / Rule。

- 文档类型：**Diagnostic Layer 接入规格评审（翻译层 / 非统计研究 / 非规则）**
- 阶段命名：**Phase B.2 · Measurement Infrastructure Expansion**
- 状态：**APPROVED → IMPLEMENTATION**（用户 2026-08-16 批准进入代码；治理状态 = Measurement Validated / Continuous Observation Enabled / Behavioral Interpretation Pending）
- 管线命名：**B2.0 Manual Observation Pipeline**（手动 CSV 摄入；严禁称 "B2 Live Trading Pipeline"）
- 日期：2026-08-16
- 上游设计：`docs/EQ_Series_v0.1_Trading_Coach_Diagnostic_Mapping.md`（已按 3 修正点收口）
- 上游实现闸门：`docs/EQ_Series_v0.1_Trading_Coach_Diagnostic_Engine_Spec_Review.md`（B.1 已收口，§11 Closure）
- 冻结测量源：`backend/os_layers/entry_quality_eq1m.py::compute_trade`（EQ-1M 已验证观察的逐笔测量核心，本规格原样复用）
- 既有 Coach：`docs/trading_coach/Trading_Coach_v0.2_设计.md`、`docs/trading_coach_prd_v0.1.md`

---

## 0. 边界（铁律，先读）

B.2 = **B.1 引擎（不变） + 摄入适配器（新） + 累积存储（新）**。它不是统计研究、不是分类器、不是规则、不是 Coach 反馈回路。

```
Real Trade (手动导出 blotter + 价格序列)
   │  ingestion adapter（仅搬运 + 调用冻结测量）
   ▼
Frozen Measurement（eq1m.compute_trade 原样复用，仅外部化 contract_multiplier）
   │  逐笔原始测量 → 与 B.1 输入 schema 字节兼容
   ▼
Diagnostic Engine v0.1（B.1 代码，不变；只读测量值 → 四维诊断 + DNA）
   │  累积存储（append，去重，重算滚动 DNA）
   ▼
Observation-only Output（描述性 DNA + 里程碑计数；无解释、无规则、无自动干预）
```

| 铁律 | 含义 |
| --- | --- |
| 不重算 EQ | 路径系数 a/b/indirect、bootstrap/permutation 一概不跑；只消费已验证测量定义 |
| 不回写研究冻结参数 | `K=2 / W=48 / IAE_WIN=10 / seed` 不可改；适配器复用 `compute_trade` 原逻辑 |
| 不接入生产 | 不写 `run_daily` / `risk_guard` / `shadow` / CIO；不产生任何交易信号 |
| 不自动干预 | 引擎只测量、只落盘；绝不向交易终端/Coach UI 推送"建议/告警/标签" |
| 不跨入 Interpretation | "你的 DNA 显示你总是回吐利润" 这类定性结论 **禁止**；DNA 仅描述性 |
| 不跨入 Rule | 任何基于累积 DNA 的 cutoff / 阈值 / 执行规则 **禁止**（那是 Phase D） |

**现实约束（必须诚实声明）**：当前沙箱**没有 MT5 实时连接**，A 股是**手动交易**。"真实交易数据流"这个自动化 source **目前不存在于系统中**。B.2 v0.1 **不假装有 live feed**——它定义为**手动摄入**（用户平仓后导出 blotter + 价格序列，按需运行适配器）。未来 MT5 自动适配器（B.2.1）可单独预登记，但即便那时也必须是 Observation-only，绝不能自动下单或自动改风控。

### 0.1 冻结边界（用户批准，2026-08-16）

B.2 的任务边界 = **「把已经验证的 Measurement Engine 接入持续交易记录」，而不是继续研究行为机制**。Measurement Validated / Behavioral Interpretation Pending 的状态继续保持。

| 层 | B.2 做什么 | B.2 不做什么 |
| --- | --- | --- |
| 数据 | 摄入手动 CSV | 假装存在 live feed |
| Measurement | 复用 B.1 冻结定义 | 修改 CP、IAE、MFE 等算法 |
| Storage | 去重、累计、版本记录 | 根据结果筛选交易 |
| Diagnostic | 自动生成客观指标 | 自动解释「为什么」 |
| Output | Measurement / descriptive statistics | Buy/Sell、止损调整、行为处方 |
| Automation | 自动计算 | 自动干预 |
| Research | 记录样本变化 | 根据新数据修改研究规格 |

### 0.2 `trade_measurement.py` 职责必须极窄

固化管线（任何 B.2 数据流都必须经过这一条）：

```
Raw Trade CSV
   ↓
B2 Ingestion Adapter
   ↓
trade_measurement.py
   ↓
Canonical Trade Measurement
   ↓
Accumulation Store
   ↓
Coach Diagnostic Engine
   ↓
Observation Output
```

`trade_measurement.py` **只能回答**：

> 「这笔交易客观上发生了什么？」

**不能回答**：

> 「这笔交易做得好不好？」「哪里出了问题？」「以后应该怎么做？」

后三类属 Interpretation，留待 Phase C / D，不在本模块的权限内。

### 0.3 B2.0 命名与演进路线

- 本阶段命名为 **B2.0 Manual Observation Pipeline**（手动 CSV 摄入）。**严禁**称 "B2 Live Trading Pipeline"——后者会给人"系统已拥有实时交易终端连接"的错觉。
- 未来独立验证、单独预登记的层级：
  `B2.0 Manual CSV → B2.1 MT5 Adapter → B2.2 A-share Trade Adapter → B2.3 Unified Trade Stream`。每层单独验证、单独预登记，不跨层复用"已验证"标签。

### 0.4 最终治理状态（用户定调，2026-08-16）

- 阶段：**Phase B.2 · Measurement Infrastructure Expansion**。
- 状态：**Measurement Validated / Continuous Observation Enabled / Behavioral Interpretation Pending**。
- 原则：*系统可以越来越快地知道发生了什么，但在进入 Interpretation 阶段之前，它没有资格告诉你应该做什么。*

---

## 1. 一句话目标

> **把 Diagnostic Engine 接到真实交易上：用户每平一批仓，导出的逐笔记录经冻结测量翻译成四维原始诊断，累积进跨样本 Trading DNA——全程只测量、只描述、不解释、不干预。**

这把系统从"210 笔历史样本的一次性测量"推进到"随时间滚动积累的真实交易测量基底"，为 Phase C（行为反馈）和 Phase D（规则化）提供**经重复证据、而非一次性相关性的**前进资质。

---

## 2. 现实约束与数据来源（OBSERVATION-only 的物理边界）

| 来源 | 当前可达性 | B.2 v0.1 摄入方式 |
| --- | --- | --- |
| MT5（外汇/期货） | 沙箱无连接；用户本地有终端 | **手动导出** `trades.csv`（已平仓 history）+ `XAUUSD_M5.csv` 等价格序列 |
| A 股（手动交易） | 通达信本地数据 `C:\new_tdx64\vipdoc` 可用 | 价格序列**自动**从 vipdoc 读 M5；逐笔 blotter **手动**记录（用户填 trading journal） |
| 未来 MT5 适配器 | 不存在 | 留接口，B.2.1 单独预登记；即便接入也 Observation-only |

- **没有自动化流**。B.2 v0.1 的运行模型 = 用户主动触发（CLI / 后续自动化任务），读取本地文件，落盘。
- 这反而最契合 Observation-only：**不可能**自动干预，因为系统根本没有写交易终端的权限。

---

## 3. 输入（两层：trade_blotter + price_bars）

### 3.1 `trade_blotter.csv`（用户手动导出/填写，每平仓一笔一行）

| 列 | 含义 | 必填 |
| --- | --- | --- |
| `ticket` | 券商成交单号（稳定去重键） | 是（A 股可用 `journal_<日期>_<序号>` 替代） |
| `instrument` | 品种（如 XAUUSD / 600519.SH） | 是 |
| `direction` | BUY / SELL | 是 |
| `entry_time` | 开仓时间（ISO8601 UTC，A 股用本地时区但需一致） | 是 |
| `entry_price` | 开仓价 | 是 |
| `exit_time` | 平仓时间 | 是 |
| `exit_price` | 平仓价 | 是 |
| `volume` | 手数 / 股数（用作 contract_multiplier 的一部分） | 是 |
| `pnl` | 该笔盈亏（账户币种） | 是 |
| `sl_trigger_price` | 止损触发价（若有） | 否（空=无 SL） |
| `exit_reason` | manual / sl / tp | 是 |

### 3.2 `price_bars`（M5 OHLC，覆盖 entry 前 W+K 根 ~ entry 后全程 + 余量）

- 至少含 entry 之前 `W+K+margin` 根（供 CP-D 在 entry 前已收盘 bar 上找 swing）与 entry→exit 全程 + `IAE_WIN` 余量。
- 列：`time, open, high, low, close`（与 eq1m `load_m5` 完全一致）。
- A 股：适配器从 `C:\new_tdx64\vipdoc` 按 `instrument` 自动切片；MT5：用户导出同名 CSV。

### 3.3 `contract_multiplier`（每品种外部化，不再硬编码 100）

| 品种类 | multiplier 语义 | 例 |
| --- | --- | --- |
| XAUUSD 标准手 | 100 oz × volume(手) | volume=0.1 → mult=10 |
| A 股 | 股数（= volume，因 1 手=100 股，volume 直接填股数或手数×100 需约定） | 买 1000 股 → mult=1000 |
| 期货 | 合约乘数 × volume | 按合约 |

- **字段命名**：引擎沿用 `*_usd` 后缀，但 B.2 中其语义 = "账户币种金额"（A 股为 CNY）。百分位/DNA 对单位无感，仅描述分布位置。文档明确标注此约定，避免误读为美元。

---

## 4. 测量契约（Frozen Reuse，不可重推导）

B.2 的适配器**不写新的测量逻辑**。它把 `entry_quality_eq1m.py` 中已验证的 `compute_trade` 及其依赖（`find_cp` / `favorable_usd` / `adverse_usd` / `parse_dt` / 冻结常量 `K=2, W=48, IAE_WIN=10`）**逐字提取**到 `backend/os_layers/trade_measurement.py`，仅做一处外部化：

```python
# trade_measurement.py（从 entry_quality_eq1m.compute_trade 逐字提取，仅 mult 外部化）
def compute_trade(t, bars, times, contract_multiplier):
    """与 eq1m.compute_trade 字节一致；contract_multiplier 取代原 CONTRACT_MULT*vol。
    返回 per_trade 记录（schema 与 eq1m_observation 完全相同），无 CP 则返回 None。"""
    ...
    mult = contract_multiplier          # 原：CONTRACT_MULT * vol
    ...
```

**不可变性护栏**：
- `trade_measurement.py` 头部注明"逐字提取自 EQ-1M v0.1，冻结常量与数学与原文件一致；任何改动须同步改 EQ-1M 预登记文档并重走 Gate 0"。
- **`entry_quality_eq1m.py` 本身不修改**（保留其冻结 provenance 与 Gate 0）。
- B.2 **不调用** EQ-1M 的 `mediation_decomp` / `bootstrap` / `permutation`（那是 Research 层统计，本层禁止）。

### 4.1 Round-trip Oracle = B.2 的 Hard Gate（逐字段比较全部 measurement primitives）

- 用 `trade_measurement.compute_trade`（contract_mult=100）重跑历史 `trade_path.json` + `XAUUSD_M5.csv`，产出 210 笔。
- 与 `eq1m_observation_v0_1.json::per_trade` **逐字段、逐笔**比较（不只比最终统计量）：
  - 比较字段（覆盖用户清单 trade_id / CP(→etd) / ETD / IAE / MFE / MAE / Giveback / P&L / direction / exit info）：
    `trade_id, direction, etd_bars, etd_minutes, IAE_usd, Giveback_usd, Giveback_late_usd, MFE_usd, MAE_usd, PnL_usd, initial_risk_usd, mfe_peak_idx, duration_bars, overlap, exit_reason, sl_present`（共 16 个测量 primitive）。
- **任何一个冻结字段变化 → STOP**（sys.exit(2)）。回 Mapping / B.1 修订并独立记录，不静默修适配器。
- 此测试证明：**B.2 是把 B.1 的测量系统工程化，不是借「接入实时数据」重新发明一套算法**。
- **保真要求**：`trade_measurement.compute_trade` 必须**逐字复制** `eq1m.compute_trade`（含其读取 `t.get("ticket") or t.get("id")` 的写法 —— 历史源 key 为 `trade_id`，故测量输出 `trade_id` 恒为 null，与冻结 observation 一致）。**不得**为"修正"历史 id 丢失而改读 `trade_id` 键，否则会破坏 Oracle 字节一致。真实交易的去重键在摄入层从原始 blotter 单独提取（见 §9），不依赖测量输出里的 `trade_id`。
- 任何 `seed` / `ingest` 运行**前必须先过 Oracle Gate**；不过则整体 STOP，不产生任何累积输出。

---

## 5. 输出（累积存储 + 复用 B.1 引擎）

```
trade_blotter.csv + price_bars
   │  adapter → trade_measurement.compute_trade（逐笔）
   ▼
backend/output/coach_accumulated_per_trade.json   # {per_trade: [累积全部有效笔]}
   │  去重（见 §9 去重键）→ append
   ▼
coach_diagnostics.main(input=累积文件)            # B.1 引擎，代码不变
   ▼
backend/output/coach_dna_accumulated.json          # 全历史 DNA + 每笔诊断 + self_check
```

- **B.1 引擎代码零改动**：它只读 `per_trade`，不知道数据来自历史还是实时。累积文件即其输入。
- **滚动百分位**：B.2 喂入的是全历史累积集，故 `etd_percentile` / `iae_percentile` 等为**滚动累积百分位**（随 N 增长重算）；仍标注"仅描述分布、无决策含义"。
- **D4 边界继承 B.1**：`capture_efficiency` 在 `MFE<=0` 返回 null；三原始字段保留不折叠（§7）。

---

## 6. B.2 只做 6 件事

1. **读** 用户导出的 `trade_blotter.csv` + 对应 `price_bars`。
2. **逐笔测量**：调用冻结 `trade_measurement.compute_trade`（外部化 multiplier）→ 产出与 B.1 输入字节兼容的 per_trade；无 CP 笔按 EQ-1 口径排除。
3. **去重 + 累积**：以稳定键去重后 append 到 `coach_accumulated_per_trade.json`。
4. **复用 B.1 引擎**：对全累积集跑 `coach_diagnostics.main` → 每笔四维诊断 + 滚动 DNA。
5. **里程碑标记**：N 跨过 100/200/500/1000 时，在输出写一行**描述性**里程碑注记（仅 N + median/P25/P75），不做稳定/模式结论。
6. **落盘 + self_check**：输出 `coach_dna_accumulated.json`，含机器可校验护栏（§8）。

---

## 7. D4 数学边界（必锁，继承 B.1 §5，不可绕过）

```python
def capture_efficiency(mfe_usd, giveback_usd):
    if mfe_usd is None or mfe_usd <= 0:
        return None                      # 无定义：避免 0/0 与极小 MFE 极端值
    return (mfe_usd - giveback_usd) / mfe_usd
```

- 保留 `MFE_usd` / `Giveback_usd` / `capture_efficiency` 三原始字段，不折叠。
- B.2 累积集同样须通过 `n_mfe_le0 == n_capture_efficiency_null` 自检。

---

## 8. 允许的 / 禁止的（B.2 专用，含滑向 Interpretation/Rule 的红线）

| 类别 | 允许 | 禁止（B.2 高危红线） |
| --- | --- | --- |
| 摄入 | 手动 CSV；A 股价格从 vipdoc 自动切片；外部化 multiplier | 假装 live feed；自动拉 MT5（B.2.1 才谈）；任何网络自动下单 |
| 测量 | 原样复用 `compute_trade`；round-trip Oracle 测试 | 改写测量数学；新增参数；跑 pathway 统计 |
| 累积 | append + 稳定键去重；滚动 DNA 重算 | 改历史已落盘笔；删/覆盖旧笔 |
| 输出形态 | 每笔连续值、滚动百分位（标注无决策义）、`diagnostic_label=null`、DNA 描述统计、里程碑计数 | 分类标签、cutoff、分位阈值规则、**"你的最大问题是…"式定性结论** |
| 解释 | 中性事实陈述（"Giveback/MFE = 97.7%"） | "你止盈太晚""IAE 偏高说明逆势"等解释；**声称 DNA 已稳定** |
| 规则 | — | 任何信号/执行规则/仓位建议/基于 DNA 的自动动作 |
| 自动干预 | — | 向交易终端/Coach UI 推送告警/标签/建议；写 `run_daily`/`risk_guard`/`shadow` |
| 生产 | — | 接入 CIO / 生产决策链；回写研究冻结参数 |

**self_check 须显式机器校验（写进 `coach_dna_accumulated.json`）**：

```json
"self_check": {
  "n_measurement_mismatch_vs_oracle": 0,   // round-trip 测试通过
  "n_duplicate_dropped": <int>,            // 去重生效
  "n_diagnostic_label_nonnull": 0,         // 无分类
  "n_cutoff_rules": 0,                     // 无阈值
  "n_interpretation_strings": 0,           // 无解释性句子
  "n_auto_intervention_actions": 0,        // 无自动干预
  "d4_boundary_ok": true,
  "no_classification": true,
  "observation_only": true
}
```

- `n_interpretation_strings` / `n_auto_intervention_actions` 是 B.2 新增护栏，专门堵"滑动门"：任何输出字符串若含解释性动词（"应该/太晚/太早/偏高/偏低/稳定/模式"）或任何写生产/推送动作，计数 >0 → 视为防火墙破裂，STOP。

---

## 9. 跨样本 DNA 累积与里程碑（描述性，不声称稳定）

- **累积存储**：`coach_accumulated_per_trade.json` = `{per_trade: [...全部有效笔...]}`。每批新交易 append 前先去重。
- **去重键**：`(instrument, ticket)`；A 股无 ticket 时用 `journal_<日期>_<序号>` 作为稳定键。重跑同批 blotter → 同键跳过，不重复计数。
- **滚动 DNA**：每次运行对全累积集重算 median/P25/P75 + exit/direction 分布；百分位随 N 增长重算（滚动累积）。
- **里程碑**：N 跨过 100 / 200 / 500 / 1000 时，输出写里程碑注记，格式**仅**：

  ```
  "milestone": {"n": 210, "note": "DNA recomputed at N=210 (descriptive only; stability NOT claimed)"}
  ```

  明确标注 **stability NOT claimed**——210 笔（甚至 1000 笔）只能证明测量系统在跑，不能证明 Trading DNA 跨时间/跨市场稳定。稳定性结论须 Phase C/D 的重复证据。
- **诚实上限**：B.2 不产出"失败模式画像""行为结论"。这些进入 Phase C（行为反馈，用户已明确暂缓）与 Phase D（规则化，须独立样本 + Pre-registration + Out-of-sample）。

---

## 10. 与 B.1 / 防火墙的映射（可追溯）

| B.1 要素 | B.2 落实 |
| --- | --- |
| §0 单向翻译、不重算 EQ | §0/§4 适配器原样复用 `compute_trade`，禁跑 pathway 统计 |
| §2 只读测量、不回写冻结参数 | §4 `trade_measurement.py` 逐字提取，常量不变 |
| §3 只连续值 + `diagnostic_label=null` | §5/§8 累积集仍经 B.1 引擎，label 恒 null |
| §5 D4 边界 | §7 继承，累积集同过自检 |
| §6 允许/禁止表 | §8 扩展 B.2 专用红线（无 live feed / 无自动干预 / 不声称稳定） |
| Mapping 3 修正点 | 全部继承：B.2 仍不分类、D4 边界锁死、"IAE 独立诊断价值"不作为强结论 |

---

## 11. 验证计划

1. `python -m py_compile backend/os_layers/trade_measurement.py backend/os_layers/coach_b2_ingest.py` → 编译通过。
2. **Round-trip Oracle 测试**：`trade_measurement.compute_trade`（mult=100）重跑历史 → 与 `eq1m_observation_v0_1.json::per_trade` 逐字段相等；不等则 STOP。
3. **Bootstrap 种子**：首跑以历史 210 笔（真实交易）seed 累积存储（去重键 `eq1m_<index>`），验证 N=210 与 B.1 DNA 一致。
4. **去重测试**：同 blotter 跑两次 → `n_duplicate_dropped` 正确、N 不变。
5. **D4 边界**：累积集 `n_mfe_le0 == n_capture_efficiency_null`。
6. **防火墙自检**：`n_diagnostic_label_nonnull==0` / `n_cutoff_rules==0` / `n_interpretation_strings==0` / `n_auto_intervention_actions==0` / `observation_only==true`。
7. 输出落盘 `coach_accumulated_per_trade.json` + `coach_dna_accumulated.json`。

---

## 12. 决策规则（收口）

- B.2 是**测量翻译 + 累积**，不是统计声称，**不需要 Pre-Registration / Gate 0**（那些是 Research 层闭环护栏，已在 EQ-1M 收口）。
- 但须以 **OBSERVATION / DESIGN** 状态收口：实现成功后，在本文档 §14 记录"已接入真实数据流、测量态校验通过、防火墙自检全绿"，不推导任何交易结论、不产信号、不声称 DNA 稳定。
- 若运行发现 Mapping/B.1/eq1m 矛盾（字段缺失、边界歧义、测量偏差），**回对应文档修订并独立记录**，不静默改适配器逻辑。
- B.2.1（MT5 自动适配器）须单独预登记，且无论如何 Observation-only。

---

## 13. 下一步

- 本文档评审通过后 → 实现 `backend/os_layers/trade_measurement.py`（冻结提取 + round-trip 测试）与 `backend/os_layers/coach_b2_ingest.py`（CSV 摄入 + 去重 + 累积 + 调 B.1 引擎）。
- 首跑 seed 历史 210 → 产出首批累积 DNA。
- 之后：用户每平一批仓 → 导出 blotter → 运行 B.2 → DNA 滚动增长；跨过里程碑仅计数、不解释。
- **严禁**从此跨入 Interpretation / Rule。Phase C（行为反馈）与 Phase D（规则化）须独立预登记、独立样本重复验证后才可能。

## 14. Closure（2026-08-16，用户批准进入 Code）

- **状态**：APPROVED → IMPLEMENTATION。治理状态 = **Measurement Validated / Continuous Observation Enabled / Behavioral Interpretation Pending**。
- **用户冻结边界（§0.1）**：7 层边界表全部采纳；B.2 任务 = 把已验证 Measurement Engine 接入持续交易记录，而非继续研究行为机制。
- **架构锁定（§0.2）**：`trade_measurement.py` 职责极窄，只答「客观上发生了什么」，不答「好不好 / 哪里错 / 以后怎么做」（后三类属 Interpretation）。
- **Hard Gate（§4.1）**：Round-trip Oracle 升级为 B.2 准入闸，逐字段比较全部 16 个 measurement primitives；任一冻结字段变化即 STOP。
- **命名（§0.3）**：本阶段 = **B2.0 Manual Observation Pipeline**；B2.1/2.2/2.3 留作独立预登记层。
- **原则（§0.4）**：系统可越来越快知道发生了什么，但进入 Interpretation 前无资格告诉你该做什么。
- **批准后的验证序列**：`trade_measurement.py` → `coach_b2_ingest.py` → `py_compile` → Oracle Test → Gate 0（Oracle PASS + self_check 绿）→ 首次历史 210 笔回放（seed 累积存储，DNA 与 B.1 一致）。**不再增加研究问题**。

## 14.1 验证结果（2026-08-16 已实现并跑通）

| 检查项 | 结果 |
| --- | --- |
| `py_compile` | OK（`trade_measurement.py` / `coach_b2_ingest.py`） |
| **Oracle Hard Gate** | **PASS** — 210 笔 × 16 primitive 逐字段一致 vs `eq1m_observation_v0_1.json` |
| seed 历史 210 回放 | measured(valid)=210（excluded no-CP=0）；首跑 new/dup/total=210/0/210；重跑幂等 0/210 |
| DNA 与 B.1 一致（程序化比对） | etd median=6/P25=3/P75=8；iae P75=11.95；mfe median=2.225/P75=16.6；giveback P75=12.455；capture P75=0.687(n=114)；exit 67-142-1；dir 148-62 —— distributions 全等 |
| D4 边界 | n_mfe_le0=96 == n_capture_eff_null=96 → d4_boundary_ok=True |
| B.2 self_check | oracle_pass=True；n_interpretation_strings=0；n_auto_intervention_actions=0；no_classification=True；**firewall_ok=True** |
| 里程碑 | [100, 200] 触发，注记 "stability NOT claimed"（描述性，不声称稳定） |
| ingest（B2.0 Manual CSV） | CSV 解析→测量值逐字段（除 trade_id）与冻结 obs 一致；累积去重幂等（3/0 后 0/3）；真实 blotter 携带真实 ticket（历史源 trade_id=null，属预期，非偏差） |

- **状态**：Measurement Validated / Continuous Observation Enabled / Behavioral Interpretation Pending。
- **结论**：B.2 已把 B.1 的测量系统**工程化**到持续交易记录上，Oracle Hard Gate 证明零重推导；防火墙（含 `n_interpretation_strings==0` / `n_auto_intervention_actions==0`）机器可校验全绿。下一步=用户每平一批仓→导出 blotter→`python coach_b2_ingest.py ingest --blotter ... --price ... --mult ...`；严禁跨入 Interpretation / Rule。

## 14.2 正式收口 + B2.0 Observation Period（2026-08-17，用户定调）

- **正式收口判断**：B.2 进入 **FORMALLY CLOSED**。治理状态钉死为 **Measurement Validated → Continuous Observation Enabled → Behavioral Interpretation Pending**。
- **架构分界（最关键）**：系统的「测量能力」已进入持续运行阶段，但「解释能力」与「干预能力」仍被**物理隔离**。这比单句 `Observation-only` 更可靠——因为已有机器级护栏：`firewall_ok` + `n_interpretation_strings==0` + `n_auto_intervention_actions==0` + `no_classification` + Oracle Hard Gate。
- **关键结果**：B.2 与 B.1 的 DNA **程序化一致** → B.2 没有偷偷创造新测量系统；只是把已验证 Measurement Engine 从「一次性历史研究」扩展为「可持续接受新交易的 Observation Infrastructure」。这是关键架构分界。
- **B2.0 Observation Period（新增治理状态，机器可读，写入 `coach_dna_accumulated.json["b2_self_check"]["observation_period"]`，每次 seed/ingest 复写）**：
  - 期间**只允许**：① 摄入真实交易 ② 自动测量 ③ 累积 ④ 更新描述性 DNA ⑤ 记录样本数量 ⑥ 记录数据质量 ⑦ 记录异常。
  - 期间**禁止**：① 根据新数据修改测量定义 ② 根据结果修改 CP/ETD/IAE 定义 ③ 根据结果增加分类 ④ 根据结果产生交易规则 ⑤ 根据结果修改仓位 ⑥ 根据结果连接 Risk Guard ⑦ 根据结果重新定义成功/失败。
  - 系统**只回答**：「最近发生了什么？」（ETD/IAE/MFE/Giveback/Exit Quality 描述性变化、Long-Short 描述性差异、新旧样本漂移）；**暂不回答**：「以后应该怎么交易。」
- **不急于 B2.1**：用户明确建议先让 B2.0 真正观察起来，避免把重心拉回工程；MT5 自动接入只有当手动 CSV 的使用摩擦确实值得自动化时才做。
- **演进路线（各独立预登记）**：B2.0 Manual CSV Continuous Observation（已完成）→ B2.0 Observation Period（先积累真实样本）→ B2.1 MT5 自动摄入 → B2.2 A 股交易数据适配 → B2.3 Unified Trading Observation。
- **Interpretation 门（铁）**：`Measurement Validated ≠ Behavioral Interpretation Validated`。未来真正进入 Interpretation 须重走 **Observation → Interpretation Specification → Pre-Registration → Code → Gate 0 → Run**；严格遵循 EQ-1 / EQ-1R 先例：先发现关系 → 再判断是否值得建立解释模型 → 最后才考虑能否形成规则。此链**不可反向**。
- **当前项目地图**：`EQ-1` → Measurement primitives validated → `EQ-1R` → Risk-normalization robustness validated → `B.1` → Diagnostic Engine validated → `B.2` → Continuous Observation Enabled → **[CURRENT: Behavioral Interpretation Pending]** → 未来独立 Interpretation Study → Interpretation Validated? → 只有此时才讨论 Rule。
- **最正确的下一步动作**：不是继续开发，而是让 B2.0 开始积累真实样本。这一步看似慢，实则在为整个 Trading Coach 建立最重要的东西：**长期、不可被结果反向塑造的行为测量基线。**
