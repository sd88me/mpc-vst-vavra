#!/usr/bin/env python3
"""Vavra's native MPC skin: skins/TUI.json + skins/Q-Links.json + the PNGs they use (docs/SDK-PORTING.md; the widget machinery is
Xenia's tools/make_tui.py). The art is drawn from code by tools/vavra_art.py in the look of the microQ's panel and editor; the pages are
laid out here, every control in a block of four with its own Q-Link frame (at most four blocks per sub-tab).

Popups are drawn pick-lists on ONE ui_open parameter (index 437; value k + 1 = the k-th popup of params.lock, the order the front end
uses). The bank and sound names in the displays take the data wheel and Q-Links (an invisible value field over each).
    python3 tools/make_tui.py              # -> skins/   (build-sdk.sh copies it to Plugin Skins/)
    python3 tools/make_tui.py --preview    # also docs/skin-preview/<tab>.png, composed offline (Titillium at the MPC's text scale)"""
import hashlib, json, os, re, shutil, sys
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vavra_art as A

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get("VAVRA_SKIN_OUT", os.path.join(ROOT, "skins"))
PREVIEW = os.environ.get("VAVRA_PREVIEW", os.path.join(ROOT, "docs", "skin-preview"))
LOCK = [l.strip() for l in open(os.path.join(ROOT, "params.lock")) if l.strip()]
PARAMS = {p["key"]: p for p in json.load(open(os.path.join(ROOT, "vst", "params.json")))["params"]}
POPUPS = [k[:-len("__open")] for k in LOCK if k.endswith("__open")]
UI_INDEX = LOCK.index(POPUPS[0] + "__open")          # 437: ui_open sits in the first popup slot
UI_STEPS = len(POPUPS) + 1                           # 0 closed, k + 1 = pick-list k
TUI_PX = 0.62                                        # a Label draws its text at about 0.62 x its height (Maze, on the device)
GESTURE = "Instant"
KNOB = 64
CLEAR = "clear.png"


def PI(key):
    return UI_INDEX if key == "ui_open" else LOCK.index(key)


def P(key):
    return "Parameter %d" % PI(key)


def hexcol(rgb, a=255):
    return "%02x%02x%02x%02x" % ((a,) + tuple(rgb))


# ---- a JSON writer that keeps key order and allows the overlay widgets' duplicate "version" key ------------------------------
class Obj:
    def __init__(self, *pairs):
        self.pairs = list(pairs)


def dump(v, ind=0):
    sp = "  " * ind
    pairs = v.pairs if hasattr(v, "pairs") else list(v.items()) if isinstance(v, dict) else None
    if pairs is not None:
        if not pairs:
            return "{}"
        return "{\n%s\n%s}" % (",\n".join("%s  %s: %s" % (sp, dump(k), dump(x, ind + 1)) for k, x in pairs), sp)
    if isinstance(v, list):
        return "[]" if not v else "[\n%s\n%s]" % (",\n".join(sp + "  " + dump(x, ind + 1) for x in v), sp)
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v) if isinstance(v, float) else str(v)
    return '"%s"' % str(v).replace("\\", "\\\\").replace('"', '\\"')


# ---- TUI building blocks --------------------------------------------------------------------------------------------------
def bounds(b, focus="No", ind=None):
    d = {"version": 2 if ind else 1, "acceptsHWFocus": focus, "showWhenDataModelInvalid": "Show", "whenVisible": "Always",
         "boundsType": "Absolute", "bounds": b}
    if ind:
        d["additionalInvalidatingHandles"] = ind
    return d


def entry(name, typ, data, b, remap=None, focus="No", ind=None, visible=None):
    e = {"version": 2, "componentData": {"version": 1, "name": name, "type": typ, "data": data},
         "handle remapping": {"version": 1, "map": [{"key": "Data", "value": remap}] if remap else []},
         "bounds": bounds(b, focus, ind)}
    if visible:
        e["bounds"]["whenVisible"] = visible
    return e


def bg(colour="0", image=""):
    return {"version": 1, "focussed": {"version": 1, "colour": colour, "image": image}, "unfocussed": {"version": 1, "colour": colour, "image": image}}


def component(children, actions=None, ignore=False, background=None):
    return {"version": 2, "actions": actions or [], "backgroundData": background or bg(), "ignoreMousePresses": ignore,
            "disableCoarseDataWheel": False, "componentsData": children}


def act(on, handler, extra=""):
    return {"version": 1, "onAction": on, "handler": handler, "handleName": "Data", "additionalData": extra}


def text_style(h, colour, just="horizontallyCentred verticallyCentred", style="SemiBold"):
    return {"version": 1, "font": {"version": 1, "name": "Titillium Web", "style": style, "height": float(h)}, "colour": colour,
            "justification": just, "case": "Original"}


def label(b, key, h=22, colour=None, just="horizontallyCentred verticallyCentred", style="SemiBold"):
    colour = colour or hexcol(A.INK)
    return entry("label", "Label", {"version": 1, "textStyle": text_style(h, colour, just, style), "type": "Value", "handleName": "Data"}, b, P(key))


FOCUS = {"version": 1, "backgroundColour": "00000000", "outlineColour": hexcol(A.BLUE_DK), "backgroundInset": 4.0, "outlineThickness": 2.0}
FIELDS = set()                                         # (w, h) of every display field that steps a value (display_row)
FIELD_KEY = {"bank_name": "bank_index", "preset_name": "preset"}


def definitions():
    def knob_def(strip):
        return component([
            entry("focus", "Focus", FOCUS, "-6 -6 %d %d" % (KNOB + 12, KNOB + 12), visible="WhenFocussed"),
            entry("knob", "Knob", {"version": 3, "knobType": "FilmStrip", "filmStrip": strip, "numFrames": 101, "invert": False,
                                   "dragOrientation": "Vertical", "handleName": "Data"}, "0 0 %d %d" % (KNOB, KNOB)),
        ], actions=[act("Mouse Down", "Q-Link"), act("Double Click", "Show Overlay", "knob overlay"), act("Enter Pressed", "Show Overlay", "knob overlay")])
    overlay = component([entry("overlay", "KnobOverlay", Obj(
        ("version", 2), ("version", 1),
        ("actions", [{"version": 1, "onAction": "Focus Lost", "handler": "Focus Lost", "handleName": "Focus Lost", "additionalData": ""}]),
        ("overlayType", "Knob With Header"), ("scaleType", "Linear"), ("polarityType", "Unipolar"),
        ("showMinusSign", True), ("handleName", "Data")), "0 0 1280 800", focus="Yes")], ignore=True)
    out = [{"key": "vknob", "value": knob_def("knob_vv.png")}, {"key": "vknob_red", "value": knob_def("knob_vv_red.png")},
           {"key": "knob overlay", "value": overlay}]
    for w, h in sorted(FIELDS):      # an invisible value slider over a live name: the data wheel, a Q-Link or a drag steps it
        ts = {"version": 1, "font": {"version": 1, "name": "Roboto", "style": "Regular", "height": 20.0}, "colour": "00000000",
              "justification": "horizontallyCentred verticallyCentred", "case": "Original"}
        out.append({"key": "lcdfield%dx%d" % (w, h), "value": component([
            entry("focus", "Focus", FOCUS, "0 0 %d %d" % (w, h), visible="WhenFocussed"),
            entry("field", "Knob", {"version": 4, "knobType": "ValueSlider", "textStyle": ts, "dragOrientation": "Horizontal",
                                    "handleName": "Data"}, "0 0 %d %d" % (w, h)),
        ], actions=[act("Mouse Down", "Q-Link")])})
    return out


def save(im, name):
    im.save(os.path.join(OUT, name))
    return name


def button(kids, key, b, on, off, bid=1, n=1, name=None):
    kids.append(entry(name or key, "Button", {"version": 2, "onImage": on, "offImage": off, "buttonId": bid, "numButtonsInGroup": n,
                                              "handleName": "Data", "gestureBehaviour": GESTURE}, b, remap=P(key)))


def hit_zone(kids, key, x, y, w, h):
    """an invisible momentary touch zone over a printed arrow (a dark flash while held)"""
    on = "hit_%dx%d.png" % (w, h)
    if not os.path.exists(os.path.join(OUT, on)):
        save(A.arrow_image(w, h, 1, True), on)
    button(kids, key, "%d %d %d %d" % (x, y, w, h), on, CLEAR, name=key + " hit")


PICK_DEFS = {}


def pick_panel(key, opts):
    """A drawn pick-list for the choice `key`: a panel with one radio Button per option (text baked in) and a close key, shown only
    while ui_open == its popup index + 1. Shared per option list. Centred on the page; columns grow to fit the height."""
    n = POPUPS.index(key)
    hdr, gap = 46, 4
    ch = 44 if len(opts) <= 24 else 40 if len(opts) <= 40 else 34
    rows_max = (600 - hdr - 16) // (ch + gap)
    cols = 1 if len(opts) <= 8 else max(2, -(-len(opts) // rows_max))
    cols = max(cols, 3) if len(opts) > 12 else cols
    rows = -(-len(opts) // cols)
    cw = 260 if cols == 1 else min(236, (1240 - 16) // cols - gap)
    pw, ph = cols * (cw + gap) + gap + 12, hdr + rows * (ch + gap) + gap + 10
    ck = "list_%d_%s" % (len(opts), hashlib.md5("|".join(opts).encode()).hexdigest()[:8])
    if ck not in PICK_DEFS:
        kids = [entry("panel", "Image", {"version": 2, "imageType": "Regular", "colour": "0", "image": save(A.list_panel(pw, ph), ck + "_bg.png")},
                      "0 0 %d %d" % (pw, ph))]
        size = 16 if cw >= 200 else 14
        for i, o in enumerate(opts):
            r, c = i % rows, i // rows                 # down the columns
            on = save(A.list_key(cw, ch, o, True, size), "%s_%d_on.png" % (ck, i))
            off = save(A.list_key(cw, ch, o, False, size), "%s_%d_off.png" % (ck, i))
            kids.append(entry("opt %d" % i, "Button", {"version": 2, "onImage": on, "offImage": off, "buttonId": i, "numButtonsInGroup": len(opts),
                                                        "handleName": "Data", "gestureBehaviour": GESTURE},
                              "%d %d %d %d" % (8 + gap + c * (cw + gap), hdr + r * (ch + gap), cw, ch)))
        xon = save(A.list_key(56, 34, "X", True, 18), "x_on.png")
        xoff = save(A.list_key(56, 34, "X", False, 18), "x_off.png")
        kids.append(entry("close", "Button", {"version": 2, "onImage": xon, "offImage": xoff, "buttonId": 0, "numButtonsInGroup": UI_STEPS,
                                              "handleName": "Data", "gestureBehaviour": GESTURE}, "%d 6 56 34" % (pw - 66), remap=P("ui_open")))
        PICK_DEFS[ck] = (pw, ph, component(kids))
    pw, ph, _ = PICK_DEFS[ck]
    x, y = (1280 - pw) // 2, max(4, (628 - ph) // 2)
    return entry("list " + key, ck, {"version": 1, "handleName": "Data"}, "%d %d %d %d" % (x, y, pw, ph), remap=P(key),
                 ind=["IndexedEnabling/%d/%d/Parameter %d" % (n + 1, UI_STEPS, UI_INDEX)])


# ---- a page: art + widgets at the same coordinates + Q-Link blocks -----------------------------------------------------------
RED_KNOBS = {"F1Cutoff", "F2Cutoff"}


class Page:
    def __init__(self, name, fn):
        self.name, self.fn = name, fn
        self.art = A.panel()
        self.kids, self.panels = [], []
        self.pos = {}                 # key -> (x0, y0, x1, y1) of the control with its caption and value
        self.subs = [[]]              # per sub-tab: [(keys, rect)]

    # controls
    def knob(self, key, cx, cy, cap, red=None):
        red = key in RED_KNOBS if red is None else red
        A.caption(self.art, cx, cy - 47, cap, width=112)
        self.kids.append(entry(key, "vknob_red" if red else "vknob", {"version": 1, "handleName": "Data"},
                               "%d %d %d %d" % (cx - KNOB // 2, cy - KNOB // 2, KNOB, KNOB), remap=P(key), focus="Yes"))
        self.kids.append(label("%d %d 112 24" % (cx - 56, cy + 34), key, 23))
        self.pos[key] = (cx - 56, cy - 60, cx + 56, cy + 60)

    def pick(self, key, cx, cy, w, cap):
        """a pick-list field: the caption on a blue tab at its left (the editor's "Source"), the choice live on the cream part"""
        tab = int(A.F(15).getlength(cap)) + 18 if cap else 0
        A.pick_field(self.art, cx, cy, w)
        d = ImageDraw.Draw(self.art)
        x0 = cx - w // 2
        if cap:
            d.rectangle((x0 + 2, cy - 15, x0 + tab, cy + 15), fill=A.BLUE + (255,))
            d.text((x0 + tab // 2 + 1, cy), cap, font=A.F(15), fill=A.WHITE + (255,), anchor="mm")
        self.kids.append(label("%d %d %d %d" % (x0 + tab + 8, cy - 17, w - tab - 44, 34), key, 22, hexcol(A.INK), "left verticallyCentred"))
        self.kids.append(entry(key + " field", "Button", {"version": 2, "onImage": CLEAR, "offImage": CLEAR, "buttonId": POPUPS.index(key) + 1,
                                                          "numButtonsInGroup": UI_STEPS, "handleName": "Data", "gestureBehaviour": GESTURE},
                               "%d %d %d %d" % (x0, cy - 17, w, 34), remap=P("ui_open")))
        self.panels.append(pick_panel(key, PARAMS[key]["options"]))
        self.pos[key] = (x0, cy - 17, x0 + w, cy + 17)

    def switch(self, key, cx, cy, cap):
        A.caption(self.art, cx, cy - 30, cap, width=120)
        button(self.kids, key, "%d %d 76 36" % (cx - 24, cy - 18), save(A.switch_image(True), "sw_on.png"), save(A.switch_image(False), "sw_off.png"))
        self.pos[key] = (cx - 56, cy - 42, cx + 56, cy + 20)

    def key(self, key, cx, cy, cap, w=110, h=70, ink=A.BLUE_DK):
        tag = "key_%s_%dx%d" % (key, w, h)
        on = save(A.oval_key(w, h, cap, True, ink=ink), tag + "_on.png")
        off = save(A.oval_key(w, h, cap, False, ink=ink), tag + "_off.png")
        button(self.kids, key, "%d %d %d %d" % (cx - w // 2, cy - h // 2, w, h), on, off)

    def readout(self, key, x0, y0, x1, y1, size=21, just="horizontallyCentred verticallyCentred"):
        A.lcd(self.art, x0, y0, x1, y1, cells=0)
        self.kids.append(label("%d %d %d %d" % (x0 + 8, y0, x1 - x0 - 16, y1 - y0), key, size, hexcol(A.LCD_INK), just))

    # Q-Link blocks
    def block(self, keys, rect=None, pad=6):
        ks = [k for k in keys if k]
        if rect is None:
            boxes = [self.pos[k] for k in ks]
            rect = (min(b[0] for b in boxes) - pad, min(b[1] for b in boxes) - pad, max(b[2] for b in boxes) + pad, max(b[3] for b in boxes) + pad)
        assert len(self.subs[-1]) < 4, "%s: more than four Q-Link blocks on a sub-tab" % self.name
        self.subs[-1].append((ks, rect))

    def subtab(self):
        self.subs.append([])

    def section(self, x0, y0, x1, y1, title):
        A.section(self.art, x0, y0, x1, y1, title)

    def tabs(self, bgfile):
        kids = [entry("bg", "Image", {"version": 2, "imageType": "Regular", "colour": "0", "image": bgfile}, "0 0 1280 628")] + self.kids + self.panels
        out = []
        for sub, blocks in enumerate(self.subs):
            groups = ["%d %d %d %d" % (r[0], r[1], r[2] - r[0], r[3] - r[1]) for _, r in blocks]
            out.append({"version": 1, "tabName": self.name, "fnKeyIndex": self.fn, "fnKeySubIndex": sub,
                        "componentDefinition": component(kids, background=bg(hexcol(A.YELLOW))), "qlinkBoundsData": groups})
        return out


def display(pg, x0, y0, x1, y1, rows):
    """The two-row display of MAIN and BANKS: a green LCD; each row [(x_end, get, prev, next)], a rule between fields, ink arrows."""
    A.lcd(pg.art, x0, y0, x1, y1)
    n = len(rows)
    rh = (y1 - y0) / n
    d = ImageDraw.Draw(pg.art)
    for i, (fields, size) in enumerate(rows):
        ry0, ry1 = int(y0 + i * rh), int(y0 + (i + 1) * rh)
        if i:
            d.line((x0 + 6, ry0, x1 - 6, ry0), fill=A.LCD_DK + (255,), width=1)
        display_row(pg, x0, ry0, ry1, fields, size)


def display_row(pg, x0, y0, y1, fields, size, aw=40):
    d = ImageDraw.Draw(pg.art)
    xs = x0
    for i, (xe, get, prev, nxt) in enumerate(fields):
        if i:
            d.line((xs, y0 + 6, xs, y1 - 6), fill=A.LCD_INK + (255,), width=1)
        cy = (y0 + y1) // 2
        pad = aw if prev else 0
        if prev:
            for k, ax, dr in ((prev, xs, -1), (nxt, xe - aw, 1)):
                A.tri(d, ax + aw // 2, cy, dr)
                hit_zone(pg.kids, k, ax, y0, aw, y1 - y0)
        pg.kids.append(label("%d %d %d %d" % (xs + pad + 10, y0, xe - xs - 2 * pad - 16, y1 - y0), get, size, hexcol(A.LCD_INK), "left verticallyCentred"))
        if get in FIELD_KEY:
            fw, fh = xe - xs - 2 * pad, y1 - y0
            FIELDS.add((fw, fh))
            pg.kids.append(entry(FIELD_KEY[get] + " field", "lcdfield%dx%d" % (fw, fh), {"version": 1, "handleName": "Data"},
                                 "%d %d %d %d" % (xs + pad, y0, fw, fh), remap=P(FIELD_KEY[get]), focus="Yes"))
        xs = xe


# ---- the pages ---------------------------------------------------------------------------------------------------------------
def page_main(fn):
    pg = Page("MAIN", fn)
    A.band(pg.art, 0, 18, 1280, 110, oval=(-90, -24, 1370, 122))
    A.wordmark(pg.art, 34, 22, 62)
    display(pg, 300, 26, 1262, 102, [([(640, "bank_name", "bank_prev", "bank_next"), (1262, "preset_name", "preset_prev", "preset_next")], 27),
                                     ([(830, "loading_status", None, None), (1262, "engine_stats", None, None)], 20)])
    # the microQ's own LCD, live
    pg.section(16, 128, 812, 372, "lcd")
    A.lcd(pg.art, 60, 172, 768, 346, cells=34)
    pg.kids.append(label("70 182 690 72", "lcd1", 50, hexcol(A.LCD_INK), "left verticallyCentred"))
    pg.kids.append(label("70 262 690 72", "lcd2", 50, hexcol(A.LCD_INK), "left verticallyCentred"))
    pg.section(828, 128, 1264, 372, "sound")
    pg.key("all_notes_off", 940, 196, "PANIC")
    pg.key("init_patch", 1150, 196, "RELOAD")
    pg.key("fav_save", 940, 288, "+ FAV")
    pg.key("fav_delete", 1150, 288, "- FAV")
    pg.readout("fav_text", 860, 330, 1232, 358, 19)
    # quick edit: three blocks
    pg.section(16, 388, 470, 620, "filter 1")
    for i, (k, c) in enumerate((("F1Cutoff", "Cutoff"), ("F1Resonance", "Resonance"), ("F1EnvMod", "Env Amount"), ("FilterEnvDecay", "F.Env Decay"))):
        pg.knob(k, 82 + i * 108, 520, c)
    pg.section(486, 388, 940, 620, "amp & mod")
    for i, (k, c) in enumerate((("AmpEnvAttack", "Attack"), ("AmpEnvRelease", "Release"), ("Lfo1Speed", "LFO 1 Speed"), ("FX2Mix", "FX 2 Mix"))):
        pg.knob(k, 552 + i * 108, 520, c)
    pg.section(956, 388, 1264, 620, "output")
    pg.knob("AmpVolume", 1056, 520, "Volume")
    pg.knob("gain", 1164, 520, "Gain %")
    for keys in (["F1Cutoff", "F1Resonance", "F1EnvMod", "FilterEnvDecay"], ["AmpEnvAttack", "AmpEnvRelease", "Lfo1Speed", "FX2Mix"], ["AmpVolume", "gain"]):
        pg.block(keys)
    pg.block(["bank_index", "preset"], rect=(296, 22, 1266, 64))
    return pg


def page_banks(fn):
    """BANKS (Xenia's): the bank tiles (left), the 30 sounds of the page (3 x 10, down the columns), the display with BANK / SOUND
    steppers, the favourite keys. Tile names are Value labels UNDER transparent Buttons (a label on top would swallow the tap)."""
    pg = Page("BANKS", fn)
    A.band(pg.art, 0, 0, 1280, 74)
    display(pg, 20, 13, 800, 61, [([(320, "bank_name", "bank_prev", "bank_next"), (800, "preset_name", "preset_prev", "preset_next")], 26)])
    pg.key("fav_save", 880, 38, "+ FAV", w=100, h=66, ink=A.WHITE)
    pg.key("fav_delete", 990, 38, "- FAV", w=100, h=66, ink=A.WHITE)
    pg.readout("fav_text", 1060, 21, 1264, 53, 19)
    layer = Image.new("RGBA", pg.art.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    on_cache = {}

    def tile_on(w, h):
        S = 4
        im = Image.new("RGBA", (w * S, h * S), (0, 0, 0, 0))
        dd = ImageDraw.Draw(im)
        dd.rounded_rectangle((0, 0, w * S - 1, h * S - 1), 5 * S, fill=A.BLUE + (60,), outline=A.BLUE_DK + (255,), width=3 * S)
        lx, ly, lr = 14 * S, h * S // 2, 5 * S
        dd.ellipse((lx - lr - S, ly - lr - S, lx + lr + S, ly + lr + S), fill=(60, 40, 0, 255))
        dd.ellipse((lx - lr, ly - lr, lx + lr, ly + lr), fill=A.LED_ON + (255,))
        dd.ellipse((lx - lr // 2 - S, ly - lr // 2 - S, lx, ly), fill=(255, 200, 180, 255))
        return im.resize((w, h), Image.LANCZOS)

    def tile(key, x, y, w, h):
        ld.rounded_rectangle((x, y, x + w - 1, y + h - 1), 5, fill=(255, 250, 220, 120), outline=A.BLUE + (200,), width=1)
        pg.kids.append(label("%d %d %d %d" % (x + 28, y, w - 34, h), key, 22, hexcol(A.INK), "left verticallyCentred"))
        if (w, h) not in on_cache:
            on_cache[(w, h)] = save(tile_on(w, h), "tile_on_%dx%d.png" % (w, h))
        button(pg.kids, key, "%d %d %d %d" % (x, y, w, h), on_cache[(w, h)], CLEAR, name=key + " tile")

    def page_stepper(cx, cy, w, h, get, prev, nxt):
        aw, x0, y0 = 40, cx - w // 2, cy - h // 2
        ld.rounded_rectangle((x0 + aw, y0, x0 + w - aw - 1, y0 + h - 1), 5, fill=(255, 250, 220, 160), outline=A.BLUE + (220,), width=1)
        pg.kids.append(label("%d %d %d %d" % (x0 + aw, y0, w - 2 * aw, h), get, 21, hexcol(A.INK)))
        d = ImageDraw.Draw(pg.art)
        for k, bx, dr in ((prev, x0, -1), (nxt, x0 + w - aw, 1)):
            A.tri(d, bx + aw // 2, y0 + h // 2, dr, 10, A.BLUE_DK)
            hit_zone(pg.kids, k, bx, y0, aw, h)

    pg.section(10, 80, 306, 620, "banks")
    for i in range(10):
        tile("bank_slot_%d" % (i + 1), 20, 118 + 44 * i, 276, 40)
    page_stepper(158, 588, 276, 38, "bank_page_text", "bank_page_prev", "bank_page_next")
    pg.section(318, 80, 1270, 620, "sounds")
    page_stepper(1100, 100, 300, 34, "patch_page_text", "patch_page_prev", "patch_page_next")
    for c in range(3):
        for r in range(10):
            tile("patch_slot_%d" % (c * 10 + r + 1), 328 + c * 314, 126 + r * 49, 306, 44)
    pg.art = Image.alpha_composite(pg.art, layer)
    pg.block(["bank_index", "preset"], rect=(16, 8, 804, 64))
    return pg


def osc_row(pg, n, y0, extra=None):
    """one oscillator: Shape / PWM / FM sources, then three blocks: pitch, wave, sub"""
    o = "O%d" % n
    pg.section(10, y0, 1270, y0 + 296, "oscillator %d" % n)
    pg.pick(o + "Shape", 232, y0 + 66, 340, "SHAPE")
    pg.pick(o + "PwmSource", 676, y0 + 66, 340, "PWM SOURCE")
    pg.pick(o + "FmSource", 1080, y0 + 66, 300, "FM SOURCE")
    ky = y0 + 196
    pitch = [(o + "Octave", "Octave"), (o + "Semi", "Semitone"), (o + "Detune", "Detune"), (o + "BendRange", "Bend Range")]
    wave = [(o + "PulseWidth", "Pulsewidth"), (o + "Pwm", "PWM"), (o + "FmAmount", "FM Amount"), (o + "KeyTrack", "Keytrack")]
    for i, (k, c) in enumerate(pitch):
        pg.knob(k, 76 + i * 104, ky, c)
    for i, (k, c) in enumerate(wave):
        pg.knob(k, 520 + i * 104, ky, c)
    sub = []
    if n < 3:
        sub = [(o + "SubFreqDiv", "Sub Freq Div"), (o + "SubVolume", "Sub Level")]
        for i, (k, c) in enumerate(sub):
            pg.knob(k, 964 + i * 104, ky, c)
    if extra:
        extra(ky)
    return [k for k, _ in pitch], [k for k, _ in wave], [k for k, _ in sub]


def page_osc12(fn):
    pg = Page("OSC 1/2", fn)
    blocks = [osc_row(pg, 1, 6), osc_row(pg, 2, 320, lambda ky: pg.switch("Sync", 1196, ky + 4, "Sync to O3"))]
    for i, bl in enumerate(blocks):
        if i:
            pg.subtab()
        for b in bl:
            pg.block(b + (["Sync"] if i and b is bl[2] else []))
    return pg


def filter_row(pg, n, y0, extra=None):
    f = "F%d" % n
    pg.section(10, y0, 1270, y0 + 296, "filter %d" % n)
    pg.pick(f + "Type", 170, y0 + 62, 240, "TYPE")
    pg.pick(f + "ModSource", 480, y0 + 62, 300, "CUTOFF MOD")
    pg.pick(f + "FmSource", 800, y0 + 62, 280, "FM SOURCE")
    pg.pick(f + "PanModSource", 1110, y0 + 62, 280, "PAN MOD")
    ky = y0 + 196
    a = [(f + "Cutoff", "Cutoff"), (f + "Resonance", "Resonance"), (f + "Drive", "Drive"), (f + "KeyTrack", "Keytrack")]
    b = [(f + "EnvMod", "Env Amount"), (f + "VelMod", "Env Velocity"), (f + "CutoffMod", "Mod Amount"), (f + "FmAmount", "FM Amount")]
    c = [(f + "Pan", "Panning"), (f + "PanMod", "Pan Amount")]
    for i, (k, cp) in enumerate(a):
        pg.knob(k, 76 + i * 104, ky, cp)
    for i, (k, cp) in enumerate(b):
        pg.knob(k, 520 + i * 104, ky, cp)
    for i, (k, cp) in enumerate(c):
        pg.knob(k, 964 + i * 104, ky, cp)
    if extra:
        extra(ky)
    return [k for k, _ in a], [k for k, _ in b], [k for k, _ in c]


def page_filters(fn):
    pg = Page("FILTERS", fn)
    blocks = [filter_row(pg, 1, 6), filter_row(pg, 2, 320, lambda ky: pg.switch("FilterRouting", 1196, ky + 4, "Serial"))]
    for i, bl in enumerate(blocks):
        if i:
            pg.subtab()
        for b in bl:
            pg.block(b + (["FilterRouting"] if i and b is bl[2] else []))
    return pg


PAGES = [("MAIN", page_main), ("BANKS", page_banks), ("OSC 1/2", page_osc12), ("FILTERS", page_filters)]


def qlinks_for(pages):
    maps = []
    for pg in pages:
        for sub, blocks in enumerate(pg.subs):
            q = {"Q-Link %d" % n: -1 for n in range(1, 17)}
            for gi, (keys, _) in enumerate(blocks[:4]):
                for i, key in enumerate(keys[:4]):
                    q["Q-Link %d" % (13 - 4 * gi + i)] = PI(key)
            maps.append({"Tab": pg.fn + 1, "SubTab": sub + 1, "Bank Direction": "RowTopDown", "Q-Links": q})
    return {"version": 4, "info": {"version": 1, "type": "CompleteDescription"},
            "Screen Mode Q-Links": {"version": 4, "map": maps}, "Program Mode Q-Links": {"Q-Link %d" % n: -1 for n in range(1, 17)}}


# ---- offline preview: compose a tab the way the MPC draws it --------------------------------------------------------------
SAMPLE = {"preset_name": "A001 LosAngeles2019 T", "bank_name": "BANK A", "loading_status": "Ready - ROM loaded",
          "engine_stats": "DROPOUTS 0   CPU 40%", "patch_page_text": "PAGE 1 / 4", "bank_page_text": "1 / 2",
          "lcd1": "Inst:1  Sound:A001", "lcd2": "LosAngeles2019 T", "fav_text": "FAVOURITES 3 / 64",
          "bank_slot_1": "BANK A", "bank_slot_2": "BANK B", "bank_slot_3": "BANK C", "bank_slot_4": "FORUMONE SOUNDS A",
          "bank_slot_5": "FORUMONE SOUNDS B", "bank_slot_6": "FORUMTHREE UQ A", "bank_slot_7": "FORUMTWO UQ A",
          "bank_slot_8": "FACTORY2001 A", "bank_slot_9": "FACTORYSET 2000", "bank_slot_10": "FACTORYSET 2000 B"}
NAMES = ["LosAngeles2019 T", "Rain         WMF", "Pad Of Doom    T", "Wurlitzer     DK", "Kakophonia 1  HM"]


def sample_text(key):
    if key in SAMPLE:
        return SAMPLE[key]
    if key.startswith("patch_slot_"):
        i = int(key[11:])
        return "%03d %s" % (i, NAMES[i % len(NAMES)])
    p = PARAMS.get(key, {})
    if "options" in p:
        return p["options"][p["options"].index(p["default"]) if isinstance(p["default"], str) else int(p["default"])]
    return str(p.get("default", ""))


def preview(pages, arts, defs, open_list=None, sub=0, suffix=""):
    os.makedirs(PREVIEW, exist_ok=True)
    for pg in pages:
        im = Image.open(os.path.join(OUT, arts[pg.name])).convert("RGBA")
        d = ImageDraw.Draw(im)
        for e in pg.kids + pg.panels:
            cd = e["componentData"]
            x, y, w, h = [int(float(v)) for v in e["bounds"]["bounds"].split()]
            ind = [h for h in e["bounds"].get("additionalInvalidatingHandles", []) if h.endswith("Parameter %d" % UI_INDEX)]
            if ind and ind[0].split("/")[1] != str(open_list):
                continue
            if cd["type"] in ("vknob", "vknob_red"):
                st = Image.open(os.path.join(OUT, "knob_vv_red.png" if cd["type"] == "vknob_red" else "knob_vv.png"))
                fr = 70 if cd["type"] == "vknob_red" else 50
                im.alpha_composite(st.crop((0, KNOB * fr, KNOB, KNOB * (fr + 1))).convert("RGBA"), (x, y))
            elif cd["type"] == "Label":
                key = LOCK[int(e["handle remapping"]["map"][0]["value"].split()[1])]
                ts = cd["data"]["textStyle"]
                cen = "horizontallyCentred" in ts["justification"]
                col = tuple(int(ts["colour"][i:i + 2], 16) for i in (2, 4, 6))
                f, s = A.F(int(ts["font"]["height"] * TUI_PX * 1.25), False), sample_text(key)
                if f.getlength(s) > w:
                    while s and f.getlength(s + "...") > w:
                        s = s[:-1]
                    s = s.rstrip() + "..."
                d.text((x + w / 2 if cen else x + 2, y + h / 2), s, font=f, fill=col, anchor="mm" if cen else "lm")
            elif cd["type"] == "Button" and cd["name"] in ("bank_slot_1 tile", "patch_slot_1 tile"):
                im.alpha_composite(Image.open(os.path.join(OUT, cd["data"]["onImage"])).convert("RGBA"), (x, y))
            elif cd["type"] == "Button" and cd["data"]["offImage"] != CLEAR:
                img = cd["data"]["onImage"] if cd["name"] in ("Sync", "FilterRouting") else cd["data"]["offImage"]
                im.alpha_composite(Image.open(os.path.join(OUT, img)).convert("RGBA"), (x, y))
            elif cd["type"] in defs:
                for s2 in defs[cd["type"]]["componentsData"]:
                    sx, sy, sw, sh = [int(float(v)) for v in s2["bounds"]["bounds"].split()]
                    img = s2["componentData"]["data"].get("image") or s2["componentData"]["data"].get("offImage")
                    if img:
                        im.alpha_composite(Image.open(os.path.join(OUT, img)).convert("RGBA"), (x + sx, y + sy))
        for _, r in pg.subs[sub] if sub < len(pg.subs) else []:   # the Q-Link outlines, as the MPC draws them with the bounds overlay on
            d.rectangle(r, outline=(255, 255, 255, 200), width=2)
        name = re.sub(r"[^a-z0-9]+", "_", pg.name.lower()).strip("_")
        im.convert("RGB").save(os.path.join(PREVIEW, "%s%s%s.png" % (name, suffix, "_list%d" % open_list if open_list else "")))


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    save(Image.new("RGBA", (8, 8), (0, 0, 0, 0)), CLEAR)
    save(A.knob_strip(KNOB), "knob_vv.png")
    save(A.knob_strip(KNOB, red=True), "knob_vv_red.png")
    pages, arts, tabs = [], {}, []
    for fn, (name, make) in enumerate(PAGES):
        pg = make(fn)
        arts[name] = save(pg.art.convert("RGB"), "bg_%s.png" % re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_"))
        pages.append(pg)
        tabs += pg.tabs(arts[name])
    on_q = {k for pg in pages for blocks in pg.subs for keys, _ in blocks for k in keys}
    shown = {k for pg in pages for k in pg.pos}
    missing = sorted(shown - on_q - set(POPUPS))
    if missing:
        print("controls on no Q-Link:", ", ".join(missing))
    repl = [{"key": P(k), "value": PARAMS[k]["options"]} for k in POPUPS]
    defs = definitions() + [{"key": k, "value": v[2]} for k, v in PICK_DEFS.items()]
    tui = {"pageData": {"version": 1, "componentDefinitions": {"version": 2, "importFiles": [], "localComponentDefinitions": defs},
                        "replacementStrings": repl, "info": {"version": 1, "type": "CompleteDescription"}, "tabs": tabs}}
    open(os.path.join(OUT, "TUI.json"), "w").write(dump(tui) + "\n")
    open(os.path.join(OUT, "Q-Links.json"), "w").write(dump(qlinks_for(pages)) + "\n")
    bad = [f for f in os.listdir(OUT) if re.search(r'[<>:"/\\|?*]', f)]
    assert not bad, "file names that exFAT rejects: %s" % bad
    assert "object at" not in open(os.path.join(OUT, "TUI.json")).read()
    if "--preview" in sys.argv:
        dd = {x["key"]: x["value"] for x in defs}
        preview(pages, arts, dd)
        preview([pg for pg in pages if pg.name == "OSC 1/2"], arts, dd, open_list=POPUPS.index("O1Shape") + 1)
        preview([pg for pg in pages if pg.name == "FILTERS"], arts, dd, open_list=POPUPS.index("F1ModSource") + 1)
    print("wrote", OUT, "-", len(tabs), "tabs,", len(os.listdir(OUT)), "files,", len(PICK_DEFS), "pick-lists")


if __name__ == "__main__":
    main()
