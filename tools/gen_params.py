#!/usr/bin/env python3
"""Write vst/params.json and src/dsp/vavra_params.h from gearmulator's own parameter table for the microQ
(skin/parameterDescriptions_mq.json, the file the Vavra editor is built from).

The VST parameter index is the position in params.json and saved projects bind to it: the engine's own keys come first, then the
microQ's single parameters in table order, then everything added later. Append only (vst/params.lock, checked by gen_vst.py).

Each single parameter becomes one VST parameter named like the table's name (O1Octave, F1Cutoff, Slot3SAmount ...):
  - a value list with a label for every value -> an option list
  - `signed`, `keytrack`, `pan`, `filterBalance` (centre 64) -> a whole number with 64 taken off (kind 0, off 64)
  - `octaves` -> -4..4 (raw 16 + 12 n ... the table's own 16..112 in steps of 12; kind 2)
  - everything else -> the raw whole number
Several parameters share one byte as bit fields (VoiceMode / UnisonoCount, the envelope mode / trigger, the arp steps): the
"singledump" packet of the table gives their mask and shift (kind | 0x80 in the header). The FX bytes (130-143, 146-159) mean
something else for each effect type: they are exposed as FX1 P1..P14 / FX2 P1..P14 with a label table per type."""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SRC = os.path.join(ROOT, "skin", "parameterDescriptions_mq.json")
OUT = os.path.join(ROOT, "vst", "params.json")
HDR = os.path.join(ROOT, "src", "dsp", "vavra_params.h")


def load():
    def strip(line):
        out, ins, i = [], False, 0
        while i < len(line):
            c = line[i]
            if c == '"':
                ins = not ins
            if not ins and line.startswith("//", i):
                break
            out.append(c)
            i += 1
        return "".join(out)
    t = "\n".join(strip(l) for l in open(SRC).read().split("\n"))
    t = re.sub(r",(\s*[\]}])", r"\1", t)
    return json.loads(t)


D = load()
DF = D["parameterdescriptiondefaults"]
VL = D["valuelists"]
rows, page = [], 0
for x in D["parameterdescriptions"]:
    page = x.get("page", page)
    y = dict(DF)
    y.update(x)
    y["page"] = page
    rows.append(y)
MASK = {}
for e in D["midipackets"]["singledump"]:
    if e.get("type") == "param" and "mask" in e:
        MASK[e["name"]] = (int(str(e["mask"]), 0), int(str(e.get("shift", 0)), 0))

N_PER_BANK, N_BANKS, N_PATCH_TILES = 100, 3, 30

NAMES = {
    "PitchModSrc": "Pitch Mod Source", "PitchModAmount": "Pitch Mod Amount", "GlideEnable": "Glide", "GlideMode": "Glide Mode",
    "GlideRate": "Glide Rate", "VoiceMode": "Mono", "UnisonoCount": "Unisono", "UnisonoDetune": "Unisono Detune",
    "NoiseModeF1": "Noise/Ext F1", "NoiseModeF2": "Noise/Ext F2", "FilterRouting": "Filter Routing", "AmpVolume": "Amp Volume",
    "AmpVelocity": "Amp Velocity", "AmpModSource": "Amp Mod Source", "AmpModAmount": "Amp Mod Amount", "FX1Type": "FX 1 Type",
    "FX2Type": "FX 2 Type", "FX1Mix": "FX 1 Mix", "FX2Mix": "FX 2 Mix", "ControllerDelaySource": "Ctrl Delay Source",
    "ControllerDelay": "Ctrl Delay", "Tempo": "Tempo",
}


def nice(name):
    if name in NAMES:
        return NAMES[name]
    s = re.sub(r"^O(\d)", r"Osc \1 ", name)
    s = re.sub(r"^F(\d)", r"Filter \1 ", s)
    s = re.sub(r"^Lfo(\d)", r"LFO \1 ", s)
    s = re.sub(r"^Env(\d)", r"Env \1 ", s)
    s = re.sub(r"^Mod(\d)", r"Mod \1 ", s)
    s = re.sub(r"^Slot(\d)F", r"Fast Slot \1 ", s)
    s = re.sub(r"^Slot(\d)S", r"Slot \1 ", s)
    s = re.sub(r"^Arp(\d\d)", lambda m: "Arp Step %d " % (int(m.group(1)) + 1), s)
    s = s.replace("FilterEnv", "Filter Env ").replace("AmpEnv", "Amp Env ")
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def labels_for(tt, lo, hi):
    v = VL.get(tt)
    if v is None:
        return None
    if isinstance(v, dict):
        pairs = [(v.get(str(i)), i) for i in range(lo, hi + 1)]
    else:
        pairs = [(v[i] if i < len(v) else None, i) for i in range(lo, hi + 1)]
    pairs = [(s, i) for s, i in pairs if s]
    return [s for s, _ in pairs], [i for _, i in pairs]


CENTRED = {"signed", "keytrack", "pan", "filterBalance"}
params, keys_in = [], {}
MQ = []        # (key, idx, lo, hi, kind, off, map, default, mask, shift)


def add(p, sec):
    params.append(p)
    keys_in.setdefault(sec, []).append(p["key"])


# ---- engine keys first (VST index = order; never reorder)
add(dict(key="bank_index", name="BANK", min=0, max=63, default=0, display="int"), "Browse")
add(dict(key="preset", name="PRESET", min=0, max=127, default=0, display="int"), "Browse")
add(dict(key="bank_name", name="BANK NAME", min=0, max=0, default=0, display="string", poll=True), "Browse")
add(dict(key="preset_name", name="PRESET NAME", min=0, max=0, default=0, display="string", poll=True), "Browse")
add(dict(key="bank_prev", name="BANK -", min=0, max=1, default=0, momentary=True), "Browse")
add(dict(key="bank_next", name="BANK +", min=0, max=1, default=0, momentary=True), "Browse")
add(dict(key="preset_prev", name="PRESET -", min=0, max=1, default=0, momentary=True), "Browse")
add(dict(key="preset_next", name="PRESET +", min=0, max=1, default=0, momentary=True), "Browse")
add(dict(key="all_notes_off", name="PANIC", min=0, max=1, default=0, momentary=True), "Browse")
add(dict(key="rom_name", name="ROM", min=0, max=0, default=0, display="string", poll=True), "System")
add(dict(key="loading_status", name="STATUS", min=0, max=0, default=0, display="string", poll=True), "System")
add(dict(key="engine_stats", name="STATS", min=0, max=0, default=0, display="string", poll=True), "System")
add(dict(key="lcd1", name="LCD 1", min=0, max=0, default=0, display="string", poll=True), "System")
add(dict(key="lcd2", name="LCD 2", min=0, max=0, default=0, display="string", poll=True), "System")
add(dict(key="gain", name="GAIN %", min=10, max=400, default=100, display="int"), "System")
add(dict(key="init_patch", name="RELOAD", min=0, max=1, default=0, momentary=True), "System")

SECTIONS = [("Osc", ("O1", "O2", "O3", "Sync", "PitchMod")), ("Mixer", ("O1Level", "O2Level", "O3Level", "Noise", "RingMod", "O1Balance", "O2Balance", "O3Balance")),
            ("Voice", ("Glide", "VoiceMode", "Unisono")), ("Filters", ("F1", "F2", "FilterRouting")), ("Amp", ("Amp",)),
            ("FX", ("FX", "Fx")), ("LFO", ("Lfo",)), ("Envelopes", ("FilterEnv", "AmpEnv", "Env3", "Env4")), ("Mod", ("Mod", "Slot", "ControllerDelay")),
            ("Arp", ("Arp", "Tempo"))]


def section(name):
    best = None
    for label, prefixes in SECTIONS:
        for p in prefixes:
            if name.startswith(p) and (best is None or len(p) > best[1]):
                best = (label, len(p))
    return best[0] if best else "Other"


seen = set()
for r in rows:
    if r["page"] != 0:
        continue
    name, idx, lo, hi, tt = r["name"], r["index"], r["min"], r["max"], r["toText"]
    if name == "ControllerDelaySource":
        tt = "modSource"                           # the table gives it no value list
    if name == "Version" or tt == "ascii" or name.endswith("SpeedClocked"):
        continue
    if 130 <= idx <= 143 or 146 <= idx <= 159:
        continue                                   # FX type dependent: FX1/FX2 P1..P14 below
    mk = MASK.get(name)
    if not mk and idx in seen:
        continue
    seen.add(idx)
    lr = labels_for(tt, lo, hi) if tt not in CENTRED and tt not in ("unsignedZero", "unsignedOne") else None
    mapn = None
    dflt = r.get("default", 64 if tt in CENTRED and lo == 0 else lo)
    if tt == "octaves":
        p = dict(key=name, name=nice(name), min=-4, max=4, default=(dflt - 64) // 12 if "default" in r else 0, display="int")
        kind, off, dflt = 2, 0, r.get("default", 64)
    elif lr is not None and len(lr[0]) > 1:
        labels, raws = lr
        di = raws.index(dflt) if dflt in raws else 0
        if tt == "arpStep":
            labels = ["Note", "Pause", "Previous", "First", "Last", "First+Last", "Chord", "Random"][:len(labels)]
        if tt == "arpTiming":
            labels = [l.replace("|", "On Beat") for l in labels]
        if tt == "arpStepLength":
            labels = [l.replace("As Note Length", "Note") for l in labels]
        if len(set(labels)) != len(labels):
            labels = [l if labels.count(l) == 1 else "%s %d" % (l, i + 1) for i, l in enumerate(labels)]
        p = dict(key=name, name=nice(name), options=labels, default=labels[di])
        if raws == list(range(lo, lo + len(raws))):
            kind, off = 1, 0
        else:
            kind, off, mapn = 3, 0, raws
    elif r.get("isBool") and hi - lo == 1:
        p = dict(key=name, name=nice(name), options=["OFF", "ON"], default="ON" if dflt == hi else "OFF")
        kind, off = 1, 0
    else:
        off = 64 if tt in CENTRED else (-1 if tt == "unsignedOne" else 0)
        p = dict(key=name, name=nice(name), min=lo - off, max=hi - off, default=dflt - off, display="int")
        kind = 0
    add(p, section(name))
    MQ.append((name, idx, lo, hi, kind, off, mapn, int(dflt), mk[0] if mk else 0, mk[1] if mk else 0))

# ---- FX bytes by type: 14 knobs each, their label per effect type (from the table's own names)
FX_TYPES = {1: VL["fx1Type"], 2: VL["fx2Type"]}
FX_PREFIX = {"Chorus": "Chorus", "Flanger": "Flanger", "Phaser": "Phaser", "Overdrive": "Overdrive", "Five FX": "FiveFX", "Vocoder": "Vocoder",
             "Delay": "Delay", "Reverb": "Reverb", "5.1 Delay": "51Delay", "5.1 Delay Clocked": "51ClockDelay"}
FXLAB = {1: [], 2: []}
for fx in (1, 2):
    base = 130 if fx == 1 else 146
    for t, tname in enumerate(FX_TYPES[fx]):
        labs = [""] * 14
        pre = FX_PREFIX.get(tname)
        if pre:
            for r in rows:
                if r["page"] != 0:
                    continue
                n = r["name"]
                if pre == "FiveFX":
                    ok = n.startswith("FiveFX%d" % fx)
                    rest = n[len("FiveFX%d" % fx):]
                else:
                    ok = n.startswith("Fx%d%s" % (fx, pre)) and not (pre == "Delay" and n.startswith("Fx%d%s" % (fx, "51")))
                    rest = n[len("Fx%d%s" % (fx, pre)):]
                    if pre == "Delay" and fx == 2 and n.startswith("Fx251"):
                        ok = False
                if ok and base <= r["index"] < base + 14 and not labs[r["index"] - base]:
                    labs[r["index"] - base] = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", rest).replace("Delay Delay", "Delay").upper()[:14]
        FXLAB[fx].append(labs)
for fx in (1, 2):
    for i in range(14):
        add(dict(key="fx%d_p%d" % (fx, i + 1), name="FX %d P%d" % (fx, i + 1), min=0, max=127, default=0, display="int"), "FX")
        add(dict(key="fx%d_l%d" % (fx, i + 1), name="FX %d P%d NAME" % (fx, i + 1), min=0, max=0, default=0, display="string", poll=True), "FX")

# ---- BANKS page
for i in range(1, N_BANKS + 1):
    add(dict(key="bank_slot_%d" % i, name="BANK %d" % i, min=0, max=1, default=0, momentary=True, display="string", poll=True), "Banks")
for i in range(1, 26):
    add(dict(key="patch_slot_%d" % i, name="PATCH %d" % i, min=0, max=1, default=0, momentary=True, display="string", poll=True), "Banks")
add(dict(key="patch_page_text", name="PAGE", min=0, max=0, default=0, display="string", poll=True), "Banks")
add(dict(key="patch_page_prev", name="PAGE -", min=0, max=1, default=0, momentary=True), "Banks")
add(dict(key="patch_page_next", name="PAGE +", min=0, max=1, default=0, momentary=True), "Banks")
# favourites: "favourite" is MPC's native program list (vst.json "programs")
add(dict(key="favourite", name="FAVOURITE", min=0, max=63, default=63, display="int"), "Banks")
add(dict(key="fav_save", name="SAVE FAV", min=0, max=1, default=0, momentary=True), "Banks")
add(dict(key="fav_delete", name="DEL FAV", min=0, max=1, default=0, momentary=True), "Banks")
add(dict(key="fav_text", name="FAVOURITES", min=0, max=0, default=0, display="string", poll=True), "Banks")
for i in range(26, N_PATCH_TILES + 1):                # appended later (0.1.0 had 25 tiles)
    add(dict(key="patch_slot_%d" % i, name="PATCH %d" % i, min=0, max=1, default=0, momentary=True, display="string", poll=True), "Banks")
# sound-set files in banks/: more bank tiles, paged (appended)
for i in range(4, 11):
    add(dict(key="bank_slot_%d" % i, name="BANK %d" % i, min=0, max=1, default=0, momentary=True, display="string", poll=True), "Banks")
add(dict(key="bank_page_text", name="BANK PAGE", min=0, max=0, default=0, display="string", poll=True), "Banks")
add(dict(key="bank_page_prev", name="BANK PAGE -", min=0, max=1, default=0, momentary=True), "Banks")
add(dict(key="bank_page_next", name="BANK PAGE +", min=0, max=1, default=0, momentary=True), "Banks")

order = ["Browse", "Banks", "System"] + [s for s, _ in SECTIONS] + ["Other"]
sections = [{"label": s, "keys": keys_in[s]} for s in order if s in keys_in]
json.dump({"name": "Vavra", "params": params, "sections": sections}, open(OUT, "w"), indent=1)

with open(HDR, "w") as f:
    f.write("/* generated by tools/gen_params.py from skin/parameterDescriptions_mq.json: do not edit.\n"
            " * One row per microQ single parameter: VST key, byte in the single (0 = the first parameter byte), raw range, how a VST value\n"
            " * maps to the raw value (kind 0: raw = value + off, 1: option list, raw = lo + index, 2: octaves, raw = 64 + 12 * value,\n"
            " * 3: option list over the sparse raw values in map), and for a bit field its mask and shift in the byte. */\n"
            "#pragma once\n#include <stdint.h>\n"
            "struct mq_param_t { const char *key; uint16_t idx; int16_t lo, hi; uint8_t kind; int16_t off; const uint8_t *map; uint8_t nmap; int16_t def; uint8_t mask, shift; };\n")
    for k, idx, lo, hi, kind, off, mapn, dflt, mk, sh in MQ:
        if mapn:
            f.write("static const uint8_t mq_map_%s[] = {%s};\n" % (k, ",".join(str(i) for i in mapn)))
    f.write("static const mq_param_t g_mq_params[] = {\n")
    for k, idx, lo, hi, kind, off, mapn, dflt, mk, sh in MQ:
        f.write('    {"%s", %d, %d, %d, %d, %d, %s, %d, %d, %d, %d},\n' % (k, idx, lo, hi, kind, off, ("mq_map_" + k) if mapn else "nullptr",
                                                                  len(mapn) if mapn else 0, dflt, mk, sh))
    f.write("};\nstatic const int MQ_NUM_PARAMS = %d;\n" % len(MQ))
    f.write("#define VV_BANKS %d\n#define VV_PER_BANK %d\n#define VV_PATCH_TILES %d\n" % (N_BANKS, N_PER_BANK, N_PATCH_TILES))
    # per effect type: the bytes it uses, packed onto the first knobs (offset from the FX's first byte, -1 = unused), and their names
    for fx in (1, 2):
        f.write("static const int8_t g_fx%d_byte[%d][14] = {\n" % (fx, len(FXLAB[fx])))
        for labs in FXLAB[fx]:
            used = [i for i, l in enumerate(labs) if l]
            f.write("    {%s},\n" % ", ".join(str(x) for x in used + [-1] * (14 - len(used))))
        f.write("};\nstatic const char *const g_fx%d_labels[%d][14] = {\n" % (fx, len(FXLAB[fx])))
        for labs in FXLAB[fx]:
            used = [l for l in labs if l]
            f.write("    {%s},\n" % ", ".join(json.dumps(l) for l in used + [""] * (14 - len(used))))
        f.write("};\n")
    f.write("#define FX1_TYPES %d\n#define FX2_TYPES %d\n" % (len(FXLAB[1]), len(FXLAB[2])))
print("params.json: %d params (%d microQ single parameters), %d sections" % (len(params), len(MQ), len(sections)))
for fx in (1, 2):
    for t, labs in enumerate(FXLAB[fx]):
        print(" fx%d %-18s %s" % (fx, FX_TYPES[fx][t], [l for l in labs if l]))
