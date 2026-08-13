#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XL YouTube 频道视觉包装生成器
================================
基于已校准的玻璃+原木品牌底图与 XL 母标，生成：
  1. 频道头图 (2560x1440)
  2. 16:9 视频封面模板 x3
  3. 9:16 Shorts 封面模板
  4. 支持用真实图表截图生成具体视频封面（--cover 模式）

输出目录：output/xljr-youtube-packaging/
"""
import argparse
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
WORKSPACE = Path(r"C:\Users\JOY\WorkBuddy\个人AI研投系统")
OUT_DIR = WORKSPACE / "output" / "xljr-youtube-packaging"

BRAND_ROOT = Path(r"C:\Users\JOY\WorkBuddy\2026-07-29-13-04-22\xl-brand-system")
VISUAL_LIB = BRAND_ROOT / "visual-library" / "calibration-04"

XL_MARK_DARK_BG = BRAND_ROOT / "video" / "xl-mark-dark.png"   # 浅色标，用于深色背景
XL_MARK_LIGHT_BG = BRAND_ROOT / "video" / "xl-mark-light.png" # 深色标，用于浅色背景

FONT_PATH = Path(r"C:\Windows\Fonts\msyh.ttc")
FONT_BOLD = Path(r"C:\Windows\Fonts\msyhbd.ttc")
FONT_FALLBACK = Path(r"C:\Windows\Fonts\NotoSansSC-VF.ttf")

# ---------------------------------------------------------------------------
# 品牌色
# ---------------------------------------------------------------------------
C_NEAR_BLACK = (20, 18, 16)
C_WARM_WHITE = (244, 240, 231)
C_GRAPHITE = (90, 88, 84)
C_TITANIUM = (184, 181, 173)
C_LIGHT_GRAY = (230, 228, 222)


def _resolve_font(preferred: Path, fallback: Path) -> Path:
    return preferred if preferred.exists() else fallback


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """加载中文字体，失败则回退到 Noto Sans SC。"""
    path = FONT_BOLD if bold else FONT_PATH
    path = _resolve_font(path, FONT_FALLBACK)
    if not path.exists():
        raise FileNotFoundError(f"找不到中文字体: {path}")
    return ImageFont.truetype(str(path), size)


def ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def rgba(hex_or_tuple, alpha: int):
    if isinstance(hex_or_tuple, str):
        h = hex_or_tuple.lstrip("#")
        r, g, b = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        return (r, g, b, alpha)
    return (*hex_or_tuple, alpha)


def load_rgba(path: Path) -> Image.Image:
    return Image.open(str(path)).convert("RGBA")


def crop_cover(img: Image.Image, target_w: int, target_h: int, gravity: str = "top") -> Image.Image:
    """
    按比例裁剪并缩放，使 img 填满 target 尺寸。
    gravity: top | center | bottom — 控制多余像素从哪边裁掉。
    这里默认 top，可主动避开水印常在的右下角。
    """
    sw, sh = img.size
    tar = target_w / target_h
    src = sw / sh

    if src > tar:
        # 原图更宽：按目标高度裁剪宽度
        new_h = sh
        new_w = int(new_h * tar)
    elif src < tar:
        # 原图更高：按目标宽度裁剪高度
        new_w = sw
        new_h = int(new_w / tar)
    else:
        return img.resize((target_w, target_h), Image.Resampling.LANCZOS)

    if gravity == "top":
        left, top = (sw - new_w) // 2, 0
    elif gravity == "bottom":
        left, top = (sw - new_w) // 2, sh - new_h
    else:
        left, top = (sw - new_w) // 2, (sh - new_h) // 2

    cropped = img.crop((left, top, left + new_w, top + new_h))
    return cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)


def add_gradient_overlay(img: Image.Image, direction: str,
                         start_color: tuple, end_color: tuple,
                         start_pos: float = 0.0, end_pos: float = 1.0) -> None:
    """
    在 img 上原地叠加半透明渐变。
    direction: vertical | horizontal
    start_pos/end_pos: 渐变在 0~1 之间开始/结束的位置。
    """
    w, h = img.size
    arr = np.array(img).astype(np.float32)

    if direction == "vertical":
        total = h
        mask = np.linspace(0, 1, total).reshape(-1, 1)
        y0, y1 = int(start_pos * h), int(end_pos * h)
        grad_region = np.zeros((h, w, 4), dtype=np.float32)
        for i in range(y0, y1):
            t = (i - y0) / max(1, y1 - y0)
            grad_region[i, :] = [
                start_color[j] * (1 - t) + end_color[j] * t for j in range(4)
            ]
    else:
        total = w
        x0, x1 = int(start_pos * w), int(end_pos * w)
        grad_region = np.zeros((h, w, 4), dtype=np.float32)
        for i in range(x0, x1):
            t = (i - x0) / max(1, x1 - x0)
            grad_region[:, i] = [
                start_color[j] * (1 - t) + end_color[j] * t for j in range(4)
            ]

    # 混合 RGB，保留原图 Alpha
    alpha = grad_region[:, :, 3:4] / 255.0
    rgb = arr[:, :, :3]
    blended_rgb = rgb * (1 - alpha) + grad_region[:, :, :3] * alpha
    result = np.concatenate([blended_rgb, arr[:, :, 3:4]], axis=2)
    img.paste(Image.fromarray(np.clip(result, 0, 255).astype(np.uint8)), (0, 0))


def add_text_centered(draw: ImageDraw.ImageDraw, text: str, x: int, y: int,
                      font: ImageFont.FreeTypeFont, fill: tuple, anchor: str = "lt") -> None:
    draw.text((x, y), text, font=font, fill=fill, anchor=anchor)


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def add_chip(draw: ImageDraw.ImageDraw, text: str, x: int, y: int,
             font: ImageFont.FreeTypeFont, bg: tuple, fg: tuple, radius: int = 6) -> None:
    """绘制圆角分类标签。"""
    tw, th = text_size(draw, text, font)
    pad_x, pad_y = 16, 8
    w, h = tw + pad_x * 2, th + pad_y * 2
    # 圆角矩形
    draw.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=bg)
    draw.text((x + pad_x, y + pad_y), text, font=font, fill=fg)
    return w, h


def paste_logo(img: Image.Image, logo_path: Path, target_h: int, x: int, y: int) -> None:
    logo = load_rgba(logo_path)
    ratio = target_h / logo.height
    new_w = int(logo.width * ratio)
    logo = logo.resize((new_w, target_h), Image.Resampling.LANCZOS)
    img.paste(logo, (x, y), logo)


def render_xl_mark(stroke_color: tuple, out_w: int = 1024) -> Image.Image:
    """
    按 BRAND_SPEC.md v1.6 锁定的几何重绘透明 XL 母标。
    来源：01-xl-logo-vertical.svg 中 <g transform="translate(208.6 80.0) scale(0.4200)"> 的四条 path。
    几何：细对角线(40) + 粗对角线(82) + 右竖线(82) + 底横线(40)，暖白 #F4F0E7 / 暖黑 #141210。
    实现：在 1000x1000 正方形内「均匀缩放」坐标后绘制，再裁切到标体，
    严格保持标体宽高比 735.8:420 ≈ 1.752（非均匀缩放会压扁，绝不可取）。
    """
    S = 1000
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 已含 translate+scale(0.42) 的规范坐标（落在 1000x1000 画布内）
    seg = {
        "d1": ((606.7, 80.0), (208.6, 500.0)),    # 细对角线 40
        "d2": ((208.6, 80.0), (606.7, 500.0)),    # 粗对角线 82
        "v":  ((654.6, 80.0), (654.6, 500.0)),    # 右竖线 82
        "h":  ((637.4, 500.0), (944.4, 500.0)),    # 底横线 40
    }
    w_thin = int(round(40 * 0.42))    # 16.8 -> 17
    w_thick = int(round(82 * 0.42))   # 34.4 -> 34

    d.line([seg["d1"][0], seg["d1"][1]], fill=stroke_color, width=w_thin)
    d.line([seg["d2"][0], seg["d2"][1]], fill=stroke_color, width=w_thick)
    d.line([seg["v"][0], seg["v"][1]], fill=stroke_color, width=w_thick)
    d.line([seg["h"][0], seg["h"][1]], fill=stroke_color, width=w_thin)

    # 裁切到标体（含笔宽留白），保持比例
    pad = 18
    bbox = (int(208.6) - pad, int(80.0) - pad, int(944.4) + pad, int(500.0) + pad)
    img = img.crop(bbox)
    img = img.resize((out_w, max(1, int(out_w * img.height / img.width))),
                    Image.Resampling.LANCZOS)
    return img


# 规范 XL 标（内存渲染，避免早期 video/xl-mark-*.png 几何偏差）
XL_MARK_LIGHT_IMG = render_xl_mark(C_WARM_WHITE)   # 暖白标，用于深色背景
XL_MARK_DARK_IMG = render_xl_mark(C_NEAR_BLACK)    # 暖黑标，用于浅色背景


def paste_xl_mark(img: Image.Image, light: bool, target_h: int, x: int, y: int) -> None:
    """light=True 贴暖白标（深色背景）；light=False 贴暖黑标（浅色背景）。"""
    mark = XL_MARK_LIGHT_IMG if light else XL_MARK_DARK_IMG
    ratio = target_h / mark.height
    new_w = int(mark.width * ratio)
    mark = mark.resize((new_w, target_h), Image.Resampling.LANCZOS)
    img.paste(mark, (x, y), mark)


def _ink_centroid_x(mark_img: Image.Image) -> float:
    """返回透明 XL 标内可见墨迹的 x 质心（画布坐标系）。无墨迹时退化为画布中心。"""
    arr = np.array(mark_img.convert("RGBA"))
    a = arr[:, :, 3].astype(np.float64)
    total = a.sum()
    if total == 0:
        return float(mark_img.width / 2)
    xs = np.arange(mark_img.width, dtype=np.float64)
    return float((a.sum(axis=0) * xs).sum() / total)


def paste_xl_mark_centered(img: Image.Image, light: bool, target_h: int,
                           center_x: int, y: int) -> int:
    """
    贴 XL 标，使其可见墨迹中心对齐到 center_x（而非透明画布中心）。

    关键：规范 XL 标的墨迹在画布内偏左（X 交叉线在左、右侧仅单竖线+横臂延伸），
    若按画布居中，视觉 logo 会落在 center_x 左侧，与同处 center_x 的文字错位。
    本函数补偿该偏移，让 logo 墨迹与文字落在同一中轴。
    返回：实际贴入后 logo 墨迹中心在画布中的 x。
    """
    mark = XL_MARK_LIGHT_IMG if light else XL_MARK_DARK_IMG
    ratio = target_h / mark.height
    new_w = int(round(mark.width * ratio))
    mark = mark.resize((new_w, target_h), Image.Resampling.LANCZOS)
    ink_cx = _ink_centroid_x(mark)            # 墨迹在缩放后画布中的 x 质心
    x = int(round(center_x - ink_cx))          # 贴图 x，使墨迹中心落在 center_x
    img.paste(mark, (x, y), mark)
    return int(round(x + ink_cx))


# ---------------------------------------------------------------------------
# 具体资产生成
# ---------------------------------------------------------------------------
def make_channel_banner(base_path: Path = VISUAL_LIB / "C04-02_wood-glass-data-wall.png") -> Path:
    """生成 YouTube 频道头图 2560x1440。

    YouTube 各设备安全区：中心 1546x423。
    所有关键文字均放置在该区域内，确保桌面/移动端不被裁切。
    """
    W, H = 2560, 1440
    SAFE_W, SAFE_H = 1546, 423
    SAFE_L = (W - SAFE_W) // 2
    SAFE_T = (H - SAFE_H) // 2
    CENTER_X = W // 2

    base = load_rgba(base_path)
    canvas = crop_cover(base, W, H, gravity="top")

    # 中心安全区添加横向暗色带（上下柔边），保证整行文字 readability 一致
    band = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    band_arr = np.array(band)
    cy = SAFE_T + SAFE_H // 2
    half_h = SAFE_H // 2 + 40
    for y in range(H):
        dist = abs(y - cy) / half_h
        alpha = max(0, 1 - dist) * 165
        band_arr[y, :] = (20, 18, 16, int(alpha))
    band = Image.fromarray(band_arr)
    canvas = Image.alpha_composite(canvas, band)

    draw = ImageDraw.Draw(canvas)
    fonts = {
        "name": load_font(54, bold=True),
    }

    # logo + 品牌名：整体在安全区内垂直居中；logo 墨迹与文字均对齐到同一中轴 CENTER_X
    logo_h = 190
    gap = 26
    text_h = 54
    total_h = logo_h + gap + text_h
    start_y = SAFE_T + (SAFE_H - total_h) // 2

    # XL 标：按墨迹中心对齐到 CENTER_X（补偿规范标墨迹偏左，避免与文字错位）
    logo_ink_cx = paste_xl_mark_centered(canvas, light=True, target_h=logo_h,
                                         center_x=CENTER_X, y=start_y)

    # 品牌名 实测文字宽度后水平居中（与 logo 墨迹同处中轴 CENTER_X）
    txt = "Joy Research"
    tb = draw.textbbox((0, 0), txt, font=fonts["name"])
    tw = tb[2] - tb[0]
    draw.text((CENTER_X - tw // 2, start_y + logo_h + gap), txt,
              font=fonts["name"], fill=C_WARM_WHITE)

    # 校验：logo 墨迹中心应与文字中心都落在 CENTER_X
    print(f"[verify] logo_ink_cx={logo_ink_cx}  text_cx={CENTER_X}  (expect equal)")

    out = OUT_DIR / "channel_banner.png"
    canvas.convert("RGB").save(str(out), "PNG", optimize=True)
    print(f"[OK] {out}")
    return out


def make_thumbnail_template(base_path: Path, category: str, title_lines: list,
                            out_name: str, real_chart_path: Path = None,
                            accent: tuple = C_GRAPHITE) -> Path:
    """生成 1280x720 视频封面模板。"""
    W, H = 1280, 720
    base = load_rgba(base_path)
    canvas = crop_cover(base, W, H, gravity="top")

    # 如果有真实图表截图，作为中央视觉主体（保留品牌边框）
    if real_chart_path and real_chart_path.exists():
        chart = load_rgba(real_chart_path)
        # 目标区域：中央 960x540，上下左右留白 80
        cw, ch = 960, 540
        chart = crop_cover(chart, cw, ch, gravity="center")
        # 添加 2px 钛灰边框
        overlay = Image.new("RGBA", (cw + 4, ch + 4), C_TITANIUM)
        overlay.paste(chart, (2, 2), chart)
        canvas.paste(overlay, ((W - cw - 4) // 2, 90), overlay)

    # 底部渐变，用于标题并覆盖右下角水印
    add_gradient_overlay(canvas, "vertical",
                         rgba(C_NEAR_BLACK, 0), rgba(C_NEAR_BLACK, 245),
                         start_pos=0.35, end_pos=1.0)

    draw = ImageDraw.Draw(canvas)
    fonts = {
        "title": load_font(52, bold=True),
        "sub": load_font(28),
        "chip": load_font(22),
    }

    # 分类标签
    add_chip(draw, category, 48, 48, fonts["chip"], rgba(C_NEAR_BLACK, 200), C_WARM_WHITE, radius=8)

    # XL 标右上角
    paste_xl_mark(canvas, light=False, target_h=56, x=W - 104, y=48)

    # 标题（左下，最多 3 行）
    y = H - 170
    for i, line in enumerate(title_lines[:3]):
        fill = C_WARM_WHITE if i == 0 else C_TITANIUM
        size = fonts["title"] if i == 0 else fonts["sub"]
        add_text_centered(draw, line, 48, y, size, fill)
        _, th = text_size(draw, line, size)
        y += th + (20 if i == 0 else 12)

    out = OUT_DIR / out_name
    canvas.convert("RGB").save(str(out), "PNG", optimize=True)
    print(f"[OK] {out}")
    return out


def make_shorts_template(base_path: Path = VISUAL_LIB / "C04-05_wood-glass-vertical.png") -> Path:
    """生成 1080x1920 Shorts 封面模板。"""
    W, H = 1080, 1920
    base = load_rgba(base_path)
    canvas = crop_cover(base, W, H, gravity="center")

    # 底部大渐变覆盖水印 + 放标题
    add_gradient_overlay(canvas, "vertical",
                         rgba(C_NEAR_BLACK, 0), rgba(C_NEAR_BLACK, 255),
                         start_pos=0.28, end_pos=1.0)

    draw = ImageDraw.Draw(canvas)
    fonts = {
        "title": load_font(72, bold=True),
        "sub": load_font(36),
        "chip": load_font(26),
    }

    add_chip(draw, "研究笔记", 60, 80, fonts["chip"], rgba(C_NEAR_BLACK, 180), C_WARM_WHITE, radius=10)
    paste_xl_mark(canvas, light=False, target_h=72, x=W - 132, y=80)

    add_text_centered(draw, "方向对了", 60, H - 360, fonts["title"], C_WARM_WHITE)
    add_text_centered(draw, "怎么拿住？", 60, H - 270, fonts["sub"], C_TITANIUM)

    out = OUT_DIR / "shorts_template.png"
    canvas.convert("RGB").save(str(out), "PNG", optimize=True)
    print(f"[OK] {out}")
    return out


def make_cover_example(chart_path: Path, title_lines: list, category: str,
                       out_name: str) -> Path:
    """演示：用真实图表截图合成一张具体视频封面。"""
    return make_thumbnail_template(
        base_path=VISUAL_LIB / "C04-01_wood-glass-desk.png",
        category=category,
        title_lines=title_lines,
        out_name=out_name,
        real_chart_path=chart_path,
    )


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def build_all():
    ensure_dir(OUT_DIR)
    make_channel_banner()
    make_shorts_template()
    make_thumbnail_template(
        VISUAL_LIB / "C04-04_wood-glass-data-closeup.png",
        "框架教学",
        ["信念兑现引擎", "把判断优势变成利润"],
        "thumbnail_template_01_framework.png",
    )
    make_thumbnail_template(
        VISUAL_LIB / "C04-01_wood-glass-desk.png",
        "研究笔记",
        ["交易宪法 v1.1", "五条规则，过闸才能下单"],
        "thumbnail_template_02_research_log.png",
    )
    make_thumbnail_template(
        VISUAL_LIB / "C04-03_wood-glass-report.png",
        "复盘数据",
        ["为什么方向对 93%", "却只吃到 11.7%？"],
        "thumbnail_template_03_review.png",
    )

    # 演示：用 base 图本身当"图表截图"跑一遍 --cover 流程
    example_chart = VISUAL_LIB / "C04-04_wood-glass-data-closeup.png"
    make_cover_example(
        example_chart,
        ["R 太紧 = 拿不住", "止损应放在 ATR×3"],
        "复盘数据",
        "cover_example_01_atr_exit.png",
    )


def main():
    parser = argparse.ArgumentParser(description="XL YouTube 视觉包装生成器")
    parser.add_argument("--cover", action="store_true", help="生成演示封面（默认全量）")
    parser.add_argument("--chart", type=Path, default=None, help="真实图表截图路径")
    parser.add_argument("--title", type=str, default="标题\n副标题", help="封面标题，用 \\n 分行")
    parser.add_argument("--category", type=str, default="研究笔记")
    parser.add_argument("--out", type=Path, default=OUT_DIR / "custom_cover.png")
    args = parser.parse_args()

    ensure_dir(OUT_DIR)

    if args.cover:
        title_lines = args.title.split("\\n")
        make_cover_example(args.chart or VISUAL_LIB / "C04-04_wood-glass-data-closeup.png",
                           title_lines, args.category, args.out.name)
    else:
        build_all()


if __name__ == "__main__":
    main()
