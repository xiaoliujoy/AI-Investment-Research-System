# -*- coding: utf-8 -*-
"""生成 Joy Research Episode 001 小红书配图（数据卡/清单/金句等）。
用代码绘制而非 AI 生图，确保中文与数字 100% 准确、风格统一、零 credit 消耗。
"""
from PIL import Image, ImageDraw, ImageFont
import os

OUT = "generated-images"
os.makedirs(OUT, exist_ok=True)

FONT_DIR = "C:/Windows/Fonts"

def load(size, bold=False):
    """优先微软雅黑（粗体/常规），缺则回退默认。"""
    names = (["msyhbd.ttc", "msyh.ttc"] if bold else ["msyh.ttc", "msyhbd.ttc"])
    for n in names:
        p = os.path.join(FONT_DIR, n)
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()

W, H = 1080, 1440
BG_TOP = (13, 20, 16)
BG_BOT = (22, 36, 28)
GREEN = (46, 125, 82)
WHITE = (235, 240, 237)
GRAY = (150, 165, 158)


def bg():
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        t = y / H
        r = int(BG_TOP[0] + (BG_BOT[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOT[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOT[2] - BG_TOP[2]) * t)
        for x in range(W):
            px[x, y] = (r, g, b)
    return img


def footer_bar(d, footer="XIAO LIU JOY RESEARCH"):
    d.rectangle([80, H - 132, 150, H - 127], fill=GREEN)
    d.text((80, H - 110), footer, font=load(34, True), fill=GRAY)


def card(num, label, big, sub, desc_lines):
    img = bg(); d = ImageDraw.Draw(img)
    d.text((80, 120), label, font=load(40, True), fill=GREEN)
    bsize = 210 if len(big) <= 4 else (170 if len(big) <= 6 else 140)
    d.text((80, 230), big, font=load(bsize, True), fill=WHITE)
    d.text((80, 230 + bsize + 30), sub, font=load(50, True), fill=GREEN)
    y = 230 + bsize + 120
    for line in desc_lines:
        d.text((80, y), line, font=load(40), fill=GRAY); y += 62
    footer_bar(d)
    img.save(os.path.join(OUT, f"xhs_card{num}.png"))


# 1-3 数据卡
card(1, "市场平均跌幅", "-10.5%", "全市场个股等权平均跌幅",
     ["7月1日—29日，全市场个股等权平均。", "如果你「平均持有」股票，", "这个月大概率不好过。"])
card(2, "高位接盘代价", "629只", "回撤超40%（约占12%）",
     ["7月高点买入、拿到月底，", "回撤超40%的股票。", "追高的人，真的被闷了。"])
card(3, "单日普跌", "4783只", "A股下跌，占91.7%（7月17日）",
     ["当天超过九成A股收盘绿盘。", "市场环境明显不利，", "仍有人不停下注。"])

# 4 五问清单
img = bg(); d = ImageDraw.Draw(img)
d.text((80, 110), "我的AI每天回答5个问题", font=load(70, True), fill=WHITE)
qs = ["1  现在适合买股票吗？", "2  资金正在流向哪里？", "3  哪些方向正在变强？",
      "4  现在最大风险在哪？", "5  今天该行动，还是等待？"]
y = 300
for q in qs:
    d.text((90, y), q, font=load(54), fill=GREEN if q.startswith(("1", "5")) else WHITE)
    y += 110
d.text((90, y + 20), "作用不是替我决定，", font=load(40), fill=GRAY)
d.text((90, y + 78), "而是把情绪变成系统化判断。", font=load(40), fill=GRAY)
footer_bar(d)
img.save(os.path.join(OUT, "xhs_card4.png"))

# 5 金句卡
img = bg(); d = ImageDraw.Draw(img)
d.text((80, 130), "认知升级", font=load(40, True), fill=GREEN)
lines = ["AI第一次真正帮助我的地方，", "不是找到股票，", "而是让我停止交易。"]
y = 320
for ln in lines:
    d.text((80, y), ln, font=load(66, True), fill=WHITE); y += 100
d.text((80, y + 40), "热点不断 ≠ 机会不断", font=load(42), fill=GRAY)
d.text((80, y + 100), "新闻很多 ≠ 钱好赚", font=load(42), fill=GRAY)
d.text((80, y + 160), "下跌 ≠ 机会", font=load(42), fill=GRAY)
footer_bar(d, "刘晓  ·  Joy Research")
img.save(os.path.join(OUT, "xhs_card5.png"))

# 6 三日报证据卡
img = bg(); d = ImageDraw.Draw(img)
d.text((80, 120), "7月真实实验", font=load(70, True), fill=WHITE)
d.text((80, 220), "系统连续给出同一结论：", font=load(44), fill=GRAY)
rows = [("7/19", "不交易", "仓位 0%"), ("7/22", "不交易", "仓位 0%"), ("7/29", "不交易", "仓位 0%")]
y = 330
for date, verdict, pos in rows:
    d.text((90, y), date, font=load(60, True), fill=GREEN)
    d.text((320, y), verdict, font=load(60, True), fill=WHITE)
    d.text((640, y), pos, font=load(60, True), fill=GRAY)
    y += 110
d.text((90, y + 30), "候选观察清单 ≠ 实盘买入", font=load(46, True), fill=GREEN)
footer_bar(d)
img.save(os.path.join(OUT, "xhs_card6.png"))

# 7 互动引导卡
img = bg(); d = ImageDraw.Draw(img)
d.text((80, 380), "收藏 + 关注", font=load(130, True), fill=WHITE)
d.text((80, 580), "下期拆我的五步判断框架", font=load(50, True), fill=GREEN)
d.text((80, 680), "一个金融从业者，如何用AI", font=load(40), fill=GRAY)
d.text((80, 736), "提升投资研究与决策能力。", font=load(40), fill=GRAY)
footer_bar(d, "Joy Research  ·  Episode 001")
img.save(os.path.join(OUT, "xhs_card7.png"))

print("OK, 7 cards generated in", OUT)
