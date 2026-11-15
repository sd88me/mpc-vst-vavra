#!/usr/bin/env python3
"""Vavra's art library: the primitives of the native skin, drawn from code in the look of the microQ's front panel and its editor
(yellow panel, blue matrix labels and section frames, black knobs with a white pointer, the red cutoff, a green LCD in a blue band,
black oval keys with a red LED). tools/make_tui.py lays the pages out from these; a restyle is this file only.

Fonts: Titillium Web (SIL OFL 1.1, tools/fonts/) for everything baked; the MPC draws live text in Titillium Web too."""
import math, os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIT = os.path.join(ROOT, "tools", "fonts", "TitilliumWeb-SemiBold.ttf")
TIT_B = os.path.join(ROOT, "tools", "fonts", "TitilliumWeb-Bold.ttf")

# ---- palette ---------------------------------------------------------------------------------------------------------------
YELLOW = (246, 204, 18)        # the microQ's panel
YELLOW_HI = (252, 222, 70)     # the panel's faint sweeps
YELLOW_LO = (226, 184, 10)
BLUE = (28, 98, 178)           # matrix labels, section frames, the band behind the display
BLUE_DK = (16, 58, 118)        # captions, the band's outline
BLUE_LT = (98, 160, 222)
CREAM = (255, 240, 176)        # pick-list fields (the editor's)
INK = (20, 30, 60)             # values
LCD = (128, 206, 64)           # the editor's bright green LCD
LCD_HI = (150, 222, 84)
LCD_DK = (70, 130, 30)
LCD_INK = (14, 34, 10)
KEY = (24, 24, 26)
LED_ON = (255, 52, 36)
LED_OFF = (120, 40, 30)
WHITE = (255, 255, 255)

THEME = "microq"


def set_theme(name):
    """The skin switch's second theme goes here (make_tui.py builds every page once per theme in VAVRA_THEMES): swap the palette above
    for that theme's colours. Only "microq" is drawn so far; any other name draws the same art (the switch and the doubled TUI work)."""
    global THEME
    THEME = name


_fonts = {}


def F(size, bold=True):
    k = (size, bold)
    if k not in _fonts:
        _fonts[k] = ImageFont.truetype(TIT_B if bold else TIT, size)
    return _fonts[k]


def fit(text, size, width, bold=True):
    """the largest font up to `size` that fits `width`"""
    while size > 9 and F(size, bold).getlength(text) > width:
        size -= 1
    return F(size, bold)


def italic(im, shear=0.22):
    """shear an RGBA image to the right (an oblique for the matrix-label look: Titillium has no italic here)"""
    w, h = im.size
    extra = int(h * shear) + 2
    return im.transform((w + extra, h), Image.AFFINE, (1, shear, -shear * h, 0, 1, 0), Image.BICUBIC)


def text_img(text, size, colour, bold=True, slant=0.0):
    f = F(size, bold)
    l, t, r, b = f.getbbox(text)
    im = Image.new("RGBA", (r - l + 4, b - t + 4), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((2 - l, 2 - t), text, font=f, fill=colour)
    return italic(im, slant) if slant else im


def paste_center(base, im, cx, cy):
    base.alpha_composite(im, (int(cx - im.width / 2), int(cy - im.height / 2)))


# ---- the panel -------------------------------------------------------------------------------------------------------------
def panel(w=1280, h=628, seed=0):
    """The yellow panel: a slight top-to-bottom shade and the long faint sweeps of the microQ editor's background."""
    im = Image.new("RGBA", (w, h), YELLOW + (255,))
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / h
        d.line((0, y, w, y), fill=(int(248 - 8 * t), int(208 - 12 * t), int(22 - 8 * t), 255))
    sw = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ds = ImageDraw.Draw(sw)
    for i, (cx, cy, r) in enumerate(((-300, 900, 1100), (-260, 960, 1230), (1500, -500, 1050), (1580, -560, 1200), (640, 1500, 1260))):
        ds.ellipse((cx - r, cy - r, cx + r, cy + r), outline=YELLOW_HI + (200,), width=5)
        ds.ellipse((cx - r + 7, cy - r + 7, cx + r - 7, cy + r - 7), outline=YELLOW_LO + (120,), width=2)
    im.alpha_composite(sw)
    return im


def section(im, x0, y0, x1, y1, title, title_w=None, icons=False):
    """A section of the editor: a blue rounded frame and a filled blue title tab at its top left (white oblique caps)."""
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((x0, y0, x1, y1), 9, outline=BLUE + (255,), width=3)
    t = text_img(title.upper(), 19, WHITE, slant=0.2)
    tw = title_w or t.width + 26
    tab = Image.new("RGBA", (tw, 28), (0, 0, 0, 0))
    td = ImageDraw.Draw(tab)
    td.rounded_rectangle((0, 0, tw - 1, 27), 7, fill=BLUE + (255,))
    td.rectangle((0, 14, tw - 1, 27), fill=BLUE + (255,))
    im.alpha_composite(tab, (x0, y0))
    im.alpha_composite(t, (x0 + 12, y0 + 14 - t.height // 2 + 1))


def caption(im, cx, cy, text, size=17, colour=BLUE_DK, width=120):
    f = fit(text, size, width)
    ImageDraw.Draw(im).text((cx, cy), text, font=f, fill=colour + (255,), anchor="mm")


def knob_marker(im, cx, top):
    """the editor's small blue triangle over a knob (its centre position)"""
    ImageDraw.Draw(im).polygon([(cx - 5, top - 6), (cx + 5, top - 6), (cx, top)], fill=BLUE + (255,))


def well(im, x0, y0, x1, y1, r=6):
    """a darker recess in the panel behind a group (switches, the LCD mirror)"""
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((x0, y0, x1, y1), r, fill=YELLOW_LO + (255,))


# ---- knobs -------------------------------------------------------------------------------------------------------------------
def _knob_base(size, red):
    """The cap and skirt, shaded per pixel at 4x (light from the upper left): a ribbed black skirt like the editor's knobs, a dark
    groove, a glossy domed cap with a broad specular highlight. The light does not turn with the knob, so one base serves every frame."""
    S = 4
    n = size * S
    R = n / 2.0 - 3 * S                     # the skirt's outer radius (room for the shadow)
    cx = cy = n / 2.0 - 1.5 * S
    L = (-0.45, -0.62, 0.64)
    ln = math.sqrt(sum(v * v for v in L))
    L = tuple(v / ln for v in L)
    H = (L[0], L[1], L[2] + 1.0)            # half vector (viewer on +z)
    hn = math.sqrt(sum(v * v for v in H))
    H = tuple(v / hn for v in H)
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    px = im.load()
    ribs = 44
    capc = (150, 22, 18) if red else (26, 26, 28)
    for y in range(n):
        for x in range(n):
            dx, dy = x + 0.5 - cx, y + 0.5 - cy
            r = math.hypot(dx, dy) / R
            if r > 1.0:
                continue
            th = math.atan2(dy, dx)
            ux, uy = math.cos(th), math.sin(th)
            if r > 0.70:                                    # skirt: a cone with ribs
                t = math.sin(ribs * th)
                nr, nt, nz = 0.55, 0.55 * t, 0.62
                nx, ny = nr * ux - nt * uy, nr * uy + nt * ux
                if r > 0.95:                                # the rounded outer edge falls away
                    k = (r - 0.95) / 0.05
                    nx, ny, nz = nx + ux * k, ny + uy * k, nz * (1 - 0.7 * k)
                nl = math.sqrt(nx * nx + ny * ny + nz * nz)
                nx, ny, nz = nx / nl, ny / nl, nz / nl
                dif = max(0.0, nx * L[0] + ny * L[1] + nz * L[2])
                spc = max(0.0, nx * H[0] + ny * H[1] + nz * H[2]) ** 24
                g = 12 + 70 * dif + 150 * spc
                col = (g, g, g + 3)
            elif r > 0.655:                                 # the groove between skirt and cap
                g = 6 + 10 * (1 - abs(r - 0.68) / 0.03)
                col = (g, g, g)
            else:                                           # the cap: a shallow dome, glossy
                q = r / 0.655
                nx, ny = ux * q * 0.42, uy * q * 0.42
                nz = math.sqrt(max(0.0, 1 - nx * nx - ny * ny))
                dif = max(0.0, nx * L[0] + ny * L[1] + nz * L[2])
                spc = max(0.0, nx * H[0] + ny * H[1] + nz * H[2]) ** 40
                spc2 = max(0.0, nx * H[0] + ny * H[1] + nz * H[2]) ** 6
                base = [c * (0.55 + 0.6 * dif) for c in capc]
                col = tuple(b + 210 * spc + 26 * spc2 for b in base)
                if q > 0.93:                                # a fine bevel at the cap's edge
                    col = tuple(c * 0.75 for c in col)
            px[x, y] = tuple(int(min(255, max(0, c))) for c in col) + (255,)
    # the drop shadow on the panel, under everything
    sh = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse((cx - R + 2 * S, cy - R + 4 * S, cx + R + 3 * S, cy + R + 5 * S), fill=(60, 40, 0, 120))
    sh = sh.filter(ImageFilter.GaussianBlur(3 * S))
    sh.alpha_composite(im)
    return sh, (cx, cy, R)


def knob_strip(size=76, frames=101, red=False):
    """The editor's knob as a film strip: the shaded base plus a white pointer line on the cap (cream on the red cutoff cap),
    -135 .. +135 degrees over the frames."""
    S = 4
    base, (cx, cy, R) = _knob_base(size, red)
    out = Image.new("RGBA", (size, size * frames), (0, 0, 0, 0))
    pointer = (255, 240, 220, 255) if red else (246, 246, 246, 255)
    for f in range(frames):
        im = base.copy()
        d = ImageDraw.Draw(im)
        a = math.radians(-135 + 270 * f / (frames - 1) - 90)
        x0, y0 = cx + math.cos(a) * R * 0.16, cy + math.sin(a) * R * 0.16
        x1, y1 = cx + math.cos(a) * R * 0.60, cy + math.sin(a) * R * 0.60
        d.line((x0 + S, y0 + S, x1 + S, y1 + S), fill=(0, 0, 0, 120), width=int(3.4 * S))       # its shadow on the cap
        d.line((x0, y0, x1, y1), fill=pointer, width=int(3.4 * S))
        d.ellipse((x1 - 1.7 * S, y1 - 1.7 * S, x1 + 1.7 * S, y1 + 1.7 * S), fill=pointer)
        d.ellipse((x0 - 1.7 * S, y0 - 1.7 * S, x0 + 1.7 * S, y0 + 1.7 * S), fill=pointer)
        out.paste(im.resize((size, size), Image.LANCZOS), (0, f * size))
    return out


# ---- fields, keys, switches ------------------------------------------------------------------------------------------------
def pick_field(im, cx, cy, w, h=34):
    """A pick-list field (static art): the editor's cream field in a blue frame, a blue arrow at the right; the choice is live text."""
    d = ImageDraw.Draw(im)
    x0, y0 = cx - w // 2, cy - h // 2
    d.rounded_rectangle((x0, y0, x0 + w, y0 + h), 5, fill=BLUE + (255,))
    d.rounded_rectangle((x0 + 2, y0 + 2, x0 + w - 30, y0 + h - 2), 4, fill=CREAM + (255,))
    ax, ay = x0 + w - 15, cy + 1
    d.polygon([(ax - 7, ay - 4), (ax + 7, ay - 4), (ax, ay + 5)], fill=WHITE + (255,))


def list_key(w, h, text, lit, size=16):
    """a row of a drawn pick-list: cream, lit = the current choice (blue, white text)"""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if lit:
        d.rounded_rectangle((0, 0, w - 1, h - 1), 4, fill=BLUE_DK + (255,), outline=WHITE + (255,), width=2)
    else:
        d.rounded_rectangle((0, 0, w - 1, h - 1), 4, fill=CREAM + (255,), outline=BLUE + (255,), width=1)
    f = fit(text, size, w - 12)
    d.text((w // 2, h // 2), text, font=f, fill=(WHITE if lit else INK) + (255,), anchor="mm")
    return im


def key_cap(w, h, text, lit, size=26):
    """a key of the naming keyboard: a cream cap with a blue rim and a darker lower edge; lit (held) = blue with white text"""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 3, w - 1, h - 1), 7, fill=BLUE_DK + (255,))
    if lit:
        d.rounded_rectangle((0, 3, w - 1, h - 1), 7, fill=BLUE + (255,), outline=WHITE + (255,), width=2)
    else:
        d.rounded_rectangle((0, 0, w - 1, h - 5), 7, fill=CREAM + (255,), outline=BLUE + (255,), width=2)
    f = fit(text, size, w - 12)
    d.text((w // 2, (h - 2) // 2 + (2 if lit else 0)), text, font=f, fill=(WHITE if lit else INK) + (255,), anchor="mm")
    return im


def list_panel(w, h, title="SELECT"):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w - 1, h - 1), 10, fill=BLUE_DK + (255,))
    d.rounded_rectangle((3, 3, w - 4, h - 4), 8, fill=BLUE + (255,))
    t = text_img(title, 20, WHITE, slant=0.2)
    im.alpha_composite(t, (16, 23 - t.height // 2))
    return im


def oval_key(w, h, caption, lit, size=15, cap_w=46, cap_h=24, ink=BLUE_DK):
    """A microQ panel key: a black oval cap (the Inst / Edit keys), a small red LED up to its right (lit while held), the caption
    printed under it in blue."""
    S = 4
    im = Image.new("RGBA", (w * S, h * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, cy = w * S // 2, (cap_h // 2 + 12) * S
    rx, ry = cap_w * S // 2, cap_h * S // 2
    d.ellipse((cx - rx + S, cy - ry + 3 * S, cx + rx + S, cy + ry + 3 * S), fill=(70, 50, 0, 110))
    d.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=(6, 6, 8, 255))
    for i in range(10):
        t = i / 10
        g = int(26 + t * 26) - (8 if lit else 0)
        d.ellipse((cx - rx + (2 + i) * S - int(t * 4 * S), cy - ry + (2 + i * 0.6) * S - int(t * 3 * S),
                   cx + rx - (2 + i) * S - int(t * 4 * S), cy + ry - (2 + i * 0.6) * S - int(t * 3 * S)), fill=(g, g, g + 2, 255))
    lx, ly, lr = cx + rx + 7 * S, cy - ry - 2 * S, 4 * S
    if lit:
        glow = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse((lx - 3 * lr, ly - 3 * lr, lx + 3 * lr, ly + 3 * lr), fill=(255, 60, 30, 170))
        im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(4 * S)))
        d = ImageDraw.Draw(im)
    d.ellipse((lx - lr - S, ly - lr - S, lx + lr + S, ly + lr + S), fill=(60, 40, 0, 255))
    d.ellipse((lx - lr, ly - lr, lx + lr, ly + lr), fill=(LED_ON if lit else LED_OFF) + (255,))
    d.ellipse((lx - lr // 2 - S, ly - lr // 2 - S, lx, ly), fill=(255, 200, 180, 255) if lit else (170, 90, 80, 255))
    im = im.resize((w, h), Image.LANCZOS)
    ImageDraw.Draw(im).text((w // 2, h - size // 2 - 3), caption, font=fit(caption, size, w - 4), fill=ink + (255,), anchor="mm")
    return im


def switch_image(lit, w=76, h=36):
    """The editor's switch: a black oval with a grey thumb, the red LED beside it lit when on."""
    S = 4
    im = Image.new("RGBA", (w * S, h * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    ow, oh = 40 * S, 20 * S
    oy = (h * S - oh) // 2
    d.rounded_rectangle((0, oy + S, ow, oy + oh + S), oh // 2, fill=(70, 50, 0, 110))
    d.rounded_rectangle((0, oy, ow - S, oy + oh - S), oh // 2, fill=(10, 10, 12, 255))
    tx = ow - oh // 2 - 2 * S if lit else oh // 2 + S
    d.ellipse((tx - 7 * S, oy + oh // 2 - 7 * S, tx + 7 * S, oy + oh // 2 + 7 * S), fill=(150, 150, 154, 255) if lit else (88, 88, 92, 255))
    lx, ly, lr = ow + 12 * S, h * S // 2, 5 * S
    if lit:
        glow = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse((lx - 2 * lr, ly - 2 * lr, lx + 2 * lr, ly + 2 * lr), fill=(255, 60, 30, 150))
        im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(4 * S)))
        d = ImageDraw.Draw(im)
    d.ellipse((lx - lr - S, ly - lr - S, lx + lr + S, ly + lr + S), fill=(150, 150, 150, 255))
    d.ellipse((lx - lr, ly - lr, lx + lr, ly + lr), fill=(LED_ON if lit else (196, 180, 170)) + (255,))
    return im.resize((w, h), Image.LANCZOS)


def arrow_image(w, h, direction, lit, colour=LCD_INK):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if lit:
        d.rounded_rectangle((2, 2, w - 3, h - 3), 4, fill=colour + (70,))
    return im


def tri(d, cx, cy, direction, s=9, colour=LCD_INK):
    d.polygon([(cx + direction * s * 0.7, cy), (cx - direction * s * 0.7, cy - s), (cx - direction * s * 0.7, cy + s)], fill=colour + (255,))


# ---- the display: a green LCD in the blue band of the microQ's front -------------------------------------------------------
def band(im, x0, y0, x1, y1, oval=None):
    """The blue band the microQ's LCD sits in, and the thin blue oval that sweeps around the panel's top half."""
    d = ImageDraw.Draw(im)
    if oval:
        ox0, oy0, ox1, oy1 = oval
        d.ellipse((ox0, oy0, ox1, oy1), outline=BLUE + (255,), width=3)
    d.rectangle((x0, y0, x1, y1), fill=BLUE + (255,))
    d.line((x0, y0, x1, y0), fill=BLUE_DK + (255,), width=2)
    d.line((x0, y1, x1, y1), fill=BLUE_DK + (255,), width=2)


def lcd(im, x0, y0, x1, y1, cells=12):
    """A backlit green LCD (static art): a dark frame, brighter in the middle, faint character cells."""
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((x0 - 5, y0 - 5, x1 + 5, y1 + 5), 5, fill=(18, 30, 54, 255))
    for y in range(y0, y1 + 1):
        t = abs((y - y0) / max(1, y1 - y0) - 0.45) * 2
        d.line((x0, y, x1, y), fill=(int(LCD_HI[0] - 34 * t), int(LCD_HI[1] - 30 * t), int(LCD_HI[2] - 30 * t), 255))
    if cells:
        for x in range(x0 + 3, x1 - 2, cells):
            d.line((x, y0 + 3, x, y1 - 3), fill=(LCD[0] + 6, LCD[1] + 4, LCD[2] + 2, 255))
    for i, a in enumerate((90, 60, 30)):
        d.line((x0, y0 + i, x1, y0 + i), fill=(20, 60, 10, a))


def wordmark(im, x, y, h=64):
    """The plugin's own badge (not the hardware's logo): "Vavra" in panel yellow, oblique, on the blue band, with a small subtitle."""
    t = text_img("Vavra", int(h * 1.05), YELLOW + (255,), slant=0.22)
    im.alpha_composite(t, (x, y))
    s = text_img("DSP56300 EMULATOR", 13, WHITE + (255,), bold=True, slant=0.15)
    im.alpha_composite(s, (x + 8, y + t.height - 2))
