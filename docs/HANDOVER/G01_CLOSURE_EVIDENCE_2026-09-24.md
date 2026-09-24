# G01 · 闭环证据（2026-09-24）

> **状态**：`IMPLEMENTED + REGRESSION_PASS`，**待独立复审（independent review）**
> **依据**：R8 §6（G01 提升为工程 P0）+ `docs/HANDOVER/G01_FIX_DESIGN_v1.2.md`（§9.1 设计就绪度 GO）
> **范围**：G01-a（MOCK/TEST fail-closed）。PRODUCTION 归 G01-b，**不在本片**。
> **未做**：不重构 attribution 子系统；不改阈值 / 权重 / 评分；不碰 canonical DB。

---

## 1. 缺陷复现（修复前事实）

```text
trading_os/g2_supervisor.py:212  ap.add_argument("--db", default=DEFAULT_DB)
trading_os/g2_supervisor.py:56   DEFAULT_DB = .../backend/database/vibe_research.db   ← canonical 生产库
trading_os/g2_supervisor.py:224  sink = AttributionSink(db_path=args.db)              ← 先构造
trading_os/g2_supervisor.py:226  if args.mock:                                        ← 后判 mock

trading_os/attribution_sink.py:92-97
    def __init__(self, db_path="backend/database/vibe_research.db", ...):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)   ← 连生产库
        self._conn.execute(_DDL...)                                       ← DDL
        self._conn.commit()                                               ← commit
```

⇒ 跑 `--mock` 也会 **connect 生产库 + CREATE TABLE + commit**。
第二入口：`trading_os/submit_close.py:147`（`--serve`）同型，且**连 `--mode` 都没有**。

---

## 2. 最小修复（4 源 + 1 新测试 + 2 测试适配）

| 文件 | 变更 |
|---|---|
| `trading_os/storage_policy.py` | **新增**。模式裁决 / `DbTarget`（带签发令牌）/ 目标校验 / 全仓唯一 `sqlite3.connect` 点 / 连接来源标记 |
| `trading_os/attribution_sink.py` | 构造改为只接受 `DbTarget`、**零 I/O**；连接与建表延后到显式 `open()`；DDL / 写入分别受授权位约束；写操作前校验连接来源 |
| `trading_os/g2_supervisor.py` | **删除 `DEFAULT_DB`**；`--db` 默认 `None`；先裁决模式与目标再构造 sink；违规 → `exit 2` |
| `trading_os/submit_close.py` | **删除 `DEFAULT_DB`**；新增 `--mode {mock,test}`（`--serve` 必填）；同上门禁 |
| `trading_os/tests/test_storage_boundary.py` | **新增 26 用例**（A–G 组，含对抗性） |
| `tests/test_g2_supervisor.py` / `test_g2_bridge_attribution.py` | 适配新签名（5 处），改用 `storage_policy.test_target()` |

**关键设计点（防止"调用方自觉"型绕过）**
- `DbTarget` 需策略层令牌；手工构造 / `dataclasses.replace` / 反序列化 → `raise`
- 无 `attach(conn)` / `set_conn` 之类的公开连接注入点（v1.2 明确删除）
- 连接以 `PolicyConnection` 包装并携带来源标记；写操作前 `assert_policy_issued()`
- 全部 `raise`，**零 `assert`**（`python -O` 不得削弱）；已用 `-O` 跑测验证

---

## 3. 验收对照（R8 §6 最低条件）

| 条件 | 结果 | 证据 |
|---|---|---|
| mock/test：0 production DB connection | ✅ | `test_c1`（构造期 0 connect）/ `test_f1`（`--mock` 仅 `:memory:`）/ `test_f5`（`submit_close --serve --mode mock` 仅 `:memory:`） |
| 0 file-backed DB connection（除非显式允许的测试目标） | ✅ | `test_b1/b2/b3`（生产库路径、已存在/不存在父目录、相对、大小写变体、`\\?\` 前缀、`:memory` 近似值全拒，且不创建任何文件/目录） |
| 0 production DDL | ✅ | `test_d1`（`allow_ddl=False` → `ensure_schema()` / `open()` 均 raise） |
| 0 production commit | ✅ | `test_d2`（`allow_write=False` → `close_position()` raise） |
| 覆盖 `g2_supervisor` | ✅ | `test_f1` / `test_f2`（非 mock → exit 2 + 0 connect）/ `test_f3`（`--db <file>` → exit 2 + 0 connect + 不建文件） |
| 覆盖 `submit_close --serve` | ✅ | `test_f4`（缺 `--mode` → exit 2 + 0 connect）/ `test_f5` / `test_f6` |
| runtime validation（非 dataclass / 注解 / 调用方自觉） | ✅ | `test_e1/e2`（裸连接注入 → 写操作 raise）/ `test_e3/e4`（伪造目标 raise）/ `test_d3`（未 open → raise） |
| 不依赖 `assert` | ✅ | `test_g2`（静态：策略层零 assert）+ `python -O` 全量通过 |

---

## 4. 测试结果

```text
trading_os/tests/            72 passed            （新增 26 + 既有 46）
python -O 复跑               72 passed            （校验未被优化掉）

真实 CLI 对抗性验证：
  python trading_os/g2_supervisor.py
    → [FAIL] 存储边界拒绝（G01）：mode='UNKNOWN' 不得产出存储目标   exit=2
  python trading_os/submit_close.py --serve
    → [FAIL] 存储边界拒绝（G01）：mode='UNKNOWN' 不得产出存储目标   exit=2
```

---

## 5. 静态门禁

- `trading_os/*.py` 中 `sqlite3.connect(...)` 真实调用点 **= 1**，且位于 `storage_policy.py`（`test_g1`，AST 解析，非正则）
- `storage_policy.py` **零 assert**（`test_g2`）
- `g2_supervisor.py` / `submit_close.py` / `attribution_sink.py` **不再出现** canonical 生产库路径字面量（`test_g3`）

---

## 6. 残余局限（如实登记）

| 项 | 说明 |
|---|---|
| PRODUCTION 模式 | 未实现，归 **G01-b**。当前非 mock 一律 exit 2 —— 若将来要跑真实 G2 守护，必须先完成 G01-b |
| 蓄意改 `storage_policy.py` 本身 | 超出威胁模型，不能防 |
| 绕过策略层直接 `sqlite3.connect` | 靠 `test_g1` 静态门禁 + AGENTS 不变量约束，非运行时硬隔离 |

---

## 7. 下一步（待 CIO）

1. **独立复审**（建议 Codex Work，对应 `docs/HANDOVER/G01_CODEX_REVIEW_BRIEF_v1.1.md` 的角色分工）
2. 复审通过后独立 commit（建议语义：`fix(g01): fail-closed storage boundary for mock/test paths`）
3. 完成 F17 / F17b 后一并评估 push
