# P1-A.1 · daily-os Collection Error · Root Cause Frozen Record

> 审计日期：2026-09-03
> 阶段：P1-A Test Harness Reliability Audit
> 状态：**ROOT CAUSE CONFIRMED → 待授权最小修复（本轮未改文件）**

---

## 1. 故障现象（事实）

`daily-os/` 下两个测试文件在 `pytest --collect-only` 时**均收集失败**，中断收集，0 用例入库：

```
ERROR collecting test_e2e.py
    import app as A                      # test_e2e.py:3
    PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8777   # app.py:22
    ValueError: invalid literal for int() with base 10: '--collect-only'

ERROR collecting test_integration.py
    import app as A                      # test_integration.py:3
    PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8777   # app.py:22
    ValueError: invalid literal for int() with base 10: '--collect-only'

no tests collected, 2 errors in 0.24s
```

## 2. 根因（CONFIRMED，可信度 99%）

单点、共享副作用：

```python
# daily-os/app.py:22  （模块顶层，不在 if __name__ == "__main__": 内）
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8777
```

pytest 收集时会 `import app`，此时 `sys.argv[1]` 是 pytest 自身 CLI 参数（`--collect-only`），`int('--collect-only')` 抛 `ValueError` → import 崩溃 → collection 中断。

两个 collection error **不是两个独立问题**，是同一个导入期副作用。

## 3. 影响评估

| 维度 | 结论 |
|---|---|
| pytest collection | 中断，0 tests collected |
| 实际测试执行 | 0 |
| 业务代码影响 | 无证据表明存在 |
| 交易策略影响 | 无 |
| 关联性 | 与先前"名义 181 例 / 实际 0 例"同源，属真实 **test harness reliability failure**，非单纯两个测试写坏 |

## 4. 修复范围

- 文件：`daily-os/app.py` **单点**
- 行：`:22` 一行
- 风险等级：**P1**
- 是否需要重构：**不需要**
- 是否允许顺手修其他问题：**禁止**（不动 `run()` / `Handler` / 任何 API 语义；不碰 main_net_buy、market_cap 或其他 P1 项）

## 5. 修复候选（含语义校准）

> 校准点（用户 2026-09-03 指出）：一行修复会**改变非法 CLI 参数的错误语义**，审计必须说清。

**Candidate A（原提议，`isdigit()` 守卫）**
```python
PORT = int(sys.argv[1]) if (len(sys.argv) > 1 and sys.argv[1].isdigit()) else 8777
```
- `python app.py 8777` → 8777 ✅
- `python app.py` → 8777 ✅
- `python app.py abc` → 8777（**原行为崩溃，现静默默认**）❌ 错误可见性下降

**Candidate B（用户建议，`lstrip("-").isdigit()` 守卫）**
```python
PORT = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].lstrip("-").isdigit() else 8777
```
- `python app.py 8777` → 8777 ✅
- `python app.py -8777` → 8777 ✅（多容忍负号数字）
- `python app.py abc` → 8777（**仍静默默认**）❌ 错误可见性同样下降

**Candidate C（结构性修复：移入 `if __name__ == "__main__":`）**
```python
# 顶层不再解析 sys.argv
PORT = 8777
if __name__ == "__main__":
    import sys
    PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8777
    run()
```
- 导入期完全不碰 `sys.argv` → pytest 100% 安全
- `python app.py abc` → 运行期仍抛 `ValueError`（**错误可见性完全保留**）✅
- 但属结构性修改，超出"一行修复"范围，需用户明确放宽 P1-A 范围

**诚实结论**：所有"一行修复"都以牺牲非法参数错误可见性为代价；要同时做到导入安全 + 保留错误可见性，只有 Candidate C 的结构性改法。这与 P0 静默错误治理原则（异常必须可观察、可阻断、可审计）存在张力，需用户拍板取舍。

## 6. 验证 Gate（修复后必须四层全过）

- **Gate 1 · Collection**：`pytest --collect-only`（daily-os）→ **0 collection errors**
- **Gate 2 · Population**：确认实际 collected 数量 N > 0，不得再出现"181 expected / 0 collected"
- **Gate 3 · Execution**：实际 `pytest` 运行（非仅 collect），记录 passed/failed/skipped
- **Gate 4 · Regression（CLI smoke）**：三类入口语义不变
  - `python app.py` → 默认 8777 启动
  - `python app.py 8777` → 绑定 8777
  - `pytest --collect-only` → import 安全，无 ValueError

## 7. 制度性结论（P1-A 一级健康指标）

> **"pytest collection 成功"必须成为 Test Harness 的一级健康指标。**

今后测试报告不得仅记录 `X passed`，必须记录：

```
Collected:   N
Collection errors: 0
Executed:    N
Passed:      X
Failed:      Y
Skipped:     Z
```

否则 `0 collected / 0 failed` 会被误读为"测试通过"。这与 P0 静默错误治理同一条可靠性原则：**任何异常都必须进入可观察、可阻断、可审计的状态**。

## 8. 当前状态

- P1-A.1 = **ROOT CAUSE CONFIRMED → 待授权最小修复**
- 本轮**未修改任何文件**、**未运行生产流水线**
- 下一步（获授权后）：改 1 处 → Gate1 collection → Gate2 population → Gate3 execution → Gate4 CLI smoke → git diff 审计 → 再决定是否进入 P1-A.2（整体 harness 健康度）
