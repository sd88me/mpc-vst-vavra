// Engine-level test through the interface the wrapper uses (mpc_engine): boots the microQ ROM found in <dir>/roms, plays notes,
// changes bank and preset, moves parameters, checks the state chunk round trip.
// usage: vavra_engine_test <data dir with roms/> [seconds of audio per phase] [wav out]
extern "C" {
#include "engine.h"
}
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

static int fails = 0;
#define CHECK(c, ...) do { if (c) printf("ok   " __VA_ARGS__); else { printf("FAIL " __VA_ARGS__); fails++; } printf("\n"); } while (0)
static std::vector<int16_t> g_wav;

static std::string get(const mpc_engine_t *e, void *i, const char *k) {
    char b[8192] = {0};
    if (e->get_param(i, k, b, sizeof b) <= 0) return "";
    return b;
}

static double render_rms(const mpc_engine_t *e, void *i, double secs, double *peak = nullptr) {
    int16_t buf[256];
    double sq = 0, pk = 0; long n = 0;
    const int blocks = (int)(secs * 44100 / 128);
    auto t0 = std::chrono::steady_clock::now();
    for (int b = 0; b < blocks; b++) {
        e->render(i, buf, 128);
        g_wav.insert(g_wav.end(), buf, buf + 256);
        for (int k = 0; k < 256; k++) { double v = buf[k] / 32768.0; sq += v * v; if (fabs(v) > pk) pk = fabs(v); n++; }
        std::this_thread::sleep_until(t0 + std::chrono::microseconds((long)((b + 1) * 128 * 1e6 / 44100)));
    }
    if (peak) *peak = pk;
    return sqrt(sq / n);
}

static bool wait_ready(const mpc_engine_t *e, void *i, int seconds) {
    for (int w = 0; w < seconds * 10; w++) {
        const std::string s = get(e, i, "loading_status");
        if (s.rfind("Ready", 0) == 0) return true;
        if (s.rfind("No ", 0) == 0 || s.find("fail") != std::string::npos || s.find("did not") != std::string::npos) return false;
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    return false;
}

static void write_wav(const char *path) {
    FILE *f = fopen(path, "wb");
    if (!f) return;
    const uint32_t data = (uint32_t)g_wav.size() * 2, rate = 44100, br = rate * 4, sz = 36 + data;
    const uint16_t fmt = 1, ch = 2, ba = 4, bits = 16;
    const uint32_t fsz = 16;
    fwrite("RIFF", 1, 4, f); fwrite(&sz, 4, 1, f); fwrite("WAVEfmt ", 1, 8, f); fwrite(&fsz, 4, 1, f);
    fwrite(&fmt, 2, 1, f); fwrite(&ch, 2, 1, f); fwrite(&rate, 4, 1, f); fwrite(&br, 4, 1, f); fwrite(&ba, 2, 1, f); fwrite(&bits, 2, 1, f);
    fwrite("data", 1, 4, f); fwrite(&data, 4, 1, f); fwrite(g_wav.data(), 2, g_wav.size(), f);
    fclose(f);
}

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: %s <data dir> [seconds] [out.wav]\n", argv[0]); return 2; }
    const double secs = argc > 2 ? atof(argv[2]) : 1.5;
    const mpc_engine_t *e = mpc_engine();
    void *i = e->create(argv[1]);
    CHECK(i != nullptr, "create");

    auto t0 = std::chrono::steady_clock::now();
    const bool up = wait_ready(e, i, 240);
    printf("boot took %.1f s: ROM %s, status \"%s\"\n", std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count(),
           get(e, i, "rom_name").c_str(), get(e, i, "loading_status").c_str());
    CHECK(up, "boot finished");
    if (!up) { e->destroy(i); printf("FAILED\n"); return 1; }
    render_rms(e, i, 0.5);
    printf("bank \"%s\" preset \"%s\" tile1 \"%s\" bank tile 3 \"%s\"\n", get(e, i, "bank_name").c_str(), get(e, i, "preset_name").c_str(),
           get(e, i, "patch_slot_1").c_str(), get(e, i, "bank_slot_3").c_str());

    double pk = 0;
    const double idle = render_rms(e, i, 1.0);
    CHECK(idle < 0.002, "quiet before any note (rms %.5f)", idle);
    uint8_t on[3] = {0x90, 60, 100}, off[3] = {0x80, 60, 0};
    e->midi(i, on, 3);
    double rms = render_rms(e, i, secs, &pk);
    CHECK(rms > 0.0005, "note 60 -> rms %.4f peak %.3f", rms, pk);
    e->midi(i, off, 3);
    render_rms(e, i, 1.0);
    printf("stats: %s\n", get(e, i, "engine_stats").c_str());

    std::string n0 = get(e, i, "preset_name");
    e->set_param(i, "preset", "9");
    render_rms(e, i, 0.8);
    std::string n1 = get(e, i, "preset_name");
    CHECK(get(e, i, "preset") == "9" && n1 != n0, "preset 9 -> \"%s\" (was \"%s\")", n1.c_str(), n0.c_str());
    e->midi(i, on, 3);
    rms = render_rms(e, i, secs, &pk);
    e->midi(i, off, 3);
    CHECK(rms > 0.0005, "preset 9 note -> rms %.4f peak %.3f", rms, pk);

    const std::string cut = get(e, i, "F1Cutoff");
    e->set_param(i, "F1Cutoff", "10");
    render_rms(e, i, 0.3);
    CHECK(get(e, i, "F1Cutoff") == "10" && cut != "", "F1Cutoff %s -> %s", cut.c_str(), get(e, i, "F1Cutoff").c_str());
    e->midi(i, on, 3);
    double dark = render_rms(e, i, secs);
    e->set_param(i, "F1Cutoff", "127");
    double open = render_rms(e, i, secs);
    e->midi(i, off, 3);
    CHECK(fabs(dark - open) > 1e-4, "cutoff 10 rms %.4f, cutoff 127 rms %.4f", dark, open);
    // a bit field: UnisonoCount shares its byte with VoiceMode
    const std::string vm = get(e, i, "VoiceMode");
    e->set_param(i, "UnisonoCount", "2");
    render_rms(e, i, 0.3);
    CHECK(get(e, i, "UnisonoCount") == "2" && get(e, i, "VoiceMode") == vm, "UnisonoCount -> %s, VoiceMode stays %s", get(e, i, "UnisonoCount").c_str(), get(e, i, "VoiceMode").c_str());
    e->set_param(i, "UnisonoCount", "0");
    printf("FX2Type %s, fx2_l1 \"%s\", LCD \"%s\" / \"%s\"\n", get(e, i, "FX2Type").c_str(), get(e, i, "fx2_l1").c_str(), get(e, i, "lcd1").c_str(), get(e, i, "lcd2").c_str());
    CHECK(!get(e, i, "lcd1").empty() || !get(e, i, "lcd2").empty(), "LCD text");

    // bank C
    e->set_param(i, "bank_index", "2");
    render_rms(e, i, 1.0);
    printf("bank 2 \"%s\" preset \"%s\"\n", get(e, i, "bank_name").c_str(), get(e, i, "preset_name").c_str());
    e->midi(i, on, 3);
    rms = render_rms(e, i, secs, &pk);
    e->midi(i, off, 3);
    CHECK(rms > 0.0005, "bank C note -> rms %.4f peak %.3f", rms, pk);

    // state round trip into a second instance
    e->set_param(i, "bank_index", "0");
    e->set_param(i, "preset", "20");
    render_rms(e, i, 0.8);
    e->set_param(i, "F1Resonance", "99");
    render_rms(e, i, 0.3);
    const std::string st = get(e, i, "state");
    CHECK(st.find("\"single\":\"") != std::string::npos && st.size() < 4000, "state %zu bytes", st.size());
    const std::string name20 = get(e, i, "preset_name");
    e->destroy(i);
    void *j = e->create(argv[1]);
    e->set_param(j, "state", st.c_str());
    CHECK(wait_ready(e, j, 240), "second instance boots");
    render_rms(e, j, 1.0);
    CHECK(get(e, j, "F1Resonance") == "99" && get(e, j, "preset") == "20", "restored: preset %s resonance %s name \"%s\" (was \"%s\")",
          get(e, j, "preset").c_str(), get(e, j, "F1Resonance").c_str(), get(e, j, "preset_name").c_str(), name20.c_str());
    e->midi(j, on, 3);
    rms = render_rms(e, j, secs, &pk);
    e->midi(j, off, 3);
    CHECK(rms > 0.0005, "restored note -> rms %.4f peak %.3f", rms, pk);
    printf("stats: %s\n", get(e, j, "engine_stats").c_str());
    // the ROM names (a background microQ harvests them once, then names.dat): wait for them when a run starts without the cache
    auto t1 = std::chrono::steady_clock::now();
    for (int w = 0; w < 3000 && get(e, j, "loading_status").find("names") != std::string::npos; w++) std::this_thread::sleep_for(std::chrono::milliseconds(100));
    printf("names after %.0f s more: tile1 \"%s\" tile25 \"%s\", status \"%s\"\n", std::chrono::duration<double>(std::chrono::steady_clock::now() - t1).count(),
           get(e, j, "patch_slot_1").c_str(), get(e, j, "patch_slot_25").c_str(), get(e, j, "loading_status").c_str());
    CHECK(get(e, j, "patch_slot_1").size() > 4 && get(e, j, "patch_slot_25").size() > 4, "ROM sound names");
    e->destroy(j);
    if (argc > 3) write_wav(argv[3]);
    printf(fails ? "FAILED (%d)\n" : "PASSED\n", fails);
    return fails ? 1 : 0;
}
