# H1 Erratum 001 · Regime/Control 数据源替代（2026-08-22）

> 关联契约：`docs/H1_PreRegistration_v0.1.md`（v0.1）
> 性质：**记录式契约修正**（非静默修改）。本 Erratum 与契约共同构成 H1 的冻结规范。
> 状态：**APPROVED**（用户 2026-08-22 11:57 批准方案 1）。

## 触发原因（事实记录）

- `ak.index_zh_a_hist` 对中证指数（930955 / 000922）在当前环境持续 `ProxyError`（东财 clist 接口，`80.push2.eastmoney.com` 直连 HTTP 200 但 akshare 内部调用不可达）。
- 个股 `stock_zh_a_hist`（东财 kline 路径）正常；`stock_zh_index_daily`（新浪）不支持 930955（`KeyError 'date'`）。
- 连续 3 次重试 + 多接口探测确认：930955 官方指数序列在当前数据管道内不可获得。

## 变更内容

| 位置 | 原契约 | 修订后 |
|---|---|---|
| §2 Control | 930955 **官方指数价格序列** | **当前成分等权合成指数**（Current-Component Equal-Weight Synthetic Index），由 100 只当前成分的前复权 close 按各自首个有效值归一化后等权平均构造 |
| §5 D5 Regime | 基于 **930955 指数** vs 自身 MA250 | 基于**当前成分等权合成指数** vs 自身 MA250 |
| §7 Regime 定义 | 同上 | 同上 |
| §12 已知限制 | — | 新增限制：合成指数与主宇宙共享同一生存者偏差（KNOWN LIMITATION，与 §2 一致）；成分含后上市股会缩短合成指数有效历史长度 |

## 未变更（保持不变）

- 研究问题、Universe（当前成分）、样本区间、摩擦模型、三级 Gate 判据、输出契约、Gate 0 令牌（REGIME 阈值本身不变）。
- 契约 §0 令牌逐字保持。

## 影响评估

- Gate 2「跨 ≥2 regime 同号」检验改用合成指数划分 regime，与主篮子同源，逻辑自洽；不再依赖官方指数序列。
- Control 不再独立于成分宇宙，因此**不再具备"无偏差基线"含义**——契约 §2 中"无偏差基线"表述同步删除，替换为"同源基线（用于 regime 划分）"。
- 研究结论结构不受影响。

## 脚本同步

- `quant-lab/h1_universe_structure.py`：
  - `cmd_snapshot()` 移除对官方指数拉取的硬依赖（不再必需 `fetch_index_daily` 成功）。
  - `run_analysis()` 用 `build_synthetic_index()` 构造合成指数供 `regime_series()` 使用。
  - `fetch_index_daily()` 标记为 deprecated（保留但不作为必需数据）。
