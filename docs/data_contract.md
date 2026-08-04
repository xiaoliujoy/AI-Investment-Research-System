# Data Contract —— 核心字段契约（Trading OS 数据语义防线）

> 定位（呼应 2026-08-01 复盘）：`net_amount` 单位误读 bug 的根因是**核心字段未声明单位/语义**。
> 本契约强制：每个核心字段必须声明 `name / type / unit / frequency / source`。
> 它不是新运行时模块，而是一份**治理文档**——未来 `data_quality_check` 可据此做单位一致性校验（本期不建校验器，处于证据积累期）。
>
> 核心纪律（与「诚实 NULL」同源）：**不确定的单位标 `TBD`，绝不臆断填值。**

---

## 规则

```
field:
  name:      字段名
  type:      数据类型（float/int/text/categorical）
  unit:      单位（亿元 / 百分比% / 小数比率 / 家数 / 类别 / …）
  frequency: 频率（daily / 事件）
  source:    来源（表或采集器）
```

每条记录入库前，字段语义必须可被本契约唯一解释；跨表聚合字段（如 `sector_daily.net_amount`）必须与上游（如 `stock_flow_daily.main_net_buy`）单位一致。

---

## 字段契约（核心表）

### stock_daily（个股价格，基础层）
| field | type | unit | frequency | source | 备注 |
|---|---|---|---|---|---|
| code | text | — | daily | 通达信 | 前缀 60/00/30/68=A股；880/15/51 为指数/基金脏行，须剔除 |
| amount | float | **亿元** | daily | 通达信 | ⚠ 7-15~7-20 早期批次单位混乱，7-21 起稳定为亿 |
| change_pct | float | **百分比%**（9.99=+9.99%） | daily | 通达信 | 非小数比率；涨停判定用 ≥9.5 |
| name | text | — | daily | 通达信 | 早期批次可能为空 |

### stock_flow_daily（个股资金流）
| field | type | unit | frequency | source | 备注 |
|---|---|---|---|---|---|
| main_net_buy / super_large_net_buy / large_net_buy / medium_net_buy / small_net_buy | float | **亿元**（带符号） | daily | 东财 push2delay | 真实逐日覆盖 **2026-07-20 起**；此前为复制快照已 NULL |
| source | text | — | daily | push2delay | 复制快照期标记需 NULL，勿沿用 |

### sector_daily（板块序列 + 资金流）
| field | type | unit | frequency | source | 备注 |
|---|---|---|---|---|---|
| net_amount | float | **亿元** | daily | `SUM(stock_flow_daily.main_net_buy)` | ⚠ 曾因误当万元÷10000 显示 0.0亿 bug；与 main_net_buy 同单位 |
| change_pct | float | **百分比%** | daily | 聚合 | 非小数比率 |
| amount | float | **亿元** | daily | 聚合 | 板块成交额 |
| sector_score | float | 分数(0~100) | — | 评分层 | 属评分非数据；当前 NULL |

### market_daily（市场宽度/情绪）
| field | type | unit | frequency | source | 备注 |
|---|---|---|---|---|---|
| total_amount / sh_amount / sz_amount | float | **亿元** | daily | `build_market_daily` 聚合 | sh+sz=total 恒等式 |
| up_count / down_count / flat_count / limit_up_count / limit_down_count | int | **家数** | daily | 聚合 | 客观宽度 |
| amount_change_rate | float | **小数比率**（0.0x） | daily | 滚动计算 | ⚠ 与 change_pct 不同单位，勿混 |
| avg_5d_amount / avg_20d_amount | float | **亿元** | daily | 滚动 | — |

### limit_up_daily（涨停生态）
| field | type | unit | frequency | source | 备注 |
|---|---|---|---|---|---|
| amount | float | **亿元** | daily | 聚合 | — |
| float_cap | float | **亿元**（流通市值） | daily | 聚合 | — |
| turnover_rate | float | **百分比%**（5.22=5.22%） | daily | 聚合 | 非小数比率 |
| change_pct | float | **百分比%** | daily | 聚合 | — |
| board_height | int | **连板天数** | daily | 跨缺口回溯 | — |
| next_day_return | float | **小数比率** | 事件(T+1) | 聚合 | 验证用，非当日观察 |

### regime_history（宏观/商品 regime）
| field | type | unit | frequency | source | 备注 |
|---|---|---|---|---|---|
| risk_state | categorical | 类别(Neutral/Bull/Bear…) | daily | 计算 | — |
| a_share_stage / a_share_emotion | categorical / float | 类别 / 分数 | daily | 计算 | 部分日期为 NULL（诚实缺失） |
| fwd_1d_a_share / fwd_5d_a_share / fwd_20d_a_share | float | **小数比率**（收益率） | daily | 计算 | 验证用，含未来窗口 |

### research_decision_log（决策日志，见 build_decision_log.py）
| field | type | unit | frequency | source | 备注 |
|---|---|---|---|---|---|
| market_score | float | 分数(=a_share_emotion) | daily | regime_history | 可能为 NULL |
| action | categorical | {BUY/SELL/WAIT/NO TRADE} | 事件 | human/auto | — |
| outcome | categorical | {待验证/validated/invalid/insufficient} | 事件 | human | 验证期填 |
| error_type | categorical | {待归因/…} | 事件 | human | 验证期填 |

### trade_execution（Trader OS 实际成交/计划记录，见 backend/trader_log.py）
| field | type | unit | frequency | source | 备注 |
|---|---|---|---|---|---|
| market_type | categorical | {ASHARE/MT5} | 事件 | 手动录入 | 双市场独立计数，不可合并 |
| symbol | text | — | 事件 | 手动录入 | A股代码或 MT5 symbol；可选 |
| direction | categorical | {BUY/SELL} | 事件 | 手动录入 | — |
| exec_status | categorical | {executed/skipped/missed} | 事件 | 手动录入 | v0.1 主用 executed/skipped |
| planned | int(0/1) | 布尔 | 事件 | 手动录入 | 1=计划内；驱动 Execution Fidelity |
| exit_planned | int(0/1/NULL) | 布尔(可空) | 事件 | 手动录入 | 1=按计划退出；驱动 Holding Discipline；可选 |
| decision_state | categorical | {normal/hesitant/urgent/revenge/fomo} | 事件 | 手动录入 | §4 最低优先级，可空 |
| reason | text | — | 事件 | 手动录入 | 一句理由，可空 |
| content_hash | text | — | 事件 | 计算 | 防篡改，预留 |

### decision_snapshot（Trader OS 事前信息封存，防后视偏差，见 §2.1）
| field | type | unit | frequency | source | 备注 |
|---|---|---|---|---|---|
| market_type | categorical | {ASHARE/MT5} | 事件 | 手动/自动 | — |
| regime_state / regime_score | categorical / float | 类别/分数 | 事件 | regime_history | ASHARE 填充；MT5 暂 NULL |
| risk_budget_equity | float | 比率 | 事件 | cio_decision_history | ASHARE 填充 |
| reasoning_text | text | — | 事件 | 人填 | 当时判断理由 |
| confidence | int | 1~5 | 事件 | 人填 | — |
| content_hash | text | — | 事件 | 计算 | 防篡改 |

---

## 已知语义陷阱（已发生，写入契约防复发）

1. **单位误读**：`net_amount` 实为亿元，曾被当万元 ÷10000 → 显示 0.0亿。跨表聚合字段必须与上游同单位。
2. **百分比 vs 小数比率**：`change_pct`/`turnover_rate` 是百分比(9.99)，`amount_change_rate`/`next_day_return`/`fwd_*` 是小数比率(0.0x)。两者差 100 倍，混用即错。
3. **早期单位混乱**：`stock_daily.amount` 7-15~7-20 批次单位不稳，聚合须用金额区间兜底。
4. **复制快照伪数据**：`stock_flow_daily` 07-01~07-17 为单日快照逐股复制，非真实历史，已 NULL。任何"看似完整"的序列须先验证跨日独立性。
5. **诚实 NULL**：缺失/污染字段一律 NULL，不填充、不估算，避免伪精确污染统计。

---

## 配套机读文件
`backend/data_contract.json`（同结构，供未来校验器消费）。新增核心字段时，**先在此契约登记，再写代码**。
