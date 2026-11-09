"""生成站点图标与社交分享图（一次性脚本，产物已提交）。

为什么不用现成图片：favicon 是每个页面都会请求的资源，缺了就是一次 404；
og:image 决定链接被分享时的缩略图，没有它分享出去是一张空白卡片。

用法：python tools/gen-assets.py
依赖：Pillow；字体用 Windows 自带的微软雅黑（缺失时回退到默认字体）。
"""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SITE = Path(__file__).resolve().parent.parent
PUBLIC = SITE / "public"
BRAND = "#0969da"
INK = "#1f2328"
MUTED = "#656d76"
SOFT = "#f6f8fa"

FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
FONT_REG = "C:/Windows/Fonts/msyh.ttc"


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def counts() -> tuple[int, int]:
    data = json.loads((SITE / "data" / "resources.json").read_text(encoding="utf-8"))
    counts = data.get("counts") or {}
    return sum(counts.values()), len(counts)


def draw_folder(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, fill: str) -> None:
    """一个扁平的文件夹图标：底板 + 左上角标签，比任何文字在 16px 下都清楚。"""
    tab_w = int(w * 0.52)
    tab_h = int(h * 0.30)
    r = max(2, int(w * 0.05))
    # 标签要先探出主体上沿，否则会被主体整块盖住，看起来只是两个叠起来的方块
    d.rounded_rectangle([x, y, x + tab_w, y + tab_h + r], radius=r, fill=fill)
    d.rounded_rectangle([x, y + tab_h, x + w, y + h], radius=r, fill=fill)


def icon(size: int, bg: str | None) -> Image.Image:
    scale = 4  # 先大后缩，边缘才不锯齿
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if bg:
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=bg)
    # 16px 下标签再小就糊成一团：留 30% 高度给标签，主体压扁一点
    pad = int(s * 0.18)
    draw_folder(d, pad, int(s * 0.22), s - pad * 2, int(s * 0.52), "#ffffff")
    return img.resize((size, size), Image.LANCZOS)


def og_cover() -> None:
    w, h = 1200, 630
    total, cats = counts()
    img = Image.new("RGB", (w, h), "#ffffff")
    d = ImageDraw.Draw(img)

    # 顶部一条品牌色细线，缩略图在信息流里有辨识度
    d.rectangle([0, 0, w, 8], fill=BRAND)

    d.rounded_rectangle([80, 96, 80 + 190, 96 + 46], radius=23, fill="#eaf2fd")
    small = font(FONT_BOLD, 24)
    d.text((80 + 24, 96 + 10), "AiTop233", font=small, fill=BRAND)

    title = font(FONT_BOLD, 92)
    d.text((80, 190), "网盘资源合集", font=title, fill=INK)

    sub = font(FONT_REG, 38)
    d.text((80, 320), "影视 · 电子书 · 教程 · 软件 · 音乐", font=sub, fill=MUTED)

    meta = font(FONT_REG, 30)
    d.text((80, 400), f"{total} 条资源 · {cats} 个分类 · 持续更新", font=meta, fill="#8b949e")

    d.rectangle([80, 500, 80 + 96, 504], fill=BRAND)
    d.text((80, 530), "aitop233.github.io", font=font(FONT_REG, 26), fill="#8b949e")

    # 只画一个：叠一层浅色「影子」在缩略图里会被看成图形错位
    draw_folder(d, 810, 205, 300, 230, BRAND)

    img.save(PUBLIC / "og-cover.png", optimize=True)


def main() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    icon(32, BRAND).save(PUBLIC / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    icon(32, BRAND).save(PUBLIC / "favicon-32.png")
    icon(180, BRAND).save(PUBLIC / "apple-touch-icon.png")
    og_cover()
    print("assets written to", PUBLIC)


if __name__ == "__main__":
    main()
