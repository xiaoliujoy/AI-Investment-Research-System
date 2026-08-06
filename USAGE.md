# 使用说明 / Usage Guide

本系统是一个**本地运行的 AI 增强投资研究系统**（非自动交易、非投资建议工具）。本说明面向想在自己机器上把它跑起来的开发者 / 研究者。

> 先看 [README](README.md) 了解愿景、架构与免责声明。本文只讲「怎么跑」。

---

## 一、环境准备

- Python 3.11+（MT5 相关包仅支持 3.11；其余建议 3.13）
- Node 18+ 与 pnpm（前端看板）
- Git

```bash
git clone git@github.com:xiaoliujoy/AI-Investment-Research-System.git
cd AI-Investment-Research-System
```

---

## 二、初始化数据库

数据库 `backend/database/vibe_research.db` **不入库**（约 5GB 本地 A股数据，已被 `.gitignore` 排除）。首次需本地生成空库：

```bash
cd backend
python -c "from database.models import init_db; init_db()"
```

---

## 三、跑通每日流程（三选一）

### 方式 A：单命令全流水线（推荐）

```bash
cd backend
python run_daily.py --memo-only
```

`--memo-only` 会依次执行：数据采集 (`daily_collect`) → 技术字段回填 (`tech_fill`) → 八层决策树 → CIO 综合 → 写出**本地** memo（不触发微信公众号发表，避免无凭证报错）。整条流水线约 10~30 分钟，取决于网络与采集量。

### 方式 B：Windows 一键 `daily_run.bat`

仓库根目录 `daily_run.bat`：

```bat
daily_run.bat
```

等价于 `python run_daily.py`（全流水线 + 尝试推送微信公众号）。若未配置公众号凭证，推送会失败但 memo 照常生成。可用环境变量 `WORKBUDDY_PYTHON` 指定解释器路径。

### 方式 C：分步手动（便于调试）

```bash
cd backend
python daily_collect.py                 # 数据采集（TDX 本地优先，东财兜底，全球对齐）
python tech_fill.py                     # 技术字段回填（MA20/60、量比、突破区）
python run_daily.py --skip-step1 --memo-only   # 跳过采集，直接决策 + 出 memo
```

---

## 四、查看产物

流水线结束后在 `backend/output/` 生成（该目录被 `.gitignore` 排除，仅本地留存，**不入库**）：

| 文件 | 说明 |
|------|------|
| `memo_YYYY-MM-DD.html` | 完整版每日决策备忘录（OS2 压缩九宫格） |
| `memo_YYYY-MM-DD_wechat.html` | 公众号内联版，可直接复制粘贴发表 |

memo 回答三个问题：**今天有没有钱？钱去哪？我怎么办？** 包含：执行摘要、最终裁决（加权 IC 评分 / 仓位护栏 / 买卖建议）、盯盘清单、候选主线、逻辑链、失效条件、学习闭环、跨资产 Alpha。

> 系统**只圈主线、列候选、附数据**；最终买卖由人看图决定（Human-in-the-loop）。A股惯例：涨红跌绿。

---

## 五、看板（可选）

```bash
cd frontend
pnpm install
pnpm dev            # 打开终端打印的地址（默认 http://localhost:5899）
```

后端 API（可选）：

```bash
cd backend
python -m uvicorn app:app --host 127.0.0.1 --port 8900
```

---

## 六、AI 推理（可选）

框架开箱即用规则评分。要启用 AI 叙事 / 推理层，通过前端 UI 或 `backend/.env`（不入库）提供 LLM key。无 key 时自动降级为规则评分，不影响出 memo。

---

## 七、重要提醒

- 数据库、`.env`、`.workbuddy/`、`backend/output/`、个人笔记均**不入库**，本仓库只发布代码与方法论。
- 本系统**不下单、不执行交易、不提供个性化投资建议**。所有输出仅为研究者自身判断的辅助。
- 市场有风险，盈亏自负。详见 [README](README.md) 免责声明。
