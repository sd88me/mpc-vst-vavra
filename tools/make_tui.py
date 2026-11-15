#!/usr/bin/env python3
"""Vavra's native MPC skin: skins/TUI.json + skins/Q-Links.json + the PNGs they use (docs/SDK-PORTING.md; the widget machinery is
Xenia's tools/make_tui.py). The art is drawn from code by tools/vavra_art.py in the look of the microQ's panel and editor; the pages are
laid out here, every control in a block of four with its own Q-Link frame (at most four blocks per sub-tab).

Popups are drawn pick-lists on ONE ui_open parameter (index 437; value k + 1 = the k-th popup of params.lock, the order the front end
uses). The bank and sound names in the displays take the data wheel and Q-Links (an invisible value field over each).
    python3 tools/make_tui.py              # -> skins/   (build-sdk.sh copies it to Plugin Skins/)
    python3 tools/make_tui.py --preview    # also docs/skin-preview/<tab>.png, composed offline (Titillium at the MPC's text scale)"""
import hashlib, json, math, os, re, shutil, sys
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
KNOB = 76
BIG = 96                                             # MAIN's perf knobs
KNOB_SIZES = (KNOB, BIG)
DIAL_FRAMES = 64                                     # the dial's strip stays under the MPC's 16384 px image height (250 x 64)
DIAL = 250


def kname(kind, size):
    """the component (and film strip) of a knob: kind "", "_red" or "_bi"; sizes other than KNOB carry their size"""
    return "vknob%s%s" % (kind, "" if size == KNOB else str(size))
CLEAR = "clear.png"
# The skin switch (parameter "skin", global): every page is built once per theme and the passes are merged into one TUI.json, each entry
# shown only while skin == its theme's index: microq (0, the yellow panel), alt (1, the dark-blue microQ), phoenix (2, the Phoenix
# Edition). VAVRA_THEMES=microq builds one. SKIN (skin_next) steps round them.
THEMES = [t for t in os.environ.get("VAVRA_THEMES", "microq,alt,phoenix").split(",") if t]
THEME = THEMES[0]


def tag(name):
    """a file / component name for the theme being built (the first theme keeps the plain names)"""
    return name if THEME == THEMES[0] else "%s_%s" % (THEME, name)


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


def focus_style():
    """the focus outline in the current theme's caption colour"""
    return {"version": 1, "backgroundColour": "00000000", "outlineColour": hexcol(A.BLUE_DK), "backgroundInset": 4.0, "outlineThickness": 2.0}
FIELDS = set()                                         # (w, h) of every display field that steps a value (display_row)
FIELD_KEY = {"bank_name": "bank_index", "preset_name": "preset"}


def definitions():
    def knob_def(strip, size=KNOB, frames=101):
        return component([
            entry("focus", "Focus", focus_style(), "-6 -6 %d %d" % (size + 12, size + 12), visible="WhenFocussed"),
            entry("knob", "Knob", {"version": 3, "knobType": "FilmStrip", "filmStrip": strip, "numFrames": frames, "invert": False,
                                   "dragOrientation": "Vertical", "handleName": "Data"}, "0 0 %d %d" % (size, size)),
        ], actions=[act("Mouse Down", "Q-Link"), act("Double Click", "Show Overlay", "knob overlay"), act("Enter Pressed", "Show Overlay", "knob overlay")])
    overlay = component([entry("overlay", "KnobOverlay", Obj(
        ("version", 2), ("version", 1),
        ("actions", [{"version": 1, "onAction": "Focus Lost", "handler": "Focus Lost", "handleName": "Focus Lost", "additionalData": ""}]),
        ("overlayType", "Knob With Header"), ("scaleType", "Linear"), ("polarityType", "Unipolar"),
        ("showMinusSign", True), ("handleName", "Data")), "0 0 1280 800", focus="Yes")], ignore=True)
    out = [{"key": "knob overlay", "value": overlay}]
    for t in THEMES:
        pre = "" if t == THEMES[0] else t + "_"
        A.set_theme(t)
        for size in KNOB_SIZES:
            for kind in ("", "_red", "_bi"):
                out.append({"key": pre + kname(kind, size), "value": knob_def(pre + kname(kind, size) + ".png", size)})
        out.append({"key": pre + "vdial", "value": knob_def(pre + "dial_vv.png", DIAL, DIAL_FRAMES)})
    A.set_theme(THEMES[0])
    for w, h in sorted(FIELDS):      # an invisible value slider over a live name: the data wheel, a Q-Link or a drag steps it
        ts = {"version": 1, "font": {"version": 1, "name": "Roboto", "style": "Regular", "height": 20.0}, "colour": "00000000",
              "justification": "horizontallyCentred verticallyCentred", "case": "Original"}
        out.append({"key": "lcdfield%dx%d" % (w, h), "value": component([
            entry("focus", "Focus", focus_style(), "0 0 %d %d" % (w, h), visible="WhenFocussed"),
            entry("field", "Knob", {"version": 4, "knobType": "ValueSlider", "textStyle": ts, "dragOrientation": "Horizontal",
                                    "handleName": "Data"}, "0 0 %d %d" % (w, h)),
        ], actions=[act("Mouse Down", "Q-Link")])})
    return out


def save(im, name):
    name = tag(name)
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
    ck = tag("list_%d_%s" % (len(opts), hashlib.md5("|".join(opts).encode()).hexdigest()[:8]))
    if ck not in PICK_DEFS:
        kids = [entry("panel", "Image", {"version": 2, "imageType": "Regular", "colour": "0", "image": save(A.list_panel(pw, ph), "%s_bg.png" % ck[len(tag("")):])},
                      "0 0 %d %d" % (pw, ph))]
        size = 16 if cw >= 200 else 14
        for i, o in enumerate(opts):
            r, c = i % rows, i // rows                 # down the columns
            on = save(A.list_key(cw, ch, o, True, size), "%s_%d_on.png" % (ck[len(tag("")):], i))
            off = save(A.list_key(cw, ch, o, False, size), "%s_%d_off.png" % (ck[len(tag("")):], i))
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
        self.kids, self.panels, self.overlay = [], [], []
        self.pos = {}                 # key -> (x0, y0, x1, y1) of the control with its caption and value
        self.subs = [[]]              # per sub-tab: [(keys, rect)]

    # controls
    def knob(self, key, cx, cy, cap, red=None, box=None, size=KNOB):
        red = key in RED_KNOBS if red is None else red
        g = size - KNOB                     # a bigger knob moves its caption and value out by the difference
        box = box or (71 + g // 2, 72 + g // 2)
        if cap:
            A.caption(self.art, cx, cy - 57 - g // 2, cap, size=20 + g // 10, width=114 + g)
        p = PARAMS.get(key, {})
        bi = "options" not in p and p.get("min", 0) < 0 < p.get("max", 0)     # a -64 .. +63 value: the ring fills from the top centre
        self.kids.append(entry(key, tag(kname("_red" if red else "_bi" if bi else "", size)), {"version": 1, "handleName": "Data"},
                               "%d %d %d %d" % (cx - size // 2, cy - size // 2, size, size), remap=P(key), focus="Yes"))
        self.kids.append(label("%d %d 112 30" % (cx - 56, cy + 40 + g // 2), key, 29 + g // 8, hexcol(A.VALUE)))
        self.pos[key] = (cx - 57, cy - box[0], cx + 57, cy + box[1])

    def pick(self, key, cx, cy, w, cap):
        """a pick-list field: the caption on a blue tab at its left (the editor's "Source"), the choice live on the cream part"""
        tab = int(A.F(15).getlength(cap)) + 18 if cap else 0
        A.pick_field(self.art, cx, cy, w)
        d = ImageDraw.Draw(self.art)
        x0 = cx - w // 2
        if cap:
            d.rectangle((x0 + 2, cy - 15, x0 + tab, cy + 15), fill=A.BLUE + (255,))
            d.text((x0 + tab // 2 + 1, cy), cap, font=A.F(15), fill=A.ON_BLUE + (255,), anchor="mm")
        self.kids.append(label("%d %d %d %d" % (x0 + tab + 8, cy - 17, w - tab - 44, 34), key, 25, hexcol(A.INK), "left verticallyCentred"))
        self.kids.append(entry(key + " field", "Button", {"version": 2, "onImage": CLEAR, "offImage": CLEAR, "buttonId": POPUPS.index(key) + 1,
                                                          "numButtonsInGroup": UI_STEPS, "handleName": "Data", "gestureBehaviour": GESTURE},
                               "%d %d %d %d" % (x0, cy - 17, w, 34), remap=P("ui_open")))
        self.panels.append(pick_panel(key, PARAMS[key]["options"]))
        self.pos[key] = (x0, cy - 17, x0 + w, cy + 17)

    def switch(self, key, cx, cy, cap, width=120):
        if cap:
            A.caption(self.art, cx, cy - 34, cap, size=20, width=width)
        button(self.kids, key, "%d %d 76 36" % (cx - 24, cy - 18), save(A.switch_image(True), "sw_on.png"), save(A.switch_image(False), "sw_off.png"))
        self.pos[key] = (cx - 56, cy - 42, cx + 56, cy + 20)

    def key(self, key, cx, cy, cap, w=110, h=70, ink=None):
        tag = "key_%s_%dx%d" % (key, w, h)
        on = save(A.oval_key(w, h, cap, True, ink=ink), tag + "_on.png")
        off = save(A.oval_key(w, h, cap, False, ink=ink), tag + "_off.png")
        button(self.kids, key, "%d %d %d %d" % (cx - w // 2, cy - h // 2, w, h), on, off)

    def readout(self, key, x0, y0, x1, y1, size=21, just="horizontallyCentred verticallyCentred"):
        A.lcd(self.art, x0, y0, x1, y1, cells=0)
        self.kids.append(label("%d %d %d %d" % (x0 + 8, y0, x1 - x0 - 16, y1 - y0), key, size, hexcol(A.LCD_INK), just))

    # Q-Link blocks
    def block(self, keys, rect=None, pad=3):
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
        kids = [entry("bg", "Image", {"version": 2, "imageType": "Regular", "colour": "0", "image": bgfile}, "0 0 1280 628")] + self.kids + self.panels + self.overlay
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
    """MAIN, laid out like the microQ's front: the six keys in a blue-outlined panel centred over the LCD and joined to the blue bar
    (where Inst 1-4 sit) with volume / output gain at its right, the bar with the Vavra script, the LCD (the microQ's two lines,
    bank | sound with arrows, status | CPU) and the red data dial (it steps the sound, as in the microQ's Play mode), the blue oval, and
    the perf knobs under the bar, big, joined to it by blue lines."""
    pg = Page("MAIN", fn)
    d = ImageDraw.Draw(pg.art)
    BY0, BY1 = 146, 334                                                                    # the blue bar, a wide margin round the LCD
    x0, x1 = 300, 930                                                                      # the LCD
    mid = (x0 + x1) // 2
    base = pg.art.copy()                                                                   # the bare panel, sweeps and all
    d.ellipse((-20, 30, 1300, 800), outline=A.BLUE + (255,), width=3)                       # the oval (its bottom below the page)
    dx, dy = 1150, (BY0 + BY1) // 2                                                       # the red data dial, taller than the bar; the bar ends at it
    KP, KQ = 100, 110                                                                      # key / knob pitch in the panel
    pw = 20 + 6 * KP + 30 + 2 * KQ + 16
    px0 = mid - pw // 2
    m = Image.new("L", pg.art.size, 0)                                                     # inside the key panel: the bare panel (the oval
    ImageDraw.Draw(m).rounded_rectangle((px0, 6, px0 + pw, BY0 + 30), 14, fill=255)        # stops at its outline, the sweeps run on)
    pg.art.paste(base, (0, 0), m)
    d.rounded_rectangle((px0, 6, px0 + pw, BY0 + 30), 14, outline=A.BLUE + (255,), width=3)
    A.band(pg.art, 0, BY0, dx, BY1)
    if A.THEME == "phoenix":                                                               # the Phoenix's dial ring and its scale
        rr = DIAL // 2 + 12
        dx, dy = dx - 3, dy - 4                                                            # the dial's face centre in its frame
        ring = Image.new("RGBA", pg.art.size, (0, 0, 0, 0))
        rd = ImageDraw.Draw(ring)
        rd.ellipse((dx - rr, dy - rr, dx + rr, dy + rr), fill=A.BLUE + (255,))
        for k in range(61):
            t = math.radians(135 + 270 * k / 60)
            r0 = rr - (13 if k % 5 == 0 else 7)
            rd.line((dx + math.cos(t) * r0, dy + math.sin(t) * r0, dx + math.cos(t) * (rr - 3), dy + math.sin(t) * (rr - 3)),
                    fill=(222, 170, 170, 255), width=2)
        ring.putalpha(Image.composite(Image.new("L", ring.size, 0), ring.getchannel("A"), m.point(lambda v: 255 if v else 0)))
        pg.art.alpha_composite(ring)                                                       # behind the key panel
        d = ImageDraw.Draw(pg.art)
        dx, dy = dx + 3, dy + 4
    d.rectangle((px0 + 3, BY0 - 2, px0 + pw - 3, BY0 + 4), fill=A.BLUE + (255,))          # the panel opens into the bar
    keys = (("all_notes_off", "PANIC"), ("init_patch", "RELOAD"), ("random_patch", "RANDOM"), ("fav_save", "+ FAV"), ("fav_delete", "- FAV"), ("skin_next", "SKIN"))
    for i, (k, cap) in enumerate(keys):
        pg.key(k, px0 + 20 + KP // 2 + i * KP, 72, cap, w=KP)
    xd = px0 + 20 + 6 * KP + 15                                                            # a thin rule, then the output pair
    d.line((xd, 22, xd, BY0 - 12), fill=A.BLUE_LT + (255,), width=2)
    pg.knob("AmpVolume", xd + 15 + KQ // 2, 78, "Volume", box=(64, 66))
    pg.knob("gain", xd + 15 + KQ // 2 + KQ, 78, "Output Gain", box=(64, 66))
    # the bar: badge, LCD, data dial
    wm = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    wh = A.wordmark(wm, 0, 0, 236)
    pg.art.alpha_composite(wm.crop((0, 0, 236, wh)), (30, (BY0 + BY1) // 2 - wh // 2))
    y0, y1 = BY0 + 26, BY1 - 26
    A.lcd(pg.art, x0, y0, x1, y1, cells=0)
    d = ImageDraw.Draw(pg.art)
    r1, r2, r3 = y0 + 70, y0 + 106, y1
    d.line((x0 + 6, r1, x1 - 6, r1), fill=A.LCD_DK + (255,), width=2)
    d.line((x0 + 6, r2, x1 - 6, r2), fill=A.LCD_DK + (255,), width=1)
    pg.kids.append(label("%d %d %d 34" % (x0 + 12, y0 + 1, x1 - x0 - 24), "lcd1", 34, hexcol(A.LCD_INK), "left verticallyCentred", "Bold"))
    pg.kids.append(label("%d %d %d 34" % (x0 + 12, y0 + 34, x1 - x0 - 24), "lcd2", 34, hexcol(A.LCD_INK), "left verticallyCentred", "Bold"))
    display_row(pg, x0, r1 + 1, r2, [(570, "bank_name", "bank_prev", "bank_next"), (x1, "preset_name", "preset_prev", "preset_next")], 27, aw=32)
    display_row(pg, x0, r2 + 1, r3, [(670, "loading_status", None, None), (x1, "engine_stats", None, None)], 22)
    pg.kids.append(entry("preset dial", tag("vdial"), {"version": 1, "handleName": "Data"}, "%d %d %d %d" % (dx - DIAL // 2, dy - DIAL // 2, DIAL, DIAL),
                         remap=P("preset"), focus="Yes"))
    # the perf knobs under the bar, big, joined to it by blue lines with pointer tabs over each knob
    ky = 528
    groups = [("filter 1", [("F1Cutoff", "Cutoff"), ("F1Resonance", "Resonance"), ("F1EnvMod", "Env Amount"), ("FilterEnvDecay", "F.Env Decay")], 120),
              ("amp & mod", [("AmpEnvAttack", "Attack"), ("AmpEnvRelease", "Release"), ("Lfo1Speed", "LFO 1 Speed"), ("FX2Mix", "FX 2 Mix")], 740)]
    for title, knobs, gx in groups:
        xs = [gx + i * 140 for i in range(len(knobs))]
        gm = (xs[0] + xs[-1]) // 2
        d.line((gm, BY1, gm, 408), fill=A.BLUE + (255,), width=3)
        d.line((xs[0], 408, xs[-1], 408), fill=A.BLUE + (255,), width=3)
        for x in xs:
            d.line((x, 408, x, 414), fill=A.BLUE + (255,), width=3)
            d.polygon([(x - 7, 414), (x + 7, 414), (x, 422)], fill=A.BLUE + (255,))
        t = A.text_img(title.upper(), 16, A.ON_BLUE, slant=0.2)
        tw = t.width + 22
        d.rounded_rectangle((gm - tw // 2, 356, gm + tw // 2, 382), 7, fill=A.BLUE + (255,))
        pg.art.alpha_composite(t, (gm - t.width // 2, 369 - t.height // 2))
        d = ImageDraw.Draw(pg.art)
        for (k, c), x in zip(knobs, xs):
            pg.knob(k, x, ky, c, size=BIG, box=(96, 86))
        pg.block([k for k, _ in knobs])
    pg.block(["AmpVolume", "gain"])
    pg.block(["bank_index", "preset"], rect=(x0 - 4, r1, x1 + 4, r2 + 1))
    keyboard(pg)
    return pg


def page_banks(fn):
    """BANKS (Xenia's): the bank tiles (left), the 30 sounds of the page (3 x 10, down the columns), the display with BANK / SOUND
    steppers, the favourite keys. Tile names are Value labels UNDER transparent Buttons (a label on top would swallow the tap)."""
    pg = Page("BANKS", fn)
    A.band(pg.art, 0, 0, 1280, 74)
    display(pg, 20, 13, 800, 61, [([(320, "bank_name", "bank_prev", "bank_next"), (800, "preset_name", "preset_prev", "preset_next")], 26)])
    pg.key("random_patch", 900, 38, "RANDOM", w=116, h=66, ink=A.ON_BLUE)
    pg.key("fav_save", 1030, 38, "+ FAV", w=116, h=66, ink=A.ON_BLUE)
    pg.key("fav_delete", 1160, 38, "- FAV", w=116, h=66, ink=A.ON_BLUE)
    layer = Image.new("RGBA", pg.art.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    on_cache = {}

    def tile_on(w, h):
        S = 4
        im = Image.new("RGBA", (w * S, h * S), (0, 0, 0, 0))
        dd = ImageDraw.Draw(im)
        dd.rounded_rectangle((0, 0, w * S - 1, h * S - 1), 5 * S, fill=A.BLUE + (40,), outline=A.BLUE_DK + (255,), width=3 * S)
        lx, ly, lr = 14 * S, h * S // 2, 5 * S
        dd.ellipse((lx - lr - S, ly - lr - S, lx + lr + S, ly + lr + S), fill=(60, 40, 0, 255))
        dd.ellipse((lx - lr, ly - lr, lx + lr, ly + lr), fill=A.LED_ON + (255,))
        dd.ellipse((lx - lr // 2 - S, ly - lr // 2 - S, lx, ly), fill=(255, 200, 180, 255))
        return im.resize((w, h), Image.LANCZOS)

    def tile(key, x, y, w, h):
        ld.rounded_rectangle((x, y, x + w - 1, y + h - 1), 5, fill=A.TILE + (56,), outline=A.BLUE + (150,), width=1)
        pg.kids.append(label("%d %d %d %d" % (x + 28, y, w - 34, h), key, 22, hexcol(A.TILE_INK), "left verticallyCentred"))
        if (w, h) not in on_cache:
            on_cache[(w, h)] = save(tile_on(w, h), "tile_on_%dx%d.png" % (w, h))
        button(pg.kids, key, "%d %d %d %d" % (x, y, w, h), on_cache[(w, h)], CLEAR, name=key + " tile")

    def page_stepper(cx, cy, w, h, get, prev, nxt):
        aw, x0, y0 = 40, cx - w // 2, cy - h // 2
        ld.rounded_rectangle((x0 + aw, y0, x0 + w - aw - 1, y0 + h - 1), 5, fill=A.TILE + (90,), outline=A.BLUE + (180,), width=1)
        pg.kids.append(label("%d %d %d %d" % (x0 + aw, y0, w - 2 * aw, h), get, 21, hexcol(A.TILE_INK)))
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
    pg.kids.append(label("470 84 300 32", "fav_text", 23, hexcol(A.BLUE_DK)))
    for c in range(3):
        for r in range(10):
            tile("patch_slot_%d" % (c * 10 + r + 1), 328 + c * 314, 126 + r * 49, 306, 44)
    pg.art = Image.alpha_composite(pg.art, layer)
    pg.block(["bank_index", "preset"], rect=(16, 8, 804, 64))
    keyboard(pg)
    return pg


KB_ROWS = [("1234567890", ["kb_bksp"]), ("QWERTYUIOP", []), ("ASDFGHJKL-", []), ("ZXCVBNM", ["kb_space"])]


def keyboard(pg):
    """The naming keyboard for +FAV (Profit-5's): a full-page panel, the name being typed, 42 keys; shown while kb_open = 1, over
    everything else on the page (it is added last)."""
    ind = ["IndexedEnabling/1/2/Parameter %d" % PI("kb_open")]
    panel = A.panel()
    d = ImageDraw.Draw(panel)
    d.rounded_rectangle((20, 8, 1260, 620), 12, fill=A.SEL + (255,))
    d.rounded_rectangle((24, 12, 1256, 616), 10, fill=A.BLUE + (255,))
    t = A.text_img("FAVOURITE NAME", 22, A.ON_BLUE, slant=0.2)
    panel.alpha_composite(t, (52, 52 - t.height // 2))
    d.rounded_rectangle((300, 24, 1232, 80), 7, fill=A.CREAM + (255,), outline=A.BLUE_DK + (255,), width=2)
    pg.overlay.append(entry("kb panel", "Image", {"version": 2, "imageType": "Regular", "colour": "0", "image": save(panel.convert("RGB"), "kb_panel.png")},
                            "0 0 1280 628", ind=ind))
    pg.overlay.append(entry("kb name", "Label", {"version": 1, "textStyle": text_style(46, hexcol(A.INK), "left verticallyCentred", "Bold"),
                                                 "type": "Value", "handleName": "Data"}, "316 24 900 56", P("fav_name"), ind=ind))
    kw, kh, gap, x0, y0 = 98, 84, 8, 64, 100

    def kbkey(k, cap, x, y, w):
        on = save(A.key_cap(w, kh, cap, True), "kb_%s_%d_on.png" % (k, w))
        off = save(A.key_cap(w, kh, cap, False), "kb_%s_%d_off.png" % (k, w))
        pg.overlay.append(entry(k, "Button", {"version": 2, "onImage": on, "offImage": off, "buttonId": 1, "numButtonsInGroup": 1,
                                              "handleName": "Data", "gestureBehaviour": GESTURE}, "%d %d %d %d" % (x, y, w, kh), remap=P(k), ind=ind))
    for r, (chars, extra) in enumerate(KB_ROWS):
        y = y0 + r * (kh + gap)
        x = x0 + r * 30
        for c in chars:
            kbkey("kb_" + ("dash" if c == "-" else c.lower()), c, x, y, kw)
            x += kw + gap
        for k in extra:
            kbkey(k, {"kb_bksp": "DELETE", "kb_space": "SPACE"}[k], x, y, 1216 - x)
    y = y0 + 4 * (kh + gap)
    kbkey("kb_shift", "SHIFT", x0, y, 220)
    kbkey("kb_cancel", "CANCEL", 640 - 130, y, 260)
    kbkey("kb_save", "SAVE", 1216 - 260, y, 260)


def osc_row(pg, n, y0, extra=None):
    """one oscillator: Shape / PWM / FM sources, then three blocks: pitch, wave, sub"""
    o = "O%d" % n
    pg.section(10, y0, 1270, y0 + 296, "oscillator %d" % n)
    pg.pick(o + "Shape", 244, y0 + 66, 350, "SHAPE")
    pg.pick(o + "PwmSource", 704, y0 + 66, 350, "PWM SOURCE")
    pg.pick(o + "FmSource", 1088, y0 + 66, 300, "FM SOURCE")
    ky = y0 + 202
    pitch = [(o + "Octave", "Octave"), (o + "Semi", "Semitone"), (o + "Detune", "Detune"), (o + "BendRange", "Bend Range")]
    wave = [(o + "PulseWidth", "Pulsewidth"), (o + "Pwm", "PWM"), (o + "FmAmount", "FM Amount"), (o + "KeyTrack", "Keytrack")]
    for i, (k, c) in enumerate(pitch):
        pg.knob(k, 76 + i * 112, ky, c)
    for i, (k, c) in enumerate(wave):
        pg.knob(k, 536 + i * 112, ky, c)
    sub = []
    if n < 3:
        sub = [(o + "SubFreqDiv", "Sub Freq Div"), (o + "SubVolume", "Sub Level")]
        for i, (k, c) in enumerate(sub):
            pg.knob(k, 996 + i * 112, ky, c)
    if extra:
        extra(ky)
    return [k for k, _ in pitch], [k for k, _ in wave], [k for k, _ in sub]


def page_osc12(fn):
    pg = Page("OSC 1/2", fn)
    blocks = [osc_row(pg, 1, 6), osc_row(pg, 2, 320, lambda ky: pg.switch("Sync", 1204, ky + 4, "Sync to O3"))]
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
    ky = y0 + 202
    a = [(f + "Cutoff", "Cutoff"), (f + "Resonance", "Resonance"), (f + "Drive", "Drive"), (f + "KeyTrack", "Keytrack")]
    b = [(f + "EnvMod", "Env Amount"), (f + "VelMod", "Env Velocity"), (f + "CutoffMod", "Mod Amount"), (f + "FmAmount", "FM Amount")]
    c = [(f + "Pan", "Panning"), (f + "PanMod", "Pan Amount")]
    for i, (k, cp) in enumerate(a):
        pg.knob(k, 76 + i * 112, ky, cp)
    for i, (k, cp) in enumerate(b):
        pg.knob(k, 536 + i * 112, ky, cp)
    for i, (k, cp) in enumerate(c):
        pg.knob(k, 996 + i * 112, ky, cp)
    if extra:
        extra(ky)
    return [k for k, _ in a], [k for k, _ in b], [k for k, _ in c]


def page_filters(fn):
    pg = Page("FILTERS", fn)
    blocks = [filter_row(pg, 1, 6), filter_row(pg, 2, 320, lambda ky: pg.switch("FilterRouting", 1204, ky + 4, "Serial"))]
    for i, bl in enumerate(blocks):
        if i:
            pg.subtab()
        for b in bl:
            pg.block(b + (["FilterRouting"] if i and b is bl[2] else []))
    return pg


def page_osc3mix(fn):
    pg = Page("OSC 3/MIX", fn)
    pg.section(10, 6, 942, 302, "oscillator 3")
    pg.pick("O3Shape", 244, 72, 350, "SHAPE")
    pg.pick("O3PwmSource", 704, 72, 350, "PWM SOURCE")
    ky = 208
    pitch = [("O3Octave", "Octave"), ("O3Semi", "Semitone"), ("O3Detune", "Detune"), ("O3BendRange", "Bend Range")]
    wave = [("O3PulseWidth", "Pulsewidth"), ("O3Pwm", "PWM"), ("O3FmAmount", "FM Amount"), ("O3KeyTrack", "Keytrack")]
    for i, (k, c) in enumerate(pitch):
        pg.knob(k, 76 + i * 112, ky, c)
    for i, (k, c) in enumerate(wave):
        pg.knob(k, 536 + i * 112, ky, c)
    pg.section(954, 6, 1270, 302, "pitch mod")
    pg.pick("PitchModSrc", 1112, 72, 280, "SOURCE")
    pg.pick("O3FmSource", 1112, 118, 280, "O3 FM")
    pg.knob("PitchModAmount", 1112, ky + 10, "Mod Amount")
    pg.section(10, 318, 1270, 618, "mixer")
    mix = [("O1Level", "Osc 1 Level"), ("O1Balance", "Osc 1 Bal"), ("O2Level", "Osc 2 Level"), ("O2Balance", "Osc 2 Bal"),
           ("O3Level", "Osc 3 Level"), ("O3Balance", "Osc 3 Bal"), ("NoiseLevel", "Noise Level"), ("NoiseBalance", "Noise Bal"),
           ("RingModLevel", "Ring Level"), ("RingModBalance", "Ring Bal")]
    for i, (k, c) in enumerate(mix):
        pg.knob(k, 76 + i * 112 + (i // 4) * 16, 470, c)
    A.caption(pg.art, 1210, 440, "F1  <  >  F2", size=16, width=110)
    A.caption(pg.art, 1210, 466, "balance", size=16, width=110)
    pg.block([k for k, _ in pitch]); pg.block([k for k, _ in wave]); pg.block(["PitchModAmount"])
    pg.subtab()
    keys = [k for k, _ in mix]
    pg.block(keys[0:4]); pg.block(keys[4:8]); pg.block(keys[8:10])
    return pg


def page_amp(fn):
    pg = Page("AMP & GLIDE", fn)
    pg.section(10, 6, 634, 302, "amplifier")
    pg.pick("AmpModSource", 322, 72, 360, "MOD SOURCE")
    for i, (k, c) in enumerate((("AmpVolume", "Volume"), ("AmpVelocity", "Velocity"), ("AmpModAmount", "Mod Amount"))):
        pg.knob(k, 210 + i * 112, 208, c)
    pg.section(646, 6, 1270, 302, "glide")
    pg.pick("GlideMode", 958, 72, 360, "MODE")
    pg.switch("GlideEnable", 830, 212, "Glide On")
    pg.knob("GlideRate", 1010, 208, "Rate")
    pg.section(10, 318, 634, 618, "unison")
    pg.pick("UnisonoCount", 322, 384, 360, "VOICES")
    pg.switch("VoiceMode", 210, 524, "Mono On")
    pg.knob("UnisonoDetune", 400, 520, "Detune")
    pg.section(646, 318, 1270, 618, "noise / external")
    pg.pick("NoiseModeF1", 958, 420, 400, "FILTER 1 FEED")
    pg.pick("NoiseModeF2", 958, 500, 400, "FILTER 2 FEED")
    pg.block(["AmpVolume", "AmpVelocity", "AmpModAmount"])
    pg.block(["GlideRate", "GlideEnable"])
    pg.block(["UnisonoDetune", "VoiceMode"])
    return pg


ENV_NAMES = (("FilterEnv", "filter envelope"), ("AmpEnv", "amp envelope"), ("Env3", "envelope 3"), ("Env4", "envelope 4"))


def page_env(fn):
    """four envelope rows: mode and trigger at the left under the title, then A, AL, D, S, D2, S2, R; two blocks a row, two rows a sub-tab"""
    pg = Page("ENVELOPES", fn)
    for r, (e, title) in enumerate(ENV_NAMES):
        y0 = 4 + r * 156
        pg.section(10, y0, 1270, y0 + 150, title)
        pg.pick(e + "Mode", 130, y0 + 68, 220, "")
        ky = y0 + 78
        knobs = [("Attack", "Attack"), ("AttackLevel", "Att. Level"), ("Decay", "Decay"), ("Sustain", "Sustain"),
                 ("Decay2", "Decay 2"), ("Sustain2", "Sustain 2"), ("Release", "Release"), ("TriggerMode", "Trigger")]
        for i, (k, c) in enumerate(knobs):
            pg.knob(e + k, 330 + i * 112 + (i // 4) * 24, ky, c, box=(66, 70))
        A.caption(pg.art, 130, y0 + 112, "MODE", size=15)
    for r, (e, _) in enumerate(ENV_NAMES):
        if r == 2:
            pg.subtab()
        pg.block([e + k for k in ("Attack", "AttackLevel", "Decay", "Sustain")])
        pg.block([e + k for k in ("Decay2", "Sustain2", "Release", "TriggerMode")])
    return pg


def page_lfo(fn):
    """three LFO rows: shape, sync and clocked at the left, five knobs; one block per LFO, the three Keytracks as a column block"""
    pg = Page("LFO", fn)
    for n in (1, 2, 3):
        y0 = 4 + (n - 1) * 208
        l = "Lfo%d" % n
        pg.section(10, y0, 1270, y0 + 202, "lfo %d" % n)
        pg.pick(l + "Shape", 150, y0 + 66, 260, "SHAPE")
        pg.switch(l + "Sync", 90, y0 + 150, "Sync")
        pg.switch(l + "Clocked", 220, y0 + 150, "Clocked")
        ky = y0 + 112
        for i, (k, c) in enumerate((("Speed", "Speed"), ("StartPhase", "Start Phase"), ("Delay", "Delay"), ("Fade", "Fade"))):
            pg.knob(l + k, 420 + i * 112, ky, c)
        pg.knob(l + "KeyTrack", 1060, ky, "Keytrack")
    for n in (1, 2, 3):
        l = "Lfo%d" % n
        pg.block([l + k for k in ("Speed", "StartPhase", "Delay", "Fade")])
    pg.block(["Lfo%dKeyTrack" % n for n in (1, 2, 3)])
    return pg


def page_slots(fn, name, kind, title):
    """eight modulation slots, two columns of four: source, amount, destination; the amounts are two column blocks"""
    pg = Page(name, fn)
    for col in range(2):
        x0 = 10 + col * 636
        pg.section(x0, 4, x0 + 624, 618, "%s %d-%d" % (title, col * 4 + 1, col * 4 + 4))
        for r in range(4):
            n = col * 4 + r + 1
            cy = 110 + r * 140
            k = "Slot%d%s" % (n, kind)
            A.caption(pg.art, x0 + 34, cy, str(n), size=34)
            pg.pick(k + "Source", x0 + 180, cy - 26, 240, "SRC")
            pg.pick(k + "Destination", x0 + 180, cy + 26, 240, "DEST")
            pg.knob(k + "Amount", x0 + 400, cy + 6, "Amount")
            if r < 3:
                ImageDraw.Draw(pg.art).line((x0 + 16, cy + 70, x0 + 608, cy + 70), fill=A.BLUE_LT + (255,), width=1)
    for col in range(2):
        pg.block(["Slot%d%sAmount" % (col * 4 + r + 1, kind) for r in range(4)])
    return pg


def page_modifiers(fn):
    pg = Page("MODIFIERS", fn)
    for m in range(4):
        x0, y0 = 10 + (m % 2) * 636, 4 + (m // 2) * 210
        pg.section(x0, y0, x0 + 624, y0 + 202, "modifier %d" % (m + 1))
        k = "Mod%d" % (m + 1)
        pg.pick(k + "Source1", x0 + 200, y0 + 60, 340, "SOURCE A")
        pg.pick(k + "Operator", x0 + 200, y0 + 104, 340, "OPERATOR")
        pg.pick(k + "Source2", x0 + 200, y0 + 148, 340, "SOURCE B")
        pg.knob(k + "Constant", x0 + 480, y0 + 116, "Constant")
    pg.section(10, 424, 1270, 618, "controller delay")
    pg.pick("ControllerDelaySource", 400, 530, 420, "SOURCE")
    pg.knob("ControllerDelay", 820, 532, "Delay")
    pg.block(["Mod1Constant", "Mod3Constant"])
    pg.block(["Mod2Constant", "Mod4Constant"])
    pg.block(["ControllerDelay"])
    return pg


def page_fx(fn):
    """FX 1 over FX 2: the type in the title row, MIX and the 14 knobs in two rows of eight; the knobs take the names of the chosen
    effect's parameters (live labels, "-" where the effect has none); four blocks per effect, a sub-tab each"""
    pg = Page("FX", fn)
    for e in (1, 2):
        y0 = 4 + (e - 1) * 310
        pg.section(10, y0, 1270, y0 + 304, "effect %d" % e)
        pg.pick("FX%dType" % e, 420, y0 + 16, 340, "TYPE")
        keys = ["FX%dMix" % e] + ["fx%d_p%d" % (e, i) for i in range(1, 15)]
        for i, k in enumerate(keys):
            r, c = i // 8, i % 8
            cx, cy = 86 + c * 146 + (c // 4) * 22, y0 + 96 + r * 134
            if i == 0:
                pg.knob(k, cx, cy, "", box=(62, 64))
                A.caption(pg.art, cx, cy - 50, "Mix", size=20)
            else:
                pg.knob(k, cx, cy, "", box=(62, 64))
                pg.kids.append(label("%d %d 140 26" % (cx - 70, cy - 63), "fx%d_l%d" % (e, i), 26, hexcol(A.BLUE_DK)))
        if e == 2:
            pg.subtab()
        pg.block(keys[0:4], pad=2); pg.block(keys[4:8], pad=2); pg.block(keys[8:12], pad=2); pg.block(keys[12:15], pad=2)
    return pg


def page_arp(fn):
    pg = Page("ARP", fn)
    pg.section(10, 4, 1270, 302, "arpeggiator")
    pg.pick("ArpMode", 230, 70, 380, "MODE")
    pg.pick("ArpPattern", 640, 70, 380, "PATTERN")
    pg.pick("ArpDirection", 1050, 70, 380, "DIRECTION")
    pg.pick("ArpSortOrder", 230, 130, 380, "SORT ORDER")
    pg.pick("ArpVeloMode", 640, 130, 380, "VELOCITY")
    pg.switch("ArpSameNoteOverlap", 940, 212, "Same Note Overlap", width=220)
    pg.switch("ArpPatternReset", 1150, 212, "Pattern Reset", width=200)
    A.caption(pg.art, 640, 274, "While MPC plays, the arpeggiator follows its tempo; when stopped, the TEMPO knob sets it.", size=18, width=1100)
    pg.section(10, 318, 1270, 618, "timing")
    knobs = [("Tempo", "Tempo"), ("ArpClock", "Clock"), ("ArpLength", "Length"), ("ArpTFactor", "T-Factor"),
             ("ArpOctaveRange", "Range"), ("ArpMaxNotes", "Max Notes"), ("ArpPatternLength", "Pattern Len")]
    for i, (k, c) in enumerate(knobs):
        pg.knob(k, 120 + i * 140 + (i // 4) * 60, 470, c)
    pg.block([k for k, _ in knobs[:4]])
    pg.block([k for k, _ in knobs[4:]])
    return pg


def page_steps(fn, first):
    """eight steps of the user pattern: a column each (step, glide, accent, length, timing); Q-Links on accents and lengths"""
    pg = Page("ARP STEPS %d-%d" % (first + 1, first + 8), fn)
    pg.section(10, 4, 1270, 618, "arp steps %d-%d" % (first + 1, first + 8))
    rows = [("Step", "STEP", 150), ("Glide", "GLIDE", 236), ("Accent", "ACCENT", 330), ("Length", "LENGTH", 430), ("Timing", "TIMING", 530)]
    for _, cap, y in rows:
        A.caption(pg.art, 72, y, cap, size=19)
    for c in range(8):
        n = first + c
        cx = 196 + c * 140
        A.caption(pg.art, cx, 80, str(n + 1), size=30)
        for kind, _, y in rows:
            k = "Arp%02d%s" % (n, kind)
            if kind == "Glide":
                pg.switch(k, cx - 6, y + 14, "")
            else:
                pg.pick(k, cx, y, 132, "")
    pg.block(["Arp%02dAccent" % (first + c) for c in range(4)]); pg.block(["Arp%02dAccent" % (first + c) for c in range(4, 8)])
    pg.block(["Arp%02dLength" % (first + c) for c in range(4)]); pg.block(["Arp%02dLength" % (first + c) for c in range(4, 8)])
    return pg


PAGES = [("MAIN", page_main), ("BANKS", page_banks), ("OSC 1/2", page_osc12), ("OSC 3/MIX", page_osc3mix), ("FILTERS", page_filters),
         ("ENVELOPES", page_env), ("AMP & GLIDE", page_amp), ("LFO", page_lfo),
         ("MOD FAST", lambda fn: page_slots(fn, "MOD FAST", "F", "fast slots")),
         ("MOD SLOTS", lambda fn: page_slots(fn, "MOD SLOTS", "S", "slots")),
         ("MODIFIERS", page_modifiers), ("FX", page_fx), ("ARP", page_arp),
         ("ARP STEPS 1-8", lambda fn: page_steps(fn, 0)), ("ARP STEPS 9-16", lambda fn: page_steps(fn, 8))]


def qlinks_for(pages):
    maps = []
    for pg in pages:
        for sub, blocks in enumerate(pg.subs):
            q = {"Q-Link %d" % n: -1 for n in range(1, 17)}
            column = bool(blocks) and all((r[3] - r[1]) > (r[2] - r[0]) for _, r in blocks)
            for gi, (keys, _) in enumerate(blocks[:4]):
                for i, key in enumerate(keys[:4]):
                    q["Q-Link %d" % ((13 + gi - 4 * i) if column else (13 - 4 * gi + i))] = PI(key)
            maps.append({"Tab": pg.fn + 1, "SubTab": sub + 1, "Bank Direction": "Column" if column else "RowTopDown", "Q-Links": q})
    return {"version": 4, "info": {"version": 1, "type": "CompleteDescription"},
            "Screen Mode Q-Links": {"version": 4, "map": maps}, "Program Mode Q-Links": {"Q-Link %d" % n: -1 for n in range(1, 17)}}


# ---- offline preview: compose a tab the way the MPC draws it --------------------------------------------------------------
SAMPLE = {"preset_name": "A001 LosAngeles2019 T", "bank_name": "BANK A", "loading_status": "Ready - ROM loaded",
          "engine_stats": "DROPOUTS 0   CPU 40%", "patch_page_text": "PAGE 1 / 4", "bank_page_text": "1 / 2",
          "fx1_l1": "Speed", "fx1_l2": "Depth", "fx1_l3": "-", "lcd1": "Inst:1  Sound:A001", "lcd2": "LosAngeles2019 T", "fav_text": "FAVOURITES 3 / 64",
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


def preview(pages, arts, defs, open_list=None, sub=0, suffix="", keyboard=False):
    os.makedirs(PREVIEW, exist_ok=True)
    kb = "IndexedEnabling/1/2/Parameter %d" % PI("kb_open")
    for pg in pages:
        im = Image.open(os.path.join(OUT, arts[pg.name])).convert("RGBA")
        d = ImageDraw.Draw(im)
        for e in pg.kids + pg.panels + pg.overlay:
            cd = e["componentData"]
            x, y, w, h = [int(float(v)) for v in e["bounds"]["bounds"].split()]
            hs = e["bounds"].get("additionalInvalidatingHandles", [])
            ind = [h for h in hs if h.endswith("Parameter %d" % UI_INDEX)]
            if ind and ind[0].split("/")[1] != str(open_list):
                continue
            if (kb in hs) != keyboard and (keyboard or kb in hs):
                continue
            if cd["type"].endswith("vdial"):
                im.alpha_composite(Image.open(os.path.join(OUT, cd["type"][:-5] + "dial_vv.png")).crop((0, DIAL * 19, DIAL, DIAL * 20)).convert("RGBA"), (x, y))
            elif "vknob" in cd["type"]:
                st = Image.open(os.path.join(OUT, cd["type"] + ".png"))
                fr = 85 if "_red" in cd["type"] else 70 if "_bi" in cd["type"] else 45
                im.alpha_composite(st.crop((0, w * fr, w, w * (fr + 1))).convert("RGBA"), (x, y))
            elif cd["type"] == "Image" and keyboard:
                im.alpha_composite(Image.open(os.path.join(OUT, cd["data"]["image"])).convert("RGBA"), (x, y))
            elif cd["type"] == "Label":
                key = LOCK[int(e["handle remapping"]["map"][0]["value"].split()[1])]
                ts = cd["data"]["textStyle"]
                cen = "horizontallyCentred" in ts["justification"]
                col = tuple(int(ts["colour"][i:i + 2], 16) for i in (2, 4, 6))
                f, s = A.F(int(ts["font"]["height"] * TUI_PX * 1.25), False), ("My Pad_" if key == "fav_name" else sample_text(key))
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
        for _, r in (pg.subs[sub] if sub < len(pg.subs) and not keyboard else []):   # the Q-Link outlines (the bounds overlay on)
            d.rectangle(r, outline=(255, 255, 255, 200), width=2)
        name = re.sub(r"[^a-z0-9]+", "_", pg.name.lower()).strip("_")
        im.convert("RGB").save(os.path.join(PREVIEW, "%s%s%s%s.png" % (name, suffix, "_list%d" % open_list if open_list else "",
                                                                       "_keyboard" if keyboard else "")))


def build_pass():
    """one theme's pages: art, widgets, Q-Link blocks"""
    A.set_theme(THEME)
    for size in KNOB_SIZES:
        save(A.knob_strip(size), kname("", size) + ".png")
        save(A.knob_strip(size, red=True), kname("_red", size) + ".png")
        save(A.knob_strip(size, bipolar=True), kname("_bi", size) + ".png")
    save(A.dial_strip(DIAL, frames=DIAL_FRAMES), "dial_vv.png")
    pages, arts, tabs = [], {}, []
    for fn, (name, make) in enumerate(PAGES):
        pg = make(fn)
        arts[name] = save(pg.art.convert("RGB"), "bg_%s.png" % re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_"))
        pages.append(pg)
        tabs += pg.tabs(arts[name])
    return pages, arts, tabs


def main():
    global THEME
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    THEME = THEMES[0]
    save(Image.new("RGBA", (8, 8), (0, 0, 0, 0)), CLEAR)
    passes = []
    for THEME in THEMES:
        passes.append(build_pass())
    THEME = THEMES[0]
    pages, arts, tabs = passes[0]
    if len(THEMES) > 1:   # one TUI.json: each pass's entries shown only while skin == its index (Xenia's skin switch)
        skin = PI("skin")
        for ti, t in enumerate(tabs):
            merged = []
            for which, (_, _, ptabs) in enumerate(passes):
                for e in ptabs[ti]["componentDefinition"]["componentsData"]:
                    b = e["bounds"]
                    b["version"] = 2
                    b.setdefault("additionalInvalidatingHandles", []).append("IndexedEnabling/%d/%d/Parameter %d" % (which, len(THEMES), skin))
                    merged.append(e)
            t["componentDefinition"]["componentsData"] = merged
    for pg in pages:   # the Q-Link frames of one sub-tab must not overlap (the MPC draws them all)
        for sub, blocks in enumerate(pg.subs):
            rs = [r for _, r in blocks]
            for i in range(len(rs)):
                for j in range(i + 1, len(rs)):
                    a, b = rs[i], rs[j]
                    assert not (a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]), "%s sub-tab %d: Q-Link frames overlap %s %s" % (pg.name, sub + 1, a, b)
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
        preview([pg for pg in pages if pg.name == "MOD FAST"], arts, dd, open_list=POPUPS.index("Slot1FDestination") + 1)
        preview([pg for pg in pages if pg.name == "MAIN"], arts, dd, keyboard=True)
        for t, (tpages, tarts, _) in zip(THEMES[1:], passes[1:]):     # the other themes: every page, suffixed
            preview(tpages, tarts, dd, suffix="_" + t)
            preview([pg for pg in tpages if pg.name == "MAIN"], tarts, dd, keyboard=True, suffix="_" + t)
    print("wrote", OUT, "-", len(tabs), "tabs,", len(os.listdir(OUT)), "files,", len(PICK_DEFS), "pick-lists,", len(THEMES), "theme(s)")


if __name__ == "__main__":
    main()
