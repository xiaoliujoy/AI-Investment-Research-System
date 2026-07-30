# Asset Intelligence Protocol（AIP）— 统一投资语言契约

> 状态：Phase 1.8 契约 v1.0（**core 已落地** — `backend/asset_intelligence/{protocol,validator}.py` + 单元测试 17/17 通过；**商品 adapter 迁移完成**；**A股 adapter + CIO 统一消费已完成**（Phase 1.8-B：equity_engine/{analysis,adapter}.py + CIO 改为消费 List[AssetIntelligence]，单测 9/9 通过））
> 归属：Trading OS v3.0-beta 第一站
> 上游：Layer 1 Asset Data → 本契约 → Layer 3 Investment Decision（IC / CIO / Regime Engine）
> 设计哲学：系统只「观察 + 排序 + 判环境」，**不输出配置比例**（配置模型留 Phase 3，需回测/回撤/相关性验证）

---

## 0. 为什么要有这份契约

过去各资产输出结构不统一，导致系统无法跨资产比较：

| 资产 | 现状（Phase 1.7 之前） | 问题 |
|------|----------------------|------|
| 商品 | `commodity_engine/adapter.py` → `AssetSignal{score, stage, confidence(字符串), drivers, risks}` | 最接近协议，但 `stage` 仅为商品用语、`confidence` 为字符串 |
| A股 | `equity_engine/adapter.py` → `AssetIntelligence{asset_class=equity, symbol=CN_EQ_ALL, ...}`（Phase 1.8-B 抽离自旧 `_derive_a_share_env`，判断逻辑归 `analysis.py`，I/O 归 `adapter.py`） | **已纳入协议**，与商品同台排序 |
| 债券 / ETF / 现金 / BTC / FX | 无结构化输出 | 无法进入统一排序与 Regime 推导 |

AIP 让**每个资产都回答同一组六个问题**，使 IC / CIO / Regime Engine 能用同一套语义消费。

---

## 1. 六元组契约（核心）

每个资产引擎输出**一个** `AssetIntelligence` 对象：

```python
@dataclass
class AssetIntelligence:
    asset_class: str        # 资产类别枚举（见 §2）
    symbol: str             # 标的代码（"AU0" | "CU0" | "SC0" | "CN_EQ_ALL" | "US10Y" | "DXY" | ...）
                            # 注：A股用 CN_EQ_ALL（资产集合），非单只个股/单只 ETF（如 CN_EQ_TECH）
    name: str               # 人类可读名（"沪铜" | "A股" | "美债10Y" | "美元指数"）
    state: str              # 资产自身状态（语义化，见 §3）
    score: float            # 0-100 强弱（越高 = 越 favorable / 越占优）
    trend: str              # "up" | "down" | "sideways"（动量方向，见 §4）
    drivers: list[str]      # 为什么（因果驱动，≥1 条，见 §5）
    risks: list[str]        # 什么会错（失效条件，≥1 条，见 §6）
    confidence: float       # 0-1 浮点可信度（见 §7）
    detail: dict = {}       # 引擎特定扩展字段（可选，不进入跨资产比较）
```

### 字段速查

| 字段 | 类型 | 含义 | 消费方 |
|------|------|------|--------|
| `asset_class` | enum | 资产类别 | 路由 / 分组 |
| `symbol` / `name` | str | 标的身份 | 展示 |
| `state` | str | 资产自身状态（非全局 Regime） | CIO 描述 + Regime Engine 输入 |
| `score` | float 0-100 | 强弱 | 机会排序（已存在逻辑） |
| `trend` | enum | 动量方向 | CIO 描述 + 趋势确认 |
| `drivers` | list[str] | 为什么 | CIO「为什么」段 + 用户人工验证 |
| `risks` | list[str] | 什么会错 | CIO「失效条件」段 |
| `confidence` | float 0-1 | 可信度 | 排序加权 + 展示标签 |
| `detail` | dict | 引擎私有 | 不跨资产 |

---

## 2. 资产类别枚举（asset_class）

```python
ASSET_CLASSES = {
    "equity",    # 股票（含 A股、个股、指数）
    "commodity", # 商品（黄金/铜/原油/白银/螺纹…）
    "bond",      # 债券（利率债/信用债，收益率曲线为核心）
    "etf",       # 交易所基金（底层资产评分聚合）
    "cash",      # 现金 / 货币基金（持有 / 观望）
    "crypto",    # 加密货币（BTC 等，风险偏好代理）
    "fx",        # 外汇（DXY / 汇率）
}
```

---

## 3. state 语义化规范（资产自身状态，非全局 Regime）

> ⚠️ 区分：`state` = **单个资产**的本地状态；`risk_state`（Global Snapshot，Phase 1.6）= **全局**环境。
> Phase 2 Regime Engine 将消费各资产 `state` + 全局 `risk_state` 推导**六状态全局 Regime**。

各资产 `state` 取值表：

| asset_class | state 取值 | 说明 |
|-------------|-----------|------|
| equity / etf | `上行` / `震荡` / `下行` | 基于评分 + 价格结构；可加修饰（如 `上行-领涨`） |
| commodity | `上行` / `震荡` / `下行` + 修饰 | 修饰词：`避险` / `周期` / `供给`（如 `上行-周期`、`下行-避险`） |
| bond | `牛` / `震荡` / `熊` | 收益率**下行 = 牛**（价格涨），上行 = 熊 |
| cash | `持有` / `观望` | 环境变量决定，几乎恒为持有 |
| crypto | `上行` / `震荡` / `下行` | 风险偏好代理 |
| fx | `美元强` / `中性` / `美元弱` | DXY 趋势语义 |

---

## 4. trend 派生规则

`trend` 由价格 / 评分动量派生，**统一口径**，避免各 adapter 自定：

```
trend = "up"       if slope_20d >  +T1  else
        "down"     if slope_20d <  -T1  else
        "sideways"
```

- `slope_20d`：近 20 日 score 或收盘价回归斜率（归一化到日变动 %）
- `T1`：阈值，默认 **0.3%（日均变动绝对值）**，可在 adapter 内按资产微调
- 商品可用 `commodity_factor_daily.score` 的斜率；A股可用 IC 方向 + 市场宽度变化；债券用收益率斜率取反。

---

## 5. drivers 规范（为什么）

- 每条为**因果陈述**，格式 `[维度]: [具体内容]`
- 维度词表（建议）：`宏观` / `资金` / `产业` / `技术` / `情绪` / `估值` / `供需` / `政策`
- 例：
  - 商品沪铜：`["资金: OI连续增仓", "产业: 制造业PMI回升", "宏观: DXY走弱"]`
  - A股：`["资金: 北向净流入放大", "情绪: 市场宽度68%", "产业: AI硬件主线持续"]`
- **≥1 条**；为空视为校验失败（见 §8）。

---

## 6. risks 规范（什么会错 / 失效条件）

- 每条为**会使当前判断失效的条件**，格式同上维度词表
- 例：
  - 商品沪铜：`["宏观: DXY反弹至104+", "供需: 库存超预期累库", "技术: 跌破MA20"]`
  - A股：`["资金: 成交额萎缩至万亿下", "情绪: 市场宽度跌破40%", "宏观: 美债收益率破5%"]`
- **≥1 条**；为空视为校验失败。

---

## 7. confidence 规范（可信度）

```python
def confidence_label(c: float) -> str:
    if c >= 0.7:  return "高"
    if c >= 0.4:  return "中"
    return "低"
```

派生因子（adapter 自行组合，给出 0-1）：
- **数据新鲜度**：最新数据距今天数（0 天→1.0，>5 天→衰减）
- **健康度**：来自 `commodity_health.json`（商品）/ 数据体检（A股）状态映射
  - HEALTHY → 1.0 / WATCH → 0.6 / STALE → 0.3
- **信号一致性**：多子因子方向是否一致（一致→高，分裂→低）
- **样本充分性**：历史样本是否足够（如商品 ≥60 日、A股 ≥20 交易日）

> 旧 `AssetSignal.confidence` 为字符串「高/中/低」，AIP 升级为 **0-1 浮点 + 标签**，
> 既保留展示可读性，又支持排序加权与 Regime 投票。

### ⚠️ §7.5 `score` 与 `confidence` 必须语义分离（Phase 1.8-C 用户审计 #2）

两者极易被实现者「同源过强」而退化成同一个数字，必须明确区分：

| 维度 | `score` | `confidence` |
|------|---------|--------------|
| 回答的问题 | **「这个资产现在有多强 / 多 favorable？」**（方向 + 强弱） | **「我对这个判断有多确定？」**（信号质量） |
| 取值范围 | 0–100（越高越占优） | 0–1（越高越可靠） |
| 来源 | 方向类因子合成（IC 裁决 / 广度 / 主线 / 斜率） | 信号质量类因子（数据新鲜度 / 健康度 / 多子因子一致性 / 样本充分性） |
| 能否独立变化 | 能：高 score 也可低 confidence（如强方向但数据陈旧） | 能：低 score 也可高 confidence（如明确偏弱但数据极干净） |
| 跨资产消费 | 机会排序（降序比较） | 排序加权 + 展示标签 + Regime 投票权重 |

**铁律**：
- `score` 与 `confidence` **不得由同一组输入线性推导**（例：不能 `confidence = score/100`）。
- 降级占位（中性 / 缺数据）应给**低 score + 低 confidence**（如 score=22.5、confidence=0.30），
  而不是高 confidence 掩盖低确定性。
- 各 adapter 须在 `analyze_*` / `_to_signal` 内分别构造二者，并在注释中标明各自来源。

---

## 8. 校验规则（根因防御，呼应 `_DB_PATH` 可靠性教训）

每个 adapter 必须：

1. **降级不崩溃**：任何异常 → 返回 `has_data=False` 的空对象，绝不让 CIO 渲染失败。
2. **类型强约束**：
   - `confidence` ∈ [0, 1]，越界 clamp
   - `trend` ∈ {`up`, `down`, `sideways`}
   - `score` ∈ [0, 100]
3. **非空约束**：`drivers` 与 `risks` 各自 **≥1 条**，否则补默认「数据不足，信号待验证」。
4. **asset_class 白名单**：必须 ∈ §2 枚举，否则拒绝写入。
5. **DB 路径单源**：所有 adapter 经 `backend/db.py:get_conn()`，禁止各自 `__file__` 拼路径（已踩坑）。

---

## 9. 各资产 adapter 映射（Phase 1.8 实现范围）

| asset_class | Adapter 模块 | 数据源 | Phase 1.8 状态 |
|-------------|-------------|--------|---------------|
| commodity | `commodity_engine/adapter.py`（**重构**） | `commodity_factor_daily` + `commodity_health.json` | ✅ 实现（补 `trend`/`state`/`confidence` 浮点） |
| equity (A股) | `equity_engine/adapter.py`（**Phase 1.8-B 新增，从 `cio_agent._derive_a_share_env` 抽出**；判断逻辑归 `equity_engine/analysis.py`，I/O 归 `adapter.py`） | IC `can_buy` + `sentiment.breadth` + L4 `main_lines` | ✅ 实现 |
| bond | `bond_adapter.py`（骨架） | `global_history` 利率（US10Y / CN10Y）+ 收益率曲线 | 🚧 骨架，不编造评分 |
| etf | `etf_adapter.py`（骨架） | 底层资产评分聚合（待定） | 🚧 骨架 |
| cash | 常量 | — | ✅ 常量 `持有` |
| crypto (BTC) | 融入 `snapshot` macro | `global_history.BTC` | 🚧 骨架（macro 已采） |
| fx (DXY) | 融入 `snapshot` macro | `global_history.DXY` | 🚧 骨架（macro 已采） |

> **严守边界**：bond / etf / crypto / fx 在 Phase 1.8 **只建骨架、不编造评分**——
> 缺回测/相关性验证前，任何「精确」数字都是伪精确（用户原则）。

---

## 10. 消费方约定

| 消费方 | 如何消费 AIP |
|--------|-------------|
| **CIO** (`_build_global_asset_obs`) | 合并所有 adapter 输出（commodity + equity + 未来 bond/etf）→ 跨资产机会排序；并调用 `build_universe_snapshot()` 产出统一宇宙快照（Phase 1.9 Dashboard 输入）。IC 裁决层（can_buy/direction）由 CIO 从 `brain.committee` 读取，不进 AIP `detail`。 |
| **Regime Engine**（Phase 2） | 消费各资产 `state` + Global Snapshot `risk_state` → 推导**六状态全局 Regime**（Liquidity Expansion / Growth Recovery / Inflation Shock / Liquidity Tightening / Risk Aversion / Transition）。 |
| **Validation Dashboard**（Phase 1.9-B） | 消费 `regime_history` + `asset_intelligence_history` → 验证「观察体系是否具备统计意义上的决策价值」（不预测，只验证；见 §13）。 |

**禁止：**
- 任何 adapter 输出配置比例（股票 %/ 商品 %/ 现金 %）。
- 用 `score` 直接做买卖信号（score 仅用于排序与环境描述）。

---

## 11. 与旧 AssetSignal 的差异（迁移清单）

| 旧 AssetSignal | AIP | 动作 |
|---------------|-----|------|
| `asset` (str 自由) | `asset_class` (枚举) | 重命名 + 约束 |
| `category` | （移入 `detail` 或 `state` 修饰） | 降级 |
| `stage` (商品用语) | `state` (语义化，按资产类) | 升级 |
| — | `trend` | **新增** |
| `confidence` (str) | `confidence` (float 0-1) + 标签 | 升级 |
| `drivers` / `risks` | 同名 | 保留 + 非空约束 |
| `detail` | 同名 | 保留（可选） |

CIO / 渲染层读取时统一改为新字段名；旧 `AssetSignal` 类名在 Phase 1.8 重构时退役。

---

*本文档为 Phase 1.8 实现前的契约基线。代码实现须严格遵循 §1–§8 字段与校验规则，
任何偏离需回到本文档修订并重新对齐架构文档 `docs/trading-os-architecture.md`。*

---

## 12. 已知问题 / Backlog（用户审计记录）

以下为 Phase 1.8-C 评审中用户提出、并经确认「先不改代码、在协议层记录」的两条审计问题。
Phase 1.9-A 已对部分问题做工程层面的承接，标注于每条之下。

### 问题 #1：`generated_at` 使用本地时间（用户审计 #1）

- **现象**：`universe.py:build_universe_snapshot` 与 `regime_history.build_regime_history`
  的 `generated_at` 均用 `datetime.now()` / `datetime.now().strftime(...)`（本地时区）。
  对跨资产 / 跨时区资产（外盘商品、宏观）而言，本地时间会引入歧义。
- **建议**：未来统一改为 UTC——
  `datetime.datetime.now(datetime.timezone.utc).isoformat()`（或 `utcnow()`）。
- **Phase 1.9-A 处置**：**未改代码**（与用户「先不改动」一致）。
  但 `asset_intelligence_history` 落库的 canonical `date` 一律取**交易日 `trade_date`**
  （由调用方 `os2_report.write(memo, path)` 显式传入 `memo.trade_date`），而非 `generated_at`，
  因此历史层的横轴（date）与时区无关、稳定可比对；时区问题只残留在 `generated_at`
  这一审计元数据列。待 Phase 1.9-B Dashboard 上线前统一切 UTC。

### 问题 #2：`score` 缺失默认 0 会隐藏「无评分」（用户审计 #2）

- **现象**：`universe.py` 排序键 `(x.get("score") or 0)` 中，缺失 score 会回落到 0
  （最低排序），从而**把「该资产没有评分」误表达为「评分最低 / 最不 favorable」**。
- **建议**：协议层明确增加 `enabled: false` 或 `observation_status: "unavailable"`，
  使「无真实评分」与「真实低分」可区分；Dashboard 据此过滤空壳，不参与强弱排序。
- **Phase 1.9-A 处置（已落地）**：
  - `protocol.make_skeleton` 早已在 `detail` 写 `enabled: False`（空壳资产）。
  - `asset_intelligence.history._asset_enabled()` 读取该标志写入 `enabled` 列
    （真实资产默认 `enabled=1`，空壳 `=0`）。
  - `load_universe_history(only_enabled=True)` / `load_universe_panel(only_enabled=True)`
    可直接过滤空壳，Dashboard 据此把 `score=50` 的占位值排除在真实排序之外。
  - `score=None` 落库存 **NULL**（不伪造 0），进一步避免「缺失=0」语义污染。
  - 后续如需「unavailable」显式语义，可在 validator 层把 `detail.enabled=False`
    提升为顶层 `observation_status` 字段（保持向后兼容，旧 detail 仍可用）。

---

## 13. Phase 1.9-B 验证层（Investment Intelligence Validation Dashboard）

目标：把系统从「信号生成」推向「研究系统」——验证**观察到的信息是否具备统计意义上的
决策价值**，而非预测。这是 Phase 2 Regime Engine 的数据地基。

### 13.1 三条验证问题（均不预测）

1. **Regime 状态有效性**（来源 `regime_history`）：不同环境下市场后续表现如何？
   Risk Off 是否真的对应更低收益 / 更高风险？若无区分 → 状态定义需调整。
2. **Asset Intelligence 信号验证**（来源 `asset_intelligence_history`）：score 是否具备
   **横截面排序能力**？高分档未来收益/胜率是否系统性优于低分档？（不是预测，是排序验证）
3. **Confidence 校准**（来源同上）：高 confidence 是否真的更可靠？若 High≈Low →
   confidence 只是标签，需重新设计（呼应 §7.5 score≠confidence 铁律）。

### 13.2 模块结构（模块化，不进 CIO）

```
asset_intelligence/
├── history.py            (Phase 1.9-A：落库)
├── validation/           (Phase 1.9-B1：验证引擎，无 UI)
│   ├── returns.py       前向收益引擎（商品 close / A股聚合净值；A股序列按需+区间受限，避免全表扫描）
│   ├── regime_eval.py   Regime 状态有效性
│   ├── signal_eval.py   Score 分层排序能力
│   ├── confidence_eval.py Confidence 校准 + 区分度诊断
│   └── report.py        汇总 → output/dashboard/validation_report.json（v0.1）
└── dashboard/           (Phase 1.9-B2：可视化，待建)
```

### 13.3 边界与样本量警示（关键）

- **不新增复杂表**：B1 只读 `regime_history` + `asset_intelligence_history`，产出 JSON。
- **样本不足风险**：regime_history≈243 样本（三状态同质化：236 Neutral / 7 Risk On / 0 Risk Off），
  对框架验证够，对形成稳定规则不够。signal/confidence 段依赖 `asset_intelligence_history`
  累积（每日 memo 落库后才有），初期为 0 属正常。
- **结论必带可信度**：每段标注样本量与可靠性（无样本/低/中/较高）；报告 `overall_caveat`
  明示「任何结论仅用于方法验证，不构成投资规则；Phase 2 须待验证稳定后启动」。
- **A股序列性能**：`stock_daily` 约 2335 万行，`returns.load_price_series` 对 A股聚合
  **绝不**做全表 GROUP BY——仅当确有 CN_EQ_ALL 信号且给定日期区间时做区间受限查询。
