# Trading OS 3.0 Architecture / 多资产研究操作系统架构

> **Version:** 3.0-alpha (frozen 2026-07-29)
> **Status:** Architecture freeze baseline — Phase 0~1.5 committed
> **Purpose:** 防止架构漂移。所有新功能（ETF/债券/美元/BTC/房地产）必须归入本框架。

---

## 核心变化：从 A股系统 → 多资产操作系统

```
v2.0 (2026-07 前)                    v3.0 (2026-07-29 起)

A股数据                                全球资产数据
  ↓                                      ↓
A股分析（八层树）                         跨资产观察层
  ↓                                      ↓
IC 决策                                 Asset Signal（统一协议）
  ↓                                      ↓
CIO 输出                                IC 决策
  ↓                                      ↓
交易建议                                 CIO 输出
                                         ↓
                                       Portfolio（未来）
```

**本质区别：** v2.0 是「一个会分析股票的 AI」；v3.0 是「一个观察全球资产环境的投资研究系统」。

---

## v3.0-alpha 版本定义（架构冻结节点）

> 本定义于 2026-07-30 由用户正式确认，作为 GitHub 项目第一阶段展示版本、后续研究体系基础。

```
v3.0-alpha
│
├── Equity OS（股票操作系统）
│   ├── A股行情（stock_daily）
│   ├── 资金（capital_flow / stock_flow_daily）
│   ├── 情绪（market_daily / limit_up_daily）
│   ├── 行业（sector_daily / industry_map）
│   └── 龙头（leader selection · 八层树 L5）
│
├── Commodity OS（商品操作系统）
│   ├── 商品数据（commodity_daily · 内盘8+外盘3）
│   ├── 黄金引擎（gold_engine · 贵金属子引擎）
│   ├── 商品评分（commodity_engine/scoring · v1）
│   └── 商品观察（commodity_engine/adapter · AssetSignal）
│
├── Global Asset Layer（全球资产层）
│   ├── Global Snapshot（commodity_engine/snapshot · Phase 1.6）
│   ├── Risk State（Risk On/Neutral/Risk Off 粗判）
│   └── Cross Asset Observation（cio_agent.global_asset_obs）
│
└── Decision Layer（决策层）
    ├── IC（investment_committee · 唯一裁决）
    ├── CIO（cio_agent.produce · 研究员输出）
    └── Report（os2_report · Trading OS 2.0 日报）
```

**投资思想 ↔ 系统模块映射（架构一致性）：**

| 投资思想 | 系统模块 | 状态 |
|---------|---------|------|
| 判环境 | Global Snapshot / Regime Engine（Phase 2） | ✅ Snapshot / ⏳ Regime |
| 选方向 | Sector / Commodity Ranking | ✅ 已实现 |
| 定标的 | Leader Selection（人工看图最终确认） | ✅ 人工 |

**边界纪律（用户 2026-07-30 重申）：**
- Risk State 是「市场环境温度计」，**不是买卖信号**。
- 例：`Risk Off` 系统应回答「成长股降低攻击性 / 高估值科技风险增加 / 黄金关注避险属性 / 美债等待确认 / 商品分品种判断」，**绝不输出「Risk Off = 买黄金」**。
- 任何 Regime 状态只描述「环境」，不做点位预测、不给配置比例。

---

## 三层架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 3 — Investment Decision Layer / 投资决策层            │
│                                                              │
│  Asset Regime Engine → Investment Committee → CIO → Portfolio│
│  （状态识别）          （唯一裁决）        （研究员输出）（未来）│
└──────────────────────────────┬──────────────────────────────┘
                               │ AssetSignal 协议
                               ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 2 — Asset Intelligence Layer / 资产智能层              │
│                                                              │
│  评分引擎 · 周期识别 · 状态判断 · 机会排序 · 风险识别         │
│                                                              │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐           │
│  │ A股智能  │ │ 商品智能  │ │ 债券智能  │ │ 未来...  │           │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘           │
└──────────────────────────────┬──────────────────────────────┘
                               │ 原始数据
                               ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 1 — Asset Data Layer / 资产数据层                     │
│                                                              │
│  行情 · 资金流 · 宏观因子 · 另类数据                          │
│                                                              │
│  Equity │ Commodity │ Bond │ FX │ Crypto │ Real Estate       │
└─────────────────────────────────────────────────────────────┘
```

---

## Layer 1：Asset Data Layer / 资产数据层

### 职责

采集、清洗、存储、健康检查所有资产类别的原始市场数据。**不做任何评分或判断。**

### 数据类别

| 类别 | 子类 | 当前状态 | 数据源 | 存储位置 |
|------|------|---------|--------|----------|
| **Equity（股票）** | A股行情 | ✅ 成熟 | TDX 本地 + 东财兜底 | `stock_daily` |
| | 个股资金流 | ⚠️ 部分 | push2delay（东财封禁中） | `stock_flow_daily` |
| | 板块资金/成交 | ✅ 成熟 | 同花顺 + 新浪 | `sector_flow_daily` |
| | 市值/估值 | ✅ 成熟 | datacenter-web | 运算列 |
| **Commodity（商品）** | 内盘期货 | ✅ 完成 | 新浪 `futures_zh_daily_sina` | `commodity_daily` |
| | 外盘期货 | ✅ 完成 | akshare `futures_foreign_hist` | `commodity_daily` + `global_history` |
| | 商品因子 | ✅ 完成 | 内部计算 | `commodity_factor_daily` |
| | 库存/仓单 | 🔜 Phase2 | EM 接口（待调参） | `commodity_supply_daily`（待建） |
| **Macro（宏观）** | 全球指数 | ✅ 成熟 | akshare | `global_history` / `global_market_daily` |
| | 宏观因子 | ✅ 成熟 | FRED / akshare | `global_history` (DXY/US10Y/TIPS/BTC) |
| **Bond（债券）** | 利率/信用 | ❌ 未开始 | 待定 | — |
| **FX（外汇）** | 主要货币对 | ❌ 未开始 | 待定 | — |
| **Crypto（加密）** | BTC/ETH | ⚠️ 仅DXY关联 | global_history 有 BTC | — |
| **Real Estate（地产）** | REITs/房价 | ❌ 未开始 | 待定 | — |

### 关键模块

```
backend/
├── daily_collect.py          # 主调度器（step 1~5，含 3.5 commodity）
├── data_health.py            # A股数据健康检查（5项）
├── commodity_health.py       # 商品数据健康检查（4类）
├── commodity_engine/
│   ├── collector.py          # 商品数据采集（内盘+外盘+增量自愈）
│   └── symbol_map.py         # 8品种元数据映射
├── capital_flow/             # A股资金流采集
└── fill_stock_flow.py        # 个股资金流回填
```

### 设计原则

1. **增量幂等**：重复运行不产生脏数据。
2. **源分离**：每个资产类别有独立采集链路，互不阻塞。
3. **健康门控**：`data_health.py` + `commodity_health.py` 双轨检查；health 失败 → OS2 强制 final=NO。
4. **沙箱鲁棒**：优先绕开被封接口（新浪替代东财 push2），不依赖实时行情源。

---

## Layer 2：Asset Intelligence Layer / 资产智能层

### 职责

将 Layer 1 的原始数据转化为**可比较的结构化信号**：
- 评分（score）
- 周期阶段（stage）
- 置信度（confidence）
- 驱动因素（drivers）
- 风险标签（risks）

**不做最终买卖决策。**

### 各资产智能引擎

#### A股智能引擎（成熟）

| 引擎 | 模块 | 输出 | 权重体系 |
|------|------|------|----------|
| 资金共识 | `capital_flow/` | 板块资金净流入 + 成交额排名 | 板块评分=资金+成交两维并重 |
| 黄金研究 | `gold_engine/` | 8维评分（全球环境/流动性/避险/情绪等） | 独立权重体系 |
| 资金迁移 | `capital_migration.py` | sector_flow_history.json | 迁移叙事 |
| 因果推理 | `causal_reasoning.py` | 因果链 JSON | — |
| 情景推演 | `scenario_engine.py` | 多情景评估 | — |
| 八层分析树 | `decision_tree.py` | L0~L8 全层证据 | — |

**IC 投票权重（A股）：**
```
资金(Capital)    40
产业(Industry)   25
宏观(Macro)      15
技术(Technique)  10
风险(Risk)       10
```

#### 商品智能引擎（v1，Phase 1 完成）

| 引擎 | 模块 | 输出 | 权重体系 |
|------|------|------|----------|
| 商品评分 | `commodity_engine/scoring.py` | commodity_factor_daily | **宏观40/资金25/技术25/风险10** |
| 商品适配器 | `commodity_engine/adapter.py` | AssetSignal 统一结构 | — |
| 商品健康 | `commodity_health.py` | commodity_health.json | — |

**商品评分权重（v1，与 A股不同）：**
```
宏观(Macro)      40    ← 复用 Gold Engine _score_* 逻辑，从 DB 喂入
资金(Fund Flow)  25    ← OI趋势 + 量比
技术(Technical)  25    ← MA20/MA60 + 动量 + RSI14
风险(Risk)       10    ← 年化波动罚分 + DXY跳变罚分
周期(Cycle)      —     ← Phase2 有库存后启用
供给(Supply)     —     ← Phase2 有库存后启用
```

**v2 目标权重（Phase2+）：**
```
宏观30 / 供需25 / 资金20 / 技术15 / 风险10
```

#### 未来资产引擎（规划）

| 资产 | 计划阶段 | 预计权重特征 | 备注 |
|------|---------|-------------|------|
| 债券 | Phase 2.x | 利率敏感度 + 信用利差 + 久期 | 国债收益率曲线为核心输入 |
| FX（美元） | Phase 2.x | DXY趋势 + 利差 + 避险情绪 | 已有 DXY 数据在 global_history |
| ETF | Phase 1.8 | 底层资产评分聚合 | Asset Intelligence Protocol 覆盖 |
| BTC | Phase 3.x | 风险偏好代理 + 与传统资产相关性 | 已有 BTC 价格数据 |

### Asset Intelligence Protocol（AIP，Phase 1.8 契约 · 升级自统一 AssetSignal）

> 完整契约（字段规范 / 各资产 adapter 映射 / 校验规则 / 消费方约定）见独立文档：
> **[`docs/asset-intelligence-protocol.md`](./asset-intelligence-protocol.md)**

Phase 1.8 的核心不是「接口统一」，而是让**所有资产进入同一套投资语言**——每个资产都回答六个同样的问题：状态 / 强弱 / 趋势 / 为什么 / 什么会错 / 可信度。

```python
@dataclass
class AssetIntelligence:           # 旧 AssetSignal 的升级版
    asset_class: str     # equity | commodity | bond | etf | cash | crypto | fx
    symbol: str          # "AU0" | "CU0" | "SC0" | "A_SHARE" | "US10Y" | ...
    name: str            # "沪铜" | "A股" | "美债10Y" | ...
    state: str           # 资产自身状态（六状态语义化，见契约文档）
                         #   equity/etf: 上行/震荡/下行
                         #   commodity:  上行/震荡/下行(+避险/周期/供给修饰)
                         #   bond:       牛/震荡/熊(收益率下行=牛)
                         #   fx:         美元强/中性/美元弱
    score: float         # 0-100 强弱（越高越 favorable）
    trend: str           # up | down | sideways  （价格/评分动量派生）
    drivers: list[str]   # ["宏观: DXY走弱支撑", "资金: OI增仓"]  ≥1
    risks: list[str]     # ["波动率偏高", "换月风险"]            ≥1
    confidence: float    # 0-1 浮点 + 标签（≥0.7 高 / 0.4-0.7 中 / <0.4 低）
    detail: dict = {}    # 引擎特定扩展字段（可选）
```

**关键设计决策（与旧 AssetSignal 的差异）：**
- 新增 `trend`（动量方向）、`state` 语义化（旧 `stage` 仅商品用语）、`confidence` 升级为 0-1 浮点。
- 所有资产引擎输出同一结构，CIO / Regime Engine 只消费标准化结果。
- A股 adapter 在 Phase 1.8 从 `cio_agent._derive_a_share_env` 内联派生**抽出独立化**（`a_share_adapter.py`），进入同一套语言。
- **不含配置比例**——配置模型留 Phase 3，需回测/回撤/相关性验证。

---

## Layer 3：Investment Decision Layer / 投资决策层

### 职责

消费 Layer 2 的 AssetSignal，产出**可执行的决策备忘录**和**行动建议**。

### 当前模块

```
backend/
├── brain/
│   ├── decision_tree.py        # 八层分析树（L0~L8）
│   ├── cio_agent.py            # CIO produce() → InvestmentDecisionMemo
│   └── committee/
│       └── investment_committee.py  # IC decide() — 唯一裁决源
├── notify/
│   └── os2_report.py           # Trading OS 2.0 日报渲染（9区块含 GA）
└── learning_center.py          # 学习回放 → 权重校准
```

### CIO 输出结构（InvestmentDecisionMemo）

| 字段段 | 内容 | 来源 |
|--------|------|------|
| thesis | 核心观点 + 全球关联 | L1~L3 综合 |
| evidence | 证据链（主张+证据+不确定性） | L4~L5 |
| money_map | 资金地图 + 迁移叙事 | capital_flow + migration |
| main_lines | 投资主线（星级+阶段+持续性） | L4~L5 筛选 |
| trading_plan | 交易计划（机会/条件/放弃） | L6 |
| risk | 最大风险 + 证伪场景 | L7 |
| historical | 历史经验结论 | L8 |
| learning | 学习块（命中率/校准建议） | learning_center |
| **global_asset_obs** | **全球资产观察（Phase 1.5 新增）** | **adapter + A股环境派生** |
| position_layer | 仓位层建议 | IC + risk_budget |

### 未来扩展：Asset Regime Engine（Phase 2）

```
Layer 3 未来形态：

  Asset Regime Engine          ← 新增中间层
    │  判读全局状态：
    │  Risk On / Risk Off /
    │  Inflation Shock /
    │  Growth Recovery /
    │  Liquidity Expansion/Tightening
    ▼
  Investment Committee         ← 已有，消费 Regime 状态调整权重
    │  加权投票（可随 Regime 动态调整）
    ▼
  CIO Agent                   ← 已有，合成 memo
    │  含跨资产机会排序
    ▼
  Portfolio Allocation         ← Phase 3，输出配置比例
    │  股 / 商 / 现 % （需回测验证）
    ▼
  Execution                   ← 人工看图下单（不变）
```

**Regime 状态定义（Phase 2 目标 — 六状态模型）：**

> 注意区分：Phase 1.6 的 `Risk On / Neutral / Risk Off` 是**粗判温度计**（基于 DXY/US10Y/BTC 三因子的启发式阈值），仅用于日报观察。Phase 2 的 Asset Regime Engine 将升级为以下**六状态模型**——两状态（Risk On/Off）太粗，无法刻画 2020 流动性扩张 / 2022 通胀冲击 / 2023 AI成长 / 2025 政策驱动 的本质差异。

| # | Regime | 定义 | 典型宏观特征 | 受益资产 | 受损资产 |
|---|--------|------|------------|---------|---------|
| 1 | Liquidity Expansion | 流动性扩张 | 央行放水 / 降息 / 扩表 | 所有风险资产 / 成长股 / 商品 | 现金 / 美元 |
| 2 | Growth Recovery | 增长恢复 | 增长确认 + 通胀回落 | 周期股 / 工业商品 / 新兴 | 防御股 / 黄金 |
| 3 | Inflation Shock | 通胀冲击 | 通胀超预期 + 供给冲击 | 商品 / 价值股 / TIPS | 成长债 / 高估值科技 |
| 4 | Liquidity Tightening | 流动性收紧 | 加息 / 缩表 / 信用收缩 | 现金 / 短债 | 所有风险资产 / 长债 |
| 5 | Risk Aversion | 风险规避 | 避险情绪 + 不确定性上升 | 美元 / 国债 / 黄金 | 成长股 / 新兴市场 / 高贝塔 |
| 6 | Transition | 环境切换 | 状态边界模糊 / 因子矛盾 | 降低攻击性 / 观望 | 追涨杀跌 |

**状态识别输入（Phase 2 设计）：** DXY 趋势 + 美债曲线(2s10s) + 实际利率(TIPS) + 通胀预期(BEI) + 信用利差 + BTC 风险偏好 + VIX 类波动率 + 商品内部分化。多因子状态机，非单因子阈值。

**训练基础：** Phase 1.7 `regime_history` 历史验证层提供的「每日 Regime 状态 + 未来收益分布」是六状态模型校准与回测的依据。

---

## 数据流全景

```
每日自动触发 run_daily.py
        │
        ▼
┌─ daily_collect.py ─────────────────────────────┐
│ step 1: A股行情 (quotes)                        │
│ step 2: A股板块 (sector)                        │
│ step 3: A股资金/市值 (cap)                      │
│ step 3.5: 商品数据 (commodity) ← Phase 0 新增   │
│   ├ 3.5a: ensure_commodity_daily()              │
│   ├ 3.5b: ensure_commodity_health()             │
│   └ 3.5c: ensure_commodity_factor()             │
│ step 4: 对齐 (align)                            │
│ step 5: 数据健康 (health)                       │
└────────────┬───────────────────────────────────┘
             │
             ▼
┌─ brain/cio_agent.py :: produce() ─────────────┐
│ 1. build_brain()  → 八层数据读取               │
│ 2. build_tree()   → 分析树推理                  │
│ 3. committee.decide() → IC 加权投票             │
│ 4. _build_* blocks → 各段构建                   │
│    ├ ... (thesis/evidence/money_map/...)        │
│    ├ _build_global_asset_obs()  ← Phase 1.5    │
│    │   ├ adapter.build_commodity_signals()      │
│    │   ├ _derive_a_share_env()                 │
│    │   └ _merge_opportunity_ranking()          │
│    └ learning / position_layer                 │
└────────────┬───────────────────────────────────┘
             │ InvestmentDecisionMemo
             ▼
┌─ notify/os2_report.py ────────────────────────┐
│ render_html()        → 本地日报 HTML           │
│ render_wechat_html() → 公众号内联版             │
│   含 9 区块（Phase 1.5 后）：                   │
│   ①核心观点 ②证据链 ③资金地图 ④主线           │
│   ⑤交易计划 ⑥风险 ⑧学习 ⑨应用                │
│   ★全球资产观察★（介于③与⑥之间）               │
└────────────────────────────────────────────────┘
```

---

## 版本节点与路线图

### 已完成版本节点

| 版本 | 日期 | 内容 | Commit |
|------|------|------|--------|
| v2.0 | 2026-07-10 | A股 Trading OS 2.0（五中心八层） | 早期 commits |
| v3.0-alpha | 2026-07-29 | Commodity OS Phase 0~1.5（跨资产观察层） | `c4e945d` |
| v3.0-alpha+ | 2026-07-30 | Phase 1.6 Global Asset Snapshot（风险状态 + 宏观快照） | `57e78e5` |
| v3.0-alpha++ | 2026-07-30 | v3.0-alpha 正式版本定义 + 六状态 Regime 设计 + 路线图调整 + Phase 1.7 Regime 历史验证层 | (本回合) |

### v3.0 路线图（调整后）

```
v3.0-alpha (当前 ✓ 架构冻结节点)
  │  Phase 0   商品数据链路 + 历史回填
  │  Phase 0.5 商品健康层
  │  Phase 1   商品评分引擎 v1
  │  Phase 1.5 CIO 全球资产观察接入
  │  Phase 1.6 Global Asset Snapshot（风险温度计）
  │  Phase 1.7 Regime 历史验证层（regime_history + 回溯 + 收益分布）✅ 已完成
  │
  ▼
v3.0-beta (下一站，2026-07-30 用户调整顺序)
  │  Phase 1.8 Asset Intelligence Protocol（AIP，六元组统一投资语言）
  │             ├─ 契约文档 docs/asset-intelligence-protocol.md
  │             ├─ 商品 adapter 重构到 AIP（state/trend/confidence浮点）
  │             ├─ A股 adapter 从 cio_agent 抽出独立化（a_share_adapter.py）
  │             └─ 债券/ETF/现金/BTC/FX 留骨架（不编造评分）
  │  Phase 1.9 Regime Backtest Dashboard（Phase1.7 验证数据可视化，YouTube/GitHub 素材）
  │
  ▼
v3.0-stable
  │  Phase 2   Asset Regime Engine（六状态模型，非两状态，吃 AIP.state + snapshot.risk_state）
  │  Phase 2.5 Portfolio Allocation（需回测验证后再开放比例）
  │
  ▼
v3.1 (远期)
  │  Phase 3   自动化资产配置
  │  更多资产：债券/FX/BTC/REITs
  │
  ▼
v4.0 (愿景)
     Xiao Liu Investment Intelligence Platform
```

### 关键原则

1. **不预测，只观察**：Phase 1.5/1.6 只做「看见+排序」，不给配置比例。
2. **先状态识别，再配置**：Regime Engine（判环境）必须在 Allocation（给比例）之前。
3. **每步可独立交付**：每个 Phase 都是一个可用版本，不是半成品。
4. **伪精确是大敌**：没有 5 年以上数据 + 多周期回测 + 最大回撤验证，不出配置比例。

---

## 与旧文档的关系

| 文档 | 定位 | 范围 |
|------|------|------|
| `docs/architecture.md` | v2.0 A股五中心八层实现映射 | A股 only |
| `docs/architecture/system-overview.md` | v2.0 演进蓝图 | A股 only |
| **`docs/trading-os-architecture.md`（本文档）** | **v3.0 跨资产三层架构冻结基线** | **全资产** |
| `strategy/commodity-os-design.md` | Commodity OS 详细设计 + DDL + 实现记录 | 商品子系统 |

---

*Frozen as baseline on 2026-07-29. All future development must conform to this three-layer structure.*
