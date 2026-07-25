# 市场情绪周期判断模型

## 一、概述

市场情绪周期是交易框架的第一道过滤器。

**核心思想**：不要预测市场，只识别当前所处阶段，并据此调整仓位和策略。

输出：市场当前所处的 **阶段标签** + **情绪评分**。

---

## 二、市场阶段定义

| 阶段 | 核心特征 | 仓位建议 | 策略方向 |
|------|----------|----------|----------|
| **启动期** | 冰点修复，资金试探性进场 | 3-5成 | 试仓龙头，观察持续性 |
| **发酵期** | 主线浮现，板块效应显现 | 5-7成 | 加仓龙头，持有主线 |
| **加速期** | 增量资金入场，全面上涨 | 7-9成 | 重仓龙头，享受主升 |
| **高潮期** | 全民狂欢，补涨蔓延 | 5-7成 | 开始减仓，保留核心 |
| **分歧期** | 龙头断板，中位股杀跌 | 3-5成 | 清仓跟风，仅留龙头 |
| **修复期** | 杀跌后企稳，资金回流 | 3-5成 | 观察新方向，轻仓试错 |
| **退潮期** | 跌停漫延，高度压缩 | 0-2成 | 空仓等待，防守为主 |

---

## 三、数据采集

### 3.1 每日盘后数据

```python
# 来自 backend/api 已有接口
daily_metrics = {
    # 全市场情绪 (api/market/overview)
    "up_count": 1926,          # 上涨家数
    "down_count": 3171,         # 下跌家数
    "flat_count": 97,           # 平盘家数
    "limit_up": 68,             # 涨停数（含一字）
    "limit_up_real": 62,        # 真实涨停（非一字）
    "limit_down": 14,           # 跌停数（含一字）
    "limit_down_real": 11,      # 真实跌停
    "active_ratio": 0.3702,     # 活跃度
    
    # 短线情绪 (api/market/emotion)
    "zt_count": 69,             # 涨停
    "dt_count": 12,             # 跌停
    "max_boards": 8,            # 最高连板
    "lianban_count": 6,         # 连板股数量（2板+）
    "seal_rate": 0.68,          # 封板率
    "break_rate": 0.32,         # 炸板率
    "promotion_rate": 0.45,     # 晋级率
    
    # 成交额 (需新增采集)
    "total_amount": 2.8e12,     # 两市成交额（元）
    "amount_change_rate": 0.15, # 成交额变化率（vs前日）
    
    # 昨日涨停股今日表现（需新增采集）
    "yesterday_zt_avg_pct": 2.3,  # 昨日涨停股今日平均涨幅
    "yesterday_zt_win_rate": 0.65, # 昨日涨停股今日上涨比例
}
```

### 3.2 衍生指标计算

```python
# 1. 涨跌比 (Advance-Decline Ratio)
ad_ratio = up_count / down_count  # >1 偏多，<1 偏空

# 2. 涨停占比
zt_ratio = limit_up / total_stocks  # 全市场涨停比例

# 3. 真实涨停真实跌停比
zt_dt_ratio = limit_up_real / max(limit_down_real, 1)

# 4. 情绪得分 (Composite Sentiment Score)
emotion_score = (
    ad_ratio * 15 +
    zt_ratio * 200 +
    seal_rate * 20 -
    break_rate * 15 +
    promotion_rate * 15 +
    max_boards * 3 +
    lianban_count * 2 +
    yesterday_zt_avg_pct * 3
)

# 5. 成交额动量
amount_momentum = amount_change_rate  # 放大或缩小
```

---

## 四、阶段判断逻辑

### 4.1 综合评分模型

```
市场情绪分 = 
    成交额因子(25%) + 
    赚钱效应因子(30%) + 
    连板高度因子(20%) + 
    资金活跃度因子(15%) + 
    昨日涨停表现因子(10%)
```

### 4.2 各因子计算

#### 成交额因子 (0-100)

```python
def amount_factor(total_amount, change_rate):
    score = 0
    # 绝对量评分
    if total_amount > 3e12:     # 3万亿+
        score += 60
    elif total_amount > 2e12:   # 2-3万亿
        score += 45
    elif total_amount > 1.5e12: # 1.5-2万亿
        score += 30
    elif total_amount > 1e12:   # 1-1.5万亿
        score += 15
    else:                       # <1万亿
        score += 5
    
    # 变化率评分
    if change_rate > 0.3:       # 放量30%+
        score += 40
    elif change_rate > 0.15:
        score += 30
    elif change_rate > 0:
        score += 20
    elif change_rate > -0.15:
        score += 10
    else:
        score += 0
    
    return min(score, 100)
```

#### 赚钱效应因子 (0-100)

```python
def profit_factor(up, down, zt, dt, seal_rate):
    ad_ratio = up / max(down, 1)
    zt_dt_ratio = zt / max(dt, 1)
    
    score = 0
    # 涨跌比评分
    if ad_ratio > 2.0:      score += 30
    elif ad_ratio > 1.5:    score += 25
    elif ad_ratio > 1.0:    score += 15
    elif ad_ratio > 0.7:    score += 10
    else:                   score += 5
    
    # 涨停跌停比评分
    if zt_dt_ratio > 5:     score += 30
    elif zt_dt_ratio > 3:   score += 25
    elif zt_dt_ratio > 2:   score += 15
    elif zt_dt_ratio > 1:   score += 10
    else:                   score += 5
    
    # 封板率评分
    score += seal_rate * 40  # 最高40分
    
    return min(score, 100)
```

#### 连板高度因子 (0-100)

```python
def height_factor(max_boards, lianban_count, promotion_rate):
    score = 0
    # 最高连板评分
    if max_boards >= 8:         score += 40
    elif max_boards >= 6:       score += 35
    elif max_boards >= 4:       score += 25
    elif max_boards >= 3:       score += 15
    elif max_boards >= 2:       score += 10
    else:                       score += 5
    
    # 连板数量评分
    if lianban_count >= 15:      score += 30
    elif lianban_count >= 10:    score += 25
    elif lianban_count >= 6:     score += 20
    elif lianban_count >= 3:     score += 15
    else:                       score += 5
    
    # 晋级率评分
    score += promotion_rate * 30
    
    return min(score, 100)
```

#### 资金活跃度因子 (0-100)

```python
def activity_factor(active_ratio, turnover_concentration):
    score = 0
    # 活跃度评分
    if active_ratio > 0.6:      score += 50
    elif active_ratio > 0.45:   score += 40
    elif active_ratio > 0.3:    score += 30
    elif active_ratio > 0.2:    score += 20
    else:                       score += 10
    
    # 资金集中度（成交额前20占全市场比例）
    if turnover_concentration > 0.25:  score += 50
    elif turnover_concentration > 0.20: score += 40
    elif turnover_concentration > 0.15: score += 30
    elif turnover_concentration > 0.10: score += 20
    else:                             score += 10
    
    return min(score, 100)
```

#### 昨日涨停表现因子 (0-100)

```python
def continuation_factor(avg_pct, win_rate):
    score = 0
    # 平均涨幅评分
    if avg_pct > 5:     score += 50
    elif avg_pct > 3:   score += 40
    elif avg_pct > 1:   score += 30
    elif avg_pct > 0:   score += 20
    elif avg_pct > -2:  score += 10
    else:               score += 0
    
    # 上涨比例评分
    if win_rate > 0.7:  score += 50
    elif win_rate > 0.6: score += 40
    elif win_rate > 0.5: score += 30
    elif win_rate > 0.4: score += 20
    else:               score += 10
    
    return min(score, 100)
```

---

## 五、阶段判定阈值

### 5.1 综合评分计算

```python
market_score = (
    amount_factor * 0.25 +
    profit_factor * 0.30 +
    height_factor * 0.20 +
    activity_factor * 0.15 +
    continuation_factor * 0.10
)
```

### 5.2 阶段判定规则

| 阶段 | 综合分 | 核心条件 | 辅助条件 |
|------|--------|----------|----------|
| **启动期** | 20-35 | 成交额<1.5万亿，涨跌比<1 | 连板高度≤3，炸板率>40% |
| **发酵期** | 35-50 | 成交额1.5-2万亿，涨跌比1-1.5 | 连板高度3-4，主线板块出现 |
| **加速期** | 50-70 | 成交额>2万亿，涨跌比>1.5 | 连板高度5-7，涨停>50家 |
| **高潮期** | 70-85 | 成交额>2.5万亿，涨跌比>2 | 连板高度≥8，涨停>80家 |
| **分歧期** | 50-65 | 龙头断板或高度下降 | 炸板率突增，跌停>20家 |
| **修复期** | 35-50 | 杀跌后企稳 | 跌停减少，龙头止跌 |
| **退潮期** | <35 | 成交额萎缩，涨跌比<0.7 | 连板高度≤2，跌停>30家 |

### 5.3 阶段转换信号

```
启动期 → 发酵期：成交额连续2日放大，涨停数>40
发酵期 → 加速期：主线板块明确，龙头确立，涨停>50
加速期 → 高潮期：涨停>80，连板高度≥8，补涨蔓延
高潮期 → 分歧期：龙头首次断板，炸板率>40%
分歧期 → 修复期：跌停<15家，龙头止跌
分歧期 → 退潮期：跌停>30家，连板高度降至≤2
修复期 → 启动期：新方向出现，资金重新进场
退潮期 → 启动期：冰点出现，成交额极度萎缩后企稳
```

---

## 六、数据依赖关系

| 数据 | 来源接口 | 状态 |
|------|----------|------|
| 涨跌家数、涨停跌停 | `/api/market/overview` | ✅ 已有 |
| 连板高度、封板率、晋级率 | `/api/market/emotion` | ✅ 已有 |
| 两市成交额 | 需新增 | ❌ 待开发 |
| 成交额变化率 | 需新增 | ❌ 待开发 |
| 昨日涨停股今日表现 | 需新增 | ❌ 待开发 |
| 资金集中度 | 需新增 | ❌ 待开发 |

---

## 七、实现建议

### 7.1 新增接口

```
GET /api/market/amount        # 两市成交额 + 变化率
GET /api/market/continuation  # 昨日涨停股今日表现
GET /api/market/concentration # 资金集中度
```

### 7.2 实现优先级

1. **P0**：市场情绪评分 + 阶段判断（基于现有数据）
2. **P1**：成交额数据 + 变化率
3. **P2**：昨日涨停股今日表现
4. **P3**：资金集中度 + 板块集中度

### 7.3 数据持久化

建议新增 `strategy_market_cycle` 表，每日盘后记录：
- 日期、综合评分、阶段标签
- 各因子得分
- 关键指标快照
