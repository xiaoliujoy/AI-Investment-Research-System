# Commodity OS 1.0 落地设计（v2 用户确认版）

> **v2 更新（2026-07-29）**：用户确认战略定位 + 三层表结构 + 内盘为核/外盘锚；并**实测 akshare 数据源可用**（新浪内盘含 OI/结算、外盘 hist 可回填 global_history）。
> 本文 = Phase 0 技术设计（数据源 / 表结构 / collector / 接入点）。开发根：`backend/`。

---

## 0. 战略定位（用户确认）

从「A股交易辅助系统」升级为「**多资产投资决策操作系统**」：

```
                Data OS
                   |
      ┌────────────┴────────────┐
      ↓                         ↓
  Equity Engine             Commodity Engine
      ↓                         ↓
 A股机会判断              商品周期判断
      ↓                         ↓
      └────────────┬────────────┘
                   ↓
          Portfolio Decision
                   ↓
                 CIO  →  资产配置建议（股票/商品/现金 权重）
```

未来 CIO 不是只答「今天买什么股票」，而是答「当前环境下，股票/商品/现金的资金权重如何」。

---

## 1. 现有能力盘点（真实水位 ≈ 6/10）

| 能力 | 状态 | 证据 |
|---|---|---|
| **Gold Engine（黄金引擎）** | ✅ 生产级 | `backend/gold_engine/` 8维评分，CIO 已消费（`cio_agent.py:1748`） |
| **全球宏观因子** | ✅ 齐全 | `global_history` 含 DXY/US10Y/US2Y/TIPS/BTC，历史完整（2021起） |
| **CIO 全球/宏观格** | ✅ 已有 | `os2_report.py` 含「宏观」权重 + 「全球」格 |
| **商品→A股 叙述映射** | ⚠️ 浅层 | `commodity_data.py:a_share_link` 沪金→黄金/沪铜→有色 |
| **商品采集链路** | ❌ 不存在 | `global_market/data_adapter/collector.py:collect_all()` 只采美股/亚股/宏观，**完全不含商品期货**；`save_to_database` 未写 category/region 列 |
| **global_market_daily（商品日线）** | ⚠️ 严重残缺 | 仅 2 天（07-10/07-14），volume=0、category=None |
| **global_history（商品历史）** | ❌ 缺商品 | 28927行但无 XAU/CL/HG |
| **global_score / global_rps** | ❌ 空表 | 0 行未落库 |
| **持仓量 OI / 期货资金流** | ❌ 不存在 | DB 无此字段（需 Phase 0 新建） |
| **内盘中国商品期货** | ❌ 未接入 | 现有商品数据走外盘（XAU/CL/HG），内盘 AU/AG/CU/SC 未接入 |

**一句话**：Gold Engine + 宏观因子现成；最大坑是「商品数据链路」——历史几乎为零、采集链路缺失。

---

## 2. 用户确认的三项决策

- **① Phase 0 启动**：✅ 同意。先打通数据链路，再谈评分。
- **② 内外盘选型**：**内盘为交易核心，外盘为宏观锚**。
  - 内盘（交易决策）：沪金 AU / 沪铜 CU / 原油 SC / 沪银 AG / 螺纹 RB
  - 外盘（环境判断）：XAU / CL / HG
- **③ 表设计**：采用**三层结构**（职责分离，预留 OI/换月/基差/库存返工空间）：
  - `global_market_daily`（全球资产价格层，保留）
  - `commodity_daily`（商品交易层，新建）
  - `commodity_factor_daily`（商品评分层，新建）

---

## 3. 数据源验证结论（2026-07-29 实测，关键！）

用 akshare 实测（沙箱环境），结果：

| 接口 | 用途 | 结果 |
|---|---|---|
| `futures_zh_daily_sina("AU0")` | 内盘主力连续日线 | ✅ **4518 行历史**，列含 `date/open/high/low/close/volume/hold/settle`，最新 2026-07-28（沪金收 885.1 / 持仓 165227 / 结算 888.34） |
| `futures_main_sina("AU0")` | 内盘主力（同上备援） | ✅ 4518 行，列名中文（持仓量/动态结算价） |
| `futures_foreign_hist("GC")` | 外盘历史 | ✅ **2589 行**，含 `date/open/high/low/close/volume/position/settlement`，可回填 `global_history` 的 XAU/CL/HG |
| `futures_foreign_commodity_realtime("GC")` | 外盘实时 | ✅ 现有 collector 已用，列含持仓量（实时值为0，历史有值） |
| `futures_inventory_em` / `futures_shfe_warehouse_receipt` | 库存/仓单 | ⚠️ 接口存在但参数待调（Phase 2 再攻） |
| `futures_hist_em("AU2510")` | 东财期货历史 | ❌ KeyError，且沙箱封东财 → **不用东财** |

**关键结论**：
1. **内盘主力连续日线 + 持仓量(OI) + 结算价 全部可得**（新浪源）——你设计的 `commodity_daily` 的 `open_interest`/`settlement` 字段**完全可行**。
2. 新浪源恰好绕开沙箱封的东财 → **Phase 0 数据源稳定无网络风险**。
3. 外盘历史可回填 `global_history` 的商品缺口。
4. **Phase 0 数据源 100% 可行，无接口/网络不确定性** → 可以放心进入实现。

---

## 4. Phase 0 技术设计

### 4.1 数据源选型（最终）
- **内盘（交易核心）**：`futures_zh_daily_sina(symbol="AU0"/"CU0"/"SC0"/"AG0"/"RB0")`，主力连续，含 OI+结算，新浪源沙箱兼容
- **外盘（宏观锚）**：`futures_foreign_hist("GC"/"CL"/"HG")` 回填历史 + `futures_foreign_commodity_realtime` 取实时
- **不用东财**（沙箱封）

### 4.2 表结构 DDL（三层 + 映射 + 供需）

```sql
-- ① 商品交易行情层（含 OI/结算/主力）
CREATE TABLE IF NOT EXISTS commodity_daily (
  date            TEXT,
  symbol          TEXT,
  name            TEXT,
  market          TEXT,   -- 内盘/外盘
  category        TEXT,   -- 贵金属/能源/有色/黑色/农产品
  close           REAL,
  change_pct      REAL,
  volume          REAL,
  open_interest   REAL,   -- 持仓量(hold)
  settlement      REAL,   -- 结算价(settle)
  main_contract   TEXT,   -- 主力连续代码(AU0)或实际合约
  source          TEXT,   -- futures_zh_daily_sina / futures_foreign_hist
  PRIMARY KEY (date, symbol)
);

-- ② 商品每日评分层（Phase 1 落库）
CREATE TABLE IF NOT EXISTS commodity_factor_daily (
  date             TEXT,
  symbol           TEXT,
  name             TEXT,
  category         TEXT,
  macro_score      REAL,  -- L1 宏观周期
  cycle_score      REAL,  -- L2 大类周期
  fund_score       REAL,  -- L4 资金趋势
  technical_score  REAL,  -- L5 技术趋势
  total_score      REAL,  -- 加权合成
  stage            TEXT,   -- 周期阶段
  analysis         TEXT,
  PRIMARY KEY (date, symbol)
);

-- ③ 品种元数据映射
CREATE TABLE IF NOT EXISTS commodity_symbol_map (
  symbol         TEXT PRIMARY KEY,
  name           TEXT,
  market         TEXT,
  category       TEXT,
  em_link        TEXT,   -- A股板块(AU→黄金)
  inner_symbol   TEXT,   -- 内盘code(如有)
  foreign_symbol TEXT    -- 外盘code(如有)
);

-- ④ 供需基本面层（Phase 2，提前建表避免后期返工）
CREATE TABLE IF NOT EXISTS commodity_supply_daily (
  date        TEXT,
  symbol      TEXT,
  inventory   REAL,
  production  REAL,
  consumption REAL,
  source      TEXT,
  PRIMARY KEY (date, symbol)
);
```

### 4.3 collector 架构（新建独立模块）

```
backend/commodity_engine/
  __init__.py
  collector.py      -- 采集 + 写 commodity_daily + 回填历史
  symbol_map.py     -- 品种元数据（初始化 commodity_symbol_map）
  (Phase1: scoring.py / engine.py)
```

`collector.py` 关键函数：
- `collect_commodity_daily(target_date)`：采 target 日增量 → `commodity_daily`
  - 内盘：`futures_zh_daily_sina` 取 target 日一行
  - 外盘：`futures_foreign_commodity_realtime` 取实时（或 `futures_foreign_hist` 末行）
- `ensure_commodity_history()`：首次/缺失回填全历史
  - 内盘：`futures_zh_daily_sina` 全历史（~4518 行）→ `commodity_daily`（market=内盘）
  - 外盘：`futures_foreign_hist` 全历史（~2589 行）→ `commodity_daily`（market=外盘）+ **同步回写 `global_history` 的 XAU/CL/HG**（补全现有缺口）
- `collect_and_save()`：对外入口，先 ensure_history（幂等）再每日增量
- 字段映射：`hold→open_interest`、`settle→settlement`、`"AU0"→main_contract`

### 4.4 run_daily / daily_collect 接入点（精确）

`daily_collect.py:collect()`（line 80）现有 step 3 调 `ensure_global_history()`。新增一步（step 3.5）：

```python
# 3.5) commodity daily（新增）
if only in (None, "commodity", "align"):
    _append(ensure_commodity_daily())
```

- `ensure_commodity_daily()` 内部首次自动 `ensure_commodity_history()`（幂等，已回填则跳过）
- `run_daily.py` 经 `daily_collect.collect()` 自动带动，**无需额外改 run_daily**
- 支持 `python daily_collect.py --only commodity` 单独重跑

### 4.5 历史回填方案
- 内盘：全历史 → `commodity_daily`（market=内盘）
- 外盘：全历史 → `commodity_daily`（market=外盘）+ 回写 `global_history`（XAU/CL/HG）
- 幂等：`PRIMARY KEY(date,symbol)` + `INSERT OR REPLACE`

**Phase 0 交付物**：商品日线连续可跑 + 历史补齐 + 每日随 `run_daily` 自动更新，CIO 可读取。

---

## 5. 评分模型权重（商品，不照搬股票）

| 因素   | 权重 | 对应层 |
| ---- | -: | --- |
| 宏观周期 | 30 | L1 |
| 供需趋势 | 25 | L2/L3 |
| 资金趋势 | 20 | L4（价格+量+OI） |
| 技术趋势 | 15 | L5（ATR/均线/突破） |
| 风险   | 10 | L7 |

> 理由：商品价格长期由宏观+供需决定，资金只是加速器。与 A股（资金40/产业25/宏观15/技术10/风险10）权重结构不同。

### 5.1 v1 落地权重（Phase 1，**不伪造供需**）

用户决策（2026-07-29 评估）：Phase 1 时供需数据为空（无库存/仓单接口），硬给 25% 会产生虚假精确。故 v1 临时调整：

| 因素   | v1 权重 | Phase 2 目标 |
| ---- | -: | -: |
| 宏观   | 40 | 30 |
| 供需   | 0（留空） | 25 |
| 资金   | 25 | 20 |
| 技术   | 25 | 15 |
| 风险   | 10 | 10 |

- v1 只评 **AU/CU/SC 三品种**（黄金 AU0+XAU / 铜 CU0+HG / 原油 SC0+CL），对应流动性避险 / 全球制造周期 / 通胀供给冲击三个经济变量。
- 宏观分复用 **Gold Engine 评分逻辑**（DB 源 DXY/TIPS/Fed/Oil/BE/Geo），不依赖 thsdk 实时；铜/油再叠加成长/供给倾斜。
- 输出含**解释型文本**（综合/阶段/主要驱动/风险/策略），非黑盒分数。

---

## 6. CIO 升级：Asset Allocation Block

日报新增资产配置建议（**非自动交易，仅资金方向建议**）：

```
资产配置判断
股票: 防守
商品: 黄金趋势增强
现金: 等待
建议：A股 20% / 黄金 30% / 现金 50%
```

---

## 7. Cross Asset Engine（优先级提升）

商品↑ → 美元压力 → 避险资金增加 → 黄金股受益 → A股有色板块关注提升。
铜↑ → 全球制造周期改善 → A股铜矿/电网/新能源。
Phase 3 实现，但架构预留（扩展 `a_share_link` 到量化级）。这是系统独特价值点。

---

## 8. 分阶段（确认版）

- **Phase 0 数据链路**（本技术设计）：建表 + collector + 接入 run_daily + 历史回填 ✅
- **Phase 0.5 商品数据质量层**：`commodity_health.py` 新鲜度/异常/连续性/完整性 ✅
- **Phase 1 评分引擎**：AU/CU/SC v1 权重，落库 `commodity_factor_daily`（黄金直接挂 Gold Engine 子引擎）✅
- **Phase 1.5 CIO 接入**：新增「全球资产观察」（统一 AssetSignal 适配器 + A股环境派生 + 机会排序，不含配置比例）✅
- **Phase 2 CIO 升级 + Asset Regime Engine 中间层 + 日报全球资产页 + 供需（commodity_supply_daily）** ⏳
- **Phase 3 Cross Asset 量化传导** ⏳

1.0 范围严格按三代表起步：黄金 + 原油 + 铜，跑通后再扩黑色/农产品。

---

## 9. Phase 0.5 + Phase 1 实现记录（2026-07-29）

### 9.1 Phase 0.5 商品数据质量层（`backend/commodity_health.py`）
- 每日检查 `commodity_daily` 8 品种，原则「数据过期不编造」：
  - **新鲜度**：相对数据前沿（所有品种最大日期）滞后 ≤1→HEALTHY / 2~4→WATCH / ≥5→STALE（与系统时钟解耦，沙箱鲁棒）
  - **价格异常**：单日 |change_pct|>8% 标记（涨跌停/极端波动/合约切换）
  - **合约连续性**：implied close-to-close 与 reported change_pct 差异>5% 标记换月缝合跳变
  - **完整性**：volume/OI=0 行数；**区分内盘异常缺失（>0.5% 或 >3 行才告警）vs 外盘正常缺失（OI/volume 恒为0，akshare 限制）**
- 输出 `output/commodity_health.json`；接入 `daily_collect --only health`（commodity 步骤后 3.5b）。

### 9.2 Phase 1 评分引擎（`backend/commodity_engine/scoring.py`）
- 三品种 AU0/CU0/SC0（内盘为交易核心，外盘为宏观锚）；v1 权重 宏观40/资金25/技术25/风险10（供需留空）。
- 宏观分：复用 Gold Engine `_score_*` 逻辑，宏观量全部从 `global_history`（DXY/US10Y/US2Y/CL）DB 源喂入 → 黄金=全局环境分；铜=0.6全局+0.4成长；原油=0.6全局+0.4供给。
- 资金分：内盘 OI 20日趋势 + 量比（外盘 OI 恒0 退化为量比）。
- 技术分：MA20/MA60 排列 + 20日动量 + RSI(14)。
- 风险分（越高越安全）：年化波动率罚分 + DXY 跳变罚分。
- 输出 `commodity_factor_daily`（含 stage + analysis JSON 解释型文本）。已回填 250日×3=750 行；接入 `daily_collect --only factor`（3.5c），增量幂等。
- 验证（2026-07-28 截面）：AU 综合53.6 下跌趋势（技术弱）/ CU 综合62.6 震荡（资金强）/ SC 综合53.3 震荡（技术强但波动高）。

---

### 9.3 Phase 1.5 全球资产观察接入（`backend/commodity_engine/adapter.py` + `backend/brain/cio_agent.py` + `backend/notify/os2_report.py`）
- **统一 AssetSignal 适配器**（`commodity_engine/adapter.py`，Phase 1.8 协议基础）：把 `commodity_factor_daily` 最新评分 + analysis JSON + `commodity_health.json` 置信度转换为 CIO 可消费的标准化结构 `{asset, symbol, name, category, score, stage, confidence, drivers, risks, detail}`；输出商品三品种信号（按 score 降序）+ 商品环境判读 + 商品内部机会排序。**不输出任何配置比例**。
- **CIO 接入**（`cio_agent.py`）：`InvestmentDecisionMemo` 新增 `global_asset_obs` 字段；新增 `_build_global_asset_obs(brain, tree)`（调 adapter + `_derive_a_share_env` 派生 A股环境：IC 裁决/主线/市场宽度 + `_merge_opportunity_ranking` 合并跨资产排序）；在 `produce()` 中于学习块后接线。失败降级为空块，绝不崩溃。
- **日报渲染**（`os2_report.py`）：新增 `_global_asset_inner(memo, wechat)` 双渲染助手 + `.ga-*` CSS；在「为什么」与「失效条件」之间注入「全球资产观察」区块（P1，本地 + 公众号对称）。区块结构：资产表（商品三品种↑↓→ + A股等待确认）｜ 商品环境 / A股环境 ｜ 机会排序（仅排序·不含配置比例）｜ 边界备注。
- **明确边界（用户决策）**：Phase 1.5 只做「看见商品 + 机会排序」，不给股票%/黄金%/现金% 配置比例——缺回测/最大回撤/波动率/相关性矩阵，配置模型留待 Phase 3。

### 9.4 Phase 1.6 Global Asset Snapshot（`backend/commodity_engine/snapshot.py` + CIO 接线 + 渲染）
- **目标（用户 2026-07-29 评估）**：在 Phase 1.5「看见商品」基础上，加一层「判环境」——每天回答「今天全球资金在哪里，风险偏好如何」。不是预测，只是观察。对应投资哲学「判环境 → 选方向 → 定标的」三闭环的前半（选方向=商品+股票；定标的=人工看图）。
- **新模块 `commodity_engine/snapshot.py`**：`build_global_snapshot(a_share_env)` 读取 `global_history`（DXY/US10Y/TIPS/BTC）+ `commodity_factor_daily` 最新评分，输出 `{date, risk_state, assets{equity/commodity/macro}, narrative, has_data}`。
- **风险状态粗判**（`_derive_risk_state`）：基于 DXY/US10Y/BTC 三因子各打分后取均值，≥65→Risk On / 40~65→Neutral / <40→Risk Off。明确标注「Phase 1.6 粗估，Phase 2 Asset Regime Engine 将用多因子状态机替代」。
- **CIO 接线**（`cio_agent.py` `_build_global_asset_obs`）：调 `build_global_snapshot(a_share_env=a_share)` 把 `risk_state` + `snapshot` + `snapshot_text` 并入 `global_asset_obs`；失败降级不影响日报。
- **日报渲染**（`os2_report.py` `_global_asset_inner`）：资产表之后新增「🌐 风险偏好：Risk On/Neutral/Risk Off」行（颜色编码：绿/黄/红），本地+公众号双渲染。
- **实测（2026-07-29）**：风险偏好=Risk Off（DXY=100.7 偏强 / 美债10Y=4.57% / BTC=$63k）；商品偏强沪铜(63)/偏弱原油(54)；环境总结「风险偏好=Risk Off；DXY=100.7；美债10Y=4.57%；商品偏强:沪铜；商品偏弱:原油」。
- **边界遵守**：Snapshot 不输出配置比例；宏观分仅做环境判读，不做点位预测。

### 9.5 Phase 1.7 Regime 历史验证层（`backend/regime_history.py` + `daily_collect` step3.5d）
- **目标（用户 2026-07-30 评估）**：系统最薄弱的不是功能，而是「判断有没有长期有效性」。Phase 1.7 建立 `regime_history` 表，逐日记录 risk_state + 资产状态 + 未来 1/5/20 日收益，验证「判环境」能力是否长期有效。这是 Phase 2 六状态 Asset Regime Engine 的训练基础。
- **新模块 `regime_history.py`**：`build_regime_history()` 复用 `snapshot._score_macro_item` + `_REGIME_THRESHOLDS`（单一事实源，保证与线上口径一致），逐日回溯：
  - 宏观：global_history 的 DXY/US10Y/BTC → risk_state（同线上 `_derive_risk_state` 三因子）
  - 商品状态：commodity_factor_daily 的 AU0/CU0/SC0 stage
  - A股代理：stock_daily 全市场每日均值涨跌%（替代指数序列，因库内无指数价）
  - 资产状态：market_daily 的 emotion_score/stage
  - 远期收益：黄金(AU0 收盘价) 1/5/20 日 + 最大回撤；A股(均值涨跌累乘) 1/5/20 日
  - 幂等 upsert；`validate_regime(state)` 按 risk_state 分组出收益分布；`format_regime_report()` 人类可读。
- **流水线接入**（`daily_collect.py` step3.5d）：`only in (None,"regime","commodity","align","factor")` → `ensure_regime_history()`，每日自动追加最新交易日一行。
- **实测回溯（2026-07-30，243 样本 = ~250 交易日）**：

  | risk_state | n | A股 1D | A股 5D | A股 20D | 黄金 1D | 黄金 5D | 黄金 20D |
  |---|---|---|---|---|---|---|---|
  | Neutral | 236 | +0.68% | +3.07% | +13.56% | +0.13% | +0.41% | +1.36% |
  | Risk On | 7 | -0.07% | +2.85% | +13.20% | -2.02% | -2.85% | +1.67% |
  | Risk Off | 0 | — | — | — | — | — | — |

- **关键发现（纠偏）**：回溯修复后，原 Phase 1.6 实测「Risk Off 27.3」被证实是 `_score_macro_item` bug 的**假象**（旧逻辑把 DXY=100.74/BTC=63366 错当美债收益率打分→22，均值 27.3 错落 Risk Off）。修复后线上 2026-07-30 真实状态 = **Neutral 45.0**（DXY→45 / US10Y→38 / BTC→52）。历史 243 样本中 236 为 Neutral、仅 7 为 Risk On、0 为 Risk Off——**三状态粗模型在当前宏观下严重同质化**，恰好佐证用户「两状态太粗、必须六状态」的判断，也说明 Phase 2 六状态模型 + 更多样本是必经之路。
- **边界遵守**：只记录与回溯，不预测、不给配置比例；明确标注「样本远未达 5 年回测要求，当前仅建立闭环」。

### 9.6 Phase 1.8 重新定义：Asset Intelligence Protocol（AIP，契约阶段）

- **用户 2026-07-30 重新定义**：Phase 1.8 目标**不是**「接口统一」，而是建立**统一投资语言**——让股票/商品/债券/ETF/现金/BTC/FX 都回答同一组六个问题（state / score / trend / driver / risk / confidence）。完整契约见 **[`docs/asset-intelligence-protocol.md`](../docs/asset-intelligence-protocol.md)**，并已在 [`docs/trading-os-architecture.md`](./trading-os-architecture.md) Layer 2 升级为 AIP。
- **与旧统一 AssetSignal 的差异**：新增 `trend`（动量方向）、`state` 语义化（旧 `stage` 仅商品用语）、`confidence` 升级为 0-1 浮点；`asset`→`asset_class`（枚举约束）。
- **Phase 1.8 实现范围（契约确定，代码待实现）**：
  - 商品 adapter 重构到 AIP（补 `trend` / `state` / `confidence` 浮点）
  - 新增 `a_share_adapter.py`，把 `cio_agent._derive_a_share_env` 内联派生**抽出独立化**
  - 债券/ETF/现金/BTC/FX 留**骨架**，严守「不编造评分」边界
- **新增 Phase 1.9（用户提议）**：Regime Backtest Dashboard——把 Phase 1.7 的 `regime_history` 验证数据做成可视化有效性报告，作 YouTube/GitHub 展示素材。
- 当前状态：**契约已冻结，代码未实现**（本回合按用户选择「先出协议规范文档」）。

---

*Phase 0 / 0.5 / 1 / 1.5 / 1.6 / 1.7 ✅ 已实现（2026-07-29~30）：
- Phase 0：4 张表 + `commodity_engine/collector.py` + `daily_collect` step3.5 + 历史回填 32324 行/8品种 + 外盘回写 `global_history` 的 XAU/CL/HG。数据源实测可行、幂等自愈、run_daily 自动带动。
- Phase 0.5：`commodity_health.py` 四类检查，接入 step3.5b，输出 `commodity_health.json`（overall=HEALTHY）。
- Phase 1：`commodity_engine/scoring.py`，AU/CU/SC v1 权重，复用 Gold Engine 宏观逻辑（DB 源，不依赖 thsdk 实时），落 `commodity_factor_daily` 750 行，接入 step3.5c，解释型输出。
- Phase 1.5：`commodity_engine/adapter.py` 统一 AssetSignal 协议 + CIO `global_asset_obs` 字段与 `_build_global_asset_obs` 接线 + 日报「全球资产观察」区块（本地/公众号双渲染，介于为什么与失效条件之间），机会排序不含配置比例。
- Phase 1.6：`commodity_engine/snapshot.py` Global Asset Snapshot（DXY/US10Y/TIPS/BTC + 商品评分 → 风险偏好 Risk On/Neutral/Risk Off 粗判）+ CIO 并入 `global_asset_obs.risk_state` + 日报「🌐 风险偏好」行渲染。
- Phase 1.7：`backend/regime_history.py` Regime 历史验证层（逐日回溯 risk_state + 资产状态 + 远期收益落 `regime_history` 表）+ `daily_collect` step3.5d 接入；243 样本验证三状态模型同质化严重（236 Neutral/7 Risk On/0 Risk Off），佐证 Phase 2 六状态必要性。
下一步（用户确认开发顺序，2026-07-30 调整为 1.7 先于 1.8）：Phase 1.8 统一 AssetSignal 协议覆盖 A股/ETF/债券 → Phase 2 加 **Asset Regime Engine 中间层（六状态模型：Liquidity Expansion / Growth Recovery / Inflation Shock / Liquidity Tightening / Risk Aversion / Transition）**（Commodity→Regime→IC→CIO）+ 真实资产配置（股票%/商品%/现金%）+ 供需库存接口（commodity_supply_daily）→ Phase 3 资产配置模型。Phase 2 暂缓（用户明确要求，需先积累样本+回测）。*
