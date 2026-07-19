"""
Generate Inno Setup wizard banners (+ an app splash) for HomeUpdater.

Arabic is reshaped (arabic_reshaper) and reordered (python-bidi) before drawing,
otherwise Pillow renders the letters isolated and left-to-right. Uses Segoe UI
(a Windows system font that covers Arabic) as a stand-in for the brand fonts.

Run with the backend venv:
    .venv/Scripts/python.exe ../../03_الموارد/logo/generate_wizard_banners.py
"""

from __future__ import annotations

from pathlib import Path

import arabic_reshaper
from PIL import Image, ImageDraw, ImageFont

try:  # python-bidi moved get_display around across versions
    from bidi import get_display
except ImportError:  # pragma: no cover
    from bidi.algorithm import get_display

SS = 4  # supersample
FONTS = Path("C:/Windows/Fonts")
LAT_SEMI = str(FONTS / "seguisb.ttf")  # Segoe UI Semibold
AR_FONT = str(FONTS / "segoeui.ttf")  # Segoe UI (covers Arabic)

TOP = (30, 136, 229)  # #1E88E5
BOTTOM = (8, 40, 116)  # deep navy
WHITE = (255, 255, 255)
TEAL = (38, 166, 154)  # #26A69A


def _ar(text: str) -> str:
    return get_display(arabic_reshaper.reshape(text))


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _gradient(w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h), BOTTOM)
    d = ImageDraw.Draw(img)
    for y in range(h):
        d.line([(0, y), (w, y)], fill=_lerp(TOP, BOTTOM, y / h))
    return img


def _house(d: ImageDraw.ImageDraw, cx: float, cy: float, w: float) -> None:
    d.polygon(
        [(cx, cy - 0.42 * w), (cx - 0.5 * w, cy - 0.02 * w), (cx + 0.5 * w, cy - 0.02 * w)],
        fill=WHITE,
    )
    d.rounded_rectangle(
        [cx - 0.34 * w, cy - 0.08 * w, cx + 0.34 * w, cy + 0.38 * w], radius=0.03 * w, fill=WHITE
    )
    d.polygon(
        [(cx, cy + 0.02 * w), (cx - 0.13 * w, cy + 0.14 * w), (cx + 0.13 * w, cy + 0.14 * w)],
        fill=TEAL,
    )
    d.rounded_rectangle(
        [cx - 0.055 * w, cy + 0.12 * w, cx + 0.055 * w, cy + 0.30 * w], radius=0.02 * w, fill=TEAL
    )


def _centered(d, text, font, cy_top, canvas_w):
    bbox = d.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    d.text(((canvas_w - tw) / 2 - bbox[0], cy_top), text, font=font, fill=WHITE)


def draw_banner(w: int, h: int, house_y=0.30, house_w=0.50, name=True) -> Image.Image:
    W, H = w * SS, h * SS
    img = _gradient(W, H)
    d = ImageDraw.Draw(img)
    _house(d, W * 0.5, H * house_y, W * house_w)
    if name:
        _centered(d, "HomeUpdater", ImageFont.truetype(LAT_SEMI, int(W * 0.135)), H * 0.52, W)
        _centered(d, _ar("محدِّث المنزل"), ImageFont.truetype(AR_FONT, int(W * 0.10)), H * 0.63, W)
    return img.resize((w, h), Image.LANCZOS)


def draw_splash(size=800) -> Image.Image:
    S = size * 2
    img = _gradient(S, S)
    d = ImageDraw.Draw(img)
    _house(d, S * 0.5, S * 0.37, S * 0.34)
    _centered(d, "HomeUpdater", ImageFont.truetype(LAT_SEMI, int(S * 0.072)), S * 0.56, S)
    _centered(d, _ar("محدِّث المنزل"), ImageFont.truetype(AR_FONT, int(S * 0.052)), S * 0.65, S)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    here = Path(__file__).resolve().parent
    root = here.parent.parent
    inst = root / "02_التطوير" / "installer" / "assets"
    gen = here / "generated"
    inst.mkdir(parents=True, exist_ok=True)
    gen.mkdir(parents=True, exist_ok=True)

    # Large wizard image (Welcome/Finished) — 100% + 200% for high DPI.
    for w, h, suffix in [(164, 314, ""), (328, 628, "@2x")]:
        draw_banner(w, h).save(inst / f"wizard-large{suffix}.bmp")
    draw_banner(164, 314).save(gen / "wizard-large.png")  # preview

    # Small wizard image (interior page header) — just the mark.
    for w, h, suffix in [(55, 58, ""), (110, 116, "@2x")]:
        draw_banner(w, h, house_y=0.5, house_w=0.66, name=False).save(
            inst / f"wizard-small{suffix}.bmp"
        )
    draw_banner(55, 58, house_y=0.5, house_w=0.66, name=False).save(gen / "wizard-small.png")

    # App splash (PNG).
    draw_splash(800).save(gen / "splash-800.png")

    for p in sorted(inst.glob("wizard-*.bmp")) + sorted(gen.glob("wizard-*.png")) + [
        gen / "splash-800.png"
    ]:
        print("  ", p.relative_to(root))


if __name__ == "__main__":
    main()
