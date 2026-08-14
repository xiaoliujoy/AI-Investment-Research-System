# Strategy Research Contract v0.1

> **状态：v0.1 FROZEN（2026-08-14 用户定调冻结）。**
> 不再扩展字段、不加 UI、不加数据库、不加 AI 自动评分。v0.2 仅允许在真实实验跑出字段缺口后，从实验需求反向产生。
>
> **定位：Observation 层研究语言。** 只描述实验、不改变生产决策链（`run_daily` / `risk_guard` / `shadow`）。机器可读内核见 `backend/os_layers/research_contract.py`。
>
> **治理边界：当前 Phase 1E FROZEN / OBSERVATION MODE**，`RISK_GUARD_ENABLED` 恒=0。任何写入 Contract 的新实验，结论只能进观察层，不经人工 Release Gate + `RISK_GUARD_ENABLED=1` 不得进入生产。

---

## 1. 为什么需要它

你已有的零件（Momentum A/B、黄金 E1/E4、Trading Coach、AI CIO）各自有真实实验数据，但**缺乏统一研究语言**：今天测 Exit 用一组参数，明天测 Robustness 用另一组，后天测 Momentum 又一套——结果无法互比。Contract 把每个实验强制收口到同一 13 字段结构，让「Entry / Stop / Exit / Sizing / Testing / Robustness」能用同一种话说。

核心原则（来自你的架构修正）：

> 现在真正该建设的不是「更聪明的策略」，而是「能持续产生、验证、比较、淘汰策略的研究机器」。

---

## 2. 13 字段模板（顺序即研究流水线）

| # | 字段 | 问题 | N/A 规则 |
| - | --- | --- | --- |
| 01 | Hypothesis | 要验证的明确假设（先假设，后参数） | 必填 |
| 02 | Market/Universe | 资产/市场/样本边界，写死 | 必填 |
| 03 | Regime | 市场状态（须是事前变量） | 缺失须写理由 |
| 04 | Signal | 触发关注的信号，是否可复现 | 缺失须写理由 |
| 05 | Entry | 进入条件，是否机械可执行 | 缺失须写理由 |
| 06 | Stop | 失效条件，失效位是否写死 | 缺失须写理由 |
| 07 | Exit | 兑现条件（当前最大价值泄漏点） | 缺失须写理由 |
| 08 | Position Sizing | 风险预算 ÷ 失效位距离 | 缺失须写理由 |
| 09 | Costs/Execution | 成本与执行摩擦假设 | 缺失须写理由 |
| 10 | Testing | 回测方法，样本内/外划分 | 必填 |
| 11 | Robustness | 换参数/时间/资产/Regime 是否成立 | 缺失须写理由 |
| 12 | Attribution | 收益来自哪一层 | 缺失须写理由 |
| 13 | Decision | 采纳/否决/继续观察/进下一实验 | 必填 |

**N/A 铁律**：任何字段为 `N/A` 必须同时写 `note` 理由（如 Signal/Selection 层研究天然不含 Entry/Stop）。空 N/A 无理由 = `validate()` 报错。

---

## 3. Evidence Status：研究可信度状态机

```
CLAIM → LOCATED → REPRODUCED → VALIDATED → ROBUST → ACCEPTED → PRODUCTION
```

| 状态 | 含义 |
| --- | --- |
| CLAIM | 口头/聊天提出，无项目数据 |
| LOCATED | 在项目数据/代码找到对应事实（有路径+字段） |
| REPRODUCED | 能重跑脚本得到同一数字 |
| VALIDATED | 独立逻辑交叉验证通过 |
| ROBUST | 稳健性验证通过（参数×时间×资产×Regime） |
| ACCEPTED | 经人工 Review Gate，进入研究库 |
| PRODUCTION | 获生产资格（需 release_gate APPROVED + RISK_GUARD_ENABLED=1） |

**单向前进原则**：正常 `set()` 只允许状态升级，回退会抛错。这保证 Research Record 不被静默篡改。

### 关于「NOT LOCATED / NOT VERIFIED」

当一个数字声称存在但检索不到来源（如 `ATR×3 PF 1.52`），**状态保持 `CLAIM`**，在 `note` 写 `NOT LOCATED`，并追加一条 Erratum 事件（见 §4）。状态机不引入「已证伪」分支——因为「未找到」≠「不存在」，只能记为待定位的 CLAIM。

---

## 4. Erratum 机制（2026-08-14 增补）

**原则：Evidence Status 是当前证据状态；Erratum 是历史事件。**

状态机单向前进，但研究过程难免误标（如曾在文档里误写「已核实」）。错误处理方式：

```
ATR×3 PF 1.52
       ↓ CLAIM
       ↓ LOCATED   (误标)
       ↓ 发现来源不存在
       ↓ ERRATUM   (追加历史事件，不静默改写)
       ↓ CLAIM / NOT VERIFIED
```

- **不允许** `VALIDATED → CLAIM` 这种静默回退。任何回退必须经 `add_erratum()`，它追加一条 `ErratumEvent`（`timestamp / field / claim / finding / previous_status / restored_status / note`），可选地纠正字段状态。
- 原状态机保持单向前进：回退是「被记录的事件」，不是状态机的正常边。
- 审计性：即使字段状态被纠正，Erratum 列表永久保留，可还原「曾被认为 LOCATED」的历史。

`research_contract.py` 实现：`ErratumEvent` 数据类 + `ResearchContract.errata` 列表 + `add_erratum()`；`--check` 会打印所有 Erratum 事件。

---

## 5. 研究可信度链

任何数字进入 Research Record 前必须走完：

```
Claim → Source → Reproduce → Validate → Record
```

聊天里说的数字（如「ATR×3 PF 1.52」「Median ATR 8.49」）**不能直接进结论**，必须先定位源 artifact、能重跑、再记录。这是上一轮审计纠正两个数字偏差的制度化。

---

## 6. 三实例互证（本版交付）

| 实例 | 类型 | 当前价值 | 整体状态 |
| --- | --- | --- | --- |
| `RC-GOLD-ENTRY-E1E4` | Entry | 已有实证优势（确认入场净 +$2389.3 / n=46） | VALIDATED |
| `RC-GOLD-STOP-ATR3` | Stop | **证据链断裂案例**（基线 1.0182 可复现；1.52 找不到） | CLAIM + Erratum |
| `RC-MOMENTUM-AB` | Signal | 研究中的模型比较（drift=0 复刻通过；Incremental 未完成） | CLAIM→部分 REPRODUCED |

三个实例覆盖 Entry / Stop / Signal 三层，且一个 MT5 单笔交易、一个 Signal/Selection 非交易型，证明 **Contract 是跨实验统一语言，不是黄金实验专用模板**。

实例文件：`backend/output/research_contracts/RC-*.json`，均 `--check` 通过。

---

## 7. 下一步：Exit Engine Observation v0.1

Contract 三实例验证完成后，进入 Exit Engine，第一颗钉子是 `RC-GOLD-EXIT-TRAIL`（已随本交付创建，纯 Contract 实例，不写引擎代码）：

> **H1：在 Signal / Entry / Stop / Position / 成本 / 数据 全部固定不变的前提下，对已有正确方向的黄金交易引入适度 Trailing Exit，能否减少 Giveback 并提高 Realized P&L。**

**控制变量设计（H1 的核心）**：唯一变化项 = Exit；其余全部固定。这样若 PF/capture 改善，可干净归属到 Exit 层（正是第 12 层 Attribution 要解决的问题）。**禁止参数寻优**——先验证假设，再寻参。

---

## 8. 使用方式

```bash
# 生成空白模板
python backend/os_layers/research_contract.py --skeleton RC-ID "标题" Layer --out backend/output/research_contracts/RC-ID.json

# 校验（含 errata 输出）
python backend/os_layers/research_contract.py --check backend/output/research_contracts/RC-ID.json
```

代码约束：stdlib-only，不依赖生产模块；`validate()` 返回问题列表，`set()` 强制状态单向前进，`add_erratum()` 是唯一回退通道。
