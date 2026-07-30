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
| A股 | `equity_engine/adapter.py` → `AssetIntelligence{asset_class=equity, symbol=CN_A_SHARE, ...}`（Phase 1.8-B 抽离自旧 `_derive_a_share_env`，判断逻辑归 `analysis.py`，I/O 归 `adapter.py`） | **已纳入协议**，与商品同台排序 |
| 债券 / ETF / 现金 / BTC / FX | 无结构化输出 | 无法进入统一排序与 Regime 推导 |

AIP 让**每个资产都回答同一组六个问题**，使 IC / CIO / Regime Engine 能用同一套语义消费。

---

## 1. 六元组契约（核心）

每个资产引擎输出**一个** `AssetIntelligence` 对象：

```python
@dataclass
class AssetIntelligence:
    asset_class: str        # 资产类别枚举（见 §2）
    symbol: str             # 标的代码（"AU0" | "CU0" | "SC0" | "A_SHARE" | "US10Y" | "DXY" | ...）
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
| equity (A股) | `a_share_adapter.py`（**新增，从 `cio_agent._derive_a_share_env` 抽出**） | IC `can_buy` + `sentiment.breadth` + `market_daily` + L4 `main_lines` | ✅ 实现 |
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
| **CIO** (`_build_global_asset_obs`) | 合并所有 adapter 输出 → 跨资产机会排序（已有逻辑保留）；A股以 `state=等待确认` 占位（IC 裁决前）。 |
| **Regime Engine**（Phase 2） | 消费各资产 `state` + Global Snapshot `risk_state` → 推导**六状态全局 Regime**（Liquidity Expansion / Growth Recovery / Inflation Shock / Liquidity Tightening / Risk Aversion / Transition）。 |
| **Backtest Dashboard**（Phase 1.9） | 消费 `regime_history` + 各 `state` 历史 → 环境有效性报告。 |

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
