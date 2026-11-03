#!/usr/bin/env python3
"""Images cut from gearmulator's Vavra skin "mqDefault" (skin/mqDefault/, by theusualsuspects, GPL-3.0):
  skin/parts/bg.png           the ring background at the MPC's 1280 x 628 (a part of mqDefaultBG.png without its buttons and LCD)
  skin/parts/logo.png         the "theusualsuspects / DSP56300 Emulator / Vavra" corner of mqDefaultBG.png
  vst/images/knob_mq.png      the encoder filmstrip (encoder_ranged_page0.png: 96 frames of 128 px in a 16 x 6 grid -> 101 frames of 104 px)
  vst/images/tile.png         the 270 x 110 Instruments-browser tile
Committed outputs, so a build does not need the large sources."""
import os
from PIL import Image, ImageFilter

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SK = os.path.join(ROOT, "skin", "mqDefault")
PARTS = os.path.join(ROOT, "skin", "parts")
IMG = os.path.join(ROOT, "vst", "images")
os.makedirs(PARTS, exist_ok=True)
os.makedirs(IMG, exist_ok=True)
W, H = 1280, 628

src = Image.open(os.path.join(SK, "mqDefaultBG.png")).convert("RGB")
bg = src.crop((425, 440, 3400, 1898)).resize((W, H), Image.LANCZOS)
bg.save(os.path.join(PARTS, "bg.png"))

# the logo with its own alpha: gold (r well above b) and black (far darker than the grey rings) stay, the rings go
logo = src.crop((2760, 60, 3392, 352))
out = Image.new("RGBA", logo.size)
lp, op = logo.load(), out.load()
for y in range(logo.height):
    for x in range(logo.width):
        r, g, b = lp[x, y]
        gold = (r - b - 40) / 80.0
        dark = (38 - (r + g + b) / 3) / 18.0
        a = int(255 * max(0.0, min(1.0, max(gold, dark))))
        op[x, y] = (r, g, b, a)
logo = out.crop(out.getbbox())
logo.save(os.path.join(PARTS, "logo.png"))

strip = Image.open(os.path.join(SK, "encoder_ranged_page0.png")).convert("RGBA")
fw = strip.width // 16
n = (strip.width // fw) * (strip.height // fw)
film = Image.new("RGBA", (104, 104 * 101))
for i in range(101):
    f = i * (n - 1) // 100
    x0, y0 = (f % 16) * fw, (f // 16) * fw
    film.paste(strip.crop((x0, y0, x0 + fw, y0 + fw)).resize((104, 104), Image.LANCZOS), (0, i * 104))
film.save(os.path.join(IMG, "knob_mq.png"))

tile = bg.resize((270, 110), Image.LANCZOS)
s = min(250 / logo.width, 100 / logo.height)
l = logo.resize((int(logo.width * s), int(logo.height * s)), Image.LANCZOS)
tile.paste(l, ((270 - l.width) // 2, (110 - l.height) // 2), l)
tile.save(os.path.join(IMG, "tile.png"))
print("assets written (%d knob source frames)" % n)
