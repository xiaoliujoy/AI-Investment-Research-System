# H2-A 结论与收口（v0.1 封存，2026-08-15）

> 配套机器可读产出：
> - 原始结果 `backend/output/research_contracts/h2a_observation_v0_1.json`
> - 预登记契约 `RC-H2A-PREREG-v0.1.json`（顶层 `h2a_result` 块 + `13_decision` 已更新为 FAIL）
> - Phase H2 契约 `RC-ENTRY-ARCHETYPE-ID-v0.1.json`（`13_decision` 已更新：H2-A FAILED → 终止 E2-conditioned Exit 路线）
>
> 本文件不修改预登记设计（`docs/H2A_PreRegistration_v0.1.md` 已封存），仅记录首跑结论与后续研究转向。

---

## 1. 用户决策（2026-08-15）

选 **(a)：接受 H2-A 的 FAIL，终止 E2-conditioned Exit 路线**。

H2-A v0.1 到此**封存：不改、不重跑、不优化、不救。**

---

## 2. H2-A 最终研究结论（严谨措辞）

> **H2-A FAIL**
>
> 在预先登记的 XAUUSD M5 数据、entry-time information set，以及固定 A/B/C Archetype 定义下，没有发现能够稳定识别 `E2_anticipatory_suffered` 的 ex-ante Archetype。
>
> A 类占 96.2%，E2 Lift 仅 1.029，未达到预设经济门槛；训练与验证方向不一致；Permutation Null empirical percentile 为 40.7%，未显示超出随机标签基线的证据。
>
> B 类 N=0，C 类 N=8，因此两者缺乏足够检验能力。
>
> 因此，**当前证据不支持建立 E2-conditioned Exit 策略。**
>
> E2 暂保留为 post-trade execution archetype，而不作为生产系统中的 ex-ante state variable。

**比"E2 是 post-trade artifact"更严谨的边界**：本结论证明的是

> 「在当前预登记、当前信息集、当前 Archetype 定义下，没有证据表明历史 E2 能被 entry_time 当时的信息稳定识别。」

**不是**证明「E2 本体一定是 artifact」。因为 B=N=0、C=N=8，我们无法声称"所有可能的 entry archetype 都无法预测 E2"——结论必须限定在**当前冻结规格**。

---

## 3. 这次结果其实非常干净（为什么支持终止）

| 证据 | 结果 | 判断 |
| --- | ---: | --- |
| A Lift | 1.029 | 几乎等于基线 |
| A 稳定性 | ❌ | train / validation 方向不一致 |
| A 经济门槛 | ❌ | < 1.25 |
| Permutation | 40.7% | 完全没有超出 null |
| B | N=0 | 无检验能力 |
| C | N=8 | 样本不足且负富集 |
| Hard Gate | 0 个通过 | FAIL |

最关键的是 **Permutation 40.7%**。如果只有 B=0、C=8，还不能用"样本没切开"搪塞——但 A 是 202 笔，Lift 只有 1.029，同时 permutation percentile 只有 40.7%。也就是说，即使把 A 当成主要研究对象，也没有看到"E2 富集"。所以这不是单纯的"Archetype 没切分样本导致实验失败"，而是**当前 ex-ante 描述体系没有发现 E2 的可识别结构**。

---

## 4. 最有价值的发现：E2 很可能不是"市场状态"

真正重要的不是 FAIL，而是它揭示的因果结构：

你原来的 E2（先苦后甜）本质上用**交易发生之后的价格路径**定义（MFE/MAE/capture 全部事后变量）。我们问的是"入场之前，市场是否已呈现可识别这种结果的结构"——没有找到。

这意味着 E2 更可能是：

```
交易者选择
    ↓
提前入场 (anticipatory)
    ↓
承担更大的短期 adverse excursion
    ↓
有些交易后来走对
    ↓
被 post-trade 分类成 E2
```

而不是：

```
市场状态
    ↓
E2 入场
    ↓
未来价格路径
```

这是完全不同的研究结论：**E2 是交易执行方式产生的结果，不是可事前识别的市场状态。**

---

## 5. 与 Trading DNA 形成闭环

这恰好和你之前已发现的交易者稳定事实闭环：

- 最强信号 = 跨股票 + MT5 同构「方向对、拿不住」(~90%)
- 主要 Alpha = 方向判断；主要损耗 = 执行 / 持有
- 核心归因 = 浮亏厌恶（正确交易短期浮亏 → 痛阈止损 → 趋势没持仓）

我们进一步问"能不能在 entry 时提前知道这笔会成为 E2"，答案：**当前证据不能**。

于是"识别 E2 → 针对 E2 用特殊 Exit"失去了最关键前提——**如果 entry 时根本不知道它是不是 E2，生产系统就无法可靠调用这个 Exit**。所以 H2-A FAIL 帮我们砍掉了一条极易越做越复杂的路线。

---

## 6. 为什么不做 v0.2（坚定）

最危险的诱惑是：

```
结果 FAIL
  ↓ 修改 Archetype
  ↓ 重新测试
  ↓ 找到一个 PASS
  ↓ 解释为发现
```

这正是一路以来花大力气建立 Pre-Registration 要堵的反向链路。所以：

- **H2-A v0.1 到此封存。不改、不重跑、不优化、不救。**
- 不把"A 太粗"当成重开实验的理由；不做 lookback 调参、突破定义调参、ATR 调参、threshold 调参。

---

## 7. 但"entry timing 研究线"不永久关闭

这是两个概念，必须拆开：

- **关闭的是**：`E2-conditioned Exit` 这条具体研究假设。
- **暂时保留的是**：`Entry Quality / Execution Quality` 这个更大的研究问题——它比 E2 更重要。

已有事实：E2 作为 post-trade archetype 可被识别，但无法用当前 ex-ante Archetype 稳定预测。

未来若继续研究 Entry，应**换问题**：

- 不再问：「如何提前预测 E2？」
- 改问：**「哪些 entry 行为本身，会导致更差的风险暴露和更低的信念兑现率？」**

它不需要预测未来属于哪个 E2，只需研究：

```
Entry decision
    ↓
initial adverse excursion
    ↓
stop distance
    ↓
MFE realization
    ↓
exit quality
    ↓
最终 P&L / 信念兑现率
```

这与 Trading DNA 的结果高度一致，是研究重心应回到的核心瓶颈。

---

## 8. 可信度与边界

- **可信度：高，约 90%。**
- 唯一需保留的边界：B=0、C=8 限制检验力，所以不能声称"所有可能的 entry archetype 均无法预测 E2"；准确结论限定在**当前冻结规格**。

## 9. 性质判定

**H2-A 不是失败的实验，而是一次成功的 falsification experiment**——它在没有让数据反向修改假设的情况下，把一个看起来很有吸引力的研究路线杀掉了。对正在构建的整套 Trading System，这比再找到一个漂亮 backtest 更有价值。
