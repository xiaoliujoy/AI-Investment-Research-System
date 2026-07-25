# 风险控制体系

## 一、概述

风控不是限制收益，而是**保护本金**。

**核心思想**：活着比赚钱重要。大赚后不系统回撤才是高手。

输出：仓位建议 + 止损信号 + 风险等级。

---

## 二、仓位管理

### 2.1 总仓位规则

**核心原则**：市场决定仓位，不靠感觉。

```python
def position_size(market_score, sector_score, leader_score):
    """
    三层过滤确定仓位
    """
    # 市场分决定基础仓位
    if market_score > 70:       base = 0.8
    elif market_score > 55:     base = 0.6
    elif market_score > 40:     base = 0.4
    elif market_score > 25:     base = 0.2
    else:                       base = 0.0
    
    # 板块分调整
    if sector_score > 80:       sector_mult = 1.0
    elif sector_score > 70:     sector_mult = 0.9
    elif sector_score > 60:     sector_mult = 0.7
    elif sector_score > 50:     sector_mult = 0.5
    else:                       sector_mult = 0.3
    
    # 龙头分调整
    if leader_score > 85:       leader_mult = 1.0
    elif leader_score > 70:     leader_mult = 0.9
    elif leader_score > 60:     leader_mult = 0.7
    elif leader_score > 50:     leader_mult = 0.5
    else:                       leader_mult = 0.3
    
    return min(base * sector_mult * leader_mult, 0.9)
```

### 2.2 仓位梯度表

| 市场阶段 | 建议仓位 | 说明 |
|----------|----------|------|
| 高潮期 | 70-90% | 赚钱效应最强，全力进攻 |
| 加速期 | 60-80% | 主线明确，重仓龙头 |
| 发酵期 | 40-60% | 方向渐明，稳步推进 |
| 启动期 | 20-40% | 试探性参与 |
| 分歧期 | 20-40% | 仅保留核心 |
| 修复期 | 10-30% | 轻仓试错 |
| 退潮期 | 0-20% | 防守为主 |

### 2.3 分仓策略

```
总仓位分配：
- 龙头（空间/核心）：50-60% 仓位
- 次龙（确认卡位）：20-30% 仓位
- 观察仓（试错新方向）：10-20% 仓位
```

```
多主线并行时：
- 主线 1 龙头：40-50% 仓位
- 主线 2 龙头：20-30% 仓位
- 观察仓：10-20% 仓位
```

---

## 三、止损体系

### 3.1 止损层级

| 层级 | 触发条件 | 操作 |
|------|----------|------|
| **个股止损** | 亏损达买入价 -7% | 无条件止损 |
| **板块止损** | 板块龙头跌停或板块跌 -5% | 清仓该板块 |
| **市场止损** | 市场情绪分骤降 20+ | 减至3成以下 |
| **系统性止损** | 持仓总亏损达 -10% | 全部清仓 |

### 3.2 个股止损细则

```python
def check_stop_loss(buy_price, current_price, hold_days, is_leader):
    """
    动态止损逻辑
    """
    loss_pct = (current_price - buy_price) / buy_price
    
    # 基础止损线
    if is_leader:
        stop_line = -0.08  # 龙头止损线稍宽
    else:
        stop_line = -0.05  # 非龙头更紧
    
    # 时间衰减：持有时间越长，止损线越紧
    if hold_days > 5:
        stop_line *= 0.8  # 收紧到 -6.4% / -4%
    elif hold_days > 10:
        stop_line *= 0.6  # 收紧到 -4.8% / -3%
    
    # 盈利保护：有盈利时，止损线上移
    if loss_pct > 0.10:     # 盈利>10%
        stop_line = -0.03   # 止损线移到 -3%
    elif loss_pct > 0.05:   # 盈利>5%
        stop_line = -0.05   # 止损线移到 -5%
    
    return loss_pct <= stop_line
```

### 3.3 止盈策略

```
止盈不是卖到最高点，而是让利润奔跑的同时保护本金。

策略：
1. 不主动止盈，让利润奔跑
2. 当出现以下信号时止盈：
   - 放量滞涨（量增价不增）
   - 龙头首次断板
   - 板块出现批量跌停
   - 市场情绪进入退潮期
3. 分批止盈：
   - 50% 仓位按信号止盈
   - 50% 仓位让利润奔跑
```

---

## 四、市场退潮处理

### 4.1 退潮识别

```python
def is_market_declining(daily_data):
    """
    市场退潮判断
    """
    signals = 0
    
    # 1. 连板高度下降
    if daily_data["max_boards"] <= 2:
        signals += 3
    
    # 2. 跌停数量增加
    if daily_data["dt_count"] > 30:
        signals += 3
    elif daily_data["dt_count"] > 20:
        signals += 2
    
    # 3. 炸板率上升
    if daily_data["break_rate"] > 0.5:
        signals += 2
    
    # 4. 昨日涨停股表现差
    if daily_data["yesterday_zt_avg_pct"] < -2:
        signals += 3
    
    # 5. 成交额萎缩
    if daily_data["amount_change_rate"] < -0.2:
        signals += 2
    
    return signals >= 5  # 5分以上判定退潮
```

### 4.2 退潮应对

```
退潮第1天：
- 减仓至3成以下
- 清仓跟风股
- 仅保留绝对龙头

退潮第2天：
- 再减仓至1-2成
- 龙头断板即清

退潮第3天：
- 空仓观望
- 等待新方向
```

---

## 五、龙头失败处理

### 5.1 龙头失败信号

```python
def is_leader_failing(leader_data, sector_data):
    """
    龙头失败判断
    """
    # 1. 龙头跌停
    if leader_data["pct"] < -9.5:
        return True
    
    # 2. 龙头断板+放天量
    if leader_data["is_board_break"] and leader_data["volume_ratio"] > 3:
        return True
    
    # 3. 龙头被卡位（板块内另一只涨幅远超）
    if sector_data["max_leader_pct"] - leader_data["pct"] > 5:
        return True
    
    # 4. 龙头连续2日跑输板块
    if leader_data["under_sector_days"] >= 2:
        return True
    
    return False
```

### 5.2 龙头失败应对

```
龙头失败时：
1. 立即清仓该龙头
2. 观察是否有卡位龙头出现
3. 如果有卡位，轻仓试仓新龙头
4. 如果没有卡位，清仓该板块
5. 市场可能进入退潮，整体减仓
```

---

## 六、高位风险判断

### 6.1 高位信号

```python
def high_risk_signals(stock_data, market_data):
    """
    高位风险判断
    """
    risk_score = 0
    
    # 1. 连板高度
    if stock_data["board_height"] >= 6:
        risk_score += 30
    elif stock_data["board_height"] >= 4:
        risk_score += 20
    
    # 2. 换手率
    if stock_data["turnover"] > 0.30:
        risk_score += 25
    elif stock_data["turnover"] > 0.20:
        risk_score += 15
    
    # 3. 量比
    if stock_data["volume_ratio"] > 5:
        risk_score += 20
    elif stock_data["volume_ratio"] > 3:
        risk_score += 10
    
    # 4. 偏离度（相对5日线）
    if stock_data["deviation"] > 0.20:
        risk_score += 15
    elif stock_data["deviation"] > 0.15:
        risk_score += 10
    
    # 5. 市场情绪
    if market_data["emotion"] == "高潮期":
        risk_score += 10
    
    return risk_score
```

### 6.2 风险等级

| 风险分 | 等级 | 操作 |
|--------|------|------|
| 0-20 | 低风险 | 正常操作 |
| 20-40 | 中风险 | 控制仓位 |
| 40-60 | 高风险 | 减仓 |
| 60-80 | 极高风险 | 清仓 |
| 80-100 | 危险 | 空仓 |

---

## 七、数据依赖关系

| 数据 | 来源 | 状态 |
|------|------|------|
| 持仓数据 | 需自建 | ❌ 待开发 |
| 个股止损 | 需自建 | ❌ 待开发 |
| 连板高度 | `/api/market/emotion` | ✅ 已有 |
| 跌停数量 | `/api/market/emotion` | ✅ 已有 |
| 炸板率 | `/api/market/emotion` | ✅ 已有 |
| 成交额变化 | 需新增 | ❌ 待开发 |

---

## 八、实现建议

### 8.1 新增接口

```
GET /api/risk/position    # 仓位建议
GET /api/risk/stop-loss   # 止损检查
GET /api/risk/market      # 市场风险等级
```

### 8.2 数据持久化

建议新增 `strategy_risk_log` 表：
- 日期、风险等级、仓位建议
- 止损记录、止盈记录
- 回撤记录
