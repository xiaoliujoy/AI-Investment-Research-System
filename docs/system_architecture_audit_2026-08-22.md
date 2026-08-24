# AI 研投系统 · 架构级体检报告

> 日期：2026-08-22
> 性质：架构体检（事实核校 + 成熟度评估），非代码变更
> 数据口径：所有数字均来自本仓已落库文件实核，未核到的标注「未核」

---

## 0. 摘要（结论先行）

系统确实已经进入「复杂度开始超过有效性」的阶段。用户框架的大方向成立，但三处事实定位需要修正：

1. **Trading OS 不是从零开始。** 已有 `trading_discipline_engine.py`（Plan/Trade/Review + 信念兑现率）、`trade_measurement.py`（MFE/MAE 冻结测量）、`mt5_mfe_mae.py`、`exit_attribution_v0_1.py`、`trader_os_v0.1_architecture_freeze.md`。真实缺口是**手数自动计算 + Risk Gate 硬拦截 + MT5 实盘接口 + 实时 MFE/MAE 追踪**这一截，不是整层缺失。

2. **「执行=2/10、归因=1/10」偏低。** 实测：Execution 现状约 4/10，Attribution 约 3/10（测量骨架在，实时回填与自动化缺口在）。

3. **黄金自动化不是新项目，是 ATS 契约 v1.0 的落地过程。** `docs/ATS_Strategy_Contract_v1.0.md` 已存在（DRAFT，明确初始目标 XAUUSD/MT5）。黄金引擎 = 把契约里 OPEN 字段填满 + 走 Release Gate，不需要另起炉灶。

**真正瓶颈收敛为三点（与用户一致）：**
- ① 研究证据能否形成稳定可验证策略（H1 尚未完成）
- ② 策略信号能否无损传递到执行层（Delivery Gap，Phase 1E 已识别）
- ③ 人是否仍是系统最易错环节（MT5 数据已证实：方向对、拿不住、报复交易）

---

## 1. 四平面抽象（采纳用户框架，补充实核定位）

| 平面 | 用户定义 | 实核现状 | 成熟度（修正后） |
|---|---|---|---|
| Research OS | 市场发生了什么/为什么 | 51表、A股成熟链、商品/全球宏观、Regime/Decision Tree/IC/CIO/Narrative/Momentum/OMI/Red Team/H1/EQ/H2-A | 8/10 |
| Decision OS | 如何理解市场 | CIO + Asset Intelligence + Decision Memo + Risk Layer + Catalyst + Cross Asset | 7/10（Alpha 未证） |
| Trading OS | 如何变成合格交易 | Plan/Trade/Review 骨架 + MFE/MAE 测量 + exit attribution + **缺实时执行接口** | 4/10（原估3） |
| Governance OS | 系统是否偷偷改变自己 | Phase 1E FROZEN + Provenance + Release Gate + 14任务 Canonical Registry + ATS 契约 | 9/10 |

**关键判断：** 架构完成度明显高于投资收益能力。两者必须分开计量，不能因为"模块多"就推断"系统有效"。

---

## 2. 重大审计结论一：Research OS 明显领先 Trading OS（成立，补充证据）

实核事实：
- 数据库 **51 张表**（已计数确认）。
- MT5 黄金 210 笔（全样本 223 笔）已有完整分析链：`b2_analysis.json` 含 expectancy / tail dependency / holding profile / frequency impact / streak / entry quality 六维。
- 但 Trading OS 后半段（Execution 自动化、实时 Attribution、Strategy Allocation、Robustness、Failure Engine）确实未完成。

**边际收益判断：** 继续增加研究引擎的边际收益已开始下降。证据：CIO 有 30+ `_build_*` 模块，但 IC 自身 Alpha 在 Phase 1E 已被定性为「未证」（YES/NO 5D 无差、regime 污染）。模块数量 ≠ 决策质量改善。

---

## 3. 重大审计结论二：执行瓶颈已有数据证据（成立，数字精确化）

用户给的数字 vs 实核：

| 用户表述 | 实核结果 | 结论 |
|---|---|---|
| MFE>0 比例 90%+ | `diag_20260805_two_trades.md`：「亏损单 90.4% 曾有浮盈」；208笔 capture 中位 −0.69、POL 中位 1.70 | **成立，措辞精确为「亏损单 90.4% 曾给浮盈」** |
| 5分钟5连亏 | 体感；实测更严重：XAUUSD 最大连亏 **21 笔**（随机期望 12.7，p=0.029 显著） | **成立且低估** |
| 16分钟6连亏 | 体感；`C_报复交易` 标签在 b2 曲线中明确存在 | **成立** |
| IAE 与 Giveback ρ≈0.53 | 来自 EQ-1 观察，Phase 1E 已定性为「观察性证据，禁因果升级」 | **成立，保持观察级** |

**最致命的分布（实测）：** 持仓 <5 分钟那组 144 笔，胜率 21.5%、PF 0.25、expectancy −8.9（bootstrap 显著为负）。持仓 >4h 那组 8 笔，胜率 75%、PF 44、expectancy +181。损耗高度集中在「拿不住 + 高频反复」。

**归因结构（与用户框架一致）：**
```
方向判断 → 正确（MFE 多为正）
   ↓
出现浮盈
   ↓
未有效兑现（capture 缺口 / 被噪音止损 / 报复交易）
   ↓
收益消失
```
这不是预测问题，是执行/持有问题。作为系统设计依据足够强（可信度：高）。

---

## 4. 重大审计结论三：自动化任务缺「资金权限」维度（成立，需立即补）

现有 14 个活跃任务分层为 Production / Evidence / Publication / Governance。**没有「是否碰真实资金」维度。** 黄金 Execution Engine 一旦上线，会成为系统里第一个有资格触碰真实资金的执行类组件，必须单独标记。

补丁方案见 `docs/automation_registry_fund_permission_patch_2026-08-22.md`。

---

## 5. 系统复杂度风险（采纳用户第十条）

CIO 30+ 模块每块增加：依赖、数据源、failure mode、解释路径、调度复杂度、provenance 复杂度、维护成本。建议成熟度指标从「模块有没有」改为「模块是否真正改变决策质量」。否则进入 Feature Accumulation。

**Phase 1E 冻结期内已禁止的（不是暂停，是永久冻结项）：** 改 65/80、改 Composite 权重、改 veto、改 scoring、加特例、接 M4/M5 生产。黄金引擎**不得触碰以上任何一项**。

---

## 6. 修正后的系统成熟度评分

| 系统 | 用户评分 | 实核修正 | 判断 |
|---|---|---|---|
| 数据底座 | 8 | 8 | 强 |
| A股研究 | 8 | 8 | 生产成熟 |
| AI 决策 | 7 | 7 | 完整但 Alpha 未证 |
| Governance | 9 | 9 | 最强部分 |
| 自动化调度 | 8 | 8 | 已形成体系 |
| Quant Research | 6 | 6 | 方法学强，策略未形成 |
| Strategy Validation | 4 | 4 | H1 未完成 |
| Trading OS | 3 | **4** | 骨架在，缺实时执行 |
| Execution | 2 | **4** | 测量/纪律在，缺 MT5 接口+Risk Gate |
| Attribution | 1 | **3** | exit_attribution + trade_measurement 在，缺实时回填 |

整体可信度：高。

---

## 7. 下一阶段优先级（采纳用户排序，补充落点）

| 优先级 | 项目 | 落点 | 是否碰资金 |
|---|---|---|---|
| P0 | 黄金 Execution Engine Pre-Reg | ATS 契约 v1.0 填空 + release_gate 批准 | **是（最高权限）** |
| P0 | H1 数据链修复 | `quant-lab/h1_universe_structure.py` 草稿待运行 | 否 |
| P1 | Attribution 自动回填 | 扩展 `trade_measurement.py` + 实时 MFE/MAE | 否（记录层） |
| P1 | Red Team 首跑 | 代码完成 → LLM 环境变量 → 首跑 → 20日观察 | 否 |
| P2 | ATS 全自动 | **继续冻结** | 待定 |
| P2 | Automation Registry 资金维度补丁 | 本文 §4 | 治理 |

**暂停清单（Phase 1E 冻结 + 本次新增）：**
- 新研究引擎 / 新因子 / 新 CIO 模块
- 调 IC 权重 / 调 veto / Learning 回写生产
- vnpy 全自动
- 全球资产大扩张
- （新增）任何 Execution 类组件绕过 release_gate 直连 MT5

---

## 8. 治理原则（强化用户第八条）

**黄金自动化不直接接入 CIO。** 结构：
```
AI Research OS → Research Signal → Strategy Contract(ATS v1.0)
   → Execution Engine → MT5
```
而非 `CIO → AI → MT5`。后者会让研究层一次变化直接变真实资金风险，破坏 Production/Observation/Control 三平面。

现有 `trader_os_v0.1_architecture_freeze.md` 已冻结「Trader OS 不接 CIO、不产买卖建议、不改 Layer1」——黄金 Execution Engine 落在 Trader OS 平面，**天然合规**，只需在 `release_gate` 表新增一条 Execution Gate 批准记录（复用 `approve_risk_guard_takeover.py` 审计机制）。

---

## 9. 角色演进（采纳用户第十七条）

人从「判断→下单→管理→复盘」变为「判断/确认→系统算风险→系统执行→系统记录→系统复盘」。核心价值收敛到**判断 + 决策 + 例外处理**。

---

## 10. 待用户拍板的关键问题

1. **Risk Budget 默认单笔/日最大风险**：b2 数据显示单笔最大亏损曾达 −73.9，日最大回撤曾 −128。需要你给定风险预算绝对值（美元）还是账户权益百分比？
2. **MT5 实盘接口方式**：本沙箱无 MT5 连接器。G0 阶段需要确认是用 `MetaTrader5` Python 包直连本地终端，还是通过文件/API 桥接？这决定 G0 验收标准。
3. **黄金引擎是否先以「模拟/小资金」跑 G2**：建议首阶段用极小仓位（如 0.01 手）验证执行链路，再谈 G3。

---

## 11. 语言纪律（全系统统一，来自用户校准）

**Frozen（冻结）** vs **Deferred / Pending（暂缓/待定）** 必须严格区分：

- **Frozen**：除非通过正式变更流程（Erratum + Release Gate APPROVED），否则永远不能做。包括 Phase 1E 禁止项（改65/80、改Composite权重、改veto、接M4/M5生产等）与本契约 Hard Prohibitions。
- **Deferred / Pending**：以后可能继续，但当前未激活。包括 G3/G4、vnpy 全自动。

任何文档提及「暂停」须显式标注为 Frozen 还是 Deferred。混用会模糊治理边界——这正是本系统最需要防范的。

---

_本体检报告只描述事实与定位，不修改任何生产代码、不触碰 Phase 1E 冻结项。下一步进入 XAUUSD Execution Engine v0.1.1 Pre-Registration（FINAL FREEZE）契约。_
