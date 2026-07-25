# -*- coding: utf-8 -*-
"""微信公众号：生成图文文章（草稿 add_draft → 发表 freepublish/submit）。

依赖：Pillow（封面图，缺失则退化为纯文字文章，仍照常发表）。
公众号接口权限说明：
  - draft/add + freepublish/submit（「发布」）对绝大多数已认证公众号可用；
  - 若要「群发」到所有粉丝需认证服务号（message/mass/sendall），本模块用「发布」。
"""
import os
import io
import json
import time
import uuid
import urllib.request
import urllib.error
from .render import build_view, fmt_money

BASE = "https://api.weixin.qq.com/cgi-bin"
RED = "#e23c3c"      # A股：涨/净流入 = 红
GREEN = "#1ba784"    # A股：跌/净流出 = 绿


# ---------------- 低层 HTTP ----------------
def _get_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post_json(url, obj, timeout=20):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post_multipart(url, file_path, field="media", timeout=30):
    boundary = "----WB" + uuid.uuid4().hex
    fname = os.path.basename(file_path)
    with open(file_path, "rb") as f:
        body = f.read()
    hdr = (f"--{boundary}\r\n"
           f"Content-Disposition: form-data; name=\"{field}\"; filename=\"{fname}\"\r\n"
           f"Content-Type: image/png\r\n\r\n").encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    data = hdr + body + tail
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ---------------- 客户端 ----------------
class MPClient:
    def __init__(self, appid, secret):
        self.appid = appid
        self.secret = secret
        self._token = None
        self._exp = 0

    def token(self):
        if self._token and time.time() < self._exp:
            return self._token
        url = f"{BASE}/token?grant_type=client_credential&appid={self.appid}&secret={self.secret}"
        d = _get_json(url)
        if "access_token" not in d:
            raise RuntimeError(f"获取 access_token 失败: {d}")
        self._token = d["access_token"]
        self._exp = time.time() + d.get("expires_in", 7200) - 300
        return self._token

    def upload_thumb(self, png_path):
        """永久素材(图片) → media_id，用作文章封面 thumb_media_id。"""
        tok = self.token()
        url = f"{BASE}/material/add_material?access_token={tok}&type=image"
        d = _post_multipart(url, png_path)
        if "media_id" not in d:
            raise RuntimeError(f"上传封面失败: {d}")
        return d["media_id"]

    def upload_img_url(self, png_path):
        """临时图片 → 可直接用于 content <img src> 的 url。"""
        tok = self.token()
        url = f"{BASE}/media/uploadimg?access_token={tok}"
        d = _post_multipart(url, png_path)
        if "url" not in d:
            raise RuntimeError(f"上传内文图失败: {d}")
        return d["url"]

    def add_draft(self, articles):
        tok = self.token()
        url = f"{BASE}/draft/add?access_token={tok}"
        return _post_json(url, {"articles": articles})

    def publish(self, draft_media_id):
        tok = self.token()
        url = f"{BASE}/freepublish/submit?access_token={tok}"
        return _post_json(url, {"media_id": draft_media_id})


# ---------------- 封面图 ----------------
def make_cover(view, out_path):
    """用 Pillow 画一张主线板块净流入图作封面。成功返回路径，失败返回 None。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    W, H = 960, 540
    img = Image.new("RGB", (W, H), (245, 247, 250))
    d = ImageDraw.Draw(img)
    # 字体：优先微软雅黑（中文），否则默认
    font_big = font_sm = font_tx = None
    for fp in [r"C:/Windows/Fonts/msyh.ttc", r"C:/Windows/Fonts/msyhbd.ttc",
               r"/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"]:
        if os.path.exists(fp):
            try:
                font_big = ImageFont.truetype(fp, 40)
                font_sm = ImageFont.truetype(fp, 24)
                font_tx = ImageFont.truetype(fp, 20)
                break
            except Exception:
                continue
    if font_big is None:
        font_big = font_sm = font_tx = ImageFont.load_default()
    d.text((40, 30), f"每日研投看板  {view['trade_date']}", fill=(31, 41, 55), font=font_big)
    rk = view["risk"]
    d.text((40, 90), f"综合风险 {rk['composite']} ｜ 建议仓位 {rk['position']}",
            fill=(192, 60, 60), font=font_sm)
    # 柱状图：top 6 主线净流入
    rows = sorted(view["mains"], key=lambda x: x["net_now"], reverse=True)[:6]
    if rows:
        maxv = max(abs(r["net_now"]) for r in rows) or 1
        bx, by, bw, bh = 60, 160, 840, 320
        n = len(rows)
        gap = bw // n
        barw = int(gap * 0.6)
        zero_y = by + bh // 2
        for i, r in enumerate(rows):
            x = bx + i * gap + (gap - barw) // 2
            val = r["net_now"]
            h = int(abs(val) / maxv * (bh / 2 - 10))
            col = RED if val >= 0 else GREEN
            if val >= 0:
                d.rectangle([x, zero_y - h, x + barw, zero_y], fill=col)
            else:
                d.rectangle([x, zero_y, x + barw, zero_y + h], fill=col)
            # 数值
            label = f"{val:+.0f}"
            tw = d.textlength(label, font=font_tx)
            d.text((x + (barw - tw) / 2, (zero_y - h - 24) if val >= 0 else (zero_y + h + 6)),
                   label, fill=col, font=font_tx)
            # 板块名（若字体支持中文）
            nm = r["sector"]
            if "msyh" in (font_big.path if hasattr(font_big, "path") else "") or "wqy" in (font_big.path if hasattr(font_big, "path") else ""):
                nw = d.textlength(nm, font=font_tx)
                d.text((x + (barw - nw) / 2, zero_y + bh // 2 + 12), nm, fill=(90, 98, 112), font=font_tx)
    d.text((40, H - 36), "量化系统生成 · 仅供研究 · 不构成投资建议", fill=(150, 158, 172), font=font_tx)
    img.save(out_path, "PNG")
    return out_path


def _make_placeholder(out_path, w=960, h=540):
    """生成纯色占位封面（无图表），用于真实封面上传失败时的兜底。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    img = Image.new("RGB", (w, h), (31, 41, 55))
    d = ImageDraw.Draw(img)
    font = None
    for fp in [r"C:/Windows/Fonts/msyh.ttc", r"/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"]:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, 40)
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()
    txt = "每日研投看板"
    tw = d.textlength(txt, font=font)
    d.text(((w - tw) / 2, h / 2 - 24), txt, fill=(255, 255, 255), font=font)
    img.save(out_path, "PNG")
    return out_path


# ---------------- 文章 HTML（公众号白名单标签） ----------------
def _bar(value, maxv, color):
    w = int(abs(value) / maxv * 100) if maxv else 0
    w = max(2, min(100, w))
    sign = "▶" if value >= 0 else "◀"
    return (f'<section style="margin:4px 0;font-size:14px;color:#5a6275;">'
            f'{sign}<span style="display:inline-block;width:{w}%;height:14px;'
            f'background:{color};border-radius:3px;vertical-align:middle;"></span> '
            f'<b style="color:{color};">{value:+.1f}亿</b></section>')


def build_article_html(view, cover_url=None, author=""):
    v = view
    rk = v["risk"]
    sec = []
    sec.append(f'<section style="padding:12px 16px;background:#1f2937;color:#fff;'
               f'font-size:20px;font-weight:bold;border-radius:8px 8px 0 0;">'
               f'📊 每日研投看板 · {v["trade_date"]}</section>')
    sec.append(f'<section style="padding:10px 16px;background:#f5f7fa;font-size:15px;">'
               f'综合风险 <b style="color:#c03c3c;">{rk["composite"]}</b> ｜ '
               f'建议仓位 <b style="color:#1ba784;">{rk["position"]}</b> ｜ '
               f'全市场上涨占比 {rk["up_ratio"]}%</section>')
    if cover_url:
        sec.append(f'<section style="text-align:center;margin:10px 0;">'
                   f'<img src="{cover_url}" style="max-width:100%;border-radius:8px;"></section>')
    # L4 主线
    sec.append('<section style="margin-top:14px;font-size:17px;font-weight:bold;color:#1f2937;">'
               '① 主线板块（资金共识）</section>')
    maxv = max((abs(m["net_now"]) for m in v["mains"]), default=1) or 1
    for m in v["mains"]:
        color = RED if m["net_now"] >= 0 else GREEN
        sec.append(f'<section style="margin:8px 0;padding:8px 12px;background:#fff;border-left:4px solid {color};'
                   f'border-radius:4px;font-size:15px;"><b>{m["sector"]}</b> '
                   f'<span style="color:#8a93a6;">〔{m["stage"]}〕</span><br>{_bar(m["net_now"], maxv, color)}'
                   f'<span style="font-size:13px;color:#8a93a6;">{m["reason"][:50]}</span></section>')
    # L5 龙头
    if v["leaders"]:
        sec.append('<section style="margin-top:14px;font-size:17px;font-weight:bold;color:#1f2937;">'
                   '② 龙头体系</section>')
        for ld in v["leaders"]:
            parts = " ｜ ".join(f"{role[0]}{ld[role]}" for role in
                               ["产业龙头", "资金龙头", "技术龙头", "情绪龙头"] if role in ld)
            sec.append(f'<section style="margin:6px 0;padding:6px 12px;background:#f5f7fa;'
                       f'border-radius:4px;font-size:14px;"><b>{ld["sector"]}</b>：{parts}</section>')
    # L6 候选
    if v["candidates"]:
        sec.append('<section style="margin-top:14px;font-size:17px;font-weight:bold;color:#1f2937;">'
                   '③ 突破候选（人工看图定买卖）</section>')
        sec.append('<section style="font-size:13px;color:#8a93a6;margin:4px 0;">'
                   '系统只圈候选并给数据，最终买卖由你人工看图确认。</section>')
        for c in v["candidates"]:
            rcol = RED if c["risk_score"] >= 60 else ("#e6a23c" if c["risk_score"] >= 40 else GREEN)
            sec.append(f'<section style="margin:6px 0;padding:6px 12px;background:#fff;'
                       f'border-radius:4px;font-size:14px;">{c["name"]}({c["code"]}) '
                       f'<b>{c["breakout"]}</b> ｜ 风险'
                       f'<b style="color:{rcol};">{c["risk_score"]:.0f}</b> ｜ 成交{c["amount_yi"]:.0f}亿</section>')
    # L7 风险三维
    sec.append('<section style="margin-top:14px;font-size:17px;font-weight:bold;color:#1f2937;">'
               '④ 风险预算（三维）</section>')
    dims = [("市场风险", rk["risk_market"]), ("行业风险", rk["risk_industry"]), ("个股风险", rk["risk_stock"])]
    for name, val in dims:
        if val is None:
            continue
        color = RED if val >= 60 else ("#e6a23c" if val >= 40 else GREEN)
        sec.append(f'<section style="margin:6px 0;font-size:14px;">{name} '
                   f'<b style="color:{color};">{val}</b></section>'
                   f'{_bar(val, 100, color)}')
    # 叙事层
    sec.append('<section style="margin-top:14px;font-size:17px;font-weight:bold;color:#1f2937;">'
               '⑤ 宏观 / 产业 / 学习</section>')
    for k, label in [("L1_global_macro", "全球宏观"), ("L2_china_macro", "中国宏观"),
                     ("L3_industry", "产业趋势"), ("L8_learning", "学习进化")]:
        ly = v["narrative"].get(k, {})
        read = (ly.get("read") or "")[:120]
        sec.append(f'<section style="margin:6px 0;padding:6px 12px;background:#f5f7fa;border-radius:4px;'
                   f'font-size:14px;"><b>{label}</b>（{ly.get("status","")}）：{read}</section>')
    sec.append('<section style="margin-top:16px;padding:10px;background:#fff7e6;border-radius:6px;'
               f'font-size:13px;color:#a05a00;">⚠ 本看板由量化系统自动生成，仅供个人研究参考，'
               f'不构成任何投资建议。投资有风险，决策需独立判断。</section>')
    return "".join(sec)


def push(tree, appid, secret, author="", tmp_dir=None):
    """生成草稿并发表，返回 (ok, info)。"""
    view = build_view(tree)
    client = MPClient(appid, secret)
    tmp_dir = tmp_dir or os.path.dirname(os.path.abspath(__file__))
    cover_url = None
    thumb_id = None
    png = os.path.join(tmp_dir, f"cover_{view['trade_date']}.png")
    real_cover = make_cover(view, png)
    cover_url = None
    thumb_id = None
    if real_cover:
        try:
            thumb_id = client.upload_thumb(png)
            cover_url = client.upload_img_url(png)
        except Exception as e:
            thumb_id = None
            print("  [公众号] 真实封面上传失败，改用占位图兜底:", repr(e)[:80])
    if not thumb_id:
        # 占位图兜底：保证 thumb_media_id 存在，文章仍能发表
        ph = os.path.join(tmp_dir, f"cover_placeholder_{view['trade_date']}.png")
        _make_placeholder(ph)
        try:
            thumb_id = client.upload_thumb(ph)
        except Exception as e:
            return False, {"err": f"占位封面上传也失败，文章未发表: {e}"}
    html = build_article_html(view, cover_url=cover_url, author=author)
    digest = f"综合风险{rk_digest(view)} ｜ 建议仓位{view['risk']['position']}"
    article = {
        "title": f"每日研投看板 {view['trade_date']}",
        "author": author or "量化研投",
        "digest": digest,
        "content": html,
        "thumb_media_id": thumb_id,
        "need_open_comment": 0,
        "only_fans_can_comment": 0,
    }
    d = client.add_draft([article])
    if "media_id" not in d:
        return False, {"step": "add_draft", "resp": d}
    pub = client.publish(d["media_id"])
    return True, {"draft_media_id": d["media_id"], "publish": pub}


def _cover_view_from_memo(memo):
    """从 memo 构造封面所需的 view（仅取装饰性数据，避免再读 decision_tree.json）。"""
    from notify.os2_report import compute_weighted_score
    sc = compute_weighted_score(memo)
    mains = []
    for m in (memo.main_lines or [])[:6]:
        mains.append({"sector": getattr(m, "sector", ""),
                      "net_now": (getattr(m, "star_rating", 3) - 3) * 5})
    return {
        "trade_date": memo.trade_date,
        "risk": {
            "composite": sc["composite"],
            "position": getattr(memo, "position_pct", "—") or "—",
            "up_ratio": "—",
        },
        "mains": mains,
    }


def push_memo(memo, appid, secret, author="", tmp_dir=None):
    """微信公众号发布 Trading OS 2.0 压缩版（与本地 HTML 同一份决策逻辑，内联样式）。

    取代旧 build_article_html(tree) 长格式；现在直接吃 cio_agent.produce() 的 memo，
    用 os2_report.render_wechat_html 生成红涨绿跌内联版，公众号发的就是和本地看的一样的压缩版。
    """
    from notify.os2_report import render_wechat_html
    client = MPClient(appid, secret)
    tmp_dir = tmp_dir or os.path.dirname(os.path.abspath(__file__))
    view = _cover_view_from_memo(memo)
    cover_url = None
    thumb_id = None
    png = os.path.join(tmp_dir, f"cover_{view['trade_date']}.png")
    real_cover = make_cover(view, png)
    if real_cover:
        try:
            thumb_id = client.upload_thumb(png)
            cover_url = client.upload_img_url(png)
        except Exception as e:
            thumb_id = None
            print("  [公众号] 真实封面上传失败，改用占位图兜底:", repr(e)[:80])
    if not thumb_id:
        ph = os.path.join(tmp_dir, f"cover_placeholder_{view['trade_date']}.png")
        _make_placeholder(ph)
        try:
            thumb_id = client.upload_thumb(ph)
        except Exception as e:
            return False, {"err": f"占位封面上传也失败，文章未发表: {e}"}
    html = render_wechat_html(memo)
    digest = f"综合评分{view['risk']['composite']} ｜ 建议仓位{view['risk']['position']}"
    article = {
        "title": f"每日研投看板 {view['trade_date']}",
        "author": author or "量化研投",
        "digest": digest,
        "content": html,
        "thumb_media_id": thumb_id,
        "need_open_comment": 0,
        "only_fans_can_comment": 0,
    }
    d = client.add_draft([article])
    if "media_id" not in d:
        return False, {"step": "add_draft", "resp": d}
    pub = client.publish(d["media_id"])
    return True, {"draft_media_id": d["media_id"], "publish": pub}


def rk_digest(view):
    return view["risk"]["composite"]
