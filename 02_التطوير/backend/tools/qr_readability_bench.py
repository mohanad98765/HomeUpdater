"""Measure whether the pairing QR is actually readable — and what changing it buys.

Run:  python tools/qr_readability_bench.py
Needs (measurement only, deliberately NOT in requirements.txt):  zxing-cpp  pillow

## Why this exists

QR pairing failed five times in a row and the failures looked like a network problem.
Three changes were made on reasoning alone — a lower error-correction level, an integer
pixel multiple, and crispEdges — and none of them was measured. This is what measuring
them looked like, and the result contradicted the reasoning:

    candidate                       px/module   smallest capture that decodes
                                                sharp   blur .8  blur 1.5  blur 2.5
    Q, 230px  (the "too small" one)   5.61        60px     75px     130px     205px
    Q, 300px                          7.32        60px     75px     130px     205px
    L, 296px  (current)               8.00        60px     70px     120px     185px

The code that was blamed for the failures decodes from a 60-pixel capture. A phone
framing it at 25cm gives the sensor several hundred pixels. So SIZE WAS NOT THE CAUSE,
and the current settings are a real but modest 7-10% margin improvement, kept because
they are free — not because they fixed anything.

The refutation that mattered: L corrects 7% of the symbol where Q corrects 25%, so L
should lose on a noisy image. It does not — both fail at 1% speckle, because speckle at
that density destroys module sampling rather than a few codewords. The trade is safe.

Keep this runnable. The next person to propose "make the code bigger" should have to
answer this table first.
"""

from __future__ import annotations

import io
import random

import segno

try:
    import zxingcpp
    from PIL import Image, ImageFilter
except ImportError:  # pragma: no cover - a measurement tool, not part of the app
    raise SystemExit("pip install zxing-cpp pillow") from None

PAYLOAD = "WIFI:T:ADB;S:homeupdater-3dnkr7j3;P:698797;;"

CANDIDATES = {
    "Q, 230px (pre-1.18.2)": {"error": "q", "box": 230},
    "Q, 300px (1.18.2)": {"error": "q", "box": 300},
    "L, 296px (current)": {"error": "l", "box": 296},
}


def render(error: str, box: int) -> Image.Image:
    q = segno.make(PAYLOAD, error=error)
    modules = q.symbol_size(border=4)[0]
    buf = io.BytesIO()
    q.save(buf, kind="png", scale=max(1, round(box / modules)), border=4)
    img = Image.open(buf).convert("L")
    if img.width != box:  # the CSS stretch older builds applied
        img = img.resize((box, box), Image.Resampling.BILINEAR)
    return img


def capture(img: Image.Image, width: int, blur: float) -> Image.Image:
    """Model a camera: the symbol lands on `width` sensor pixels, softened by optics."""
    small = img.resize((width, width), Image.Resampling.LANCZOS)
    return small.filter(ImageFilter.GaussianBlur(blur)) if blur else small


def decodes(img: Image.Image) -> bool:
    return any(r.text == PAYLOAD for r in zxingcpp.read_barcodes(img))


def smallest_capture(img: Image.Image, blur: float) -> int | None:
    for width in range(60, 401, 5):
        if decodes(capture(img, width, blur)):
            return width
    return None


def main() -> None:
    print(f"payload ({len(PAYLOAD)} chars): {PAYLOAD}\n")
    header = f"{'candidate':24} {'px/module':>10}"
    for label in ("sharp", "blur.8", "blur1.5", "blur2.5"):
        header += f"{label:>8}"
    print(header)
    print("-" * 72)
    for name, cfg in CANDIDATES.items():
        img = render(**cfg)
        modules = segno.make(PAYLOAD, error=cfg["error"]).symbol_size(border=4)[0]
        margins = [smallest_capture(img, b) for b in (0.0, 0.8, 1.5, 2.5)]
        cells = "".join(f"{(str(m) + 'px' if m else 'never'):>8}" for m in margins)
        print(f"{name:24} {img.width / modules:>10.2f}{cells}")

    print("\nnoise tolerance (the reason to doubt the lower error level):")
    random.seed(7)
    print(f"    {'speckle':>8}  {'Q, 230px':>10}  {'L, 296px':>10}")
    for fraction in (0.0, 0.01, 0.03, 0.06):
        row = []
        for key in ("Q, 230px (pre-1.18.2)", "L, 296px (current)"):
            img = capture(render(**CANDIDATES[key]), 300, 0.5)
            px = img.load()
            for _ in range(int(img.width * img.height * fraction)):
                x, y = random.randrange(img.width), random.randrange(img.height)
                px[x, y] = 255 if px[x, y] < 128 else 0
            row.append(decodes(img))
        print(f"    {fraction:>7.0%}  {str(row[0]):>10}  {str(row[1]):>10}")


if __name__ == "__main__":
    main()
