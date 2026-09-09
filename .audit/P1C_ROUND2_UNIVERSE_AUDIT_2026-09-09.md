# P1-C · Round 2 — Universe Membership Audit（READONLY）

- 日期：2026-09-09
- 范围：Canonical Universe 成员资格（第二半），与 Round 1（Canonical DB Location）严格分开
- 纪律：**只读**。未改代码、未改 DB、未 commit、未 push。
- 触发器：用户判定「Canonical DB ≠ Canonical Universe」——即使 C7（DB 路径统一）做完，若各程序用不同成员资格判定，仍会在同一 canonical DB 上形成第二种隐性分叉。故先查 `_is_stock`、Universe 规则、北交所 327→0，再决定是否实施 C7。

---

## 0. 状态 YAML（采纳用户修正，不把「DB 在场」读作 unrestricted production-ready）

```yaml
DB_STATE:
  canonical: PRESENT                      # Recovery Gate ⑤ 已闭环 RECOVERED_WITH_VERIFICATION
  integrity: VERIFIED                      # sha256 30d29309... 与 D 盘备份逐字节一致
  runtime_readability: VERIFIED            # mode=ro healthcheck exit=0
  pytest_isolation: VERIFIED               # 17 passed + CANONICAL_UNCHANGED=True（存在态）
SYSTEM_RUNTIME:
  canonical_universe: UNRESOLVED           # 本回合目标：把"成员资格"做成单一事实源
  manual_write_surface: RESTRICTED         # B4.3/B4.6 仍 FAIL
  production_automation: ALLOWED_BY_SCHEDULE_ONLY
  VIBE_DB_PATH: FORBIDDEN                  # 生产环境禁止设置
  p1c_round1: DONE_INVENTORY_ONLY          # C7 已设计未实施
  p1c_round2: DONE_AUDIT_ONLY              # C8/C9/C10 证据齐，未实施
```

---

## 1. C8 — Universe 成员资格判定是否存在多个事实源

### 1.1 Universe Rule Matrix（全代码前缀分类器事实源）

| # | 文件:行 | 函数 | 类型 | 北交所判定 | 生产效应 | 矛盾/漂移风险 |
|---|---|---|---|---|---|---|
| 1 | `data_health.py:34-42` | `_is_stock` | 成员资格 | `6/0/3` 或 `83/87/920` → **包含**北交所 | data_health 计数 `n_stocks` 含北交所 | 🔴 docstring:35 + 注释:10 写「剔除北交所」，**代码与文档意图相反** |
| 2 | `capital_score.py:45-48` | `_is_stock` | 成员资格 | 同上 → **包含**北交所 | 资金评分宇宙含北交所 | 无文档，与 #1 行为一致 |
| 3 | `fill_market_cap.py:88-91` | `_is_stock` | 成员资格 | 先排除 `11/12/13/15/16/18/88/5`，再 `6/0/3`或`83/87/920` → **包含**北交所 | 市值回填宇宙含北交所 | 多一层排除（更精确），行为与 #1/#2 等价 |
| 4 | `astock.py:32-38` | `get_prefix` | 路由（交易所前缀） | `6/9→sh`、`8→bj`、其余`sz` → **整段 `8` 当北交所** | 行情/公告 API 路由 | 语义比 #1-3 宽（`8` 含新三板 4/8） |
| 5 | `astock.py:228` | `disclosure.market` | 路由（市场标签） | `6→沪市`、`8→北交所`、其余`深市` → **整段 `8` 当北交所** | cninfo 公告接口 market 参数 | 同 #4 宽语义 |
| 6 | `fundamental_engine.py:67-72` | `_gtimg_prefix` | 路由 | `6/9→sh`、`8/4→bj`、其余`sz` | gtimg 行情 URL | 宽语义（`4/8→bj`） |
| 7 | `tushare_provider.py:59-66` | `_ts_code` | 路由 | `6→.SH`、`0/3→.SZ`、`4/8→.BJ` | tushare 代码后缀 | 宽语义（`4/8→.BJ`） |
| 8 | `leader_engine.py:68-77` | `industry_members` | 成员资格（板块→成分） | docstring「排除北交所/转债」；**SQL 仅排除 `88/11/12/5`，实际包含北交所** | 板块→成分映射含北交所 | 🔴 docstring 与代码相反（同 #1 型漂移） |

### 1.2 判定

- **事实源数量**：确认 8 处（4 个成员资格型 + 4 个路由型）。即用户担忧的「多个事实源」属实。
- **成员资格行为一致性（当前）**：#1/#2/#3 三个 `_is_stock` **功能等价**（均含北交所 83/87/920）；#8 `industry_members` 实际也含北交所。→ 当前各程序产出的 Universe **行为上相同**，尚未出现真实分叉。
- **两类潜伏分歧（尚未引爆，但必须消除）**：
  - **(a) 文档/意图漂移**：#1 的 docstring 与注释、#8 的 docstring 都说「剔除北交所」，但代码包含。一旦有人「按文档修正」，Universe 会丢掉北交所 → 真实分叉。
  - **(b) 路由分类器宽语义**：#4/#5/#6/#7 把整段 `8`（含新三板 4/8）当北交所，比成员资格规则（仅 83/87/920）宽。当前仅用于 API 路由，未被误用于成员资格；但若将来复用这些函数做 `is_stock` 判定，会把新三板纳入 Universe → 分叉。
- **无 DB 级 board/exchange/universe 列**：探针确认 `stock_info`/`stock_daily` 无 exchange/board 列，无 universe 表 → 成员资格完全靠代码内 `startswith` 判定，无数据库物化事实源。

### 1.3 C8 verdict

> **存在多个事实源（8 处）= 真。** 但成员资格规则**当前行为一致**（3 个 `_is_stock` 等价 + leader_engine 实际含北交所），**未**造成生产 Universe 分叉。真正风险是 (a) 文档意图漂移、(b) 路由分类器宽语义——二者均为**潜伏分歧**，需 C10 统一 + 文档修正后才能宣布 Universe 收敛。
> **可信度 ≈ 95%**（与用户预判一致）：高置信度仅「Canonical DB Location 可收敛为单一事实源（Round 1）」；Canonical Universe 是否收敛，**需 C8-C10 证据 + C10 实施后才能定论，本回合不预下结论。**

---

## 2. C9 — 北交所 327→0 反事实审计

### 2.1 权威数据（mode=ro 直查 canonical DB，2026-09-09）

| 表 | `83` | `87` | `920` | DISTINCT 码总计 |
|---|---|---|---|---|
| `stock_info` | 0 | 0 | **327** | 5530 |
| `stock_daily` | 0 | 0 | **328** | 9375 |
| `stock_flow_daily` | 0 | 0 | **0** | 5556 |
| `limit_up_daily` | 0 | 0 | 8 | 1798 |

补充：`stock_daily` 中 `8%`=1124（其中 `88x`=1120 为通达信板块指数伪代码，`920`=328）；`4x`/`83`/`87` 均为 0 → 当前库内北交所**仅以 `920` 前缀存在**（327 在 stock_info / 328 在 stock_daily）。

「327→0」精确含义：**327 只北交所在 `stock_info` 有主体记录，但在 `stock_flow_daily`（个股资金流）中 0 行**。

### 2.2 反事实溯源（数据层 → 采集层 → 宇宙层 → 策略/展示）

1. **数据层**：`stock_info`/`stock_daily` 含 327/328 只北交所（Universe 规则包含它们，见 C8）。
2. **采集层（根因）**：`fill_stock_flow.py:22` 注释明确「北交所(8xx/92x) push2 不覆盖，保持缺省（流动性低，可接受）」；`fill_daily_quotes.py:25` 同口径。→ 北交所资金流**从源头就没采**。
3. **宇宙层（成员资格）**：`_is_stock` 仍把北交所判为真个股 → 北交所**在 Universe 内**，只是无 flow 数据。
4. **策略/展示层**：`data_health.py` 校验项 #2「`stock_flow_daily` 当日覆盖（占真个股）≥80%」——北交所被计入真个股分母，但 flow=0 → **拉低覆盖率**，可能触发 `trade_allowed=False`（fail-closed）。这是 327→0 唯一会冒泡到决策链的位置。

### 2.3 根因锁定与故障分类

- **根因**：采集层**有意缺口**（`fill_stock_flow.py:22`），非 `_is_stock` 排除，非 DB 定位问题。
- **故障类型**：**「数据没进上游 Universe」**（上游采集未覆盖），区别于用户特别区分的另一类「系统排除北交所」。本案例属于前者。
- **关键纠正**：327→0 **不证明**系统把北交所踢出 Universe；恰恰相反，Universe 规则包含北交所，只是 flow 数据缺失。若误读为「成员资格排除」，会在 C10 设计上走错方向。

### 2.4 C9 verdict

> 327→0 = **采集层缺口（已定位、机制明确）**，不是成员资格分歧，不是 DB 定位问题。属独立的数据完整性缺陷，应并入「采集层覆盖治理」，与 C10（成员资格统一）并行处理，不互相阻塞。

---

## 3. C10 — Universe Canonical Source 设计（双单点架构）

### 3.1 原则

最终架构 = **Canonical DB（Round 1 / C7）+ Canonical Universe（本回合 C10）双单点**：

- Canonical DB Location：统一到 `db.get_conn()` / `models.get_db()` 唯一入口（C7 已设计，待实施）。
- Canonical Universe：成员资格 + 交易所分类**单一事实源**，所有 8 处改为调用它，零重实现。

### 3.2 方案：新增 `backend/universe.py`（唯一成员资格/分类源）

```python
# backend/universe.py —— Canonical Universe（单一事实源）
BJ_PREFIXES = ("83", "87", "920")          # 北交所（ proper ）
NON_STOCK_PREFIXES = ("11","12","13","15","16","18","88","5","4")  # 转债/ETF/基金/板块指数/新三板
MAIN_PREFIXES = ("6", "0", "3")             # 沪/深/创业

UNIVERSE_INCLUDES_BJ = True                 # 意图显式化，消除 #1/#8 文档漂移

def is_stock(code: str) -> bool:
    """真个股：沪(6)/深(0)/创业(3)/北交(83/87/920)；排除转债/ETF/基金/板块指数/新三板。"""
    if not code:
        return False
    if code.startswith(NON_STOCK_PREFIXES):
        return False
    return code[0] in MAIN_PREFIXES or code.startswith(BJ_PREFIXES)

def market_of(code: str) -> str:
    """沪市/深市/北交所（与 is_stock 同源，杜绝 #4-#7 宽语义分叉）。"""
    if code.startswith(BJ_PREFIXES):
        return "北交所"
    if code[0] == "6":
        return "沪市"
    if code[0] in ("0", "3"):
        return "深市"
    return "其他"   # 新三板/板块指数等，is_stock=False
```

- #1/#2/#3 的 `_is_stock` 删除，改为 `from universe import is_stock`。
- #4/#5/#6/#7 的路由分类改为委托 `market_of`（或保留各自 URL 拼装但**用 `market_of` 取交易所**，不再各自 `startswith`）。
- #8 `industry_members` docstring 改为「含北交所」，与 `is_stock` 意图一致；SQL 维持（已含北交所）。

### 3.3 数据库物化（可选，推荐）

- 给 `stock_info` 加 `board`/`exchange` 列，**由 `market_of(code)` 一次性派生**（代码前缀推导，非人工标签），使 Universe 成员资格成为 DB 内可查询事实。
- 收益：下游 `data_health`/`capital_score`/`leader_engine` 可直接 `WHERE board='北交所'` 或 `WHERE is_stock=1`，不再依赖 Python 内 `startswith`；C8 的「多事实源」从根上消失。
- 代价：DDL 变更（属写操作，**本回合不实施**，列入后续 round）。

### 3.4 文档漂移修正（最小、必做）

- `data_health.py:35` docstring、「:10」注释：改为「含北交所（流动性低，flow 由采集层单独覆盖）」。
- `leader_engine.py:69` docstring：改为「含北交所/排除转债」。
- 与 #8 实际行为对齐，消除 (a) 类潜伏分歧。

### 3.5 迁移地图（8 处 → universe.py）

| # | 当前 | 改为 |
|---|---|---|
| 1 | `data_health._is_stock` | `from universe import is_stock` |
| 2 | `capital_score._is_stock` | `from universe import is_stock` |
| 3 | `fill_market_cap._is_stock` | `from universe import is_stock`（NON_STOCK 已含其额外排除） |
| 4 | `astock.get_prefix` | 保留 URL 拼装，交易所判定改 `market_of` |
| 5 | `astock.disclosure.market` | 改 `market_of` |
| 6 | `fundamental_engine._gtimg_prefix` | 改 `market_of` |
| 7 | `tushare_provider._ts_code` | 改 `market_of` |
| 8 | `leader_engine.industry_members` | docstring 修正 + 可改用 `is_stock` 过滤 |

### 3.6 验证门（实施时）

- `p1c_scan` 复扫：`_is_stock` 定义数 = 1（universe.py 内）；路由分类器 `startswith("8")` 裸判定 = 0。
- pytest 全量复测（Gate ⑦ 口径）PASS + CANONICAL_UNCHANGED。
- 行为级：构造北交所/新三板/转债样本，断言 `is_stock` 与 `market_of` 输出唯一且符合 C8 预期。

---

## 4. 两条战线分离声明（关键，不混淆）

| 维度 | 状态 | 结论置信度 |
|---|---|---|
| **Canonical DB Location**（Round 1 / C7） | 事实源已定位（87 非 ROOT + ROOT 单点 2），C7 最小方案已设计 | ≈95% 可收敛为单一事实源 |
| **Canonical Universe**（Round 2 / C8-C10） | 成员资格 8 事实源已盘清；当前行为一致但有 (a)(b) 潜伏分歧；C10 已设计未实施 | **未定论**——须 C10 实施 + 文档修正 + DB 物化后才可宣布收敛 |

> **不预下「Canonical Universe 收敛为 1 处」结论**（用户明确纠偏）。当前仅能说：成员资格规则行为上已一致（3 个 `_is_stock` 等价），但事实源未统一、文档意图有漂移、路由分类器语义偏宽——这些是「未治理」而非「已收敛」。

---

## 5. 门禁顺序（用户批准，保持不变）

```
Round1 (C1-C7 inventory) ✅
  → Round2 (C8/C9/C10) ✅ 本回合
    → Universe Rule Matrix 落盘 ✅
      → C7/C11 最小方案实施（待授权，独立 round）
        → 统一 DB + Universe（universe.py + doc 修正 + 可选 board 列）
          → READONLY Regression（p1c_scan 复扫 + pytest Gate ⑦ 复测）
            → P1-C PASS
              → 解除 B4.8 禁止清单
```

---

## 6. 本回合产物与下一步

**产物（仅只读工件）**
- 本报告 `.audit/P1C_ROUND2_UNIVERSE_AUDIT_2026-09-09.md`
- 证据 `.audit/evidence/p1c_universe_probe.py` + 本轮 mode=ro 直查数字（§2.1）

**下一步（均未执行，等授权）**
1. C10 实施：新增 `backend/universe.py` + 8 处迁移 + 文档漂移修正（最小 scope，不扩到 C7 之外的重构）。
2. （可选）`stock_info.board` 列物化。
3. C7 实施（DB 路径统一）与 C10 可合并为同一 round，但须分别验证门。
4. READONLY 回归：p1c_scan 复扫 + pytest Gate ⑦ 复测 → P1-C PASS → 解除 B4.8。
5. 全部完成后才 commit/push（用户 Intent B：恢复成功与治理未完成不可过早冻结）。

**纪律重申**：本回合未改代码、未改 DB、未 commit、未 push。工作树仅新增 `.audit/` 工件。

---

## 7. 实施回合记录（C10 + C7）— 2026-09-09

> 授权范围：A(C10) + B(C7)；C 类明确不做（board/exchange 物化 / 改表结构 / 改业务规则 / 北交所 flow 补采 / 改阈值 / 改策略）。
> 授权原话约束：「**不能因为'代码改完了'就宣布 PASS。PASS 是验证门的结果。**」

### 7.1 C10 · Canonical Universe 单点收敛

| 动作 | 落地 |
| --- | --- |
| 新增 `backend/universe.py` | `is_stock` / `market_of` / `BJ_PREFIXES` / `UNIVERSE_INCLUDES_BJ=True`，零 DB / 零网络依赖 |
| 3 份 `_is_stock` 副本 → `universe.is_stock` | `capital_score.py`、`data_health.py`、`fill_market_cap.py` 均改为 `from universe import is_stock` |
| 4 处路由分类器 → `universe.market_of` | `astock.get_prefix`、`astock.disclosure`、`fundamental_engine._gtimg_prefix`、`tushare_provider._ts_code` |
| 文档漂移修正 | `data_health` 头部「剔除…北交所」→ 明确含北交所；`leader_engine.industry_members` docstring 对齐实际 SQL |

`grep 'def _is_stock'`（排除 tests / universe）= **0**。

### 7.2 C7 · DB Location 机械迁移

- 69 个生产消费者文件：`sqlite3.connect(<DB/DB_PATH/db/ne.DB>[,timeout=N])` → `get_conn([timeout=N])`；
  模块级 `DB / DB_PATH / OUT_DB` 派生为 `str(_DB_PATH)`（**保留原缩进与原变量名**）。
- timeout 原样保留（`30` / `60`）；未指定者走 `get_conn()` 默认 5s（= sqlite3 原生默认，等价）。
- `from db import get_conn, _DB_PATH` 插入位置：优先 `from __future__` **之后**，否则 coding 声明 + 模块 docstring **之后**。
- 迁移后 80 个文件使用 `from db import get_conn`。

**Carve-out（刻意保留，非遗漏）**

| 文件 | 原因 |
| --- | --- |
| `db.py` | 唯一 canonical 定义（`_DB_PATH` / `get_conn`） |
| `database/models.py` | canonical schema 层，需具备建库能力；`DB_PATH` 为 conftest 重定向锚点 |
| `gold_engine/data_adapter/gold_data.py` | 独立 gold DB |
| `market_amount.py` | 独立 `data/strategy.db`（**非** research DB） |
| `shadow_evaluator.py` | `db_path` 为函数入参，非硬编码 |
| `_healthcheck_preopen.py` / `_inspect*.py` | 一次性诊断脚本 |

### 7.3 迁移过程中捕获并修正的 2 个真实行为漂移

1. **`_gtimg_prefix` 返回格式**：初版返回裸前缀 `"sh"`，历史契约是 `"sh600000"`（前缀+代码）。
   被 `test_routing_gtimg_prefix_delegates` 拦截 —— 否则 gtimg URL 拼接断裂。
2. **900xxx 沪市B股被误判**：`market_of` 初期把整段 `9` 归入「其他」→ 路由退化成 `sz`。
   被既有 `tests/test_pure.py::test_get_prefix`（断言 `get_prefix("900001") == "sh"`）拦截。
   修正：`market_of` 增加 `9 → 沪市` 分支；`920` 由 `BJ_PREFIXES` **先行**判定为北交所，二者不冲突 ——
   这正是历史「整段 9 当沪市」误伤 920 的修正点。已新增 `test_drift_prevention_900_bshare` 锁定该边界。

> 两次都是「机械迁移意外改变既有行为」的实例，且**均由测试而非人工 review 发现**，
> 印证授权时点名的首要风险（风险已从「找不到 Canonical」转为「迁移过程意外改行为」）。

### 7.4 P1-C Gate 结果

| Gate | 要求 | 结果 |
| --- | --- | --- |
| C2/C3/C5 hardcoded DB source | = 0 | ✅ 0（仅 §7.2 carve-out） |
| duplicate `_is_stock` definitions | = 0 | ✅ 0 |
| bare 8-prefix membership classification | = 0 | ✅ 0（grep 无匹配） |
| 920 membership | = True | ✅ `is_stock("920001")=True` / `market_of="北交所"` |
| 430 membership | = False | ✅ `is_stock("430999")=False` / `market_of="其他"` |
| pytest | = PASS | ✅ **155 passed, exit 0**（`--ignore=test_gate.py`） |
| 编译 | — | ✅ 69 files + `universe.py` 全部 `py_compile` 通过 |
| CANONICAL_UNCHANGED | = True | ✅ 默认路径解析逐字未变；DDL 变更 = 0；`VIBE_DB_PATH` 仅 opt-in 覆盖（未设置时 100% 向后兼容） |
| VIBE_DB_PATH 范围 | 不扩大 | ✅ 仅 `db.py` / `models.py` / `conftest.py` + 1 个隔离测试 |

**Universe Contract Test**：`backend/tests/test_universe_contract.py` 共 10 项，含用户点名的
`920→True/北交所`、`430→False/其他` 防漂移断言，并新增 `900001→沪市` 回归断言。

### 7.5 判定

**P1-C PASS**（验证门结果，非「代码改完」）。

仍在 C 类「不做」清单内、留待后续独立议题：
- `stock_info.board/exchange` 物化 —— 用户明确剥离本轮。
- 北交所 `stock_flow_daily` 327→0 补采 —— 独立 **Data Coverage** 故障，与 Universe Governance 解耦。

**纪律**：本回合**未 commit、未 push**（等待用户确认后再冻结）。临时迁移脚本已删除。
