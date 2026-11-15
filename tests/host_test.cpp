// Offline host test for the native front end (src/VavraPlugin.cpp) with the real engine and your ROM, under ASan/UBSan (tests/run.sh).
// A fake VST2 host drives it in real time (the emulator thread fills its ring at its own pace): identity and frozen order, sound, value /
// option / momentary / tile params, FX knob names, the parameter-0 nudge, the drawn pick-list flag, favourites in the PRESET menu, user
// sound-set banks, a state round trip into a second instance, a 0.1.0 project chunk (tests/data/legacy-0.1.0.chunk, made by the released
// build itself) handed over before the boot, bad chunks, the host's transport, and a 48 kHz host. Prints OK at the end, or the failed
// checks and exits 1.
#include "mpc_vst2_abi.h"
#include "params_gen.h"

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

extern "C" AEffect* VSTPluginMain(audioMasterCallback);
extern "C" void vavra_dbg_tick(AEffect*);
extern "C" int vavra_dbg_ready(AEffect*);
extern "C" int vavra_dbg_engine(AEffect*, const char*, char*, int);

static std::atomic<int> g_automate[kNumParams];
static std::atomic<int> g_updateDisplay{0};
static int g_fail = 0;
static VstTimeInfo g_time;
static bool g_giveTime = false;

static VstIntPtr host(AEffect*, VstInt32 op, VstInt32 idx, VstIntPtr, void*, float)
{
    if (op == audioMasterAutomate && idx >= 0 && idx < kNumParams) g_automate[idx]++;
    if (op == audioMasterVersion) return 2400;
    if (op == audioMasterUpdateDisplay) g_updateDisplay++;
    if (op == audioMasterGetTime) return g_giveTime ? (VstIntPtr)&g_time : 0;
    return 0;
}

#define CHECK(c, ...) do { if (c) { std::printf("  ok   "); } else { std::printf("  FAIL "); g_fail++; } std::printf(__VA_ARGS__); std::printf("\n"); } while (0)

static int idx(const char* key)
{
    for (int i = 0; i < kNumParams; i++) if (!std::strcmp(g_pspecs[i].key, key)) return i;
    std::printf("no param %s\n", key); std::exit(2);
}
static float norm(int i, float plain) { const PSpec& s = g_pspecs[i]; return s.max > s.min ? (plain - s.min) / (s.max - s.min) : 0.f; }
static float plainOf(AEffect* e, int i) { const PSpec& s = g_pspecs[i]; return s.min + e->getParameter(e, i) * (s.max - s.min); }
static std::string eng(AEffect* e, const char* k) { char b[4096]; vavra_dbg_engine(e, k, b, sizeof b); return b; }
static int engi(AEffect* e, const char* k) { return std::atoi(eng(e, k).c_str()); }
static std::string disp(AEffect* e, int i) { char b[128] = {0}; e->dispatcher(e, effGetParamDisplay, i, 0, b, 0); return b; }
static std::string progName(AEffect* e, int i) { char b[64] = {0}; e->dispatcher(e, effGetProgramNameIndexed, i, 0, b, 0); return b; }

static double g_rms, g_peak;
static std::vector<float>* g_rec;     // VAVRA_REC=<dir>: what run() renders, written as <dir>/<name>.wav (listening / analysis)
static void recWav(const char* name, const std::vector<float>& v, int sr)
{
    const char* dir = std::getenv("VAVRA_REC");
    if (!dir || v.empty()) return;
    FILE* f = std::fopen((std::string(dir) + "/" + name + ".wav").c_str(), "wb");
    if (!f) return;
    const uint32_t data = (uint32_t)(v.size() * 4), riff = 36 + data, fmt = 16, rate = (uint32_t)sr, bps = rate * 8;
    const uint16_t pcm = 3, chs = 2, align = 8, bits = 32;
    std::fwrite("RIFF", 1, 4, f); std::fwrite(&riff, 4, 1, f); std::fwrite("WAVEfmt ", 1, 8, f); std::fwrite(&fmt, 4, 1, f);
    std::fwrite(&pcm, 2, 1, f); std::fwrite(&chs, 2, 1, f); std::fwrite(&rate, 4, 1, f); std::fwrite(&bps, 4, 1, f);
    std::fwrite(&align, 2, 1, f); std::fwrite(&bits, 2, 1, f); std::fwrite("data", 1, 4, f); std::fwrite(&data, 4, 1, f);
    std::fwrite(v.data(), 4, v.size(), f);
    std::fclose(f);
}
static void run(AEffect* e, int blocks, const std::vector<std::vector<uint8_t>>& midi = {}, int frames = 128)
{
    std::vector<float> L((size_t)frames), R((size_t)frames);
    float* out[2] = {L.data(), R.data()};
    double acc = 0; long n = 0;
    g_peak = 0;
    for (int b = 0; b < blocks; b++)
    {
        if (b == 0 && !midi.empty())
        {
            std::vector<VstMidiEvent> ev(midi.size());
            std::vector<char> buf(sizeof(VstEvents) + sizeof(VstEvent*) * midi.size());
            VstEvents* evs = reinterpret_cast<VstEvents*>(buf.data());
            evs->numEvents = (VstInt32)midi.size();
            for (size_t k = 0; k < midi.size(); k++)
            {
                std::memset(&ev[k], 0, sizeof ev[k]);
                ev[k].type = kVstMidiType; ev[k].byteSize = sizeof(VstMidiEvent);
                for (size_t j = 0; j < 3 && j < midi[k].size(); j++) ev[k].midiData[j] = (char)midi[k][j];
                evs->events[k] = reinterpret_cast<VstEvent*>(&ev[k]);
            }
            e->dispatcher(e, effProcessEvents, 0, 0, evs, 0);
        }
        e->processReplacing(e, nullptr, out, frames);
        if (g_giveTime) g_time.ppqPos += frames * g_time.tempo / 60.0 / g_time.sampleRate;
        if (g_rec) for (int i = 0; i < frames; i++) { g_rec->push_back(L[i]); g_rec->push_back(R[i]); }
        for (int i = 0; i < frames; i++) { acc += (double)L[i] * L[i] + (double)R[i] * R[i]; n += 2; g_peak = std::max(g_peak, (double)std::max(std::fabs(L[i]), std::fabs(R[i]))); }
        std::this_thread::sleep_for(std::chrono::microseconds(2900 * frames / 128));
    }
    g_rms = n ? std::sqrt(acc / n) : 0;
}
static void settle(AEffect* e, int blocks = 40) { run(e, blocks); vavra_dbg_tick(e); }
static void tap(AEffect* e, int i, int blocks = 60) { e->setParameter(e, i, 1.0f); settle(e, blocks); e->setParameter(e, i, 0.0f); settle(e, 10); }
static void key(AEffect* e, int i) { tap(e, i, 30); run(e, 80); }   // a keyboard key: > 250 ms apart (a quicker repeat counts as the same tap)

static AEffect* open(const char* what, float rate = 44100.f)
{
    AEffect* e = VSTPluginMain(host);
    e->dispatcher(e, effSetSampleRate, 0, 0, nullptr, rate);
    e->dispatcher(e, effSetBlockSize, 0, 128, nullptr, 0);
    e->dispatcher(e, effMainsChanged, 0, 1, nullptr, 0);
    std::printf("%s: opened\n", what);
    return e;
}
static void close(AEffect* e) { e->dispatcher(e, effMainsChanged, 0, 0, nullptr, 0); e->dispatcher(e, effClose, 0, 0, nullptr, 0); }
static bool waitReady(AEffect* e)
{
    for (int t = 0; t < 300 && !vavra_dbg_ready(e); t++) run(e, 34);   // up to ~30 s
    run(e, 300);                                                       // the first sound arrives
    vavra_dbg_tick(e);
    return vavra_dbg_ready(e);
}
static std::vector<uint8_t> chunk(AEffect* e)
{
    void* p = nullptr;
    const VstIntPtr n = e->dispatcher(e, effGetChunk, 0, 0, &p, 0);
    return n > 0 && p ? std::vector<uint8_t>((uint8_t*)p, (uint8_t*)p + n) : std::vector<uint8_t>();
}

int main(int argc, char** argv)
{
    const char* legacyPath = argc > 1 ? argv[1] : "tests/data/legacy-0.1.0.chunk";
    const int BANK = idx("bank_index"), PRESET = idx("preset"), NEXT = idx("preset_next"), PNAME = idx("preset_name"), CUT = idx("F1Cutoff"),
              FX1 = idx("FX1Type"), FXP1 = idx("fx1_p1"), FXL1 = idx("fx1_l1"), SLOT5 = idx("patch_slot_5"), GAIN = idx("gain"),
              SAVE = idx("fav_save"), DEL = idx("fav_delete"), F1TYPE = idx("F1Type");

    const char* pf = std::getenv("MPC_PLUGIN_FOLDER");
    const std::string favFile = std::string(pf ? pf : ".") + "/vavra/favourites.dat";
    std::remove(favFile.c_str());
    std::remove((std::string(pf ? pf : ".") + "/vavra-skin.txt").c_str());

    std::printf("== identity\n");
    AEffect* a = open("A");
    char name[64] = {0};
    a->dispatcher(a, effGetEffectName, 0, 0, name, 0);
    CHECK(a->uniqueID == (VstInt32)0x56617651, "uid VavQ (%08x)", (unsigned)a->uniqueID);
    CHECK(!std::strcmp(name, VAVRA_EXPECT_NAME), "name \"%s\"", name);
    CHECK(a->numParams == 630, "630 params: 0.1.0's 583 + RANDOM, the naming keyboard, the skin switch and SKIN (%d)", a->numParams);
    CHECK(a->dispatcher(a, effGetVendorVersion, 0, 0, nullptr, 0) == 2000, "version 2000");
    {
        int bad = 0, i = 0;
        FILE* f = std::fopen("params.lock", "r");
        char line[128];
        while (f && std::fgets(line, sizeof line, f))   // 437..582: the 1.x popup flags' slots (ui_open + reserved), named "<key>__open" in the lock
        {
            line[std::strcspn(line, "\r\n")] = 0;
            if (!line[0]) continue;
            const bool slot = i >= kNumEngineParams && i < kNumEngineParams + kNumPopups;
            if (slot ? !std::strstr(line, "__open") : std::strcmp(line, g_pspecs[i].key) != 0) bad++;
            i++;
        }
        if (f) std::fclose(f);
        CHECK(f && bad == 0 && i == 630, "order = params.lock (%d keys, %d differ)", i, bad);
        CHECK(!std::strcmp(g_pspecs[583].key, "random_patch"), "583 = random_patch (appended)");
        CHECK(!std::strcmp(g_pspecs[0].key, "bank_index") && !std::strcmp(g_pspecs[437].key, "ui_open"), "0 = bank_index, 437 = ui_open");
    }
    CHECK(a->numPrograms == 64, "64 programs (the favourite slots, as 0.1.0): %d", a->numPrograms);
    CHECK(waitReady(a), "booted (%s)", eng(a, "loading_status").c_str());
    CHECK(eng(a, "patch_slot_30").size() > 4, "ROM sound names known (tile 30 \"%s\")", eng(a, "patch_slot_30").c_str());

    std::printf("== sound\n");
    std::vector<float> rec;
    g_rec = &rec;
    run(a, 200, {{0x90, 60, 100}});
    const double on = g_rms;
    if (std::getenv("VAVRA_REC"))                  // recording: hold the note ~3 s, then a C minor chord ~3 s
    {
        run(a, 800);
        run(a, 100, {{0x80, 60, 0}});
        run(a, 1000, {{0x90, 48, 100}, {0x90, 60, 100}, {0x90, 63, 100}, {0x90, 67, 100}});
        run(a, 300, {{0x80, 48, 0}, {0x80, 60, 0}, {0x80, 63, 0}, {0x80, 67, 0}});
    }
    g_rec = nullptr;
    recWav("a001_44k", rec, 44100);
    run(a, 600, {{0x80, 60, 0}});
    run(a, 200);
    const double off = g_rms;          // ~2 s after the note off
    if (on <= 1e-3)
        std::printf("    (silent: %s; %s; %s; ready %d)\n", eng(a, "loading_status").c_str(), eng(a, "engine_stats").c_str(), eng(a, "preset_name").c_str(), vavra_dbg_ready(a));
    CHECK(on > 1e-3, "note on is audible (rms %.4f)", on);
    CHECK(off < on, "note off decays (rms %.4f)", off);
    {   // a loud chord at OUTPUT GAIN 400 %: passes full scale in float (the 16-bit path clipped it hard on the MPC)
        const int G = idx("gain");
        a->setParameter(a, G, norm(G, 400));
        settle(a, 20);
        run(a, 300, {{0x90, 48, 127}, {0x90, 55, 127}, {0x90, 60, 127}, {0x90, 64, 127}, {0x90, 67, 127}, {0x90, 72, 127}});
        const double pk = g_peak;
        run(a, 400, {{0x80, 48, 0}, {0x80, 55, 0}, {0x80, 60, 0}, {0x80, 64, 0}, {0x80, 67, 0}, {0x80, 72, 0}});
        a->setParameter(a, G, norm(G, 100));
        settle(a, 20);
        CHECK(pk > 1.0, "a loud chord passes full scale unclipped (peak %.3f)", pk);
    }

    std::printf("== value params\n");
    a->setParameter(a, CUT, norm(CUT, 64));
    settle(a);
    CHECK(engi(a, "F1Cutoff") == 64, "F1 CUTOFF 64 -> engine %d", engi(a, "F1Cutoff"));
    a->setParameter(a, F1TYPE, norm(F1TYPE, 10));
    settle(a);
    CHECK(engi(a, "F1Type") == 10 && disp(a, F1TYPE) == "Comb-", "F1 TYPE last option -> engine %d, \"%s\"", engi(a, "F1Type"), disp(a, F1TYPE).c_str());
    {   // a Q-Link nudge smaller than one step still moves one step (settle)
        const float cur = plainOf(a, CUT);
        a->setParameter(a, CUT, norm(CUT, cur) + 0.3f / 127.f);
        settle(a);
        CHECK(engi(a, "F1Cutoff") == (int)cur + 1 && std::lround(plainOf(a, CUT)) == (int)cur + 1,
              "a sub-step nudge up moves one step (%d -> engine %d, host %.0f)", (int)cur, engi(a, "F1Cutoff"), plainOf(a, CUT));
    }
    std::printf("== FX knobs follow the effect type\n");
    a->setParameter(a, FX1, norm(FX1, 1));
    settle(a, 60);
    const std::string l1 = disp(a, FXL1);
    a->setParameter(a, FX1, norm(FX1, 0));
    settle(a, 60);
    CHECK(!l1.empty() && l1 != "-" && disp(a, FXL1) == "-", "FX 1 knob 1 is \"%s\" for type 1, \"%s\" for Off", l1.c_str(), disp(a, FXL1).c_str());
    a->setParameter(a, FX1, norm(FX1, 1));
    settle(a, 60);
    a->setParameter(a, FXP1, norm(FXP1, 90));
    settle(a);
    CHECK(engi(a, "fx1_p1") == 90, "FX 1 knob 1 = 90 -> engine %d", engi(a, "fx1_p1"));

    std::printf("== drawn pick-list flag\n");
    a->setParameter(a, kUiParam, norm(kUiParam, 5));
    settle(a, 5);
    CHECK(std::lround(plainOf(a, kUiParam)) == 5, "ui_open 5 holds (%.0f)", plainOf(a, kUiParam));
    a->setParameter(a, F1TYPE, norm(F1TYPE, 1));
    settle(a);
    CHECK(std::lround(plainOf(a, kUiParam)) == 0 && engi(a, "F1Type") == 1, "a pick (F1 TYPE %d) closes the list", engi(a, "F1Type"));

    std::printf("== preset step, readback, text\n");
    const int p0 = engi(a, "preset");
    const std::string n0 = disp(a, PNAME);
    const float c0 = a->getParameter(a, PNAME);
    for (int i = 0; i < kNumParams; i++) g_automate[i] = 0;
    const int ud0 = g_updateDisplay;
    a->setParameter(a, NEXT, 1.0f);
    settle(a, 300);
    vavra_dbg_tick(a);
    CHECK(engi(a, "preset") == p0 + 1, "PRESET + : engine preset %d -> %d", p0, engi(a, "preset"));
    CHECK(std::lround(plainOf(a, PRESET)) == p0 + 1, "host PRESET follows (%.0f)", plainOf(a, PRESET));
    CHECK(a->getParameter(a, NEXT) == 0.f, "PRESET + dropped back to 0");
    CHECK(disp(a, PNAME) != n0 && a->getParameter(a, PNAME) != c0, "preset name \"%s\" -> \"%s\", its counter moved", n0.c_str(), disp(a, PNAME).c_str());
    a->setParameter(a, NEXT, 0.0f);
    int told = 0;
    for (int i = 0; i < kNumParams; i++) told += g_automate[i] > 0;
    CHECK(told > 20 && g_updateDisplay > ud0, "the host heard about the new sound (%d params, %d display updates)", told, g_updateDisplay - ud0);
    {
        int bad = 0;
        for (int i = 1; i < kNumEngineParams; i++)
        {
            const PSpec& s = g_pspecs[i];
            if (!(s.flags & kPolled)) continue;
            const int ev = std::min(std::max(engi(a, s.key), (int)s.min), (int)s.max);
            if (std::lround(plainOf(a, i)) != ev) { if (bad < 5) std::printf("    %s host %.0f engine %d\n", s.key, plainOf(a, i), engi(a, s.key)); bad++; }
        }
        CHECK(bad == 0, "every value param matches the engine after the load (%d differ)", bad);
    }
    {   // a data-wheel tick on PRESET (off a step) is one sound in its direction
        const int p1 = engi(a, "preset");
        a->setParameter(a, PRESET, norm(PRESET, (float)p1 + 0.6f));
        settle(a, 300);
        CHECK(engi(a, "preset") == p1 + 1, "a wheel tick on PRESET: %d -> %d", p1, engi(a, "preset"));
    }

    std::printf("== parameter 0 (BANK)\n");
    const int b0 = engi(a, "bank_index");
    a->setParameter(a, 0, 1.0f); a->setParameter(a, 0, norm(0, (float)b0));   // the host's prepare nudge
    settle(a);
    CHECK(engi(a, "bank_index") == b0, "a nudge to the end and back changes nothing (%d)", engi(a, "bank_index"));
    a->setParameter(a, BANK, norm(BANK, 1));
    run(a, 30);
    vavra_dbg_tick(a);
    settle(a, 300);
    CHECK(engi(a, "bank_index") == 1 && eng(a, "bank_name") == "BANK B", "a held change applies (bank %d, %s)", engi(a, "bank_index"), eng(a, "bank_name").c_str());

    std::printf("== tiles\n");
    a->setParameter(a, SLOT5, 1.0f);
    settle(a, 300);
    CHECK(engi(a, "preset") == 4 && a->getParameter(a, SLOT5) == 1.f && std::lround(plainOf(a, PRESET)) == 4, "tile 5 picks preset 5 and is lit (%d)", engi(a, "preset"));
    a->setParameter(a, SLOT5, 0.0f);   // the host toggles a lit tile off: it stays lit
    settle(a);
    CHECK(a->getParameter(a, SLOT5) == 1.f && !disp(a, SLOT5).empty(), "a lit tile stays lit, shows \"%s\"", disp(a, SLOT5).c_str());

    std::printf("== RANDOM\n");
    {
        const int RND = idx("random_patch");
        int changes = 0, sets = 0;
        for (int k = 0; k < 8; k++)
        {
            const int s0 = engi(a, "bank_index") * 1000 + engi(a, "preset");
            a->setParameter(a, RND, 1.0f);
            settle(a, 200);
            vavra_dbg_tick(a);
            const int s1 = engi(a, "bank_index") * 1000 + engi(a, "preset");
            changes += s1 != s0;
            sets += s1 >= 3000;
            if (k == 0)
                CHECK(a->getParameter(a, RND) == 0.f && std::lround(plainOf(a, PRESET)) == s1 % 1000 && std::lround(plainOf(a, BANK)) == s1 / 1000,
                      "RANDOM: %d -> %d, host BANK/PRESET follow, button back to 0", s0, s1);
            a->setParameter(a, RND, 0.0f);
        }
        CHECK(changes == 8, "eight RANDOM presses, eight new sounds (%d)", changes);
        std::printf("    (%d of 8 landed in a sound set)\n", sets);
        a->setParameter(a, BANK, norm(BANK, 1));
        run(a, 30); vavra_dbg_tick(a);
        settle(a, 200);
        a->setParameter(a, SLOT5, 1.0f);
        settle(a, 300);
        a->setParameter(a, SLOT5, 0.0f);
        settle(a);
    }

    std::printf("== favourites (the engine's slots in the PRESET menu)\n");
    {
        CHECK(progName(a, 0) == "1 --" && progName(a, 63) == "64 --" && a->dispatcher(a, effGetProgram, 0, 0, nullptr, 0) == 0,
              "programs: \"%s\" .. \"%s\", current = the first empty slot", progName(a, 0).c_str(), progName(a, 63).c_str());
        a->setParameter(a, CUT, norm(CUT, 21));
        settle(a);
        const int KBO = idx("kb_open"), FNAME = idx("fav_name");
        std::string snd = eng(a, "sound_name");
        while (!snd.empty() && snd.back() == ' ') snd.pop_back();
        tap(a, SAVE);
        CHECK(a->getParameter(a, KBO) == 1.f && disp(a, FNAME) == snd + "_" && engi(a, "fav_count") == 0 && a->getParameter(a, SAVE) == 0.f,
              "+FAV opens the keyboard on \"%s\" (nothing saved yet)", disp(a, FNAME).c_str());
        a->setParameter(a, CUT, norm(CUT, 99));   // an edit while typing: the favourite keeps the sound as it was at +FAV
        settle(a);
        for (size_t i = 0; i < snd.size(); i++) key(a, idx("kb_bksp"));
        CHECK(disp(a, FNAME) == "_", "DELETE clears the name (\"%s\")", disp(a, FNAME).c_str());
        for (const char* k : {"kb_m", "kb_y", "kb_space", "kb_p", "kb_a", "kb_d"}) key(a, idx(k));
        CHECK(disp(a, FNAME) == "My Pad_", "typed \"%s\" (capital at the start and after a space)", disp(a, FNAME).c_str());
        a->setParameter(a, idx("kb_dash"), 1.0f); run(a, 20); a->setParameter(a, idx("kb_dash"), 0.0f); run(a, 5);
        a->setParameter(a, idx("kb_dash"), 1.0f); run(a, 20); a->setParameter(a, idx("kb_dash"), 0.0f); settle(a, 60);
        CHECK(disp(a, FNAME) == "My Pad-_", "a key reported twice within 250 ms types once (\"%s\")", disp(a, FNAME).c_str());
        key(a, idx("kb_bksp"));
        key(a, idx("kb_save"));
        settle(a, 20);
        const std::string fn = eng(a, "fav_name:0");
        CHECK(a->getParameter(a, KBO) == 0.f && engi(a, "fav_count") == 1 && fn == "My Pad" && progName(a, 0) == "1 My Pad",
              "SAVE: the keyboard closes, program 1 = \"%s\"", progName(a, 0).c_str());
        a->setParameter(a, CUT, norm(CUT, 21));
        settle(a);
        CHECK(a->dispatcher(a, effGetProgram, 0, 0, nullptr, 0) == 0, "the saved favourite is the current program");
        FILE* f = std::fopen(favFile.c_str(), "rb");
        CHECK(f != nullptr, "favourites.dat written (as 0.1.0 did)");
        if (f) std::fclose(f);
        tap(a, NEXT, 300);
        CHECK(a->dispatcher(a, effGetProgram, 0, 0, nullptr, 0) == 1, "after a sound change the current program is the first empty slot (%d)",
              (int)a->dispatcher(a, effGetProgram, 0, 0, nullptr, 0));
        CHECK(eng(a, "preset_name").find(fn) == std::string::npos || engi(a, "F1Cutoff") != 21, "moved away (%s)", eng(a, "preset_name").c_str());
        a->dispatcher(a, effSetProgram, 0, 0, nullptr, 0);
        settle(a, 400);
        vavra_dbg_tick(a);
        CHECK(engi(a, "F1Cutoff") == 21 && std::lround(plainOf(a, CUT)) == 21, "PRESET 1 recalls the favourite with F1 CUTOFF %d", engi(a, "F1Cutoff"));
        tap(a, SAVE);
        key(a, idx("kb_x"));
        key(a, idx("kb_cancel"));
        CHECK(a->getParameter(a, KBO) == 0.f && engi(a, "fav_count") == 1, "CANCEL closes the keyboard, nothing saved");
        tap(a, DEL);
        CHECK(engi(a, "fav_count") == 0 && progName(a, 0) == "1 --", "-FAV: program 1 = \"%s\"", progName(a, 0).c_str());
    }

    std::printf("== sound-set banks\n");
    {
        const int nb = engi(a, "bank_count");
        CHECK(nb > 3, "sound-set banks found: %d banks (ROM A-C + %d)", nb, nb - 3);
        const int BT1 = idx("bank_slot_1"), BT4 = idx("bank_slot_4");
        CHECK(disp(a, BT1) == "BANK A" && disp(a, BT4).size() > 0, "bank tiles: \"%s\", tile 4 \"%s\"", disp(a, BT1).c_str(), disp(a, BT4).c_str());
        a->setParameter(a, BT4, 1.0f);
        settle(a, 200);
        vavra_dbg_tick(a);
        const std::string un = eng(a, "preset_name");
        CHECK(engi(a, "bank_index") == 3 && engi(a, "preset") == 0 && std::lround(plainOf(a, BANK)) == 3 && un.size() > 4,
              "tile 4 loads \"%s\" sound 1: \"%s\" (host BANK %.0f)", eng(a, "bank_name").c_str(), un.c_str(), plainOf(a, BANK));
        CHECK(a->getParameter(a, BT4) == 1.f, "its tile is lit");
        a->setParameter(a, BT4, 0.0f);
        run(a, 200, {{0x90, 60, 100}});
        CHECK(g_rms > 1e-3, "a sound-set sound plays (rms %.4f)", g_rms);
        run(a, 300, {{0x80, 60, 0}});
        tap(a, NEXT, 100);
        a->setParameter(a, CUT, norm(CUT, 33));
        settle(a, 60);
        const std::string uname = eng(a, "preset_name");
        CHECK(engi(a, "preset") == 1 && uname != un, "PRESET + in a sound set: \"%s\"", uname.c_str());
        const std::vector<uint8_t> cu = chunk(a);
        AEffect* u = open("U");
        CHECK(u->dispatcher(u, effSetChunk, 0, (VstIntPtr)cu.size(), (void*)cu.data(), 0) == 1, "U takes a chunk saved on a sound-set sound (before its boot)");
        CHECK(waitReady(u), "U ready");
        settle(u, 300);
        vavra_dbg_tick(u);
        CHECK(engi(u, "bank_index") == 3 && engi(u, "preset") == 1 && engi(u, "F1Cutoff") == 33 && eng(u, "preset_name") == uname,
              "U: bank %d sound %d \"%s\", F1 CUTOFF %d", engi(u, "bank_index"), engi(u, "preset") + 1, eng(u, "preset_name").c_str(), engi(u, "F1Cutoff"));
        close(u);
    }

    std::printf("== state round trip\n");
    a->setParameter(a, BANK, norm(BANK, 0));
    run(a, 30); vavra_dbg_tick(a);
    settle(a, 100);
    a->setParameter(a, PRESET, norm(PRESET, 12));
    settle(a, 400);
    a->setParameter(a, CUT, norm(CUT, 77));
    a->setParameter(a, GAIN, norm(GAIN, 300));
    settle(a, 60);
    const std::string nameA = eng(a, "preset_name");
    const int SKIN = idx("skin");
    auto readFile = [](const std::string& path) { std::string t; if (FILE* f = std::fopen(path.c_str(), "r")) { int c; while ((c = std::fgetc(f)) != EOF) t += (char)c; std::fclose(f); } return t; };
    const std::string skinFile = std::string(pf ? pf : ".") + "/vavra-skin.txt";
    CHECK(std::lround(plainOf(a, SKIN)) == 0 && disp(a, SKIN) == "microQ", "skin: microQ without a setting file (\"%s\")", disp(a, SKIN).c_str());
    a->setParameter(a, SKIN, 1.0f);
    settle(a, 10);
    CHECK(readFile(skinFile) == "phoenix\n" && disp(a, SKIN) == "Phoenix", "skin: Phoenix is written to vavra-skin.txt (%s)", disp(a, SKIN).c_str());
    key(a, idx("skin_next"));
    settle(a, 10);
    CHECK(std::lround(plainOf(a, SKIN)) == 0 && readFile(skinFile) == "microq\n", "SKIN: Phoenix -> microQ (round)");
    key(a, idx("skin_next"));
    settle(a, 10);
    CHECK(std::lround(plainOf(a, SKIN)) == 1 && readFile(skinFile) == "alt\n" && disp(a, SKIN) == "Dark Blue", "SKIN: microQ -> Dark Blue");
    const std::vector<uint8_t> ca = chunk(a);   // saved with the skin on Dark Blue: a project must not carry it
    a->setParameter(a, SKIN, 0.0f);
    settle(a, 10);
    CHECK(readFile(skinFile) == "microq\n", "skin: back to microQ in the file");
    CHECK(ca.size() > 800 && !std::memcmp(ca.data(), "MPCP", 4), "A saves an MPC chunk (%zu bytes)", ca.size());
    AEffect* b = open("B");
    CHECK(waitReady(b), "B ready");
    CHECK(b->dispatcher(b, effSetChunk, 0, (VstIntPtr)ca.size(), (void*)ca.data(), 0) == 1, "B loads A's chunk");
    settle(b, 400);
    vavra_dbg_tick(b);
    CHECK(engi(b, "bank_index") == 0 && engi(b, "preset") == 12 && engi(b, "F1Cutoff") == 77 && engi(b, "gain") == 300,
          "B: A/%d, F1 CUTOFF %d (the edit survives), GAIN %d", engi(b, "preset"), engi(b, "F1Cutoff"), engi(b, "gain"));
    CHECK(eng(b, "preset_name") == nameA && std::lround(plainOf(b, CUT)) == 77 && std::lround(plainOf(b, GAIN)) == 300,
          "B: \"%s\", host F1 CUTOFF %.0f, GAIN %.0f", eng(b, "preset_name").c_str(), plainOf(b, CUT), plainOf(b, GAIN));
    settle(b, 10);
    CHECK(std::lround(plainOf(b, SKIN)) == 0 && readFile(skinFile) == "microq\n", "skin: a project saved on Dark Blue leaves the global microQ alone");
    b->setParameter(b, SKIN, 0.5f);
    settle(b, 10);
    run(a, 500);                                   // ~1.5 s: A's worker re-reads the file about once a second
    vavra_dbg_tick(a);
    CHECK(std::lround(plainOf(a, SKIN)) == 1, "skin: B switches to Dark Blue, A follows");
    b->setParameter(b, SKIN, 0.0f);
    settle(b, 10);

    std::printf("== a 0.1.0 project\n");
    std::vector<uint8_t> legacy;
    if (FILE* f = std::fopen(legacyPath, "rb")) { int c; while ((c = std::fgetc(f)) != EOF) legacy.push_back((uint8_t)c); std::fclose(f); }
    CHECK(legacy.size() > 800 && legacy[0] == '{', "read %s (%zu bytes)", legacyPath, legacy.size());
    AEffect* c = open("C");   // as the MPC does: the project's chunk arrives straight after the plugin opens, before the boot
    CHECK(c->dispatcher(c, effSetChunk, 0, (VstIntPtr)legacy.size(), legacy.data(), 0) == 1, "C takes the 0.1.0 chunk at once");
    {
        const std::vector<uint8_t> early = chunk(c);
        const std::string s(early.begin(), early.end());
        CHECK(s.find("\"preset\":37") != std::string::npos && s.find("\"single\":\"") != std::string::npos,
              "a save before the boot keeps the project's state with its sound");
    }
    CHECK(waitReady(c), "C ready");
    settle(c, 400);
    vavra_dbg_tick(c);
    CHECK(engi(c, "bank_index") == 1 && engi(c, "preset") == 37, "C: bank %d preset %d (B038)", engi(c, "bank_index"), engi(c, "preset"));
    CHECK(eng(c, "preset_name").rfind("B038 ", 0) == 0, "C: \"%s\"", eng(c, "preset_name").c_str());
    CHECK(engi(c, "F1Cutoff") == 40 && std::lround(plainOf(c, CUT)) == 40, "C: F1 CUTOFF %d, host %.0f (the 0.1.0 edit)", engi(c, "F1Cutoff"), plainOf(c, CUT));
    CHECK(engi(c, "gain") == 180 && std::lround(plainOf(c, GAIN)) == 180, "C: GAIN %d", engi(c, "gain"));
    c->setParameter(c, CUT, norm(CUT, 127));
    settle(c);
    run(c, 200, {{0x90, 64, 100}});
    CHECK(g_rms > 1e-3, "C plays (rms %.4f)", g_rms);
    run(c, 50, {{0x80, 64, 0}});
    {
        const std::vector<uint8_t> resaved = chunk(c);
        CHECK(resaved.size() > 800 && !std::memcmp(resaved.data(), "MPCP", 4), "C re-saves as an MPC chunk (%zu bytes)", resaved.size());
    }

    std::printf("== bad chunks\n");
    const char junk[] = "not a chunk";
    CHECK(c->dispatcher(c, effSetChunk, 0, sizeof junk, (void*)junk, 0) == 0, "junk is refused");
    const uint8_t cut[] = {'M', 'P', 'C', 'P', 2, 0, 0, 0, 200, 0, 0, 0, 5};
    CHECK(c->dispatcher(c, effSetChunk, 0, sizeof cut, (void*)cut, 0) == 0, "a truncated MPC chunk is refused");
    settle(c);
    CHECK(engi(c, "preset") == 37, "C still on preset 38");

    std::printf("== host transport\n");
    std::memset(&g_time, 0, sizeof g_time);
    g_time.sampleRate = 44100; g_time.tempo = 133; g_time.ppqPos = 0;
    g_time.flags = kVstTransportPlaying | kVstTempoValid | kVstPpqPosValid;
    g_giveTime = true;
    run(c, 400, {{0x90, 60, 100}});
    CHECK(g_rms > 1e-4, "plays while MPC's transport runs at 133 BPM (rms %.4f)", g_rms);
    run(c, 50, {{0x80, 60, 0}});
    g_giveTime = false;

    std::printf("== 48 kHz host\n");
    for (AEffect* e : {a, b, c}) close(e);
    AEffect* d = open("D", 48000.f);
    CHECK(waitReady(d), "D ready");
    std::vector<float> rec48;
    g_rec = &rec48;
    run(d, 200, {{0x90, 60, 100}});
    g_rec = nullptr;
    recWav("d_48k", rec48, 48000);
    CHECK(g_rms > 1e-3, "D plays at 48 kHz (rms %.4f; %s; %s)", g_rms, eng(d, "loading_status").c_str(), eng(d, "preset_name").c_str());
    run(d, 50, {{0x80, 60, 0}});
    close(d);

    if (g_fail) { std::printf("FAILED: %d checks\n", g_fail); return 1; }
    std::printf("OK\n");
    return 0;
}
