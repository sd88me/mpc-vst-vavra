/* Vavra for MPC: gearmulator's Waldorf microQ emulation (mqLib: the microQ's 68k firmware plus its DSP56362 voice DSP) as an
 * mpc-vst-plugins engine (wrapper/engine.h). GPL-3.0.
 *
 * One emulator thread per instance runs mqLib::Device through gearmulator's synthLib::Plugin, fills a ring of int16 stereo, and
 * render() only drains it. Everything the host does reaches the device as MIDI or sysex queued from the host's thread: notes and
 * controllers as they are, parameters as single parameter change sysex (a whole byte: some bytes carry two parameters as bit
 * fields), sounds as a ROM single copied into the single edit buffer. The parameter table is generated (tools/gen_params.py ->
 * vavra_params.h). Single mode, one part: the microQ's Multi mode, drum maps and Global settings are not exposed.
 *
 * ROM: <data_dir>/roms/ (scanned by mqLib::RomLoader: an OS update `.mid` (300-400 kB) or a 512 kB `.bin`). None ships.
 * Favourites: <data_dir>/favourites.dat (whole single dumps). */
#include "fast_cores.h"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dirent.h>
#include <strings.h>
#include <exception>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <sched.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include <thread>
#include <unistd.h>
#include <unordered_map>
#include <vector>

extern "C" {
#include "engine.h"
}

#include "synthLib/deviceTypes.h"
#include "synthLib/midiTypes.h"
#include "synthLib/midiToSysex.h"
#include "synthLib/plugin.h"
#include "synthLib/romLoader.h"
#include "mqLib/device.h"
#include "mqLib/mqmiditypes.h"
#include "mqLib/romloader.h"

#include "vavra_params.h"

namespace {

constexpr int kRate = 44100, kBlock = 128;
constexpr int kRingFrames = 16384;               // power of two
constexpr int kTargetFill = 1024;                // frames the emulator thread keeps queued (~23 ms)
constexpr int kBoostFill = 2688;                 // ~60 ms, for 400 ms after a sound load or a program change (EMULATOR_PORTS.md section 3)
constexpr int kDumpLen = 392;                    // a single dump including its sysex header
constexpr int kParamOff = 7;                     // first parameter byte of a single dump
constexpr int kNameOff = kParamOff + 363, kNameLen = 16;
constexpr int kNumBytes = kDumpLen - kParamOff - 2;
constexpr int kEditBuf = 0x20;                   // MidiBufferNum::SingleEditBufferSingleMode
constexpr int kRomBank0 = 0x40;                  // MidiBufferNum::SingleBankA
constexpr int kDeviceId = 0x7f;                  // omni
constexpr int kFx1Type = 128, kFx2Type = 144, kFx1Base = 130, kFx2Base = 146;
constexpr int kFavSlots = 64;
constexpr int kBankTiles = 10;                   // the BANKS page's bank list, paged
constexpr int kMaxBanks = 64;

using Dump = std::vector<uint8_t>;

FILE *g_log = nullptr;
void xlog(const char *fmt, ...) {
    if (!g_log) return;
    va_list ap;
    va_start(ap, fmt);
    vfprintf(g_log, fmt, ap);
    va_end(ap);
    fputc('\n', g_log);
    fflush(g_log);
}

long long mono_ms() { return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count(); }
int clampi(int v, int lo, int hi) { return v < lo ? lo : v > hi ? hi : v; }

/* CPU ticks of this process's emulator threads (ours "VVemu", gearmulator's "DSP ..." and the 68k's), for the STATS readout */
long emu_thread_ticks(pid_t host_tid) {
    long total = 0;
    DIR *d = opendir("/proc/self/task");
    if (!d) return 0;
    while (struct dirent *e = readdir(d)) {
        if (e->d_name[0] < '0' || e->d_name[0] > '9') continue;
        char path[64], line[512];
        snprintf(path, sizeof path, "/proc/self/task/%s/comm", e->d_name);
        FILE *f = fopen(path, "r");
        if (!f) continue;
        const bool ours = fgets(line, sizeof line, f) && (!strncmp(line, "VVemu", 5) || !strncmp(line, "DSP", 3) || !strncmp(line, "MC68", 4));
        fclose(f);
        if (!ours || atoi(e->d_name) == host_tid) continue;
        snprintf(path, sizeof path, "/proc/self/task/%s/stat", e->d_name);
        f = fopen(path, "r");
        if (!f) continue;
        if (fgets(line, sizeof line, f)) {
            const char *q = strrchr(line, ')');
            unsigned long ut = 0, st = 0;
            if (q && sscanf(q + 2, "%*c %*d %*d %*d %*d %*d %*u %*u %*u %*u %*u %lu %lu", &ut, &st) == 2) total += (long)(ut + st);
        }
        fclose(f);
    }
    closedir(d);
    return total;
}

enum CmdType : uint8_t { C_MIDI, C_PARAM, C_PRESET, C_PANIC, C_LOADDUMP };
struct Cmd {
    CmdType type = C_MIDI;
    uint8_t m[3] = {0, 0, 0};
    int a = 0, b = 0;
    Dump dump;
};

uint8_t checksum(const Dump &d) {     // over the parameter bytes, stored before the closing F7
    uint8_t c = 0;
    for (size_t i = kParamOff; i + 2 < d.size(); i++) c += d[i];
    return c & 0x7f;
}

struct Inst {
    std::string dir;
    std::thread th, harvester;
    std::atomic<bool> stop{false}, ready{false}, failed{false};
    std::atomic<int> harvest_progress{-1};                   // names harvested so far (-1: none running)

    std::vector<int16_t> ring = std::vector<int16_t>(kRingFrames * 2);
    std::atomic<uint32_t> wr{0}, rd{0};
    std::atomic<uint32_t> underruns{0};
    std::atomic<uint32_t> ring_min{0xffffffffu}, burst_max{0};
    std::atomic<int> emu_cpu{0};

    std::mutex qm;
    std::vector<Cmd> q;

    std::atomic<uint8_t> raw[kNumBytes];                      // the edit buffer's parameter bytes, what the UI reads and writes
    std::atomic<int> bank{0}, preset{0}, page{0}, gain{100};
    std::atomic<uint32_t> load_gen{0}, rev{1};
    std::mutex sm;                                            // names, status, LCD, the edit buffer dump
    char status[96] = "Starting...";
    char rom_name[96] = "";
    char names[VV_BANKS][VV_PER_BANK][kNameLen + 1] = {};
    Dump rom_dump[VV_BANKS][VV_PER_BANK];                    // every ROM single, from sounds.dat or the harvest
    struct FileBank { std::string name; std::vector<Dump> sounds; };
    std::vector<FileBank> fbanks;                             // <dir>/banks/: sound sets (.mid .syx), 100 singles per bank, after A/B/C
    std::atomic<int> bank_page{0};
    /* the host's transport (HAS_SONG_POS): the arpeggiator and clocked LFOs follow MPC's tempo through gearmulator's MIDI clock */
    std::atomic<double> host_bpm{0.0}, host_ppq{-1.0};
    std::atomic<bool> host_playing{false};
    bool have[VV_BANKS][VV_PER_BANK] = {};
    char cur_name[kNameLen + 1] = "";
    char lcd[2][21] = {"", ""};
    Dump cur;

    std::mutex fm;                                            // favourites (MPC's PRESET menu, vst.json "programs")
    int fav_count = 0, fav_current = -1;
    uint32_t fav_stamp = 0;
    char fav_name[kFavSlots][24] = {};
    Dump fav_dump[kFavSlots];
    std::atomic<long long> fav_list_ms{-100000};
    std::mutex stm;
    char stats_cache[96] = "";
    int stats_cpu = -1;

    void bump() { rev.fetch_add(1, std::memory_order_relaxed); }
    void set_status(const char *s) {
        { std::lock_guard<std::mutex> l(sm); snprintf(status, sizeof status, "%s", s); }
        bump();
    }
    void push(Cmd &&c) { std::lock_guard<std::mutex> l(qm); if (q.size() < 4096) q.push_back(std::move(c)); }
};

int bank_count(Inst *in) { return VV_BANKS + (int)in->fbanks.size(); }
int bank_size(Inst *in, int b) { return b < VV_BANKS ? VV_PER_BANK : b - VV_BANKS < (int)in->fbanks.size() ? (int)in->fbanks[b - VV_BANKS].sounds.size() : 0; }
std::string bank_title(Inst *in, int b) {
    if (b < VV_BANKS) return std::string("BANK ") + (char)('A' + b);
    return b - VV_BANKS < (int)in->fbanks.size() ? in->fbanks[b - VV_BANKS].name : std::string("-");
}
void name_of(const std::vector<uint8_t> &d, char *out);
/* a sound's name (under sm): ROM ones once harvested, file ones from their dump */
std::string sound_name(Inst *in, int b, int p) {
    char nm[17] = "";
    if (b < VV_BANKS) { if (p >= 0 && p < VV_PER_BANK && in->have[b][p]) return in->names[b][p]; return ""; }
    if (p >= 0 && p < bank_size(in, b)) name_of(in->fbanks[b - VV_BANKS].sounds[p], nm);
    return nm;
}

/* <dir>/banks/: every single dump (392 bytes, F0 3E 10 .. 10 ..) in each .mid / .syx file, 100 to a bank, named after the file */
void scan_banks(Inst *in) {
    const std::string dir = in->dir + "/banks";
    DIR *d = opendir(dir.c_str());
    if (!d) return;
    std::vector<std::string> files;
    while (struct dirent *e = readdir(d)) {
        const std::string n = e->d_name;
        if (n.size() > 4 && (!strcasecmp(n.c_str() + n.size() - 4, ".mid") || !strcasecmp(n.c_str() + n.size() - 4, ".syx"))) files.push_back(n);
    }
    closedir(d);
    std::sort(files.begin(), files.end());
    for (const auto &n : files) {
        synthLib::SysexBuffer buf;
        if (!synthLib::MidiToSysex::readFile(buf, (dir + "/" + n).c_str())) continue;
        synthLib::SysexBufferList msgs;
        synthLib::MidiToSysex::splitMultipleSysex(msgs, buf, false);
        std::vector<std::vector<uint8_t>> singles;
        for (auto &m : msgs)
            if (m.size() == (size_t)kDumpLen && m[0] == 0xf0 && m[1] == 0x3e && m[2] == 0x10 && m[4] == (uint8_t)mqLib::SysexCommand::SingleDump && m.back() == 0xf7)
                singles.emplace_back(m.begin(), m.end());
        if (singles.empty()) continue;
        std::string stem = n.substr(0, n.size() - 4);
        for (auto &c : stem) c = (char)toupper((unsigned char)(c == '_' ? ' ' : c));
        for (const char *drop : {"MICROQ ", "MQ "}) if (stem.rfind(drop, 0) == 0) stem.erase(0, strlen(drop));
        if (stem.size() > 15) stem.resize(15);
        const int nb = (int)(singles.size() + VV_PER_BANK - 1) / VV_PER_BANK;
        for (int k = 0; k < nb && (int)in->fbanks.size() + VV_BANKS < kMaxBanks; k++) {
            Inst::FileBank fb;
            fb.name = nb > 1 ? stem + " " + (char)('A' + k) : stem;
            fb.sounds.assign(singles.begin() + k * VV_PER_BANK, singles.begin() + std::min<size_t>(singles.size(), (size_t)(k + 1) * VV_PER_BANK));
            in->fbanks.push_back(std::move(fb));
        }
    }
    xlog("[banks] %zu file banks", in->fbanks.size());
}

std::unordered_map<std::string, int> &mq_index() {
    static std::unordered_map<std::string, int> m = [] {
        std::unordered_map<std::string, int> r;
        for (int i = 0; i < MQ_NUM_PARAMS; i++) r[g_mq_params[i].key] = i;
        return r;
    }();
    return m;
}

int value_to_raw(const mq_param_t &p, int v) {
    int raw;
    switch (p.kind) {
    case 1: raw = p.lo + v; break;
    case 2: raw = 64 + 12 * v; break;
    case 3: raw = (p.map && v >= 0 && v < p.nmap) ? p.map[v] : p.lo; break;
    default: raw = v + p.off; break;
    }
    return clampi(raw, p.lo, p.hi);
}

int raw_to_value(const mq_param_t &p, int raw) {
    switch (p.kind) {
    case 1: return raw - p.lo;
    case 2: return (int)std::lround((raw - 64) / 12.0);
    case 3:
        for (int i = 0; i < p.nmap; i++) if (p.map[i] == raw) return i;
        return 0;
    default: return raw - p.off;
    }
}

/* a parameter's raw value out of / into its byte (bit fields: mask and shift) */
int field_get(const mq_param_t &p, uint8_t byte) { return p.mask ? (byte >> p.shift) & p.mask : byte; }
uint8_t field_set(const mq_param_t &p, uint8_t byte, int raw) {
    if (!p.mask) return (uint8_t)(raw & 0x7f);
    return (uint8_t)(((byte & ~(p.mask << p.shift)) | ((raw & p.mask) << p.shift)) & 0x7f);
}

synthLib::SMidiEvent sysex_event(std::initializer_list<uint8_t> bytes) {
    synthLib::SMidiEvent e(synthLib::MidiEventSource::Host);
    e.sysex.assign(bytes.begin(), bytes.end());
    return e;
}
synthLib::SMidiEvent dump_event(const Dump &d) {
    synthLib::SMidiEvent e(synthLib::MidiEventSource::Host);
    e.sysex.assign(d.begin(), d.end());
    return e;
}
synthLib::SMidiEvent request_single(int buf, int loc) {
    return sysex_event({0xf0, 0x3e, 0x10, kDeviceId, (uint8_t)mqLib::SysexCommand::SingleRequest, (uint8_t)buf, (uint8_t)loc, 0xf7});
}
synthLib::SMidiEvent param_change(int idx, int raw) {
    return sysex_event({0xf0, 0x3e, 0x10, kDeviceId, (uint8_t)mqLib::SysexCommand::SingleParameterChange, 0x00,
                        (uint8_t)((idx >> 7) & 0x7f), (uint8_t)(idx & 0x7f), (uint8_t)(raw & 0x7f), 0xf7});
}

Dump as_edit_buffer(Dump d) {
    d[5] = kEditBuf;
    d[6] = 0;
    d[d.size() - 2] = checksum(d);
    return d;
}

void name_of(const std::vector<uint8_t> &d, char *out) {
    for (int i = 0; i < kNameLen; i++) out[i] = (char)(d[kNameOff + i] >= 32 && d[kNameOff + i] < 127 ? d[kNameOff + i] : ' ');
    out[kNameLen] = 0;
    for (int i = kNameLen - 1; i >= 0 && out[i] == ' '; i--) out[i] = 0;
}

void tune_thread() {
    pthread_setname_np(pthread_self(), "VVemu");
    // Gen2 big.LITTLE (Live III: A55 0-3, A76 4-7): the fast cores minus MPC's "Audio Processing" core. The device's own threads
    // (DSP, 68k) are created from here and inherit the mask. No-op on same-speed CPUs. VAVRA_NOPIN=1 turns it off (to compare).
    if (!getenv("VAVRA_NOPIN")) fastcores::pin_this_thread();
    int nice_val = 0;
    if (const char *e = getenv("VAVRA_NICE")) nice_val = atoi(e);
    if (nice_val) setpriority(PRIO_PROCESS, (id_t)syscall(SYS_gettid), nice_val);
}

/* the edit buffer as the current sound: what the UI shows, what the state and favourites save */
void apply_loaded(Inst *in, const Dump &d, int bank, int prog) {
    {
        std::lock_guard<std::mutex> l(in->sm);
        in->cur = d;
        name_of(d, in->cur_name);
    }
    for (int i = 0; i < kNumBytes; i++) in->raw[i].store(d[kParamOff + i]);
    if (bank >= 0) { in->bank = bank; in->preset = prog; }
    in->bump();
}

/* the edit buffer with every UI edit in it */
Dump current_dump(Inst *in) {
    Dump d;
    { std::lock_guard<std::mutex> l(in->sm); d = in->cur; }
    if (d.size() != (size_t)kDumpLen) return {};
    for (int i = 0; i < kNumBytes; i++) d[kParamOff + i] = in->raw[i].load();
    d[d.size() - 2] = checksum(d);
    return d;
}

/* A 512 kB flash dump as read off the chip (any case of .bin): gearmulator wants it byte-swapped (the OS version "2.23" at the
 * start); a dump that starts ".232" is swapped here. */
mqLib::ROM find_raw_bin(const std::string &dir) {
    DIR *d = opendir(dir.c_str());
    if (!d) return {};
    mqLib::ROM out;
    while (struct dirent *e = readdir(d)) {
        const std::string n = e->d_name;
        if (n.size() < 5 || strcasecmp(n.c_str() + n.size() - 4, ".bin")) continue;
        FILE *f = fopen((dir + "/" + n).c_str(), "rb");
        if (!f) continue;
        std::vector<uint8_t> data(mqLib::ROM::g_romSize + 1);
        const size_t got = fread(data.data(), 1, data.size(), f);
        fclose(f);
        if (got != mqLib::ROM::g_romSize) continue;
        data.resize(got);
        if (!memcmp(data.data(), ".232", 4))
            for (size_t i = 0; i + 1 < data.size(); i += 2) std::swap(data[i], data[i + 1]);
        mqLib::ROM r(data, n);
        if (r.isValid()) { out = r; break; }
    }
    closedir(d);
    return out;
}

/* the ROM singles, cached on the device: "VVSND1\n\0" + 300 single dumps (the user's own ROM content; never shipped) */
const char kSndMagic[8] = {'V', 'V', 'S', 'N', 'D', '1', '\n', 0};

bool names_load(Inst *in) {
    FILE *f = fopen((in->dir + "/sounds.dat").c_str(), "rb");
    if (!f) return false;
    char magic[8];
    std::vector<uint8_t> all((size_t)VV_BANKS * VV_PER_BANK * kDumpLen);
    const bool ok = fread(magic, 1, 8, f) == 8 && !memcmp(magic, kSndMagic, 8) && fread(all.data(), 1, all.size(), f) == all.size();
    fclose(f);
    if (!ok) return false;
    std::lock_guard<std::mutex> l(in->sm);
    for (int i = 0; i < VV_BANKS * VV_PER_BANK; i++) {
        Dump d(all.begin() + (size_t)i * kDumpLen, all.begin() + (size_t)(i + 1) * kDumpLen);
        if (d[0] != 0xf0 || d.back() != 0xf7) return false;
        name_of(d, in->names[i / VV_PER_BANK][i % VV_PER_BANK]);
        in->rom_dump[i / VV_PER_BANK][i % VV_PER_BANK] = std::move(d);
        in->have[i / VV_PER_BANK][i % VV_PER_BANK] = true;
    }
    xlog("[names] from sounds.dat");
    return true;
}

void names_save(Inst *in) {
    const std::string path = in->dir + "/sounds.dat", tmp = path + ".tmp";
    FILE *f = fopen(tmp.c_str(), "wb");
    if (!f) return;
    bool ok = fwrite(kSndMagic, 1, 8, f) == 8;
    {
        std::lock_guard<std::mutex> l(in->sm);
        for (int b = 0; b < VV_BANKS; b++)
            for (int p = 0; p < VV_PER_BANK; p++) ok = ok && in->rom_dump[b][p].size() == (size_t)kDumpLen && fwrite(in->rom_dump[b][p].data(), 1, kDumpLen, f) == (size_t)kDumpLen;
    }
    ok = (fclose(f) == 0) && ok;
    if (ok) rename(tmp.c_str(), path.c_str());
    else unlink(tmp.c_str());
    xlog("[names] saved sounds.dat (%s)", ok ? "ok" : "failed");
}

/* The ROM sound names, once: a second microQ on its own thread (on the slow cores, nice 10) dumps the three banks (the
 * firmware sends a bank at ~4 singles a second and ignores other MIDI meanwhile, so the playing one cannot do it), then
 * sounds.dat caches them. One harvest per process at a time. */
std::atomic<bool> g_harvesting{false};

void harvest_names(Inst *in, std::vector<uint8_t> rom_data, std::string rom_name) {
    if (g_harvesting.exchange(true)) return;
    pthread_setname_np(pthread_self(), "VVnames");
    if (!fastcores::usable().empty()) {
        cpu_set_t set;
        CPU_ZERO(&set);
        for (int c = 0; c < 3; c++) CPU_SET(c, &set);
        sched_setaffinity(0, sizeof set, &set);
    }
    setpriority(PRIO_PROCESS, (id_t)syscall(SYS_gettid), 10);
    const auto t0 = std::chrono::steady_clock::now();
    in->harvest_progress = 0;
    try {
        synthLib::DeviceCreateParams p;
        p.romData = rom_data;
        p.romName = rom_name;
        p.hostSamplerate = (float)kRate;
        p.homePath = in->dir;
        mqLib::Device dev(p);
        synthLib::Plugin plugin(&dev, [](synthLib::Device *d) { return d; });
        plugin.setMidiClockEnabled(false);
        plugin.setHostSamplerate((float)kRate, 0.0f);
        plugin.setBlockSize(kBlock);
        std::vector<float> zero(512, 0.0f), spare(512 * 12, 0.0f);
        synthLib::TAudioInputs inputs = {};
        synthLib::TAudioOutputs outputs = {};
        for (auto &i : inputs) i = zero.data();
        for (size_t k = 0; k < outputs.size(); k++) outputs[k] = spare.data() + 512 * k;
        std::vector<synthLib::SMidiEvent> midiOut;
        int bank = 0, wait = 0, got = 0;
        bool have[VV_BANKS][VV_PER_BANK] = {};
        while (!in->stop && bank < VV_BANKS) {
            if (wait == 0) { xlog("[names] bank %d", bank); plugin.addMidiEvent(request_single(0x10, bank)); }
            if (++wait > 3000) wait = 0;                          // a bank that stopped arriving: ask again
            plugin.process(inputs, outputs, kBlock, 0.0f, 0.0f, false, false);
            midiOut.clear();
            plugin.getMidiOut(midiOut);
            for (auto &e : midiOut) {
                const auto &sx = e.sysex;
                if (sx.size() != (size_t)kDumpLen || sx[1] != 0x3e || sx[2] != 0x10 || sx[4] != (uint8_t)mqLib::SysexCommand::SingleDump) continue;
                const int b = sx[5] >= kRomBank0 ? sx[5] - kRomBank0 : sx[5], pr = sx[6];
                if (b < 0 || b >= VV_BANKS || pr >= VV_PER_BANK) continue;
                {
                    std::lock_guard<std::mutex> l(in->sm);
                    in->rom_dump[b][pr].assign(sx.begin(), sx.end());
                    name_of(in->rom_dump[b][pr], in->names[b][pr]);
                    in->have[b][pr] = true;
                }
                if (!have[b][pr]) { have[b][pr] = true; in->harvest_progress = ++got; }
                wait = 1;
                if (b == bank && pr == VV_PER_BANK - 1) { bank++; wait = 0; }
                in->bump();
            }
        }
        if (bank == VV_BANKS) names_save(in);
        xlog("[names] %d names in %.0f s", got, std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count());
    } catch (const std::exception &e) {
        xlog("[names] failed: %s", e.what());
    }
    in->harvest_progress = -1;
    in->bump();
    g_harvesting = false;
}

void emu_main(Inst *in) {
    tune_thread();
    in->set_status("Looking for the microQ ROM...");
    static std::mutex rom_lock;                     // synthLib's search-path list is one global set
    mqLib::ROM rom = [&] {
        std::lock_guard<std::mutex> l(rom_lock);
        synthLib::RomLoader::addSearchPath(in->dir + "/roms");
        mqLib::ROM r = mqLib::RomLoader::findROM();
        if (r.isValid()) return r;
        return find_raw_bin(in->dir + "/roms");
    }();
    if (!rom.isValid()) {
        in->set_status("No microQ ROM in vavra/roms/ (OS .mid or 512k .bin)");
        in->failed = true;
        return;
    }
    { std::lock_guard<std::mutex> l(in->sm); snprintf(in->rom_name, sizeof in->rom_name, "%s", rom.getFilename().c_str()); }
    in->set_status("Booting the microQ...");
    xlog("[emu] ROM %s", rom.getFilename().c_str());

    const auto t0 = std::chrono::steady_clock::now();
    std::unique_ptr<mqLib::Device> dev;
    std::unique_ptr<synthLib::Plugin> plugin;
    try {
        synthLib::DeviceCreateParams p;
        p.romData = rom.getData();
        p.romName = rom.getFilename();
        p.hostSamplerate = (float)kRate;
        p.homePath = in->dir;
        dev.reset(new mqLib::Device(p));          // boots the firmware (runs until the 68k reports boot done)
        if (!dev->isValid()) throw std::runtime_error("the microQ firmware did not start");
        plugin.reset(new synthLib::Plugin(dev.get(), [](synthLib::Device *d) { return d; }));
        plugin->setMidiClockEnabled(true);
        plugin->setHostSamplerate((float)kRate, 0.0f);
        plugin->setBlockSize(kBlock);
    } catch (const std::exception &e) {
        char b[96];
        snprintf(b, sizeof b, "microQ start failed: %.60s", e.what());
        in->set_status(b);
        in->failed = true;
        xlog("[emu] %s", b);
        return;
    }
    xlog("[emu] device up in %.1f s", std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count());

    /* Every input and output gets a buffer of its own (synthLib::Plugin shares one scratch buffer between missing inputs and
     * outputs, and the microQ mixes its external input in): inputs silent, outputs 3-6 discarded. */
    std::vector<float> zero(512, 0.0f), spare(512 * 12, 0.0f);
    float outl[512], outr[512];
    synthLib::TAudioInputs inputs = {};
    synthLib::TAudioOutputs outputs = {};
    for (auto &i : inputs) i = zero.data();
    for (size_t k = 0; k < outputs.size(); k++) outputs[k] = spare.data() + 512 * k;
    outputs[0] = outl;
    outputs[1] = outr;
    std::vector<synthLib::SMidiEvent> midiOut;

    /* a sound is picked the way the microQ's own editor does it (bank select LSB $40+bank, program change); the firmware's edit
     * buffer is then read back (name, parameter bytes). Names of all 300 come from bank dumps (the firmware streams a bank at ~4
     * singles a second) and are cached in <dir>/sounds.dat, so only the first boot waits for them. */
    struct Want { bool active = false; int bank = 0, prog = 0, waited = 0, shown_at = -1; } want;
    bool dirty[kNumBytes] = {};
    const bool need_names = !names_load(in) && !getenv("VAVRA_NOHARVEST");
    long last_ticks = 0;
    auto last_t = std::chrono::steady_clock::now();
    uint32_t block_no = 0;
    long long boost_until = 0;
    const pid_t host_tid = -1;

    auto ask_for_sound = [&](int bank, int prog) {
        want.active = true; want.bank = bank; want.prog = prog; want.waited = 0; want.shown_at = -1;
        xlog("[sound] program change %d/%d", bank, prog);
        plugin->addMidiEvent(synthLib::SMidiEvent(synthLib::MidiEventSource::Host, 0xb0, 0, 0));
        plugin->addMidiEvent(synthLib::SMidiEvent(synthLib::MidiEventSource::Host, 0xb0, 32, (uint8_t)(kRomBank0 + bank)));
        plugin->addMidiEvent(synthLib::SMidiEvent(synthLib::MidiEventSource::Host, 0xc0, (uint8_t)prog, 0));
    };

    auto produce = [&](bool to_ring) {
        std::vector<Cmd> cmds;
        { std::lock_guard<std::mutex> l(in->qm); cmds.swap(in->q); }
        for (auto &c : cmds)
            if (c.type == C_PRESET || c.type == C_LOADDUMP || (c.type == C_MIDI && (c.m[0] & 0xf0) == 0xc0)) { boost_until = mono_ms() + 400; break; }
        for (auto &c : cmds) {
            switch (c.type) {
            case C_MIDI:
                plugin->addMidiEvent(synthLib::SMidiEvent(synthLib::MidiEventSource::Host, c.m[0], c.m[1], c.m[2]));
                break;
            case C_PARAM:
                if (c.a >= 0 && c.a < kNumBytes) dirty[c.a] = true;
                break;
            case C_PRESET: {
                memset(dirty, 0, sizeof dirty);
                if (c.a < VV_BANKS) ask_for_sound(c.a, c.b);
                Dump d;
                {
                    std::lock_guard<std::mutex> l(in->sm);
                    if (c.a < VV_BANKS) d = in->rom_dump[c.a][c.b];
                    else if (c.b < bank_size(in, c.a)) d = in->fbanks[c.a - VV_BANKS].sounds[c.b];
                }
                if (c.a >= VV_BANKS) {                        // a sound from a file: straight into the edit buffer
                    want.active = false;
                    if (d.size() == (size_t)kDumpLen) {
                        const Dump eb = as_edit_buffer(d);
                        plugin->addMidiEvent(dump_event(eb));
                        apply_loaded(in, eb, c.a, c.b);
                        xlog("[sound] %d/%d \"%s\" (file)", c.a, c.b, in->cur_name);
                    }
                    break;
                }
                if (d.size() == (size_t)kDumpLen) {           // the ROM single as the firmware now has it in its edit buffer
                    want.active = false;
                    apply_loaded(in, as_edit_buffer(d), c.a, c.b);
                    xlog("[sound] %d/%d \"%s\" (cached)", c.a, c.b, in->cur_name);
                }
                break;
            }
            case C_PANIC:
                for (uint8_t ch = 0; ch < 16; ch++) {
                    plugin->addMidiEvent(synthLib::SMidiEvent(synthLib::MidiEventSource::Host, (uint8_t)(0xb0 | ch), 123, 0));
                    plugin->addMidiEvent(synthLib::SMidiEvent(synthLib::MidiEventSource::Host, (uint8_t)(0xb0 | ch), 120, 0));
                }
                break;
            case C_LOADDUMP: {
                memset(dirty, 0, sizeof dirty);
                want.active = false;
                const Dump d = as_edit_buffer(c.dump);
                plugin->addMidiEvent(dump_event(d));
                apply_loaded(in, d, -1, 0);
                break;
            }
            }
        }
        // parameter writes, coalesced per byte (the value is read at send time: a sweep sends its latest value, not every step)
        int sent = 0;
        for (int i = 0; i < kNumBytes && sent < 6; i++) {
            if (!dirty[i]) continue;
            dirty[i] = false;
            plugin->addMidiEvent(param_change(i, in->raw[i].load()));
            sent++;
        }
        /* the edit buffer, read back once the firmware shows the new sound on its LCD ("Sound:A010"): asked earlier, gearmulator's
         * cache answers with the previous sound. Asked again every ~1.5 s, and after ~3 s without the LCD, anyway. */
        if (want.active) {
            ++want.waited;
            char tag[16];
            snprintf(tag, sizeof tag, "%c%03d", 'A' + want.bank, want.prog + 1);
            bool shown;
            { std::lock_guard<std::mutex> l(in->sm); shown = strstr(in->lcd[0], tag) != nullptr; }
            if (shown && want.shown_at < 0) want.shown_at = want.waited;
            if ((want.shown_at >= 0 && (want.waited - want.shown_at) % 512 == 24) || want.waited % 1024 == 0) plugin->addMidiEvent(request_single(kEditBuf, 0));
        }

        {
            /* MPC's position, moved forward by what the ring holds: this block is heard that much later */
            const double bpm = in->host_bpm.load(), ppq = in->host_ppq.load();
            const uint32_t ahead = in->wr.load(std::memory_order_relaxed) - in->rd.load(std::memory_order_relaxed);
            const bool sync = bpm > 0.0 && ppq >= 0.0 && in->ready;
            const double my_ppq = sync ? ppq + ahead * bpm / 60.0 / kRate : 0.0;
            plugin->process(inputs, outputs, kBlock, sync ? (float)bpm : 0.0f, (float)my_ppq, sync && in->host_playing.load(), sync);
        }
        block_no++;

        midiOut.clear();
        plugin->getMidiOut(midiOut);
        for (auto &e : midiOut) {
            const auto &sx = e.sysex;
            static int dbg = getenv("VAVRA_SXLOG") ? 400 : 0;
            if (dbg > 0 && !sx.empty()) { dbg--; xlog("[sx] %zu bytes cmd %02x %02x %02x", sx.size(), sx.size() > 4 ? sx[4] : 0, sx.size() > 5 ? sx[5] : 0, sx.size() > 6 ? sx[6] : 0); }
            if (sx.size() < 6 || sx[0] != 0xf0 || sx[1] != 0x3e || sx[2] != 0x10) continue;
            if (sx[4] == (uint8_t)mqLib::SysexCommand::EmuLCD && sx.size() >= 46) {
                std::lock_guard<std::mutex> l(in->sm);
                bool changed = false;
                for (int ln = 0; ln < 2; ln++)
                    for (int i = 0; i < 20; i++) {
                        const uint8_t ch = sx[5 + ln * 20 + i];
                        const char c = (char)(ch >= 32 && ch < 127 ? ch : ' ');
                        if (in->lcd[ln][i] != c) { in->lcd[ln][i] = c; changed = true; }
                    }
                in->lcd[0][20] = in->lcd[1][20] = 0;
                if (changed) in->bump();
                continue;
            }
            if (sx.size() != (size_t)kDumpLen || sx[4] != (uint8_t)mqLib::SysexCommand::SingleDump) continue;
            Dump d(sx.begin(), sx.end());
            if (sx[5] == kEditBuf) {
                if (!want.active) continue;
                want.active = false;
                apply_loaded(in, d, want.bank, want.prog);
                xlog("[sound] loaded %d/%d \"%s\"", want.bank, want.prog, in->cur_name);
                continue;
            }

        }

        if (getenv("VAVRA_OUTLOG")) {
            static float pk[6]; static int cnt;
            for (int k = 0; k < 6; k++) for (int i = 0; i < kBlock; i++) pk[k] = std::max(pk[k], std::fabs(outputs[k][i]));
            if (++cnt % 345 == 0) { xlog("[out] %.4f %.4f %.4f %.4f %.4f %.4f", pk[0], pk[1], pk[2], pk[3], pk[4], pk[5]); memset(pk, 0, sizeof pk); }
        }
        if (!to_ring) return;
        const float g = in->gain.load() / 100.0f * 32767.0f;
        uint32_t w = in->wr.load(std::memory_order_relaxed);
        for (int i = 0; i < kBlock; i++) {
            in->ring[(w & (kRingFrames - 1)) * 2] = (int16_t)std::max(-32768.0f, std::min(32767.0f, outl[i] * g));
            in->ring[(w & (kRingFrames - 1)) * 2 + 1] = (int16_t)std::max(-32768.0f, std::min(32767.0f, outr[i] * g));
            w++;
        }
        in->wr.store(w, std::memory_order_release);
    };

    // the first sound (unless a restored state queued its own dump), and a short run so the ring starts full
    {
        bool have_state = false;
        { std::lock_guard<std::mutex> l(in->qm); for (auto &c : in->q) if (c.type == C_LOADDUMP || c.type == C_PRESET) have_state = true; }
        if (!have_state) ask_for_sound(in->bank.load(), in->preset.load());
    }
    in->set_status("Warming up...");
    for (int i = 0; (i < kTargetFill / kBlock + 2 || (want.active && i < 4000)) && !in->stop; i++) produce(true);
    in->ready = true;
    in->set_status("Ready - ROM loaded");
    if (need_names) in->harvester = std::thread(harvest_names, in, rom.getData(), rom.getFilename());
    xlog("[emu] ready after %.1f s", std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count());

    static const bool bench = getenv("VAVRA_BENCH") != nullptr;
    long long rep_ms = mono_ms();
    long slow_us = 0;
    uint32_t rep_drops = in->underruns.load();
    while (!in->stop) {
        const uint32_t fill = in->wr.load(std::memory_order_relaxed) - in->rd.load(std::memory_order_acquire);
        if (bench) in->rd.store(in->wr.load());
        const uint32_t target = mono_ms() < boost_until ? (uint32_t)kBoostFill : (uint32_t)kTargetFill;
        if (!bench && (fill >= target || fill + kBlock > (uint32_t)kRingFrames)) {
            std::this_thread::sleep_for(std::chrono::microseconds(500));
            continue;
        }
        const auto c0 = std::chrono::steady_clock::now();
        produce(true);
        const long us = (long)std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - c0).count();
        if (us > slow_us) slow_us = us;
        if (mono_ms() - rep_ms >= 5000) {           // one line per 5 s into journalctl -u acvs when dropouts rise (EMULATOR_PORTS.md section 4)
            const uint32_t d = in->underruns.load();
            const uint32_t rmin = in->ring_min.exchange(0xffffffffu), bmax = in->burst_max.exchange(0);
            if (d != rep_drops || getenv("VAVRA_RINGLOG"))
                fprintf(stderr, "Vavra: dropouts %u (+%u), ring min %u, host burst %u, slowest chunk %ld us, emu cpu %d%%\n",
                        d, d - rep_drops, rmin == 0xffffffffu ? 0 : rmin, bmax, slow_us, in->emu_cpu.load());
            rep_drops = d; slow_us = 0; rep_ms = mono_ms();
        }
        if ((block_no % 690) == 0) {               // ~2 s
            const auto now = std::chrono::steady_clock::now();
            const long tk = emu_thread_ticks(host_tid);
            const double dt = std::chrono::duration<double>(now - last_t).count();
            if (dt > 0.1) in->emu_cpu = (int)((tk - last_ticks) / 100.0 / dt * 100.0);
            if (bench) xlog("[bench] %.2fx real time, emu cpu %d%%", 690.0 * kBlock / kRate / dt, in->emu_cpu.load());
            last_ticks = tk;
            last_t = now;
        }
    }
    xlog("[emu] stopping");
    plugin.reset();
    dev.reset();
}

/* ------------------------------------------------------------------ favourites: "VVFAV1\n\0", then 24 name bytes + a single dump each */
const char kFavMagic[8] = {'V', 'V', 'F', 'A', 'V', '1', '\n', 0};
std::string fav_path(Inst *in) { return in->dir + "/favourites.dat"; }

void fav_load(Inst *in) {
    std::lock_guard<std::mutex> l(in->fm);
    in->fav_count = 0;
    FILE *f = fopen(fav_path(in).c_str(), "rb");
    if (!f) return;
    char magic[8];
    if (fread(magic, 1, 8, f) == 8 && !memcmp(magic, kFavMagic, 8)) {
        Dump d(kDumpLen);
        while (in->fav_count < kFavSlots && fread(in->fav_name[in->fav_count], 1, 24, f) == 24 && fread(d.data(), 1, kDumpLen, f) == (size_t)kDumpLen) {
            in->fav_name[in->fav_count][23] = 0;
            in->fav_dump[in->fav_count] = d;
            in->fav_count++;
        }
    }
    fclose(f);
    xlog("[fav] %d loaded", in->fav_count);
}

bool fav_write(Inst *in) {            // under fm
    const std::string path = fav_path(in), tmp = path + ".tmp";
    FILE *f = fopen(tmp.c_str(), "wb");
    if (!f) return false;
    bool ok = fwrite(kFavMagic, 1, 8, f) == 8;
    for (int i = 0; ok && i < in->fav_count; i++)
        ok = fwrite(in->fav_name[i], 1, 24, f) == 24 && fwrite(in->fav_dump[i].data(), 1, kDumpLen, f) == (size_t)kDumpLen;
    ok = (fclose(f) == 0) && ok;
    return ok && rename(tmp.c_str(), path.c_str()) == 0;
}

void fav_save(Inst *in) {
    const Dump d = current_dump(in);
    if (d.empty()) return;
    char nm[kNameLen + 1];
    name_of(d, nm);
    std::lock_guard<std::mutex> l(in->fm);
    if (in->fav_count >= kFavSlots) return;
    for (int i = 0; i < in->fav_count; i++) if (in->fav_dump[i] == d) return;      // already there
    const int i = in->fav_count;
    snprintf(in->fav_name[i], 24, "%s", nm[0] ? nm : "Favourite");
    in->fav_dump[i] = d;
    in->fav_count++;
    if (!fav_write(in)) in->fav_count--;
    else { in->fav_current = i; in->fav_stamp = in->load_gen; xlog("[fav] saved %d \"%s\"", i + 1, in->fav_name[i]); }
}

void fav_delete(Inst *in) {           // only the favourite that is the current sound
    std::lock_guard<std::mutex> l(in->fm);
    const int d = in->fav_current;
    if (d < 0 || d >= in->fav_count || in->fav_stamp != in->load_gen) return;
    for (int i = d; i + 1 < in->fav_count; i++) { memcpy(in->fav_name[i], in->fav_name[i + 1], 24); in->fav_dump[i] = in->fav_dump[i + 1]; }
    in->fav_count--;
    fav_write(in);
    in->fav_current = -1;
}

void fav_pick(Inst *in, int idx) {
    std::lock_guard<std::mutex> l(in->fm);
    if (idx < 0 || idx >= kFavSlots) return;
    if (idx < in->fav_count) {
        Cmd c;
        c.type = C_LOADDUMP;
        c.dump = in->fav_dump[idx];
        apply_loaded(in, as_edit_buffer(c.dump), -1, 0);      // the UI shows it at once; the emulator thread sends it
        in->push(std::move(c));
        in->load_gen++;
    }
    in->fav_current = idx;            // an empty slot shows as picked, nothing loads
    in->fav_stamp = in->load_gen;
    in->bump();
}

/* ------------------------------------------------------------------ the engine interface */

void *eng_create(const char *dir) {
    if (!g_log) g_log = fopen(getenv("VAVRA_LOG") ? getenv("VAVRA_LOG") : "/tmp/vavra.log", "a");
    Inst *in = new Inst();
    in->dir = dir ? dir : "";
    for (auto &r : in->raw) r.store(0);
    for (int i = 0; i < MQ_NUM_PARAMS; i++) {
        const mq_param_t &p = g_mq_params[i];
        in->raw[p.idx].store(field_set(p, in->raw[p.idx].load(), p.def));
    }
    fav_load(in);
    scan_banks(in);
    in->th = std::thread(emu_main, in);
    return in;
}

void eng_destroy(void *p) {
    Inst *in = (Inst *)p;
    if (!in) return;
    in->stop = true;
    if (in->th.joinable()) in->th.join();
    if (in->harvester.joinable()) in->harvester.join();
    delete in;
}

void select_sound(Inst *in, int bank, int prog) {
    if (in->failed) { bank = clampi(bank, 0, kMaxBanks - 1); prog = clampi(prog, 0, 127); }       // no ROM: keep what was asked
    else {
        bank = clampi(bank, 0, bank_count(in) - 1);
        prog = clampi(prog, 0, std::max(0, bank_size(in, bank) - 1));
    }
    in->bank_page = bank / kBankTiles;
    xlog("[sound] select bank %d preset %d", bank, prog);
    in->bank = bank;
    in->preset = prog;
    in->page = prog / VV_PATCH_TILES;
    Cmd c;
    c.type = C_PRESET;
    c.a = bank;
    c.b = prog;
    in->push(std::move(c));
    in->load_gen++;
    in->bump();
}

void eng_midi(void *p, const uint8_t *msg, int len) {
    Inst *in = (Inst *)p;
    if (!in || len < 1 || len > 3 || msg[0] < 0x80 || msg[0] >= 0xf0) return;
    const uint8_t st = msg[0] & 0xf0;
    if (st == 0xc0 && len >= 2) { if (msg[1] < bank_size(in, in->bank)) select_sound(in, in->bank, msg[1]); return; }
    if (st == 0xb0 && len >= 3 && (msg[1] == 0 || msg[1] == 32)) {     // bank select A/B/C: takes effect with the next program change
        if (msg[1] == 0 && msg[2] < bank_count(in)) in->bank = msg[2];
        return;
    }
    Cmd c;
    c.type = C_MIDI;
    c.m[0] = (uint8_t)(st);                    // the microQ listens on channel 1 (Global MIDI channel of a fresh device)
    c.m[1] = len > 1 ? msg[1] : 0;
    c.m[2] = len > 2 ? msg[2] : 0;
    in->push(std::move(c));
}

int slot_key(const char *key, const char *prefix, int max, bool *on) {
    const size_t n = strlen(prefix);
    if (strncmp(key, prefix, n) != 0) return 0;
    char *end = nullptr;
    const long v = strtol(key + n, &end, 10);
    if (end == key + n || v < 1 || v > max) return 0;
    if (*end == 0) { *on = false; return (int)v; }
    if (strcmp(end, "_on") == 0) { *on = true; return (int)v; }
    return 0;
}

int pages(Inst *in) { return std::max(1, (bank_size(in, in->bank) + VV_PATCH_TILES - 1) / VV_PATCH_TILES); }
int hexval(char c) { return c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1; }

void restore_state(Inst *in, const char *s) {
    auto num = [&](const char *k, int def) {
        const char *q = strstr(s, k);
        return q ? atoi(q + strlen(k)) : def;
    };
    in->bank = clampi(num("\"bank\":", 0), 0, bank_count(in) - 1);
    in->preset = clampi(num("\"preset\":", 0), 0, std::max(0, bank_size(in, in->bank) - 1));
    in->page = in->preset / VV_PATCH_TILES;
    in->gain = clampi(num("\"gain\":", 100), 10, 400);
    const char *h = strstr(s, "\"single\":\"");
    if (h) {
        h += 10;
        Dump d;
        while (hexval(h[0]) >= 0 && hexval(h[1]) >= 0) { d.push_back((uint8_t)(hexval(h[0]) * 16 + hexval(h[1]))); h += 2; }
        if (d.size() == (size_t)kDumpLen && d.front() == 0xf0 && d.back() == 0xf7) {
            apply_loaded(in, as_edit_buffer(d), -1, 0);
            Cmd c;
            c.type = C_LOADDUMP;
            c.dump = std::move(d);
            in->push(std::move(c));
            in->load_gen++;
            return;
        }
    }
    select_sound(in, in->bank, in->preset);
}

void write_byte(Inst *in, int idx, uint8_t v) {
    in->raw[idx].store(v);
    Cmd c;                                      // the emulator thread coalesces: one param change per byte, latest value
    c.type = C_PARAM;
    c.a = idx;
    in->push(std::move(c));
}

int fx_byte(const char *key, int *fx) {        // "fx1_p3" -> byte 132
    if (strncmp(key, "fx", 2) || (key[2] != '1' && key[2] != '2') || key[3] != '_' || (key[4] != 'p' && key[4] != 'l')) return -1;
    const int n = atoi(key + 5);
    if (n < 1 || n > 14) return -1;
    *fx = key[2] - '0';
    return (*fx == 1 ? kFx1Base : kFx2Base) + n - 1;
}

void eng_set(void *p, const char *key, const char *val) {
    Inst *in = (Inst *)p;
    if (!in || !key || !val) return;
    bool on = false;
    int n;
    const bool press = atoi(val) != 0;
    if ((n = slot_key(key, "bank_slot_", kBankTiles, &on)) && !on) {
        const int b = in->bank_page * kBankTiles + n - 1;
        if (press && b < bank_count(in)) select_sound(in, b, 0);
        return;
    }
    if (!strcmp(key, "bank_page_prev")) { if (press && in->bank_page > 0) { in->bank_page--; in->bump(); } return; }
    if (!strcmp(key, "bank_page_next")) { if (press && (in->bank_page + 1) * kBankTiles < bank_count(in)) { in->bank_page++; in->bump(); } return; }
    if ((n = slot_key(key, "patch_slot_", VV_PATCH_TILES, &on)) && !on) {
        if (press && in->page * VV_PATCH_TILES + n - 1 < bank_size(in, in->bank)) select_sound(in, in->bank, in->page * VV_PATCH_TILES + n - 1);
        return;
    }
    if (!strcmp(key, "patch_page_prev")) { if (press && in->page > 0) { in->page--; in->bump(); } return; }
    if (!strcmp(key, "patch_page_next")) { if (press && in->page + 1 < pages(in)) { in->page++; in->bump(); } return; }
    if (!strcmp(key, "preset")) { select_sound(in, in->bank, atoi(val)); return; }
    if (!strcmp(key, "bank_index")) { select_sound(in, atoi(val), 0); return; }
    if (!strcmp(key, "preset_next") || !strcmp(key, "preset_prev")) {
        const int np = std::max(1, bank_size(in, in->bank));
        if (press) select_sound(in, in->bank, (in->preset + (!strcmp(key, "preset_next") ? 1 : np - 1)) % np);
        return;
    }
    if (!strcmp(key, "bank_next") || !strcmp(key, "bank_prev")) {
        const int nb = bank_count(in);
        if (press) select_sound(in, (in->bank + (!strcmp(key, "bank_next") ? 1 : nb - 1)) % nb, 0);
        return;
    }
    if (!strcmp(key, "all_notes_off")) { if (press) { Cmd c; c.type = C_PANIC; in->push(std::move(c)); } return; }
    if (!strcmp(key, "init_patch")) { if (press) select_sound(in, in->bank, in->preset); return; }      // reload the stored sound
    if (!strcmp(key, "fav_save")) { if (press) { fav_save(in); in->bump(); } return; }
    if (!strcmp(key, "fav_delete")) { if (press) { fav_delete(in); in->bump(); } return; }
    if (!strcmp(key, "favourite")) { fav_pick(in, atoi(val)); return; }
    if (!strcmp(key, "gain")) { in->gain = clampi(atoi(val), 10, 400); return; }
    if (!strcmp(key, "state")) { restore_state(in, val); return; }
    int fx;
    const int fb = fx_byte(key, &fx);
    if (fb >= 0 && key[4] == 'p') { write_byte(in, fb, (uint8_t)clampi(atoi(val), 0, 127)); return; }
    auto it = mq_index().find(key);
    if (it == mq_index().end()) return;
    const mq_param_t &q = g_mq_params[it->second];
    const int raw = value_to_raw(q, atoi(val));
    write_byte(in, q.idx, field_set(q, in->raw[q.idx].load(), raw));
    if (q.idx == kFx1Type || q.idx == kFx2Type) in->bump();          // the FX knob labels change
}

int put(char *buf, int n, const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    const int r = vsnprintf(buf, n, fmt, ap);
    va_end(ap);
    return r < 0 ? 0 : std::min(r, n - 1);
}

int eng_get(void *p, const char *key, char *buf, int n) {
    Inst *in = (Inst *)p;
    if (!in || !key || n < 2) return -1;
    bool on = false;
    int k;
    if ((k = slot_key(key, "bank_slot_", kBankTiles, &on))) {
        const int b = in->bank_page * kBankTiles + k - 1;
        if (on) return put(buf, n, "%d", b == in->bank ? 1 : 0);
        return put(buf, n, "%s", b < bank_count(in) ? bank_title(in, b).c_str() : "");
    }
    if (!strcmp(key, "bank_page_text")) return put(buf, n, "%d / %d", in->bank_page + 1, (bank_count(in) + kBankTiles - 1) / kBankTiles);
    if ((k = slot_key(key, "patch_slot_", VV_PATCH_TILES, &on))) {
        const int idx = in->page * VV_PATCH_TILES + k - 1;
        if (on) return put(buf, n, "%d", idx == in->preset ? 1 : 0);
        if (idx >= bank_size(in, in->bank)) return put(buf, n, "%s", "");
        std::lock_guard<std::mutex> l(in->sm);
        return put(buf, n, "%03d %s", idx + 1, sound_name(in, in->bank, idx).c_str());
    }
    if (!strcmp(key, "patch_page_text")) return put(buf, n, "PAGE %d / %d", in->page + 1, pages(in));
    if (!strcmp(key, "preset")) return put(buf, n, "%d", in->preset.load());
    if (!strcmp(key, "bank_index")) return put(buf, n, "%d", in->bank.load());
    if (!strcmp(key, "bank_name")) return put(buf, n, "%s", in->bank < bank_count(in) ? bank_title(in, in->bank).c_str() : "-");
    if (!strcmp(key, "preset_name")) {
        std::lock_guard<std::mutex> l(in->sm);
        const int b = in->bank, pr = in->preset;
        const std::string nm = in->cur_name[0] ? std::string(in->cur_name) : sound_name(in, b, pr);
        if (b < VV_BANKS) return put(buf, n, "%c%03d %s", 'A' + b, pr + 1, nm.c_str());
        return put(buf, n, "%03d %s", pr + 1, nm.c_str());
    }
    if (!strcmp(key, "rom_name")) { std::lock_guard<std::mutex> l(in->sm); return put(buf, n, "%s", in->rom_name[0] ? in->rom_name : "-"); }
    if (!strcmp(key, "loading_status")) {
        const int h = in->harvest_progress.load();
        if (h >= 0 && in->ready) return put(buf, n, "Ready - reading sound names %d / %d", h, VV_BANKS * VV_PER_BANK);
        std::lock_guard<std::mutex> l(in->sm);
        return put(buf, n, "%s", in->status);
    }
    if (!strcmp(key, "lcd1") || !strcmp(key, "lcd2")) {
        std::lock_guard<std::mutex> l(in->sm);
        return put(buf, n, "%s", in->lcd[key[3] - '1']);
    }
    if (!strcmp(key, "engine_stats")) {
        /* any change of a polled text makes MPC re-list its menus: hold it while the PRESET menu is in use, CPU in steps of 10 */
        std::lock_guard<std::mutex> l(in->stm);
        if (mono_ms() - in->fav_list_ms < 15000 && in->stats_cache[0]) return put(buf, n, "%s", in->stats_cache);
        const int cpu = in->emu_cpu.load();
        if (in->stats_cpu < 0 || abs(cpu - in->stats_cpu) >= 10) in->stats_cpu = cpu / 10 * 10;
        snprintf(in->stats_cache, sizeof in->stats_cache, "DROPOUTS %u   CPU %d%%", in->underruns.load(), in->stats_cpu);
        return put(buf, n, "%s", in->stats_cache);
    }
    if (!strcmp(key, "gain")) return put(buf, n, "%d", in->gain.load());
    if (!strcmp(key, "favourite")) {      // the picked favourite while it is the sound, else the first empty slot
        std::lock_guard<std::mutex> l(in->fm);
        const bool cur = in->fav_current >= 0 && in->fav_stamp == in->load_gen;
        return put(buf, n, "%d", cur ? in->fav_current : std::min(in->fav_count, kFavSlots - 1));
    }
    if (!strncmp(key, "favourite:", 10)) {
        in->fav_list_ms = mono_ms();
        std::lock_guard<std::mutex> l(in->fm);
        const int i = atoi(key + 10);
        return put(buf, n, "%s", i >= 0 && i < in->fav_count ? in->fav_name[i] : "-");
    }
    if (!strcmp(key, "fav_text")) { std::lock_guard<std::mutex> l(in->fm); return put(buf, n, "FAVOURITES %d / %d", in->fav_count, kFavSlots); }
    if (!strcmp(key, "display_rev")) return put(buf, n, "%u", in->rev.load());
    int fx;
    const int fb = fx_byte(key, &fx);
    if (fb >= 0) {
        if (key[4] == 'p') return put(buf, n, "%d", (int)in->raw[fb].load());
        const int t = in->raw[fx == 1 ? kFx1Type : kFx2Type].load();
        const int i = fb - (fx == 1 ? kFx1Base : kFx2Base);
        const char *lab = fx == 1 ? (t < FX1_TYPES ? g_fx1_labels[t][i] : "") : (t < FX2_TYPES ? g_fx2_labels[t][i] : "");
        return put(buf, n, "%s", lab[0] ? lab : " ");
    }
    if (!strcmp(key, "state")) {
        int off = put(buf, n, "{\"state_version\":1,\"bank\":%d,\"preset\":%d,\"gain\":%d", in->bank.load(), in->preset.load(), in->gain.load());
        const Dump d = in->ready ? current_dump(in) : Dump();
        if (!d.empty() && off + kDumpLen * 2 + 16 < n) {
            off += put(buf + off, n - off, ",\"single\":\"");
            static const char hx[] = "0123456789abcdef";
            for (uint8_t b : d) { buf[off++] = hx[b >> 4]; buf[off++] = hx[b & 15]; }
            buf[off] = 0;
            off += put(buf + off, n - off, "\"");
        }
        off += put(buf + off, n - off, "}");
        return off;
    }
    auto it = mq_index().find(key);
    if (it != mq_index().end()) {
        const mq_param_t &q = g_mq_params[it->second];
        const int v = raw_to_value(q, field_get(q, in->raw[q.idx].load()));
        const int lo = q.kind == 0 ? q.lo - q.off : 0, hi = q.kind == 0 ? q.hi - q.off : q.kind == 2 ? 4 : q.kind == 3 ? q.nmap - 1 : q.hi - q.lo;
        return put(buf, n, "%d", q.kind == 2 ? clampi(v, -4, 4) : clampi(v, lo, hi));      // a sound may hold a byte outside the table's range
    }
    return -1;
}

void eng_render(void *p, int16_t *out, int frames) {
    Inst *in = (Inst *)p;
    if (!in || !in->ready.load(std::memory_order_acquire)) { memset(out, 0, (size_t)frames * 4); return; }
    uint32_t r = in->rd.load(std::memory_order_relaxed);
    const uint32_t avail = in->wr.load(std::memory_order_acquire) - r;
    if (avail < in->ring_min.load(std::memory_order_relaxed)) in->ring_min.store(avail, std::memory_order_relaxed);
    if ((uint32_t)frames > in->burst_max.load(std::memory_order_relaxed)) in->burst_max.store((uint32_t)frames, std::memory_order_relaxed);
    const int got = (int)std::min<uint32_t>(avail, (uint32_t)frames);
    for (int i = 0; i < got; i++, r++) {
        out[i * 2] = in->ring[(r & (kRingFrames - 1)) * 2];
        out[i * 2 + 1] = in->ring[(r & (kRingFrames - 1)) * 2 + 1];
    }
    in->rd.store(r, std::memory_order_release);
    if (got < frames) {
        memset(out + got * 2, 0, (size_t)(frames - got) * 4);
        in->underruns.fetch_add(1, std::memory_order_relaxed);
    }
}

void eng_song_pos(void *p, double ppq, double bpm, int playing, int frames) {
    (void)frames;
    Inst *in = (Inst *)p;
    if (!in) return;
    in->host_ppq = ppq;
    in->host_bpm = bpm;
    in->host_playing = playing != 0;
}

const mpc_engine_t engine = {eng_create, eng_destroy, eng_midi, eng_set, eng_get, eng_render, nullptr, eng_song_pos};

}  // namespace

extern "C" const mpc_engine_t *mpc_engine(void) { return &engine; }
