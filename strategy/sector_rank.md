# 板块热度评分模型

## 一、概述

板块优先于个股。选股先选板块。

**核心思想**：资金持续流入哪个板块，哪个板块才有利可图。单日涨幅可能是套路，资金持续性才是主线。

输出：板块热度评分（0-100）+ 板块梯队排名。

---

## 二、板块评分模型

### 2.1 综合评分公式

```
板块热度分 = 
    成交额占比(25%) + 
    成交额增速(20%) + 
    涨停数量(15%) + 
    涨幅(10%) + 
    持续性(15%) + 
    龙头强度(15%)
```

### 2.2 权重调整逻辑

| 指标 | 权重 | 理由 |
|------|------|------|
| **成交额占比** | 25% | 资金是板块活跃度的最直接体现 |
| **成交额增速** | 20% | 增速反映资金加速进场/离场，比绝对量更敏感 |
| **涨停数量** | 15% | 代表板块情绪高潮程度 |
| **涨幅** | 10% | 降低权重——涨幅可能是"最后一冲"，不是参与信号 |
| **持续性** | 15% | 主线靠资金持续，不靠一天爆发 |
| **龙头强度** | 15% | 龙头是板块的锚，龙头强则板块强 |

**为什么这样设计？**

> A股最容易出现："涨幅第一，但资金已经高潮"。
> 某板块当天涨8%、涨停20家，但成交额已天量 → 第二天容易接盘。
> 核心原则：**主线靠资金持续，不靠一天涨幅**。

### 2.3 评分范围

| 分数段 | 含义 | 操作建议 |
|--------|------|----------|
| 80-100 | 绝对主线 | 重仓参与 |
| 60-80 | 强势板块 | 积极介入 |
| 40-60 | 轮动板块 | 轻仓试错 |
| 20-40 | 弱势板块 | 观望 |
| 0-20 | 冷门板块 | 回避 |

---

## 三、因子计算

### 3.1 成交额占比因子 (0-100) — 权重 25%

```python
def amount_concentration_factor(sector_amount, total_amount):
    """
    核心逻辑：板块成交额占全市场比例。
    主线板块通常占比 > 5%。
    """
    concentration = sector_amount / max(total_amount, 1)
    
    if concentration > 0.10:       score = 100
    elif concentration > 0.08:     score = 90
    elif concentration > 0.06:     score = 80
    elif concentration > 0.05:     score = 70
    elif concentration > 0.04:     score = 60
    elif concentration > 0.03:     score = 50
    elif concentration > 0.02:     score = 40
    elif concentration > 0.01:     score = 25
    else:                          score = 10
    
    return score
```

### 3.2 成交额增速因子 (0-100) — 权重 20%

```python
def amount_momentum_factor(amount_change_rate_3d):
    """
    核心逻辑：近3日成交额复合增速。
    反映资金加速进场还是离场。
    
    amount_change_rate_3d: 近3日成交额变化率（对比前3日均值）
    """
    if amount_change_rate_3d > 1.0:     score = 100  # 翻倍
    elif amount_change_rate_3d > 0.6:   score = 90
    elif amount_change_rate_3d > 0.3:   score = 80
    elif amount_change_rate_3d > 0.15:  score = 70
    elif amount_change_rate_3d > 0:     score = 60
    elif amount_change_rate_3d > -0.15: score = 40
    elif amount_change_rate_3d > -0.3:  score = 20
    else:                              score = 10
    
    return score
```

### 3.3 涨停数量因子 (0-100) — 权重 15%

```python
def limitup_factor(zt_count, cm20_count, zt_firms_ratio):
    """
    核心逻辑：涨停数量代表板块情绪高潮程度。
    """
    # 涨停数量 (0-50分)
    if zt_count >= 15:      score_z = 50
    elif zt_count >= 10:    score_z = 45
    elif zt_count >= 6:     score_z = 35
    elif zt_count >= 3:     score_z = 25
    elif zt_count >= 1:     score_z = 15
    else:                   score_z = 0
    
    # 涨停家数占板块比例 (0-30分)
    if zt_firms_ratio > 0.10:    score_f = 30
    elif zt_firms_ratio > 0.07:   score_f = 25
    elif zt_firms_ratio > 0.05:   score_f = 20
    elif zt_firms_ratio > 0.03:   score_f = 15
    else:                        score_f = 5
    
    # 20cm股票数量（创业板科创板） (0-20分)
    if cm20_count >= 5:     score_20 = 20
    elif cm20_count >= 3:   score_20 = 15
    elif cm20_count >= 1:   score_20 = 10
    else:                   score_20 = 0
    
    return score_z + score_f + score_20
```

### 3.4 涨幅因子 (0-100) — 权重 10%（降低）

```python
def gain_factor(sector_pct, weighted_pct):
    """
    核心逻辑：涨幅反映市场认可度。
    权重降低：单日涨幅可能是"最后一冲"信号，不是参与信号。
    """
    # 板块涨幅 (0-50分) — 阈值提高，涨幅权重大幅降低
    if sector_pct > 7:      score_g = 50
    elif sector_pct > 5:    score_g = 40
    elif sector_pct > 3:    score_g = 30
    elif sector_pct > 2:    score_g = 20
    elif sector_pct > 0:    score_g = 15
    else:                   score_g = 5
    
    # 加权涨幅（大市值权重） (0-50分)
    if weighted_pct > 7:    score_w = 50
    elif weighted_pct > 5:  score_w = 40
    elif weighted_pct > 3:  score_w = 30
    elif weighted_pct > 2:  score_w = 20
    elif weighted_pct > 0:  score_w = 15
    else:                   score_w = 5
    
    return score_g + score_w
```

### 3.5 持续性因子 (0-100) — 权重 15%

```python
def duration_factor(days_in_top10, consecutive_days, rank_stability):
    """
    核心逻辑：持续性比单日爆发更重要。
    - days_in_top10: 近5日进入前10的次数
    - consecutive_days: 连续上榜天数
    - rank_stability: 排名稳定性（标准差倒数）
    """
    # 上榜频率 (0-40分)
    if days_in_top10 >= 5:      score_freq = 40
    elif days_in_top10 >= 4:    score_freq = 35
    elif days_in_top10 >= 3:    score_freq = 25
    elif days_in_top10 >= 2:    score_freq = 15
    elif days_in_top10 >= 1:    score_freq = 10
    else:                       score_freq = 0
    
    # 连续上榜 (0-40分)
    if consecutive_days >= 5:   score_con = 40
    elif consecutive_days >= 3:  score_con = 30
    elif consecutive_days >= 2:  score_con = 20
    elif consecutive_days >= 1:  score_con = 10
    else:                       score_con = 0
    
    # 排名稳定性 (0-20分)
    score_stab = min(rank_stability * 20, 20)
    
    return score_freq + score_con + score_stab
```

### 3.6 龙头强度因子 (0-100) — 权重 15%

```python
def leader_strength_factor(leader_pct, leader_turnover, leader_board, leader_rps):
    """
    核心逻辑：龙头是板块的锚。龙头强则板块强。
    增加 RPS 相对强度作为龙头质量的判断标准。
    """
    # 龙头涨幅 (0-25分)
    if leader_pct > 10:     score_g = 25
    elif leader_pct > 7:    score_g = 22
    elif leader_pct > 5:    score_g = 18
    elif leader_pct > 3:    score_g = 12
    elif leader_pct > 0:    score_g = 8
    else:                   score_g = 0
    
    # 龙头成交额（资金关注度） (0-25分)
    if leader_turnover > 1e10:    score_t = 25
    elif leader_turnover > 5e9:   score_t = 22
    elif leader_turnover > 3e9:   score_t = 18
    elif leader_turnover > 1e9:   score_t = 12
    else:                         score_t = 5
    
    # 龙头连板高度 (0-25分)
    if leader_board >= 5:    score_b = 25
    elif leader_board >= 3:  score_b = 22
    elif leader_board >= 2:  score_b = 15
    elif leader_board >= 1:  score_b = 10
    else:                   score_b = 0
    
    # 龙头 RPS 相对强度 (0-25分) — 新增
    if leader_rps > 80:     score_rps = 25
    elif leader_rps > 60:   score_rps = 20
    elif leader_rps > 40:   score_rps = 15
    elif leader_rps > 20:   score_rps = 10
    else:                   score_rps = 5
    
    return score_g + score_t + score_b + score_rps
```

---

## 四、板块梯队

### 4.1 梯队定义

| 梯队 | 条件 | 含义 |
|------|------|------|
| **T0 绝对主线** | 评分>80 + 持续3日+ | 全市场唯一核心 |
| **T1 强主线** | 评分70-80 + 持续2日+ | 明确主线，积极参与 |
| **T2 次主线** | 评分60-70 | 轮动方向，适度参与 |
| **T3 轮动** | 评分40-60 | 快进快出 |
| **T4 冷门** | 评分<40 | 回避 |

### 4.2 主线确认条件

```
主线确认 = 
    板块评分 > 70 AND
    板块成交额占全市场 > 5% AND
    连续2日进入前5 AND
    有高度龙头（连板≥3 OR RPS > 60）
```

---

## 五、数据采集

### 5.1 已有数据

| 数据 | 来源 | 状态 |
|------|------|------|
| 板块涨幅 | `/api/market/overview` → sectors | ✅ 已有 |
| 板块成交额 | `/api/market/overview` → sectors | ✅ 已有 |
| 板块净流入 | `/api/market/overview` → sectors | ✅ 已有 |
| 涨停股票 | `/api/market/overview` | ⚠️ 需拆解 |

### 5.2 需新增数据

| 数据 | 说明 | 优先级 |
|------|------|--------|
| 板块涨停数 | 板块内涨停股票数量 | P0 |
| 板块20cm数 | 创业板科创板涨停数 | P1 |
| 板块内个股明细 | 每只股票的涨跌情况 | P0 |
| 板块持续天数 | 连续进入前10的天数 | P1 |
| 龙头数据 | 板块龙头实时数据 | P0 |
| **板块成交额增速** | 近3日复合增速 | **P0** |
| **龙头 RPS** | 20日/60日相对强度 | **P1** |

---

## 六、实现建议

### 6.1 新增接口

```
GET /api/sector/rank         # 板块热度排名
GET /api/sector/detail       # 板块详情（含个股）
GET /api/sector/history      # 板块历史评分
```

### 6.2 数据持久化

建议新增 `strategy_sector_score` 表：
- 日期、板块名称、综合评分、梯队
- 各因子得分
- 龙头信息
