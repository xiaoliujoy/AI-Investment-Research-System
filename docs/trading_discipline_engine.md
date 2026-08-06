# Trading Discipline Engine —— 决策执行层（Decision Execution Layer）

- 版本：v0.1
- 日期：2026-08-05
- 模块落位：`backend/os_layers/trading_discipline_engine.py`
- 可读镜像：`docs/trading_coach/reflections.md`
- 上游冻结文档：`docs/trader_os_v0.1_architecture_freeze.md`
- 性质：实现层（Coach Agent 具体化），与 PRD 同源，不得违反架构冻结永久/强冻结项。

---

## 0. 这是一层什么

用户命名：「计划交易，交易计划」/「Trading Discipline Engine」/「Decision Execution Layer（决策执行层）」。

一句话定位：

> 你的 AI 不负责告诉你买什么。你的 AI 负责监督：**你有没有成为那个你想成为的人。**

它不是预测层，不是信号层。它测的是「决策系统」与「执行系统」的一致性。

---

## 1. 三阶段闭环（用户设计，2026-08-05）

### 1.1 Plan（交易前 · 写计划）
交易前必须写，落位 `trade_execution` 的 E3 字段（此前覆盖率 0%）：

| 字段 | 用户设计 | E3 映射 |
|---|---|---|
| 市场判断（周期/方向/逻辑） | 黄金·日线·多·下降趋势线突破 | `reason` + `signal_grade` + `expected_scenario` |
| 交易假设 | 若站稳 4100 → 趋势继续 | `expected_scenario` |
| 错误条件 | 只有跌破 3990 说明判断错 | `invalid_condition` |
| 风险计划 | 最大允许亏损 X 元 | `reason`（风险段） |
| 退出计划 | 3990 止损 / 4236 目标 | `planned_exit` + `willing_hold_4h` |

### 1.2 Trade（交易中 · 只记录有没有按计划）
每天只记录「有没有按计划」，不记录「赚没赚钱」。AI 每日生成三问：

- **Q1** 当前价格变化是否破坏原始逻辑？否 → 继续。
- **Q2** 我现在想平仓，是因为：A. 逻辑改变 / B. 浮亏难受 / C. 害怕失去利润。若 B/C → 记录，不执行。
- **Q3** 我是否正在重复过去模式？（例：连续三次小止损 → 提醒自己「你可能正在用短期波动否定长期判断」）

### 1.3 Review（交易后 · 评决策质量，不评盈亏）
AI 每日复盘三问：判断正确吗？执行正确吗？心理何时产生恐惧？改进？
三星评分（自填，非 AI 评判用户）：

| 维度 | 含义 |
|---|---|
| 决策质量 ★ | 计划本身质量（含 invalid_condition 是否被触发） |
| 执行质量 ★ | 是否按计划下单与持有 |
| 情绪管理 ★ | 恐惧出现时是否仍按规则行动 |

---

## 2. 与既有 Trader OS 架构的映射（不是新东西，是已有骨架的激活）

| 用户概念 | 既有架构落位 | 说明 |
|---|---|---|
| Plan 阶段 | E3 五字段（`signal_grade/expected_scenario/invalid_condition/willing_hold_4h/planned_exit`） | 此前覆盖率 0%，本引擎是把它从 0% 推到 100% 的机制 |
| Trade 阶段「有没有按计划」 | CCR 漏斗 `Execution Fidelity` + `Holding Discipline` | 计划内且执行 → Execution Fidelity 分子；计划内未执行 → 分母 |
| Review 三星 | `trader_review` 表 | 新表，独立存储，不与成交表耦合 |
| 心理档案 | `trader_reflection`（category=psych_profile） | 用户口述、AI 记录，原样保存 |
| 每日三问 | `daily_check_prompt()` | 提示生成，AI 不评价 |

**关键洞察的工程化**：用户提出「信念兑现率」优于「胜率」——方向判断对 70 次，但持有超过趋势启动只有 20 次。这恰好对应 CCR 漏斗中 `Holding Discipline` 是最大漏损点的既有结论（C 类出场管理 88 笔主导）。本引擎把该洞察变成可计算指标（见 §4）。

---

## 3. 架构冻结合规声明

| 冻结条款 | 本引擎处置 |
|---|---|
| §1.1 不产生买卖建议 | ✅ 引擎只记录用户写的计划，从不生成标的/方向 |
| §1.1 不写 CIO / Decision OS | ✅ 仅读写私有表 `trader_reflection` / `trader_review` 与 `trade_execution`(E3)，无 CIO 接口 |
| §1.1 不做心理诊断 / 人格标签 / 自动干预 | ✅ 心理档案为「用户口述、AI 原样保存」，引擎零分析、零标签、零干预 |
| §11 Capture > Analysis ≤60s | ✅ Plan 录入口令化、无交互阻塞；先有数据再分析 |

---

## 4. 信念兑现率 Belief Fulfillment Rate（实测）

定义（基于 `mt5_raw/trade_path.csv` 逐笔 `mfe_usd` / `mfe_capture_ratio`）：

```
方向正确   = mfe_usd > 0            （市场曾在你入场方向给过有利波动，证明你没看错）
信念兑现   = 方向正确 且 mfe_capture_ratio ≥ 0.5 （你拿到了至少一半的机会）
信念兑现率 = 信念兑现 / 方向正确
```

**2026-08-05 实算（XAUUSD 210 笔，全历史手机交易 3/05~8/05）：**

| 指标 | 数值 |
|---|---|
| 总笔数 | 210 |
| 方向正确率 | 93.3%（196/210） |
| ★ 信念兑现率 | **11.7%**（23/196） |
| 方向正确但未兑现 | 173 笔 |
| └ 出场管理失当（C 类） | 88 笔 |
| └ 浮盈倒吐成亏损（POL>1） | 133 笔 |
| 方向正确交易留在桌上 | **3268 USD**（未被捕获的 MFE） |

**解读**：你的方向判断极准（93.3% 被市场证明过），但只有 11.7% 真正兑现成钱。
这用真实数据证明了你的核心判断——**瓶颈在执行/持有层，不在分析层**。
你过去 10 年以为「交易能力不够」，实测是「信念兑现能力不够」。这是好消息：执行可训练。

> 诚实标注：`mfe_usd > 0` 是宽松口径（只要出现过一跳有利波动即算方向对）。
> 但「信念兑现率 11.7%」由 capture 阈值（≥0.5）决定，不受口径宽松影响，是稳健信号。

---

## 5. 每日工作流（用户如何发计划给 AI）

**写计划（盘前，≤60 秒）**
用户把计划发给 AI，例如：
> 黄金 日线 多。逻辑：下降趋势线突破+结构改变。若站稳4100趋势继续。错：跌破3990。风险：亏X元。损3990，目标4236。

AI 调用：
```
python backend/os_layers/trading_discipline_engine.py plan \
  --market MT5 --symbol XAUUSD --direction BUY \
  --hypothesis "日线下降趋势线突破+结构改变" \
  --invalid "跌破3990 说明判断错" --risk "最大亏X元" \
  --signal A --scenario A --hold4h y --exit "3990止损/4236目标"
```

**盘中 / 收盘（Trade 阶段）**
AI 每日对该计划生成「执行三问」（`check <id>`），用户只答「有没有偏离」，不答盈亏。

**复盘（Review 阶段）**
用户自填三星 + 三问，AI 记录：
```
python backend/os_layers/trading_discipline_engine.py review <id> \
  --dq 5 --eq 3 --em 2 --judgment y --execution n \
  --fear "4050浮亏害怕提前平" --improve "浮亏达痛阈前机械按失效位持仓" --deviation execution
```

**反思 / 心理档案（随时）**
用户口述，AI 原样记录（零诊断）：
```
python backend/os_layers/trading_discipline_engine.py reflect \
  --date 2026-08-05 --category psych_profile \
  --title "比特币爆仓事件：我的错误认知来源" --body "..."
```

---

## 6. 设计上的三点提醒（作为搭档，必须说）

1. **「禁止评价盈亏」是训练规则，不是测量禁令。**
   半年内自我对话只评「有没有按系统执行」，这完全正确（避免回到恐惧）。
   但系统仍须持续追踪 PnL / capture / POL 作为**验证层**——否则无法判断「系统」本身是否赚钱。
   三星评的是「过程质量」，PnL 是「系统真伪」。两者并存，不矛盾。

2. **「完美执行一个烂计划」仍会亏。**
   复盘已分「决策质量★」与「执行质量★」，正解。重点盯 `invalid_condition` 是否被触发：
   若失效条件命中 → 计划本身错了，归决策质量，不归执行。
   若失效条件未命中却提前平 → 归执行质量。这条客观边界能让复盘不自我欺骗。

3. **信念兑现率的分母（方向正确率）口径需固定。**
   当前用 `mfe_usd>0`（宽松）。建议正式报告统一口径，并记录在 `docs/data_contract.md`，
   避免日后「方向正确率」数字漂移造成伪精确。本引擎已登记该字段待补契约。

---

## 7. 存储 schema

```sql
trader_reflection(id, rdate, title, category, body, tags, created_at)   -- 反思/心理档案，原样保存
trader_review(id, trade_id, rdate,
    decision_quality, execution_quality, emotion_management,           -- 三星 1-5
    judgment_correct, execution_correct,                                 -- 1/0
    fear_trigger, improvement, deviation_reason, created_at)             -- 复盘三问
-- Plan 阶段复用 trade_execution 的 E3 字段（exec_status='planned' 待回填）
```

新增字段已通过 `trader_log.init()` 契约登记路径，合规 `docs/data_contract.md`（E3 段已登记）。

---

## 8. 轻量入口（已交付，2026-08-06）

为把"计划交易，交易计划"做成长期能用的习惯，新增零依赖本地入口：

- `backend/os_layers/discipline_server.py` —— 仅标准库 `http.server`，无 pip 依赖。
- `backend/os_layers/discipline_ui.html` —— 单文件界面，深绿黑品牌色，移动端友好，四个页签：
  - **盘前计划 Plan**：结构化小表单（品种/周期/方向/逻辑/失效/最大亏损/退出），≤60 秒录完。
  - **盘中执行 Trade**：自动拉取今日计划，呈现用户设计的三问（Q1 逻辑是否破坏 / Q2 平仓动机 A·B·C / Q3 是否重复模式），只记录不评价。
  - **盘后复盘 Review**：三星评分（决策/执行/情绪）+ 复盘三问 + 偏差原因；下方含心理档案/反思录入（原样保存、零诊断）。
  - **我的数据**：实时信念兑现率卡片（基于 210 笔真实交易）+ 今日计划 + 最近记录。

启动（一次命令，无后台服务常驻）：
```
python backend/os_layers/discipline_server.py
# 浏览器打开 http://127.0.0.1:8777
# 停服：Ctrl+C
```
- 仅监听本机回环 `127.0.0.1`，无鉴权（个人本地工具）；如需手机访问加 `--host 0.0.0.0` 并在可信局域网运行。
- 本次联调已全链路验证（plan/today/trade/review/reflect/status 均写库正确），测试数据已清理，真实库干净。

## 9. 下一步

- [ ] 把 `信念兑现率` 正式写入 `docs/data_contract.md`（口径固定）
- [x] 盘前计划录入做成轻量入口（本地 HTML，降启动摩擦，呼应冻结 §12.3）
- [ ] 当 E3 覆盖率 >0 后，双周出「信念兑现率趋势」而非单笔点评
- [ ] 心理档案持续积累，按冻结 §5 门槛（MT5≥100 笔）前只记录不归纳
- [ ] 可选：把启动命令写进 `daily_run.bat`，开机即起；或做成微信粘贴→我（AI）代录的对话入口

---

## 10. 产品定位重排：Execution Intelligence（执行智能）为核心（2026-08-06）

用户决策：原「预测能力 70% / 执行 30%」的权重**反转**。未来一年重点 = Execution Intelligence（执行智能），不是预测。

### 10.1 三个核心指标（新增，已落 `abcd_analysis()`）

| 指标 | 定义 | 本账户实测（210 笔 XAUUSD） |
|---|---|---|
| Thesis Survival Rate 交易逻辑存活率 | 方向正确率（市场曾朝持仓方向给有利波动） | **93.3%**（196/210） |
| Profit Capture Ratio 利润捕获率 | 方向正确交易 capture 中位 = pnl / MFE | **-0.69**（典型交易结束于自身峰值下方） |
| Premature Exit Rate 提前退出率 | (C+D) / 方向正确 | **88.3%**（173/196） |

利润捕获率为负是关键信号：你不是在「没拿到利润」，而是「创造了利润又吐回去」。

### 10.2 A/B/C/D 四分类（执行智能视角，已落仪表盘）

| 类型 | 定义 | 数量 | 占比 |
|---|---|---|---|
| A 方向错·正常止损 | mfe_usd ≤ 0 | 14 | 6.7% |
| B 方向对·正常盈利 | mfe>0 且 capture ≥ 0.5 | 23 | 11.0% |
| C 方向对·提前退出 | mfe>0, capture<0.5, pnl≥0 | 40 | 19.0% |
| D 方向对·盈利后倒亏 | mfe>0, capture<0.5, pnl<0 | 133 | 63.3% |

**★ C+D 合计 = 173 笔 = 82.4% > 80%（用户假设已验证）。**
D 类浮盈蒸发 = **3660 USD**（曾创造 1492 浮盈 → 实亏 -2167）。
→ 结论：瓶颈不在预测（93.3% 正确），而在「持有/管理盈利」。与 11.7% 信念兑现率互为印证。

> 注：此四分类与早期 `path_archetype`（A入场错56/B止损紧29/C出场管理88/D拿住37）是**不同轴**的分类（后者按路径形状、前者按方向正确性×结果）。四分类是训练相关主轴，path_archetype 作为路径补充，二者并存不冲突。

### 10.3 训练方向：90 天只练「持仓」

- 入场已够用（93.3% 方向正确），**不再强化入场**。
- 规则：开仓后**禁止研究新入场机会**，只研究「我的原始判断什么时候失效」（即盯 `invalid_condition`）。
- 持仓训练目标量化：信念兑现率 **11.7% → 40%**（需 78 笔兑现）。
  - 若把 C 类 40 笔全部拉到 capture≥0.5 → 63 笔 = 32.1%。
  - 再拉 D 类中约 15 笔 → 破 40%。**只练持有即可达成，不动入场。**

### 10.4 复盘问题重构（心理升级）

| 旧问题（诱导恐惧） | 新问题（指向执行） |
|---|---|
| 为什么我亏了？ | 为什么我无法允许正确继续发生？ |

把「留在桌上的 3268 USD」当作核心镜像：你不是没有赚大钱的能力，而是在不断**创造利润、然后放弃利润**。

### 10.5 产品定位

- 原：交易分析助手 → 现：**交易执行训练系统**。
- 核心价值：缩小「认知 → 行动 → 结果」之间的鸿沟。
- 仪表盘（轻量入口「我的数据」）已常驻展示：四分类 + 三指标 + 信念兑现率。
