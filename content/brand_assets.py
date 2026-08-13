#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Joy Research — 内容资产互联 单一来源模块
================================================
SOP v1.0 的工程落地。所有平台的固定入口与固定文案只写在这里，
任何内容生产脚本/流程直接 import 本模块，禁止在单篇内容里手抄改写。

对应规范文档： docs/XL_内容互联SOP_v1.0.md

用法（作为库）：
    from brand_assets import A_WECHAT_FOOTER, B_VIDEO_DESCRIPTION, assemble

用法（命令行，直接出文案）：
    python content/brand_assets.py --block A
    python content/brand_assets.py --block B-desc
    python content/brand_assets.py --block B-outro
    python content/brand_assets.py --block C
    python content/brand_assets.py --block D --topic "Gold update" --youtube "https://youtu.be/xxxx"
    python content/brand_assets.py --checklist video
"""

# ---------------------------------------------------------------------------
# 1. 官方入口库（固定，每次发布只调用这一版）
# ---------------------------------------------------------------------------
PLATFORMS = {
    "wechat": {
        "name": "xiaoliu_research",
        "label": "微信公众号",
        "positioning": "每日市场观察、投资研究日志、文字版研究档案",
        "url": None,  # 公众号以名称作为入口，无直接 URL
    },
    "youtube": {
        "name": "Joy Research YouTube",
        "label": "YouTube",
        "positioning": "完整视频研究档案：我的交易笔记 / 市场观察 / 投资研究 / AI 投资系统",
        "url": "https://www.youtube.com/@xiaoliujoy",
    },
    "bilibili": {
        "name": "Joy Research Bilibili",
        "label": "Bilibili",
        "positioning": "中文视频研究社区，同步 YouTube 长视频",
        "url": "https://space.bilibili.com/47330019",
    },
    "github": {
        "name": "Joy Research GitHub",
        "label": "GitHub",
        "positioning": "研究系统、代码、工具、方法论开源；研究能力证明中心",
        "url": "https://github.com/xiaoliujoy/",
    },
    "x": {
        "name": "Joy Research X",
        "label": "X (Twitter)",
        "positioning": "全球市场观点、研究碎片、英文传播入口",
        "url": "https://x.com/xiaoliujoy",
    },
}

YOUTUBE_URL = PLATFORMS["youtube"]["url"]
BILIBILI_URL = PLATFORMS["bilibili"]["url"]
GITHUB_URL = PLATFORMS["github"]["url"]
X_URL = PLATFORMS["x"]["url"]
WECHAT_NAME = PLATFORMS["wechat"]["name"]

# 统一视频标签
VIDEO_TAGS = ["#投资研究", "#交易笔记", "#AI投资", "#长期主义"]

# ---------------------------------------------------------------------------
# 2. A 类：公众号日报文末固定结尾
# ---------------------------------------------------------------------------
A_WECHAT_FOOTER = """---

📌 Joy Research

视频研究：
《我的交易笔记》
YouTube：
{yt}

Bilibili：
{bili}


AI投资研究系统：
GitHub：
{gh}


全球市场短观点：
X：
{x}""".format(yt=YOUTUBE_URL, bili=BILIBILI_URL, gh=GITHUB_URL, x=X_URL)

# ---------------------------------------------------------------------------
# 3. B 类：《我的交易笔记》视频固定文案
# ---------------------------------------------------------------------------
B_VIDEO_DESCRIPTION = """《我的交易笔记》

这是 Joy Research 的长期投资研究记录。

我会公开记录：

- 当前市场环境判断
- 我的交易计划
- 观察逻辑
- 事后复盘

这不是交易建议，而是一名投资者持续验证自己研究体系的过程。

关于《我的交易笔记》

《我的交易笔记》是 Joy Research 的长期记录系列。

我会持续记录自己对市场环境、资产走势和交易机会的观察，公开我的判断、交易计划，以及事后复盘。

这不是交易建议，而是一个投资者持续记录、验证和迭代自己研究方法的过程。

📖 每日市场观察

我会在公众号持续记录每日市场变化、全球资产表现与市场观察。

🧠 AI 投资研究系统

我正在构建一套 AI 增强型投资研究系统，并持续将部分研究框架、工具与代码开源。

🔬 三个长期记录

市场日报：记录每天发生了什么
我的交易笔记：记录我如何判断市场
AI 研究系统：记录我如何用系统和 AI 提升研究能力

这三个项目共同构成 Joy Research 的长期研究记录。

📖 每日市场观察

微信公众号：
{xw}


🎬 视频频道

YouTube：
{yt}

Bilibili：
{bili}


🧠 AI投资研究系统

GitHub：
{gh}


🌍 全球市场观点

X：
{x}


#投资研究
#交易笔记
#AI投资
#长期主义""".format(xw=WECHAT_NAME, yt=YOUTUBE_URL, bili=BILIBILI_URL, gh=GITHUB_URL, x=X_URL)

B_VIDEO_OUTRO = """如果你希望看到更加高频的市场记录，可以关注我的微信公众号 {xw}。

如果你想了解我如何构建 AI 投资研究系统，可以访问 GitHub。

这里记录的不是预测，而是一名投资者持续学习、验证和迭代的过程。""".format(xw=WECHAT_NAME)

# ---------------------------------------------------------------------------
# 4. C 类：GitHub README 固定区块
# ---------------------------------------------------------------------------
C_GITHUB_README = """## Joy Research

AI-enhanced investment research system.

本项目记录：

- 全球市场研究框架
- AI辅助投资分析
- 数据处理工具
- 投资研究方法


## Research Log

市场观察：
微信公众号：
{xw}


Video Journal:

YouTube:
{yt}

Bilibili:
{bili}


Global Notes:

X:
{x}""".format(xw=WECHAT_NAME, yt=YOUTUBE_URL, bili=BILIBILI_URL, x=X_URL)

# ---------------------------------------------------------------------------
# 5. D 类：X（Twitter）碎片格式
# ---------------------------------------------------------------------------
D_X_TEMPLATE = """[Market Note]

{topic}

我的完整分析：

YouTube:
{yt}

Daily research:

微信公众号：
{xw}

AI research system:

GitHub:
{gh}"""


def build_x_post(topic: str, youtube: str = "", daily: str = WECHAT_NAME,
                 github: str = GITHUB_URL) -> str:
    """生成 D 类 X 碎片文案。

    topic:   一句话主题，如 "Gold update:"
    youtube: 完整分析视频链接（可空，空则省去该段）
    daily:   公众号名称（默认 xiaoliu_research）
    github:  GitHub 链接（默认项目主页）
    """
    body = f"[Market Note]\n\n{topic}\n"
    if youtube:
        body += f"\n我的完整分析：\n\nYouTube:\n{youtube}"
    body += f"\n\nDaily research:\n\n微信公众号：\n{daily}"
    body += f"\n\nAI research system:\n\nGitHub:\n{github}"
    return body


# ---------------------------------------------------------------------------
# 6. 发布检查表
# ---------------------------------------------------------------------------
PUBLISH_CHECKLISTS = {
    "video": [
        "标题统一",
        "封面统一（品牌模板）",
        "简介加入入口（B_VIDEO_DESCRIPTION）",
        "标签统一（#投资研究 #交易笔记 #AI投资 #长期主义）",
        "置顶评论加入入口",
    ],
    "wechat": [
        "文末加入视频入口（A_WECHAT_FOOTER）",
        "文末加入 GitHub",
        "文末加入 X",
    ],
    "github": [
        "README 有内容入口（C_GITHUB_README）",
        "Release 有说明",
        "项目介绍关联研究理念",
    ],
    "x": [
        "用 D 类碎片格式（build_x_post）",
        "含 YouTube / 公众号 / GitHub 三个回链",
    ],
}


# ---------------------------------------------------------------------------
# 7. 调度器
# ---------------------------------------------------------------------------
def assemble(content_type: str) -> str:
    """按内容类型返回对应固定文案。

    content_type: A | B | B-desc | B-outro | C | D
    """
    mapping = {
        "A": A_WECHAT_FOOTER,
        "B": B_VIDEO_DESCRIPTION,
        "B-desc": B_VIDEO_DESCRIPTION,
        "B-outro": B_VIDEO_OUTRO,
        "C": C_GITHUB_README,
    }
    if content_type in mapping:
        return mapping[content_type]
    if content_type == "D":
        # D 类需要参数，返回模板说明
        return D_X_TEMPLATE
    raise ValueError(f"未知 content_type: {content_type}（可选 A/B/B-desc/B-outro/C/D）")


# ---------------------------------------------------------------------------
# 8. 命令行：直接产出文案
# ---------------------------------------------------------------------------
def _main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="XL 内容资产互联 · 固定文案输出")
    parser.add_argument("--block", choices=["A", "B", "B-desc", "B-outro", "C", "D"],
                        help="输出哪类固定文案")
    parser.add_argument("--topic", default="Gold update:", help="D 类主题行")
    parser.add_argument("--youtube", default="", help="D 类完整分析视频链接")
    parser.add_argument("--checklist", choices=["video", "wechat", "github", "x"],
                        help="输出发布检查表")
    parser.add_argument("--out", default=None, help="写入文件（默认打印到 stdout）")
    args = parser.parse_args()

    text = ""
    if args.checklist:
        lines = PUBLISH_CHECKLISTS[args.checklist]
        text = f"发布检查表（{args.checklist}）：\n" + "\n".join(f"- [ ] {c}" for c in lines)
    elif args.block == "D":
        text = build_x_post(topic=args.topic, youtube=args.youtube)
    elif args.block:
        text = assemble(args.block)
    else:
        parser.print_help()
        sys.exit(1)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[OK] 已写入 {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    _main()
