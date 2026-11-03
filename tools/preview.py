#!/usr/bin/env python3
"""Offline preview of the skin: every page of vst/layout.conf with its controls drawn on the page art in the layout's theme colours
(knobs from the layout's own filmstrip, sample texts in readouts, steppers, popups and lists). Approximate: MPC draws the real thing.
    tools/preview.py <out dir> [page ...]       writes <out dir>/<page>.png (1280 x 628, the plugin area)"""
import json, os, re, sys
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
VST = os.path.join(ROOT, "vst")
Y86 = 86
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(VST, "preview")
WANT = set(sys.argv[2:])
os.makedirs(OUT, exist_ok=True)
FONT = os.path.join(VST, "fonts", "LiberationSans-Bold.ttf")
_f = {}
def F(n):
    if n not in _f:
        _f[n] = ImageFont.truetype(FONT, n)
    return _f[n]

P = {p["key"]: p for p in json.load(open(os.path.join(VST, "params.json")))["params"]}
SAMPLE = {"bank_name": "BANK A", "preset_name": "A001 LosAngeles2019 T", "lcd1": "Inst:1  Sound:A001", "lcd2": "  LosAngeles2019 T",
          "loading_status": "Ready - ROM loaded", "engine_stats": "DROPOUTS 0   CPU 40%", "patch_page_text": "PAGE 1 / 4", "bank_page_text": "1 / 1",
          "fav_text": "FAVOURITES 3 / 64"}
NAMES = ["LosAngeles2019 T", "Rain        WMF", "Chor 2.0      S", "Zeitlos       T", "Expensive  WMF", "OBX Purple5 PROX", "Queen-mom    HM",
         "Juanita      HM", "Demolition   DK", "The Showroom  T"]
FX = {"fx1_l1": "DRIVE", "fx1_l2": "POST GAIN", "fx1_l5": "CUTOFF", "fx2_l1": "SIZE", "fx2_l2": "SHAPE", "fx2_l3": "DECAY", "fx2_l4": "PRE DELAY",
      "fx2_l6": "LOWPASS", "fx2_l7": "HIGHPASS", "fx2_l8": "DIFFUSION", "fx2_l9": "DAMPING"}


def hexc(s):
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


lines = open(os.path.join(VST, "layout.conf")).read().split("\n")
theme = {}
for l in lines:
    m = re.match(r"(theme_\w+|knob_strip)=(\S+)", l)
    if m:
        theme[m.group(1)] = m.group(2)
T = lambda k: hexc(theme[k])
strip = Image.open(os.path.join(VST, theme["knob_strip"])).convert("RGBA")
NFR = strip.height // strip.width


def attrs(l):
    return {k: v.strip('"') for k, v in re.findall(r'(\w+)=("[^"]*"|\S+)', l)}


def value_text(key, i):
    p = P.get(key, {})
    if "options" in p:
        return p["options"][min(len(p["options"]) - 1, (i * 3) % len(p["options"]))]
    return str(p.get("default", 64))


def render(name, ws, art):
    im = Image.open(os.path.join(VST, art)).convert("RGB")
    d = ImageDraw.Draw(im)
    for i, (op, a) in enumerate(ws):
        cx, cy = int(a.get("cx", 0)), int(a.get("cy", 0)) - Y86
        key = a.get("key", "")
        if op == "knob":
            r = int(a["r"]) + 4
            fr = strip.crop((0, strip.width * ((i * 37) % NFR), strip.width, strip.width * ((i * 37) % NFR + 1))).resize((2 * r + 8, 2 * r + 8), Image.LANCZOS)
            im.paste(fr, (cx - r - 4, cy - r - 4), fr)
            vs = int(a.get("vs", 18))
            d.text((cx, cy + r + int(a.get("vy", 10))), value_text(key, i), font=F(max(12, vs - 6)), fill=T("theme_ink"), anchor="ma")
        elif op == "toggle":
            d.rounded_rectangle((cx - 26, cy - 13, cx + 26, cy + 13), 13, fill=T("theme_box"))
            d.ellipse((cx - 22 + (26 if i % 2 else 0), cy - 9, cx - 4 + (26 if i % 2 else 0), cy + 9), fill=T("theme_accent"))
        elif op == "popup":
            w, h = int(a["w"]), int(a["h"])
            d.rectangle((cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2), fill=T("theme_box"), outline=T("theme_line"))
            d.text((cx - 10, cy), value_text(key, i), font=F(15), fill=T("theme_accent"), anchor="mm")
            d.polygon([(cx + w // 2 - 26, cy - 5), (cx + w // 2 - 12, cy - 5), (cx + w // 2 - 19, cy + 5)], fill=T("theme_accent"))
        elif op in ("readout", "stepper"):
            w, h = int(a["w"]), int(a["h"])
            txt = SAMPLE.get(a.get("get", key), FX.get(key, ""))
            if a.get("box") == "0":
                d.text((cx, cy), txt, font=F(int(a.get("tsize", 14))), fill=hexc(a.get("tcolor", theme["theme_ink"])), anchor="mm")
                continue
            dot = a.get("style") == "dotmatrix"
            bg, ink = (T("theme_display_bg"), T("theme_display_ink")) if dot else (T("theme_lcd"), T("theme_accent"))
            x0 = cx - w // 2
            if op == "stepper":
                d.rounded_rectangle((x0, cy - h // 2 - 4, x0 + w, cy + h // 2 + 4), 8, fill=T("theme_display_bezel"))
                d.polygon([(x0 + 14, cy), (x0 + 26, cy - 9), (x0 + 26, cy + 9)], fill=T("theme_display_bg"))
                d.polygon([(x0 + w - 14, cy), (x0 + w - 26, cy - 9), (x0 + w - 26, cy + 9)], fill=T("theme_display_bg"))
                x0, w = x0 + 34, w - 68
            elif dot:
                d.rounded_rectangle((x0 - 4, cy - h // 2 - 4, x0 + w + 4, cy + h // 2 + 4), 6, fill=T("theme_display_bezel"))
            d.rectangle((x0, cy - h // 2, x0 + w, cy + h // 2), fill=bg)
            if dot:
                for yy in range(cy - h // 2 + 2, cy + h // 2, 3):
                    d.line((x0, yy, x0 + w, yy), fill=T("theme_display_cell"))
            d.text((x0 + 12 if op == "stepper" else cx, cy), txt, font=F(17), fill=ink, anchor="lm" if op == "stepper" else "mm")
        elif op == "button":
            w, h = int(a.get("w", 120)), int(a.get("h", 50))
            d.rounded_rectangle((cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2), 4, fill=T("theme_btn_bg"))
            d.text((cx, cy), a.get("label", ""), font=F(18), fill=T("theme_btn_text"), anchor="mm")
        elif op == "list":
            x, y, w, h = int(a["x"]), int(a["y"]) - Y86, int(a["w"]), int(a["h"])
            cols, rows, gap, th = int(a["cols"]), int(a["rows"]), int(a["gap"]), int(a["th"])
            cw = (w - gap * (cols - 1)) / cols
            for c in range(cols):
                for r in range(rows):
                    n = c * rows + r if a.get("order") == "cols" else r * cols + c
                    x0, y0 = int(x + c * (cw + gap)), y + r * (th + gap)
                    on = n == 0
                    d.rectangle((x0, y0, int(x0 + cw), y0 + th), fill=T("theme_tile_on") if on else T("theme_box"))
                    t = (["BANK A", "BANK B", "BANK C", "MICROQ FACTORYSET 2000 A", "MICROQ FACTORYSET 2000 B", "MICROQ FACTORYSET 2000 C",
                         "MQ FACTORY2001 A", "MQ FACTORY2001 B", "MQ FACTORY2001 C", ""][n] if n < 10 else "") if key == "bank_slot" else "%03d %s" % (n + 1, NAMES[n % len(NAMES)])
                    d.text((x0 + 12, y0 + th // 2), t, font=F(15), fill=(255, 255, 255) if on else T("theme_accent"), anchor="lm")
    im.save(os.path.join(OUT, re.sub(r"[^A-Za-z0-9]+", "_", name) + ".png"))


tab, ws, art = None, [], None
for l in lines + ["[tab END]"]:
    m = re.match(r"\[tab (.+)\]", l)
    if m:
        if tab and (not WANT or tab in WANT):
            render(tab, ws, art)
        tab, ws, art = m.group(1), [], None
        continue
    op = l.split(" ", 1)[0]
    if op == "art":
        art = attrs(l)["file"]
    elif op in ("knob", "toggle", "popup", "readout", "stepper", "button", "list"):
        ws.append((op, attrs(l)))
print("preview:", OUT)
