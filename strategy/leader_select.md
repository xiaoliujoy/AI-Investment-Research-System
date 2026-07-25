# 龙头筛选模型

## 一、概述

龙头不是涨幅最高的股票，而是**资金认可度最高**的股票。

**核心思想**：龙头 = 资金共识 + 情绪锚点 + 抗跌性 + 趋势强度。选对龙头，成功80%。

输出：龙头评分（0-100）+ 龙头类型标签 + 参与建议。

---

## 二、龙头定义

### 2.1 龙头类型

| 类型 | 定义 | 特征 |
|------|------|------|
| **空间龙头** | 连板高度最高 | 打开空间，带动板块 |
| **核心龙头** | 成交额+涨幅综合最强 | 资金最认可，最安全 |
| **趋势龙头** | 走趋势不连板，RPS 持续高位 | 机构偏好，走得更远 |
| **补涨龙头** | 龙头滞涨后卡位 | 高度通常有限 |

### 2.2 龙头 vs 跟风

| 维度 | 龙头 | 跟风 |
|------|------|------|
| 涨幅 | 不一定最高 | 可能更高 |
| 成交额 | 板块内领先 | 较小 |
| 启动时间 | 最早或次早 | 晚 |
| 抗跌性 | 板块跌时抗跌 | 先跌 |
| 溢价 | 次日有高溢价 | 低溢价或无 |
| 资金态度 | 主力锁仓 | 游资快进快出 |
| RPS | 持续 > 60 | 通常 < 40 |

---

## 三、龙头基础过滤条件（必须满足）

**在进入评分之前，必须同时满足以下所有条件。不满足的直接淘汰，不参与评分。**

| 序号 | 条件 | 阈值 | 理由 |
|------|------|------|------|
| 1 | **日成交额** | > 10 亿 | 过滤小市值情绪龙，确保资金参与度 |
| 2 | **换手率** | > 5% | 确保活跃度，过滤庄股 |
| 3 | **所属板块评分** | > 70 | 龙头必须来自强势板块 |
| 4 | **市场辨识度排名** | 板块内前 3 | 必须是资金最关注的标的 |

**为什么需要过滤？**

> 没有过滤的评分容易选出"空间龙"——小市值连续5板但成交额只有5亿。
> 这种可能是情绪龙，不一定是资金龙，参与风险极高。
> 过滤后只评分"资金真正认可"的标的。

```python
def leader_basic_filter(stock_data, sector_score):
    """
    龙头基础过滤条件。
    返回 True 表示通过过滤，可以进入评分。
    """
    # 1. 日成交额 > 10亿
    if stock_data["amount"] < 1e9:
        return False
    
    # 2. 换手率 > 5%
    if stock_data["turnover_rate"] < 0.05:
        return False
    
    # 3. 所属板块评分 > 70
    if sector_score < 70:
        return False
    
    # 4. 板块内成交额排名前3
    if stock_data["amount_rank_in_sector"] > 3:
        return False
    
    return True
```

---

## 四、龙头评分模型

### 4.1 综合评分公式

```
龙头评分 = 
    资金因子(25%) + 
    空间因子(20%) + 
    强度因子(15%) + 
    质量因子(15%) + 
    RPS因子(15%) + 
    共识因子(10%)
```

### 4.2 权重调整逻辑

| 指标 | 权重 | 理由 |
|------|------|------|
| **资金因子** | 25% | 资金是龙头的根基 |
| **空间因子** | 20% | 空间代表潜在收益 |
| **强度因子** | 15% | 反映多空博弈结果 |
| **质量因子** | 15% | 决定安全边际 |
| **RPS因子** | 15% | **新增**：趋势强度，识别真正大牛股 |
| **共识因子** | 10% | 共识决定持续性 |

### 4.3 评分范围

| 分数段 | 含义 | 策略 |
|--------|------|------|
| 85-100 | 绝对龙头 | 重仓 |
| 70-85 | 核心龙头 | 积极参与 |
| 55-70 | 次龙/卡位 | 轻仓 |
| 40-55 | 跟风 | 观望 |
| <40 | 杂毛 | 回避 |

---

## 五、因子计算

### 5.1 资金因子 (0-100) — 权重 25%

```python
def capital_factor(stock_amount, sector_amount, amount_rank):
    """
    核心逻辑：资金是龙头的根基。
    已通过基础过滤（>10亿），这里进一步区分质量。
    """
    # 成交额占板块比例 (0-40分)
    amount_ratio = stock_amount / max(sector_amount, 1)
    if amount_ratio > 0.15:     score_r = 40
    elif amount_ratio > 0.10:   score_r = 35
    elif amount_ratio > 0.07:   score_r = 25
    elif amount_ratio > 0.05:   score_r = 15
    elif amount_ratio > 0.03:   score_r = 10
    else:                       score_r = 5
    
    # 全市场成交额排名 (0-30分)
    if amount_rank <= 10:       score_rank = 30
    elif amount_rank <= 30:     score_rank = 25
    elif amount_rank <= 50:     score_rank = 20
    elif amount_rank <= 100:    score_rank = 15
    elif amount_rank <= 200:    score_rank = 10
    else:                       score_rank = 5
    
    # 大单净流入 (0-30分)
    big_net = get_big_order_net(stock_code)
    if big_net > 1e8:           score_big = 30
    elif big_net > 5e7:         score_big = 25
    elif big_net > 2e7:         score_big = 20
    elif big_net > 0:           score_big = 15
    else:                       score_big = 5
    
    return score_r + score_rank + score_big
```

### 5.2 空间因子 (0-100) — 权重 20%

```python
def space_factor(board_height, is_first_board, open_height):
    """
    核心逻辑：空间代表潜在收益。
    """
    # 连板高度 (0-50分)
    if board_height >= 6:       score_h = 50
    elif board_height >= 4:     score_h = 45
    elif board_height >= 3:     score_h = 35
    elif board_height >= 2:     score_h = 25
    elif board_height >= 1:     score_h = 15
    else:                       score_h = 5
    
    # 是否首板（首板更有价值） (0-25分)
    if is_first_board:          score_f = 25
    else:                       score_f = 0
    
    # 是否打开高度（打破之前压制） (0-25分)
    if open_height:             score_o = 25
    else:                       score_o = 10
    
    return score_h + score_f + score_o
```

### 5.3 强度因子 (0-100) — 权重 15%

```python
def strength_factor(pct, percentile, relative_strength):
    """
    核心逻辑：强度反映多空博弈结果。
    """
    # 涨幅 (0-30分)
    if pct > 10:                score_p = 30
    elif pct > 7:               score_p = 25
    elif pct > 5:               score_p = 20
    elif pct > 3:               score_p = 15
    elif pct > 0:               score_p = 10
    else:                       score_p = 0
    
    # 涨幅在板块内排名百分位 (0-40分)
    if percentile > 0.95:       score_per = 40
    elif percentile > 0.90:     score_per = 35
    elif percentile > 0.80:     score_per = 25
    elif percentile > 0.70:     score_per = 15
    else:                       score_per = 5
    
    # 相对板块强度（个股涨幅-板块涨幅） (0-30分)
    if relative_strength > 5:    score_rs = 30
    elif relative_strength > 3:  score_rs = 25
    elif relative_strength > 1:  score_rs = 15
    elif relative_strength > 0:  score_rs = 10
    else:                       score_rs = 5
    
    return score_p + score_per + score_rs
```

### 5.4 质量因子 (0-100) — 权重 15%

```python
def quality_factor(turnover, seal_quality, trend_structure):
    """
    核心逻辑：质量决定安全边际。
    """
    # 换手率 (0-30分)
    if 0.05 < turnover < 0.15:  score_t = 30  # 健康换手
    elif 0.15 <= turnover < 0.25: score_t = 25  # 偏高但可接受
    elif 0.25 <= turnover < 0.35: score_t = 15  # 偏高，谨慎
    elif turnover >= 0.35:       score_t = 5   # 危险
    elif turnover <= 0.05:       score_t = 10  # 不活跃
    else:                       score_t = 15
    
    # 封板质量 (0-40分)
    if seal_quality == "一字":   score_s = 20  # 买不到
    elif seal_quality == "早板": score_s = 40  # 最强
    elif seal_quality == "中板": score_s = 30  # 中等
    elif seal_quality == "尾板": score_s = 15  # 偏弱
    else:                       score_s = 5
    
    # 趋势结构 (0-30分)
    if trend_structure == "强趋势":   score_tr = 30
    elif trend_structure == "上升通道": score_tr = 25
    elif trend_structure == "突破":    score_tr = 20
    elif trend_structure == "震荡":    score_tr = 15
    else:                              score_tr = 5
    
    return score_t + score_s + score_tr
```

### 5.5 RPS 相对强度因子 (0-100) — 权重 15%（新增）

```python
def rps_factor(rps_20, rps_60):
    """
    核心逻辑：RPS（Relative Price Strength）衡量个股相对全市场的强度。
    
    真正的大牛股不是每天涨停，而是持续跑赢市场。
    例如：过去20天股票涨30%，沪深300涨5%，RPS 极高。
    
    RPS 计算：个股涨幅在全市场中的百分位排名。
    RPS 80 表示跑赢 80% 的股票。
    
    Args:
        rps_20: 20日相对强度（0-100）
        rps_60: 60日相对强度（0-100）
    """
    # 20日 RPS (0-60分) — 中短期趋势
    if rps_20 > 90:     score_20 = 60
    elif rps_20 > 80:   score_20 = 55
    elif rps_20 > 70:   score_20 = 45
    elif rps_20 > 60:   score_20 = 35
    elif rps_20 > 50:   score_20 = 25
    elif rps_20 > 40:   score_20 = 15
    else:               score_20 = 5
    
    # 60日 RPS (0-40分) — 中长期趋势
    if rps_60 > 90:     score_60 = 40
    elif rps_60 > 80:   score_60 = 35
    elif rps_60 > 70:   score_60 = 30
    elif rps_60 > 60:   score_60 = 25
    elif rps_60 > 50:   score_60 = 15
    elif rps_60 > 40:   score_60 = 10
    else:               score_60 = 5
    
    return score_20 + score_60
```

**RPS 计算方法：**

```python
def calc_rps(stock_code, market_df, period=20):
    """
    计算个股的 RPS 相对强度。
    
    Args:
        stock_code: 股票代码
        market_df: 全市场股票涨跌幅 DataFrame
        period: 计算周期（20日或60日）
    
    Returns:
        RPS 值（0-100）
    """
    # 获取个股 period 日涨幅
    stock_pct = get_stock_period_return(stock_code, period)
    
    # 获取全市场所有股票 period 日涨幅
    all_pcts = market_df[f"return_{period}d"].values
    
    # 计算百分位排名
    import numpy as np
    percentile = np.sum(all_pcts <= stock_pct) / len(all_pcts) * 100
    
    return round(percentile, 2)
```

### 5.6 共识因子 (0-100) — 权重 10%

```python
def consensus_factor(lhm_data, attention_score, follower_count):
    """
    核心逻辑：共识决定持续性。
    """
    # 龙虎榜资金 (0-40分)
    if lhm_data:
        net_buy = lhm_data["net_buy"]
        if net_buy > 1e8:        score_l = 40
        elif net_buy > 5e7:      score_l = 35
        elif net_buy > 0:        score_l = 25
        elif net_buy > -5e7:     score_l = 15
        else:                   score_l = 5
    else:
        score_l = 10
    
    # 市场关注度 (0-30分)
    if attention_score > 80:    score_a = 30
    elif attention_score > 60:  score_a = 25
    elif attention_score > 40:  score_a = 15
    else:                       score_a = 5
    
    # 板块内跟随者数量 (0-30分)
    if follower_count >= 5:     score_f = 30
    elif follower_count >= 3:   score_f = 25
    elif follower_count >= 2:   score_f = 15
    elif follower_count >= 1:   score_f = 10
    else:                       score_f = 0
    
    return score_l + score_a + score_f
```

---

## 六、龙头判定规则

### 6.1 绝对龙头

```
条件：综合评分 > 85 AND 连板高度 >= 4 AND 板块内成交额第1 AND RPS > 70
操作：重仓参与，不轻易下车
```

### 6.2 核心龙头

```
条件：综合评分 70-85 AND 连板高度 >= 2 AND 板块内成交额前3 AND RPS > 60
操作：积极参与，主线不破不卖
```

### 6.3 次龙/卡位

```
条件：综合评分 55-70 AND 有连板 OR 成交额领先
操作：轻仓参与，注意卡位信号
```

### 6.4 趋势龙头（新增类型）

```
条件：综合评分 > 70 AND RPS 20 > 80 AND RPS 60 > 70 AND 无连板但趋势完好
操作：适合不追高的投资者，沿均线持有
```

---

## 七、数据依赖关系

| 数据 | 来源接口 | 状态 |
|------|----------|------|
| 个股成交额 | `/api/market/turnover-top` | ✅ 部分 |
| 个股涨幅 | `/api/quote` | ✅ 已有 |
| 连板数据 | `/api/market/emotion` → lianban | ✅ 部分 |
| 龙虎榜 | `/api/dragon-tiger` | ✅ 已有 |
| 大单资金 | `/api/fund-flow` | ✅ 已有 |
| 封板质量 | 需新增 | ❌ 待开发 |
| 板块内排名 | 需计算 | ❌ 待开发 |
| 趋势结构 | 需新增 | ❌ 待开发 |
| **RPS 20日** | 需新增 | **P1** |
| **RPS 60日** | 需新增 | **P1** |
| **板块评分** | `/api/sector/rank` | **P0** |

---

## 八、实现建议

### 8.1 新增接口

```
GET /api/leader/candidates    # 龙头候选列表（含过滤）
GET /api/leader/score         # 龙头评分详情
GET /api/leader/history       # 龙头历史
GET /api/leader/rps           # RPS 相对强度
```

### 8.2 数据持久化

建议新增 `strategy_leader_score` 表：
- 日期、股票代码、名称、综合评分
- 龙头类型、各因子得分
- 板块归属、连板高度
- RPS 20日、RPS 60日

### 8.3 RPS 实现方案

```python
# 方案1：基于全市场涨跌幅排名
def calc_rps_from_market(stock_code, period=20):
    """计算个股 RPS：在全市场中的涨幅百分位排名"""
    # 获取全市场股票 period 日涨幅
    market_returns = get_all_stocks_period_return(period)
    
    # 获取个股 period 日涨幅
    stock_return = get_stock_period_return(stock_code, period)
    
    # 计算百分位
    import numpy as np
    rps = np.sum(market_returns <= stock_return) / len(market_returns) * 100
    
    return round(rps, 2)

# 方案2：基于指数相对强度（简化版）
def calc_rps_from_index(stock_code, index_code="000300", period=20):
    """计算个股相对指数的强度"""
    stock_return = get_stock_period_return(stock_code, period)
    index_return = get_index_period_return(index_code, period)
    
    # 相对强度 = 个股涨幅 / 指数涨幅
    if index_return != 0:
        relative_strength = stock_return / index_return
    else:
        relative_strength = stock_return
    
    # 转换为 0-100 分
    rps = min(max(relative_strength * 50, 0), 100)
    
    return round(rps, 2)
```
