# Joy Research 内容资产互联 SOP v1.0

> 生效日：2026-08-11 ｜ 版本：v1.0 ｜ 评审节奏：执行 90 天后升级 v2.0
>
> 本文件是**人类可读的单一事实来源（spec）**。所有固定文案的最终版本以代码模块
> `content/brand_assets.py` 为准，本文件与代码模块必须保持一致；若需改动固定文案，
> 只改 `brand_assets.py`，本文件同步说明，禁止在单篇内容里手抄改写。
>
> 核心原则：**每个平台不是独立账号，而是同一个研究生态的不同入口。**
> 以后任何内容发布，自动完成：
> **内容生产 → 主平台发布 → 关联入口 → 用户沉淀 → 资产积累**

---

## 一、品牌统一入口

- 统一品牌名：**Joy Research**
- 定位：**AI 增强型投资研究记录**
- 记录：市场观察、交易计划、研究系统构建与投资者成长过程。
- 红线（全平台）：禁"AI预测/躲过暴跌/收益%"；金融内容必带"不构成投资建议/不荐股"声明。

---

## 二、官方入口库（固定，每次发布只调用这一版）

| 平台 | 名称 / 频道 | 定位 | 入口 |
|---|---|---|---|
| 微信公众号 | xiaoliu_research | 每日市场观察、投资研究日志、文字版研究档案 | 名称：xiaoliu_research |
| YouTube | Joy Research YouTube | 完整视频研究档案：我的交易笔记 / 市场观察 / 投资研究 / AI 投资系统 | https://www.youtube.com/@xiaoliujoy |
| Bilibili | Joy Research Bilibili | 中文视频研究社区，同步 YouTube 长视频 | https://space.bilibili.com/47330019 |
| GitHub | Joy Research GitHub | 研究系统、代码、工具、方法论开源；研究能力证明中心 | https://github.com/xiaoliujoy/ |
| X (Twitter) | Joy Research X | 全球市场观点、研究碎片、英文传播入口 | https://x.com/xiaoliujoy |

---

## 三、内容类型对应 SOP

### A 类：公众号日报 SOP

- 内容定位：回答「今天市场发生了什么？」
- 发布结构：正文 + 固定结尾（见 `brand_assets.py` → `A_WECHAT_FOOTER`）
- 目的：公众号用户 → 视频 → 研究系统 → 长期用户

### B 类：《我的交易笔记》视频 SOP

- 视频简介固定模板：`brand_assets.py` → `B_VIDEO_DESCRIPTION`
- 视频口播结尾固定：`brand_assets.py` → `B_VIDEO_OUTRO`
- 标签固定：`#投资研究 #交易笔记 #AI投资 #长期主义`
- 封面 / 标题统一：沿用 `gen_xl_youtube_pack.py` 的玻璃+原木品牌模板

### C 类：GitHub README SOP

- README 固定增加研究入口区块：`brand_assets.py` → `C_GITHUB_README`
- 定位：研究能力证明中心，不只是代码仓库

### D 类：X（Twitter）SOP

- 不发完整版，定位：思考碎片 + 全球传播
- 格式模板：`brand_assets.py` → `build_x_post()`
- 结构：`[Market Note]` + 主题 + 我的完整分析(YouTube) + Daily research(公众号) + AI research system(GitHub)

---

## 四、平台间流量方向

不要简单互链，设计成有向沉淀路径：

```
              GitHub
                ↑
                |
公众号 ←→ 视频 ←→ X
                |
                ↓
              B站
```

- **核心路径 A（国内用户）**：公众号 → 视频号/B站 → 长期关注
- **核心路径 B（海外用户）**：X → YouTube → GitHub
- **核心路径 C（深度用户）**：任意入口 → GitHub → 认识你的研究体系

---

## 五、发布检查表（每次发布前必跑）

### 视频发布
- [ ] 标题统一
- [ ] 封面统一（品牌模板）
- [ ] 简介加入入口（`B_VIDEO_DESCRIPTION`）
- [ ] 标签统一（`#投资研究 #交易笔记 #AI投资 #长期主义`）
- [ ] 置顶评论加入入口

### 公众号发布
- [ ] 文末加入视频入口（`A_WECHAT_FOOTER`）
- [ ] 文末加入 GitHub
- [ ] 文末加入 X

### GitHub 更新
- [ ] README 有内容入口（`C_GITHUB_README`）
- [ ] Release 有说明
- [ ] 项目介绍关联研究理念

### X 发布
- [ ] 用 D 类碎片格式（`build_x_post`）
- [ ] 含 YouTube / 公众号 / GitHub 三个回链

---

## 六、资产结构（当前阶段）

| 资产 | 作用 |
|---|---|
| 公众号日报 | 证明持续观察能力 |
| 交易笔记视频 | 证明判断过程 |
| GitHub 开源 | 证明系统能力 |
| X | 连接全球 |
| B站/视频号 | 扩大中文用户 |

五个组合的价值，高于单纯做一个财经频道。

---

## 七、未来版本升级方向

- **v2.0（90 天后评估）**：建立 Research Hub（研究中心），如 `xiaoliujoy.com`
  - 首页：市场日报 → 交易笔记 → AI 研究系统 → 个人投资方法论
  - 所有平台最终回到这里
- **当前约束**：不再增加新平台；固化本 SOP 并执行 90 天，用数据决定下一步资源投入。
- **90 天关键产出**：哪个平台带来的用户质量最高、哪个内容入口最有效。

---

## 八、自动化约定（研投君执行）

- 以后每次生产内容，研投君自动：
  1. 识别内容类型（A/B/C/D）
  2. 从 `content/brand_assets.py` 拉取对应固定文案，挂载到产出
  3. 附上对应发布检查表
  4. 用户只做「复制粘贴发表」，不发 API 凭证、不自动发布
- 固定文案改动流程：只改 `brand_assets.py` → 本文件同步 → 重新生成受影响内容
