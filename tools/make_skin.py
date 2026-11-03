#!/usr/bin/env python3
"""The MPC layout in the look of gearmulator's Vavra skin "mqDefault" (theusualsuspects): every page is drawn here (PIL) at the MPC's
1280 x 628 on the skin's dark ring background, with its "Vavra" logo, gold section panels (a darker gold title bar, grey body), cream
labels, its black encoder filmstrip and the microQ's green LCD, laid out for the MPC rather than cropped from the 3400 x 2000 plugin.
The sections follow the microQ's own (Osc, Mixer, Filters, Envelopes, LFOs, Modulation, Effects, Arpeggiator).
    make_skin.py      writes vst/layout.conf and vst/images/page_*.png (tools/make_assets.py makes the parts it draws from)"""
import json, os, re
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "vst")
PARTS = os.path.join(ROOT, "skin", "parts")
FONT = os.path.join(OUT, "fonts")
Y86, W, H = 86, 1280, 628
# LOOK (env VAVRA_LOOK): "rings" = gearmulator's mqDefault; "yellow" = the first microQ's panel; "navy" = the later dark blue one
LOOK = os.environ.get("VAVRA_LOOK", "yellow")
PAL = {
    #          panel fill        title bar       body             label           title text      dim             bg (None: rings)
    "rings":  ((207, 151, 46), (207, 151, 46), (112, 112, 112), (255, 218, 148), (24, 20, 12), (210, 196, 170), None),
    "yellow": ((28, 52, 130), (28, 52, 130), (246, 214, 40), (22, 40, 112), (255, 255, 255), (60, 76, 130), (246, 214, 40)),
    "navy":   ((186, 198, 222), (186, 198, 222), (34, 46, 78), (236, 240, 250), (28, 40, 72), (150, 164, 196), (34, 46, 78)),
}[LOOK]
GOLD, GOLD_DARK, BODY, CREAM, INK, DIM, FLAT = PAL
GOLD_DARK = (168, 122, 36) if FLAT is None else PAL[0]
SUB = INK if FLAT is None else CREAM          # headings inside a panel body
LIVE = "ffda94" if FLAT is None else "%02x%02x%02x" % CREAM
KNOB = 84

PARAMS = {p["key"]: p for p in json.load(open(os.path.join(OUT, "params.json")))["params"]}
_f = {}
def F(size, face="LiberationSans-Bold.ttf"):
    if (size, face) not in _f:
        _f[(size, face)] = ImageFont.truetype(os.path.join(FONT, face), size)
    return _f[(size, face)]
TITLE = "LiberationSans-BoldItalic.ttf"

BG = Image.open(os.path.join(PARTS, "bg.png")).convert("RGB") if FLAT is None else Image.new("RGB", (W, H), FLAT)
LOGO = Image.open(os.path.join(PARTS, "logo.png")).convert("RGBA")
if FLAT is not None:      # the hardware looks: only the "Vavra" script, in the label colour
    a = LOGO.split()[3]
    r, g, b = LOGO.convert("RGB").split()
    dark = Image.eval(r, lambda v: 255 if v < 60 else 0)
    mask = Image.composite(a, Image.new("L", a.size, 0), dark).crop((0, int(LOGO.height * 0.33), LOGO.width, LOGO.height))
    LOGO = Image.new("RGBA", mask.size, CREAM + (0,))
    LOGO.putalpha(mask)
lines = []
emit = lines.append


class Page:
    def __init__(self, name, qkeys, *more):
        self.name, self.qkeys, self.more = name, qkeys, more
        self.im = BG.copy()
        self.d = ImageDraw.Draw(self.im)
        self.widgets = []

    def chip(self, cx, y, text, size=17, font="LiberationSans-Bold.ttf"):
        """a label on a contrast chip (the hardware looks), centred at cx, top at y"""
        f = F(size, font)
        tw = int(self.d.textlength(text, font=f))
        inv = getattr(self, "inv", False)          # on a solid panel: the panel's own colours, swapped
        self.d.rounded_rectangle((cx - tw // 2 - 9, y - 3, cx + tw // 2 + 9, y + size + 4), (size + 7) // 2, fill=BODY if inv else GOLD)
        self.d.text((cx, y), text, font=f, fill=CREAM if inv else INK, anchor="ma")

    def heading(self, cx, y, text):
        """a heading inside a panel body (SLOT 1, OSC 1 ...)"""
        if FLAT is None:
            self.d.text((cx, y), text, font=F(18, TITLE), fill=SUB, anchor="ma")
        else:
            self.chip(cx, y, text, 17, TITLE)

    def panel(self, x, y, w, h, title=None, solid=False):
        """an mqDefault section: gold frame, darker gold title bar with a dark italic title, grey body"""
        if FLAT is None:
            self.d.rounded_rectangle((x, y, x + w, y + h), 6, fill=GOLD)
            self.d.rectangle((x + 3, y + 30, x + w - 3, y + h - 3), fill=BODY)
            if title:
                self.d.text((x + 12, y + 4), title, font=F(21, TITLE), fill=INK)
            return
        # the microQ panel: a rounded frame in the contrast colour with a full-width title bar (solid: filled, for the display areas)
        self.d.rounded_rectangle((x, y, x + w, y + h), 12, outline=GOLD, width=3, fill=GOLD if solid else None)
        if title:
            self.d.rounded_rectangle((x, y, x + w, y + 30), 12, fill=GOLD)
            self.d.rectangle((x, y + 14, x + w, y + 30), fill=GOLD)
            self.d.text((x + 14, y + 4), title, font=F(19, TITLE), fill=INK)

    def label(self, cx, y, s, size=17, color=None):
        if FLAT is not None and color is None:
            self.chip(cx, y, s, size - 1)
            return
        self.d.text((cx, y), s, font=F(size), fill=color or CREAM, anchor="ma")

    def ctl(self, cx, cy, key, label, w=None):
        """the right live widget for the parameter: knob (a number), toggle (two options), popup (more)"""
        p = PARAMS[key]
        opts = p.get("options")
        if opts and len(opts) == 2:
            self.label(cx, cy - 44, label)
            self.widgets.append('toggle cx=%d cy=%d label="" key=%s ns=0' % (cx, cy + Y86, key))
        elif opts and len(opts) <= 40:
            w = w or 150
            self.label(cx, cy - 46, label)
            cw = " cw=130" if len(opts) > 30 else ""
            self.widgets.append('popup cx=%d cy=%d w=%d h=34 label="" key=%s%s' % (cx, cy + Y86 - 2, w, key, cw))
        else:
            self.label(cx, cy - KNOB // 2 - 26, label)
            if getattr(self, "inv", False):       # a value window: MPC writes the value in the theme ink, which needs the panel colour behind it
                self.d.rounded_rectangle((cx - 38, cy + 44, cx + 38, cy + 74), 6, fill=BODY)
            self.widgets.append('knob cx=%d cy=%d r=%d label="" key=%s ns=0 vs=22 vy=14 bw=%d' % (cx, cy + Y86, KNOB // 2 - 8, key, KNOB + 26))

    def small_knob(self, cx, cy, key, label=None, live_label=None, bw=118):
        """dense pages: a 70 px knob, its label in 15 px (or a live label: a readout of another key)"""
        if live_label:
            self.widgets.append('readout cx=%d cy=%d w=140 h=20 label="" key=%s box=0 tsize=14 tcolor=%s tweight=700' % (cx, cy - 44 + Y86, live_label, LIVE))
        else:
            self.label(cx, cy - 58, label, 15)
        self.widgets.append('knob cx=%d cy=%d r=%d label="" key=%s ns=0 vs=18 vy=10 bw=%d' % (cx, cy + Y86, 30, key, bw))

    def row(self, x0, x1, y, items):
        cw = (x1 - x0) / len(items)
        for i, it in enumerate(items):
            if it:
                self.ctl(int(x0 + cw * (i + 0.5)), y, it[0], it[1], it[2] if len(it) > 2 else min(int(cw) - 10, 170))

    def readout(self, cx, cy, key, label, w, style="dotmatrix"):
        if label:
            self.label(cx, cy - 44, label)
        self.widgets.append('readout cx=%d cy=%d w=%d h=36 label="" key=%s style=%s' % (cx, cy + Y86, w, key, style))

    def button(self, cx, cy, key, label):
        self.widgets.append('button cx=%d cy=%d label="%s" key=%s' % (cx, cy + Y86, label, key))

    def done(self):
        fn = "images/page_%s.png" % re.sub(r"[^A-Za-z0-9]+", "_", self.name)
        self.im.save(os.path.join(OUT, fn))
        emit("")
        emit("[tab %s]" % self.name)
        emit('art x=0 y=%d w=%d h=%d file="%s"' % (Y86, W, H, fn))
        lines.extend(self.widgets)
        emit('qlinks "%s" = %s' % (self.name, ",".join(self.qkeys)))
        for title, keys in self.more:
            emit('qlinks "%s" = %s' % (title, ",".join(keys)))


emit("""# Vavra skin layout: generated by tools/make_skin.py (edit that, not this file). Every page is drawn there in the look of the mqDefault skin.
theme_bg=2e2e2e
theme_panel=707070
theme_line=a87a24
theme_ink=ffda94
theme_ink_dim=d2c4aa
theme_accent=e8b04a
theme_accent_hi=e8b04a
theme_knob_face=1a1a1a
theme_knob_ring=000000
theme_knob_dot=f2d21c
theme_lcd=262626
theme_box=262626
theme_seg_active=cf972e
theme_seg_inactive=505050
theme_seg_active_tx=181410
theme_btn_bg=262626
theme_btn_text=ffda94
theme_btn_text_plain=ffda94
theme_display_bg=269029
theme_display_cell=2c9a2f
theme_display_off=23842a
theme_display_bezel=a87a24
theme_display_ink=08200a
theme_tile_on=6e5114
label_scale=1.25
style=td3
art_css=skin.css
knob_strip=images/KNOBSTRIP.png
qlink_bounds=column""")


def header(p):
    """the logo, and the bank / sound steppers in the microQ's LCD green"""
    lg = LOGO.resize((int(LOGO.width * 0.36), int(LOGO.height * 0.36)), Image.LANCZOS) if FLAT is None else LOGO.resize((int(LOGO.width * 0.42), int(LOGO.height * 0.42)), Image.LANCZOS)
    p.im.paste(lg, (16, 4 if FLAT is None else 18), lg)
    if FLAT is None:
        p.d.rounded_rectangle((280, 8, 1272, 108), 6, fill=GOLD)
        p.d.rectangle((283, 38, 1269, 105), fill=BODY)
    else:
        p.d.rounded_rectangle((280, 8, 1272, 108), 12, outline=GOLD, width=3, fill=GOLD)
        for x0, t in ((282, "BANK"), (602, "SOUND")):
            tw = int(p.d.textlength(t, font=F(19, TITLE)))
            p.d.rounded_rectangle((x0, 8, x0 + tw + 24, 34), 10, fill=GOLD)
    p.d.text((292, 12), "BANK", font=F(19, TITLE), fill=INK)
    p.d.text((612, 12), "SOUND", font=F(19, TITLE), fill=INK)
    p.widgets.append('stepper w=290 h=44 cx=440 cy=%d label="" key=bank_index get=bank_name prev=bank_prev next=bank_next style=dotmatrix persistent=1' % (72 + Y86))
    p.widgets.append('stepper w=640 h=44 cx=944 cy=%d label="" key=preset get=preset_name prev=preset_prev next=preset_next style=dotmatrix persistent=1' % (72 + Y86))


# ---------------------------------------------------------------- MAIN
QUICK = ["F1Cutoff", "F1Resonance", "F1EnvMod", "FilterEnvDecay", "AmpEnvAttack", "AmpEnvRelease", "Lfo1Speed", "FX2Mix"]
p = Page("MAIN", QUICK + ["gain"])
header(p)
p.panel(8, 120, 760, 262, "LCD", solid=True)
p.readout(388, 200, "lcd1", "", 620)
p.readout(388, 262, "lcd2", "", 620)
p.label(388, 316, "THE MICROQ'S OWN DISPLAY", 14, DIM if FLAT is None else INK)
p.panel(780, 120, 492, 262, "ENGINE")
p.readout(1026, 200, "loading_status", "", 460, "plain")
p.readout(1026, 262, "engine_stats", "", 460, "plain")
p.button(920, 334, "all_notes_off", "PANIC")
p.button(1130, 334, "init_patch", "RELOAD")
p.panel(8, 394, 1264, 226, "QUICK EDIT", solid=True)
p.inv = FLAT is not None
p.row(8, 1272, 520, [("F1Cutoff", "Cutoff 1"), ("F1Resonance", "Reso 1"), ("F1EnvMod", "Env Mod 1"), ("FilterEnvDecay", "F.Env Decay"),
                     ("AmpEnvAttack", "Attack"), ("AmpEnvRelease", "Release"), ("Lfo1Speed", "LFO 1 Speed"), ("FX2Mix", "FX 2 Mix"), ("gain", "Gain %")])
p.done()

# ---------------------------------------------------------------- BANKS (A/B/C from the ROM, then the sound-set files in banks/)
p = Page("BANKS", ["preset", "bank_index"])
p.panel(8, 8, 250, 612, "BANKS")
p.panel(270, 8, 1002, 612, "SOUNDS")
p.widgets.append('list x=20 y=%d w=226 h=454 cols=1 rows=10 gap=6 th=40 key=bank_slot' % (46 + Y86))
p.widgets.append('stepper w=226 h=40 cx=133 cy=%d label="" key=bank_page_text get=bank_page_text prev=bank_page_prev next=bank_page_next style=dotmatrix' % (540 + Y86))
p.readout(133, 592, "fav_text", "", 226, "plain")
p.widgets.append('stepper w=480 h=40 cx=530 cy=%d label="" key=preset get=preset_name prev=preset_prev next=preset_next style=dotmatrix persistent=1' % (66 + Y86))
p.widgets.append('button cx=836 cy=%d w=96 h=40 label="+FAV" key=fav_save' % (66 + Y86))
p.widgets.append('button cx=942 cy=%d w=96 h=40 label="-FAV" key=fav_delete' % (66 + Y86))
p.widgets.append('stepper w=220 h=40 cx=1146 cy=%d label="" key=patch_page_text get=patch_page_text prev=patch_page_prev next=patch_page_next style=dotmatrix' % (66 + Y86))
p.widgets.append('list x=284 y=%d w=974 h=500 cols=3 rows=10 gap=6 th=44 key=patch_slot order=cols' % (104 + Y86))
p.done()


# ---------------------------------------------------------------- OSC 1 / 2, OSC 3 / MIX
def osc(p, n, y, x0=8, x1=1272, sub=True):
    o = "O%d" % n
    p.panel(x0, y, x1 - x0, 300, "OSC %d" % n)
    top = [(o + "Shape", "Shape", 150), (o + "PwmSource", "PWM Source", 170), (o + "FmSource", "FM Source", 170)]
    if n == 2:
        top.append(("Sync", "Sync to 3"))
    p.row(x0, x1, y + 104, top)
    knobs = [(o + "Octave", "Octave"), (o + "Semi", "Semi"), (o + "Detune", "Detune"), (o + "PulseWidth", "Pulsewidth"), (o + "Pwm", "PWM"), (o + "FmAmount", "FM"), (o + "KeyTrack", "Keytrack"), (o + "BendRange", "Bend Range")]
    if sub:
        knobs += [(o + "SubFreqDiv", "Sub Divide"), (o + "SubVolume", "Sub Level")]
    p.row(x0, x1, y + 218, knobs)


p = Page("OSC 1/2", ["O1Octave", "O1Semi", "O1Detune", "O1PulseWidth", "O1Pwm", "O1FmAmount", "O1KeyTrack", "O1SubVolume",
                     "O2Octave", "O2Semi", "O2Detune", "O2PulseWidth", "O2Pwm", "O2FmAmount", "O2KeyTrack", "O2SubVolume"])
osc(p, 1, 8)
osc(p, 2, 320)
p.done()

p = Page("OSC 3/MIX", ["O3Octave", "O3Semi", "O3Detune", "O3PulseWidth", "O3Pwm", "O3FmAmount", "PitchModAmount", "-",
                       "O1Level", "O2Level", "O3Level", "NoiseLevel", "RingModLevel", "O1Balance", "O2Balance", "O3Balance"])
osc(p, 3, 8, 8, 960, sub=False)
p.panel(972, 8, 300, 300, "PITCH MOD")
p.ctl(1122, 90, "PitchModSrc", "Source", 200)
p.ctl(1122, 230, "PitchModAmount", "Amount")
p.panel(8, 320, 1264, 300, "MIXER")
for i, (lv, bl, nm) in enumerate([("O1Level", "O1Balance", "Osc 1"), ("O2Level", "O2Balance", "Osc 2"), ("O3Level", "O3Balance", "Osc 3"),
                                  ("NoiseLevel", "NoiseBalance", "Noise/Ext"), ("RingModLevel", "RingModBalance", "Ring Mod")]):
    cx = 8 + int(1264 / 5 * (i + 0.5))
    p.heading(cx, 356, nm.upper())
    p.small_knob(cx - 60, 470, lv, "Level")
    p.small_knob(cx + 60, 470, bl, "F1 < > F2")
p.label(640, 560, "NOISE / EXTERNAL INPUT MODE: AMP & GLIDE PAGE", 13, DIM)
p.done()

# ---------------------------------------------------------------- FILTERS
p = Page("FILTERS", ["F1Cutoff", "F1Resonance", "F1Drive", "F1KeyTrack", "F1EnvMod", "F1VelMod", "F1CutoffMod", "F1Pan",
                     "F2Cutoff", "F2Resonance", "F2Drive", "F2KeyTrack", "F2EnvMod", "F2VelMod", "F2CutoffMod", "F2Pan"])
for n, y in ((1, 8), (2, 320)):
    f = "F%d" % n
    p.panel(8, y, 1264, 300, "FILTER %d" % n)
    top = [(f + "Type", "Type", 160), (f + "ModSource", "Cutoff Mod Src", 170), (f + "FmSource", "FM Source", 170), (f + "PanModSource", "Pan Mod Src", 170)]
    if n == 2:
        top.append(("FilterRouting", "Routing", 150))
    p.row(8, 1272, y + 104, top)
    p.row(8, 1272, y + 218, [(f + "Cutoff", "Cutoff"), (f + "Resonance", "Resonance"), (f + "Drive", "Drive"), (f + "KeyTrack", "Keytrack"),
                             (f + "EnvMod", "Env Mod"), (f + "VelMod", "Velocity"), (f + "CutoffMod", "Cutoff Mod"), (f + "FmAmount", "FM"),
                             (f + "Pan", "Pan"), (f + "PanMod", "Pan Mod")])
p.done()

# ---------------------------------------------------------------- AMP & GLIDE (amp, glide, voice mode, noise/ext routing)
p = Page("AMP & GLIDE", ["AmpVolume", "AmpVelocity", "AmpModAmount", "GlideRate", "UnisonoDetune", "-", "-", "-"])
p.panel(8, 8, 620, 300, "AMP")
p.row(8, 628, 82, [("AmpModSource", "Mod Source", 200)])
p.row(8, 628, 222, [("AmpVolume", "Volume"), ("AmpVelocity", "Velocity"), ("AmpModAmount", "Mod Amount")])
p.panel(640, 8, 632, 300, "GLIDE")
p.row(640, 1272, 82, [("GlideEnable", "Glide"), ("GlideMode", "Mode", 200)])
p.row(640, 1272, 222, [("GlideRate", "Rate")])
p.panel(8, 320, 620, 300, "VOICE MODE")
p.row(8, 628, 402, [("VoiceMode", "Mono"), ("UnisonoCount", "Unisono", 150)])
p.row(8, 628, 530, [("UnisonoDetune", "Unisono Detune")])
p.panel(640, 320, 632, 300, "NOISE / EXTERNAL INPUT")
p.row(640, 1272, 470, [("NoiseModeF1", "To Filter 1", 200), ("NoiseModeF2", "To Filter 2", 200)])
p.done()


# ---------------------------------------------------------------- ENVELOPES
def env(p, x, y, w, pre, title):
    p.panel(x, y, w, 300, title)
    p.ctl(x + w // 4, y + 104, pre + "Mode", "Mode", 200)
    p.small_knob(x + 3 * w // 4, y + 104, pre + "TriggerMode", "Trigger")
    ks = [("Attack", "Att"), ("AttackLevel", "Att Lvl"), ("Decay", "Dec"), ("Sustain", "Sus"), ("Decay2", "Dec 2"), ("Sustain2", "Sus 2"), ("Release", "Rel")]
    cw = w / len(ks)
    for i, (k, lab) in enumerate(ks):
        p.small_knob(int(x + cw * (i + 0.5)), y + 226, pre + k, lab, bw=86)


ENVS = [("FilterEnv", "FILTER ENVELOPE"), ("AmpEnv", "AMP ENVELOPE"), ("Env3", "ENVELOPE 3"), ("Env4", "ENVELOPE 4")]
EK = ("Attack", "Decay", "Sustain", "Release", "AttackLevel", "Decay2", "Sustain2", None)
p = Page("ENVELOPES", [e + k if k else "-" for e, _ in ENVS[:2] for k in EK], ("ENV 3/4", [e + k if k else "-" for e, _ in ENVS[2:] for k in EK]))
for i, (pre, title) in enumerate(ENVS):
    env(p, 8 + (i % 2) * 636, 8 + (i // 2) * 312, 628, pre, title)
p.done()

# ---------------------------------------------------------------- LFOs
p = Page("LFO", ["Lfo1Speed", "Lfo1StartPhase", "Lfo1Delay", "Lfo1Fade", "Lfo2Speed", "Lfo2StartPhase", "Lfo2Delay", "Lfo2Fade",
                 "Lfo3Speed", "Lfo3StartPhase", "Lfo3Delay", "Lfo3Fade", "Lfo1KeyTrack", "Lfo2KeyTrack", "Lfo3KeyTrack", "-"])
for n in (1, 2, 3):
    l = "Lfo%d" % n
    y = 8 + (n - 1) * 208
    p.panel(8, y, 1264, 200, "LFO %d" % n)
    x0 = 8
    p.ctl(110, y + 118, l + "Shape", "Shape", 170)
    p.ctl(260, y + 118, l + "Sync", "Sync")
    p.ctl(370, y + 118, l + "Clocked", "Clocked")
    for i, (k, lab) in enumerate([("Speed", "Speed"), ("StartPhase", "Start Phase"), ("Delay", "Delay"), ("Fade", "Fade"), ("KeyTrack", "Keytrack")]):
        p.small_knob(520 + i * 165, y + 110, l + k, lab)
p.done()


# ---------------------------------------------------------------- MOD SLOTS (fast and standard), MODIFIERS
def slots(name, kind, title, n):
    pre = "Slot%d" + kind
    p = Page(name, [(pre % i) + "Amount" for i in range(1, n + 1)])
    p.panel(8, 8, 1264, 612, title)
    for i in range(n):
        c, r = i % 4, i // 4
        cx, y = 8 + int(1264 / 4 * (c + 0.5)), 50 + r * 290
        p.heading(cx, y - 6, "SLOT %d" % (i + 1))
        p.widgets.append('popup cx=%d cy=%d w=270 h=34 label="" key=%s cw=130' % (cx, y + 48 + Y86, (pre % (i + 1)) + "Source"))
        p.label(cx, y + 74, "TO", 13, DIM)
        p.widgets.append('popup cx=%d cy=%d w=270 h=34 label="" key=%s cw=130' % (cx, y + 112 + Y86, (pre % (i + 1)) + "Destination"))
        p.small_knob(cx, y + 194, (pre % (i + 1)) + "Amount", "Amount")
    for i in range(1, 4):
        p.d.line((8 + 316 * i, 40, 8 + 316 * i, 612), fill=GOLD_DARK, width=2)
    p.d.line((12, 326, 1268, 326), fill=GOLD_DARK, width=2)
    p.done()


slots("MOD FAST", "F", "FAST MODULATION SLOTS (AUDIO RATE)", 8)
slots("MOD SLOTS", "S", "MODULATION SLOTS", 8)

p = Page("MODIFIERS", ["Mod1Constant", "Mod2Constant", "Mod3Constant", "Mod4Constant", "ControllerDelay"])
p.panel(8, 8, 1264, 420, "MODIFIERS")
for i in range(4):
    m = "Mod%d" % (i + 1)
    cx = 8 + int(1264 / 4 * (i + 0.5))
    p.heading(cx, 46, "MODIFIER %d" % (i + 1))
    p.widgets.append('popup cx=%d cy=%d w=270 h=34 label="" key=%s cw=130' % (cx, 104 + Y86, m + "Source1"))
    p.widgets.append('popup cx=%d cy=%d w=200 h=34 label="" key=%s' % (cx, 164 + Y86, m + "Operator"))
    p.widgets.append('popup cx=%d cy=%d w=270 h=34 label="" key=%s cw=130' % (cx, 224 + Y86, m + "Source2"))
    p.label(cx - 150, 96, "A", 15)
    p.label(cx - 150, 216, "B", 15)
    p.small_knob(cx, 352, m + "Constant", "Constant")
for i in range(1, 4):
    p.d.line((8 + 316 * i, 40, 8 + 316 * i, 424), fill=GOLD_DARK, width=2)
p.panel(8, 440, 1264, 180, "CONTROLLER DELAY")
p.ctl(400, 540, "ControllerDelaySource", "Source", 220) if "options" in PARAMS["ControllerDelaySource"] else p.small_knob(400, 532, "ControllerDelaySource", "Source")
p.small_knob(880, 532, "ControllerDelay", "Delay")
p.done()

# ---------------------------------------------------------------- FX (the knobs' names follow the effect type)
p = Page("FX", ["FX1Mix"] + ["fx1_p%d" % i for i in range(1, 8)] + ["FX2Mix"] + ["fx2_p%d" % i for i in range(1, 8)],
         ("FX 1 MORE", ["fx1_p%d" % i for i in range(8, 15)]), ("FX 2 MORE", ["fx2_p%d" % i for i in range(8, 15)]))
for n, y in ((1, 8), (2, 320)):
    p.panel(8, y, 1264, 300, "EFFECT %d" % n)
    p.ctl(120, y + 96, "FX%dType" % n, "Type", 190)
    p.ctl(120, y + 214, "FX%dMix" % n, "Mix")
    p.d.line((240, y + 40, 240, y + 290), fill=GOLD_DARK, width=2)
    for i in range(14):
        c, r = i % 7, i // 7
        p.small_knob(250 + int(1012 / 7 * (c + 0.5)), y + 92 + r * 128, "fx%d_p%d" % (n, i + 1), live_label="fx%d_l%d" % (n, i + 1))
p.done()

# ---------------------------------------------------------------- ARP, and its 16-step user pattern
p = Page("ARP", ["Tempo", "ArpClock", "ArpLength", "ArpTFactor", "ArpOctaveRange", "ArpMaxNotes", "ArpPatternLength", "-"])
p.panel(8, 8, 1264, 300, "ARPEGGIATOR")
p.row(8, 1272, 104, [("ArpMode", "Mode", 150), ("ArpPattern", "Pattern", 150), ("ArpDirection", "Direction", 150), ("ArpSortOrder", "Order", 170),
                     ("ArpVeloMode", "Velocity", 170), ("ArpSameNoteOverlap", "Note Overlap"), ("ArpPatternReset", "Pattern Reset")])
p.row(8, 1272, 228, [("Tempo", "Tempo", 130), ("ArpClock", "Clock", 130), ("ArpLength", "Length", 130), ("ArpTFactor", "Timing Factor"),
                     ("ArpOctaveRange", "Range"), ("ArpMaxNotes", "Max Notes"), ("ArpPatternLength", "User Length")])
p.panel(8, 320, 1264, 300, "TEMPO")
p.label(640, 392, "WITH MPC PLAYING, THE ARPEGGIATOR AND CLOCKED LFOS FOLLOW MPC'S TEMPO.", 17)
p.label(640, 432, "STOPPED, THEY RUN AT THE SOUND'S OWN TEMPO.", 17)
p.label(640, 492, "PATTERN \"USER\" PLAYS THE 16 STEPS ON THE ARP STEPS PAGES.", 17)
p.done()

ROWS = [("Step", "Step"), ("Glide", "Glide"), ("Accent", "Accent"), ("Length", "Length"), ("Timing", "Timing")]
for first in (0, 8):
    name = "ARP STEPS %d-%d" % (first + 1, first + 8)
    p = Page(name, ["Arp%02dAccent" % (first + i) for i in range(8)] + ["Arp%02dLength" % (first + i) for i in range(8)])
    p.panel(8, 8, 1264, 612, "USER PATTERN STEPS %d-%d" % (first + 1, first + 8))
    for r, (k, lab) in enumerate(ROWS):
        y = 100 + r * 112
        p.heading(80, y - 10, lab.upper())
        for c in range(8):
            cx = 180 + int(1080 / 8 * (c + 0.5))
            key = "Arp%02d%s" % (first + c, k)
            if r == 0:
                p.heading(cx, 46, "%d" % (first + c + 1))
            if k == "Glide":
                p.widgets.append('toggle cx=%d cy=%d label="" key=%s ns=0' % (cx, y + Y86, key))
            else:
                p.widgets.append('popup cx=%d cy=%d w=124 h=34 label="" key=%s' % (cx, y + Y86, key))
    p.done()

THEMES = {
    "yellow": dict(theme_bg="f6d628", theme_panel="f6d628", theme_line="1c3482", theme_ink="16286f", theme_ink_dim="3c4c82", theme_accent="ffffff",
                   theme_accent_hi="ffffff", theme_lcd="0e1c52", theme_box="1c3482", theme_seg_active="1c3482", theme_seg_inactive="d8bc1c",
                   theme_seg_active_tx="ffffff", theme_btn_bg="3c5cc0", theme_btn_text="ffffff", theme_btn_text_plain="ffffff", theme_display_bezel="1c3482",
                   theme_tile_on="c8202a"),
    "navy": dict(theme_bg="222e4e", theme_panel="222e4e", theme_line="bac6de", theme_ink="ecf0fa", theme_ink_dim="96a4c4", theme_accent="ecf0fa",
                 theme_accent_hi="ffffff", theme_lcd="141c32", theme_box="141c32", theme_seg_active="bac6de", theme_seg_inactive="141c32",
                 theme_seg_active_tx="1c2848", theme_btn_bg="141c32", theme_btn_text="ecf0fa", theme_btn_text_plain="ecf0fa", theme_display_bezel="bac6de",
                 theme_tile_on="c8202a"),
}
if LOOK in THEMES:
    lines = [("%s=%s" % (l.split("=")[0], THEMES[LOOK][l.split("=")[0]])) if l.split("=")[0] in THEMES[LOOK] else l for l in lines[:1]] + lines[1:]
    lines[0] = "\n".join(("%s=%s" % (l.split("=")[0], THEMES[LOOK][l.split("=")[0]])) if l.split("=")[0] in THEMES[LOOK] else l for l in lines[0].split("\n"))
open(os.path.join(OUT, "layout.conf"), "w").write(("\n".join(lines) + "\n").replace("KNOBSTRIP", "knob_mq" if FLAT is None else "knob_fp"))
print("layout.conf: %d lines" % len(lines))
