# P1-A.1 · daily-os Collection Error · Fix & Verification Report

> 修复日期：2026-09-03
> 修复方案：用户拍板 **Candidate B**（`lstrip("-").isdigit()` 守卫）
> 目标（校准后精确表述）：**修复 pytest 导入期崩溃，同时保持正常端口启动路径不变**；非法 CLI 参数错误语义属后续 CLI hygiene，不在本轮范围

---

## 1. 修改（仅一处生产代码）

`daily-os/app.py:22`：

```diff
- PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8777
+ PORT = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].lstrip("-").isdigit() else 8777
```

- 未改 `run()` / `Handler` / 任何 API 语义
- 未改测试文件、未改数据库、未运行完整生产流水线
- git diff 确认**只有这一行**变更（`git status` 仅 `M daily-os/app.py`）

## 2. 四层 Gate 验证结果

### Gate 1 · Collection —— **PASS**
```
pytest --collect-only   →  0 collection errors  （原 2 errors → 0）
```

### Gate 2 · Population —— **0 pytest 可发现测试（关键发现）**
```
pytest -v   →  collected 0 items / no tests ran
```
**真相**：`test_e2e.py` / `test_integration.py` **不是 pytest 测试文件**。二者：
- 没有任何 `test_*` 函数 / 无 unittest.TestCase 子类
- 全部逻辑在**模块顶层**：`import` 时即 `start()` 启动 HTTP 服务器、发请求、`assert`、打印 `E2E_OK` / `INTEGRATION_OK`

因此：之前的"2 个 collection error"**纯粹是 `import app` 崩溃**，不是 2 个失败用例；修复 import 崩溃后，pytest 仍收集到 **0 个测试**——这是真实状态，**不是被掩盖的失败**。这恰好印证了你警告的"0 collected / 0 failed 误读为通过"陷阱，也证明 daily-os **从未有 pytest 原生测试**，只有两个被 pytest 误当测试文件 import 的脚本。

### Gate 3 · Execution —— **0 pytest 测试被执行**
无 pytest 测试可运行。
注意：这两个脚本若直接 `python test_e2e.py` 运行，会向 `daily_os.db` 写记录（POST /api/noon 等），属**修改数据库**，本轮授权明确禁止"修改 DB"，故**未作为脚本执行**。其 E2E/集成正确性不在本轮验证范围。

### Gate 4 · Regression（CLI smoke）—— **PASS**
| 入口 | 结果 |
|---|---|
| `import app`（模拟 pytest `sys.argv=['pytest','--collect-only']`） | PORT=8777，无 ValueError ✅ |
| `python app.py` | 打印"已启动" + `http://127.0.0.1:8777`，绑定 8777 ✅ |
| `python app.py 8777` | 同上，绑定 8777 ✅ |
| `python app.py abc`（非法参数，校准预期） | PORT=8777（**静默默认，不再崩溃**——这是 B 方案的已知语义代价，已记录在案）✅ |

## 3. 验证结论

| Gate | 结果 | 说明 |
|---|---|---|
| 1 Collection | **PASS** | 0 errors |
| 2 Population | **0 tests** | 真值：daily-os 无 pytest 测试，仅两个顶层脚本 |
| 3 Execution | **0 ran** | 无 pytest 测试可执行（脚本直跑会写 DB，已禁） |
| 4 Regression | **PASS** | 正常端口启动路径不变；import 安全 |

P1-A.1 的窄目标（**消除 pytest 导入期崩溃 + 保持正常启动路径不变**）= **达成**。

## 4. 必须登记的深层发现（不修、待你决策）

> 按你的禁令"因测试暴露新问题就自动扩大修改范围" = **禁止**。以下仅登记。

**发现 F1**：daily-os 的"测试"实为脚本而非 pytest 测试。
- 影响：pytest 无法提供任何 daily-os 可执行测试覆盖；CI/本地 `pytest` 对 daily-os 永远 0 collected / 0 ran，却不会报错（静默无覆盖）。
- 这与 P0 静默治理同一条原则冲突：无覆盖却无失败信号 = 假绿。
- 可选处置（**均超出本轮一行修复范围，需你另拍板**）：
  - (a) 将两脚本改写为 pytest 原生测试（`test_*` 函数 + fixture 起停服务器 + 用 tmp DB 避免写真实库）
  - (b) 把这两文件移出 pytest 发现范围（改名 `e2e_script.py`，避免被 import 触发副作用），并显式文档"用 `python e2e_script.py` 运行"
  - (c) 在测试报告中明确标注 daily-os = 0 pytest 覆盖，作为已知缺口

**发现 F2**：`pytest collection 成功` 应升为一级健康指标（已在 P1-A.1 冻结记录写入制度性结论）。本次若只看"2 errors → 0 errors"会漏掉"0 collected"的真相，验证必须同时看 Population/Execution。

## 5. Git / 生产保护确认
- 修改文件：`daily-os/app.py`（仅 :22 一行）
- `git diff --stat`：1 file changed, 1 insertion(+), 1 deletion(-)
- 未提交、未 push（按阶段约定只改工作区）
- 未改：策略 / 权重 / 阈值 / Risk Guard / Adaptive Feedback / Decision Tree / CIO / Scheduler / 数据库
