"""날씨 아이콘 — 반투명 기하 도형으로 직접 그림 (iOS Weather 스타일)."""
from __future__ import annotations

import math
from io import BytesIO

from PIL import Image, ImageDraw
from PyQt5.QtGui import QPixmap


_cache: dict = {}


def _draw2x(fn, px: int) -> Image.Image:
    """2배 크기로 그린 뒤 LANCZOS 축소 → 자연스러운 안티앨리어싱."""
    big = fn(px * 2)
    return big.resize((px, px), Image.LANCZOS)


# ── 개별 아이콘 ─────────────────────────────────────────────────────────────────

def _sun_raw(px: int) -> Image.Image:
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    cx = cy = px / 2
    core_r = px * 0.27
    ray_inner = core_r * 1.25
    ray_outer = core_r * 1.72
    ray_w = max(2, int(px * 0.055))

    for i in range(8):
        a = math.radians(i * 45)
        x1 = cx + math.cos(a) * ray_inner
        y1 = cy + math.sin(a) * ray_inner
        x2 = cx + math.cos(a) * ray_outer
        y2 = cy + math.sin(a) * ray_outer
        d.line([(x1, y1), (x2, y2)], fill=(255, 195, 55, 210), width=ray_w)

    r = core_r
    d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(255, 200, 55, 230))
    # 하이라이트
    hr = r * 0.42
    d.ellipse([cx-r*0.52, cy-r*0.62, cx-r*0.52+hr, cy-r*0.62+hr],
              fill=(255, 240, 160, 80))
    return img


def _moon_raw(px: int) -> Image.Image:
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    cx = cy = px / 2
    r  = px * 0.30
    d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(215, 228, 255, 210))
    # 초승달 컷
    ox = r * 0.38
    d.ellipse([cx-r+ox, cy-r-ox*0.15, cx+r+ox, cy+r-ox*0.15], fill=(0, 0, 0, 0))
    return img


def _cloud_raw(px: int) -> Image.Image:
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    cx = px / 2
    cy = px * 0.58
    w  = px * 0.72
    h  = px * 0.34
    col = (218, 225, 238, 195)

    # 몸통
    d.ellipse([cx-w/2, cy-h/2, cx+w/2, cy+h/2], fill=col)
    # 상단 돌기 3개
    for ox, oy, rr in [
        (-0.16, -0.42, 0.21),
        ( 0.02, -0.54, 0.25),
        ( 0.20, -0.38, 0.19),
    ]:
        bx = cx + ox * px
        by = cy + oy * h * 2
        br = rr * px
        d.ellipse([bx-br, by-br, bx+br, by+br], fill=col)
    return img


def _partly_cloudy_raw(px: int) -> Image.Image:
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    # 태양 — 왼쪽 상단, 작게
    sun = _sun_raw(int(px * 0.72))
    img.paste(sun, (0, 0), sun)
    # 구름 — 오른쪽 하단에 겹쳐서
    cloud = _cloud_raw(int(px * 0.78))
    ox = int(px * 0.22)
    oy = int(px * 0.22)
    img.paste(cloud, (ox, oy), cloud)
    return img


def _rain_raw(px: int) -> Image.Image:
    img = _cloud_raw(px)
    d   = ImageDraw.Draw(img)
    cx  = px / 2
    drop_col = (100, 155, 230, 195)
    dr  = max(2, int(px * 0.048))
    # 빗방울 3개
    for i, (fx, fy) in enumerate([(-0.18, 0.68), (0.0, 0.73), (0.18, 0.68)]):
        x = cx + fx * px
        y = fy * px
        dy = (i % 2) * px * 0.06
        d.ellipse([x-dr, y+dy, x+dr, y+dr*2.2+dy], fill=drop_col)
    return img


def _snow_raw(px: int) -> Image.Image:
    img = _cloud_raw(px)
    d   = ImageDraw.Draw(img)
    cx  = px / 2
    flake_col = (180, 215, 255, 205)
    fr  = max(2, int(px * 0.045))
    for i, fx in enumerate([-0.18, 0.0, 0.18]):
        x = cx + fx * px
        y = px * (0.70 + (i % 2) * 0.05)
        d.ellipse([x-fr, y-fr, x+fr, y+fr], fill=flake_col)
        # 작은 십자 암시
        w = max(1, int(px * 0.025))
        d.line([(x-fr*1.6, y), (x+fr*1.6, y)], fill=flake_col, width=w)
        d.line([(x, y-fr*1.6), (x, y+fr*1.6)], fill=flake_col, width=w)
    return img


def _thunder_raw(px: int) -> Image.Image:
    img = _cloud_raw(px)
    d   = ImageDraw.Draw(img)
    cx  = px / 2 + px * 0.02
    bolt = [
        (cx + px*0.04, px*0.60),
        (cx - px*0.10, px*0.74),
        (cx + px*0.01, px*0.74),
        (cx - px*0.09, px*0.89),
        (cx + px*0.14, px*0.70),
        (cx + px*0.03, px*0.70),
    ]
    d.polygon(bolt, fill=(255, 215, 30, 230))
    return img


def _fog_raw(px: int) -> Image.Image:
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    cx  = px / 2
    col = (200, 210, 228, 160)
    lh  = max(2, int(px * 0.058))
    for fy, xfrac in [(0.32, 0.38), (0.48, 0.30), (0.64, 0.34), (0.80, 0.26)]:
        x0 = cx - xfrac * px
        x1 = cx + xfrac * px
        y  = fy * px
        d.rounded_rectangle([x0, y, x1, y + lh], radius=lh // 2, fill=col)
    return img


def _shower_raw(px: int) -> Image.Image:
    """약한 소나기 — 구름 + 짧은 빗선."""
    img = _cloud_raw(px)
    d   = ImageDraw.Draw(img)
    cx  = px / 2
    col = (100, 155, 230, 165)
    lw  = max(1, int(px * 0.035))
    for i, fx in enumerate([-0.16, 0.02, 0.18]):
        x = cx + fx * px
        y0 = px * (0.66 + (i % 2) * 0.04)
        d.line([(x, y0), (x - px*0.04, y0 + px*0.12)], fill=col, width=lw)
    return img


# ── 아이콘 디스패치 ─────────────────────────────────────────────────────────────

_EMOJI_MAP = {
    "☀️": _sun_raw,
    "🌙": _moon_raw,
    "☁️": _cloud_raw,
    "⛅": _partly_cloudy_raw,
    "🌦️": _shower_raw,
    "🌧️": _rain_raw,
    "❄️": _snow_raw,
    "⛈️": _thunder_raw,
    "🌫️": _fog_raw,
    "🌡️": _sun_raw,
}


def emoji_pixmap(emoji: str, px: int) -> QPixmap:
    key = (emoji, px)
    if key in _cache:
        return _cache[key]

    raw_fn = _EMOJI_MAP.get(emoji, _sun_raw)
    img    = _draw2x(raw_fn, px)

    buf = BytesIO()
    img.save(buf, format="PNG")
    pix = QPixmap()
    pix.loadFromData(buf.getvalue())
    _cache[key] = pix
    return pix


def desc_to_emoji(desc: str, hour: int = 12) -> str:
    low = desc.lower()
    is_night = hour < 6 or hour >= 19

    if "thunder" in low or "storm" in low:
        return "⛈️"
    if "snow" in low or "blizzard" in low or "sleet" in low:
        return "❄️"
    if "shower" in low:
        return "🌦️"
    if "rain" in low or "drizzle" in low:
        return "🌧️"
    if "fog" in low or "mist" in low or "haze" in low:
        return "🌫️"
    if "overcast" in low:
        return "☁️"
    if "partly cloudy" in low:
        return "🌙" if is_night else "⛅"
    if "cloudy" in low:
        return "☁️"
    if "clear" in low or "sunny" in low or "fair" in low:
        return "🌙" if is_night else "☀️"
    return "☀️"
