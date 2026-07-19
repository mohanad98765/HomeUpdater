"""
Generate the HomeUpdater icon set from the built-in default brand mark.

The mark: a rounded blue tile (brand gradient #1E88E5 -> #0D47A1) with a white
house and a teal (#26A69A) upward "upgrade" arrow — i.e. "home + update".

Run with any Python that has Pillow:
    python generate_icons.py

Outputs (created relative to the repo root):
  03_الموارد/logo/generated/   — PNGs at every size + master + .ico
  02_التطوير/backend/assets/    — HomeUpdater.ico + tray.png (for the exe/tray)
  02_التطوير/installer/assets/  — HomeUpdater.ico (for Inno Setup)

To use a REAL logo instead: drop logo-source.png (>=1024, square, transparent)
here and adapt this script to open+resize it rather than draw the default.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SS = 4  # supersample factor for smooth edges

TOP = (30, 136, 229)  # #1E88E5
BOTTOM = (13, 71, 161)  # #0D47A1
WHITE = (255, 255, 255, 255)
TEAL = (38, 166, 154, 255)  # #26A69A


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def draw_icon(size: int) -> Image.Image:
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # vertical brand gradient, clipped to a rounded square
    grad = Image.new("RGB", (s, s), BOTTOM)
    gd = ImageDraw.Draw(grad)
    for y in range(s):
        gd.line([(0, y), (s, y)], fill=_lerp(TOP, BOTTOM, y / s))
    mask = Image.new("L", (s, s), 0)
    margin = int(s * 0.045)
    radius = int(s * 0.225)
    ImageDraw.Draw(mask).rounded_rectangle(
        [margin, margin, s - margin, s - margin], radius=radius, fill=255
    )
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)

    def u(v: float) -> int:  # 1024-space -> supersampled pixels
        return int(v / 1024 * s)

    # white house (roof triangle + rounded body, overlapping to unify)
    d.polygon([(u(512), u(298)), (u(250), u(520)), (u(774), u(520))], fill=WHITE)
    d.rounded_rectangle([u(330), u(490), u(694), u(788)], radius=u(30), fill=WHITE)

    # teal upward "upgrade" arrow inside the house body
    d.polygon([(u(512), u(560)), (u(446), u(642)), (u(578), u(642))], fill=TEAL)
    d.rounded_rectangle([u(485), u(632), u(539), u(742)], radius=u(12), fill=TEAL)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    here = Path(__file__).resolve().parent
    root = here.parent.parent  # 03_الموارد/logo -> 03_الموارد -> repo root
    generated = here / "generated"
    backend_assets = root / "02_التطوير" / "backend" / "assets"
    installer_assets = root / "02_التطوير" / "installer" / "assets"
    for p in (generated, backend_assets, installer_assets):
        p.mkdir(parents=True, exist_ok=True)

    master = draw_icon(1024)
    master.save(generated / "icon-1024.png")

    sizes = [16, 32, 48, 64, 128, 256]
    for n in sizes:
        draw_icon(n).save(generated / f"icon-{n}.png")

    # multi-resolution .ico (Windows exe / installer / favicon)
    ico_path = generated / "HomeUpdater.ico"
    master.save(ico_path, sizes=[(n, n) for n in sizes])

    # copies where the build tooling expects them
    for dest in (backend_assets / "HomeUpdater.ico", installer_assets / "HomeUpdater.ico"):
        master.save(dest, sizes=[(n, n) for n in sizes])
    draw_icon(64).save(backend_assets / "tray.png")

    print("Generated:")
    for p in sorted(generated.glob("*")):
        print("  ", p.relative_to(root))
    print("  ", (backend_assets / "HomeUpdater.ico").relative_to(root))
    print("  ", (backend_assets / "tray.png").relative_to(root))
    print("  ", (installer_assets / "HomeUpdater.ico").relative_to(root))


if __name__ == "__main__":
    main()
