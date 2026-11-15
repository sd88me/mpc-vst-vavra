#!/usr/bin/env bash
# Offline x86 test under ASan/UBSan (no device): the native front end + the real engine and your ROM, driven by tests/host_test.cpp in
# real time. Must print OK. VAVRA_ROMS: a folder with your microQ ROM (default ./data/roms). VAVRA_BANKS: sound sets (default
# ./data/banks). VAVRA_NAME: the build's name (beta tests).
set -euo pipefail
cd "$(dirname "$0")/.."
SDK="${MPC_SDK:-$HOME/mpc-plugin-builder-sdk}"
MV="${MPC_VST:-$HOME/mpc-vst-plugins}"
ROMS="$(cd "${VAVRA_ROMS:-data/roms}" && pwd)"
python3 tools/gen_sdk_params.py >/dev/null
# A project chunk saved by the released 0.1.0 build, made from that build's own code and your ROM (not committed: it holds a ROM sound).
[ -f tests/data/legacy-0.1.0.chunk ] || VAVRA_ROMS="$ROMS" tests/make_legacy_chunk.sh >/dev/null 2>&1
# the engine (unsanitised, Release) for x86, in its own build dir: vst/build/engine/ holds the aarch64 archive
cmake -S . -B build/x86 -G Ninja -DCMAKE_BUILD_TYPE=Release -DMPC_VST="$MV" >/dev/null
cmake --build build/x86 --target vavra_dsp -j"$(nproc)" > build/engine-x86.log 2>&1 || { grep -E "error" build/engine-x86.log | head -20; exit 1; }
B=build/x86; libs=""
for l in libvavra_dsp.a mqLib/libmqLib.a wLib/libwLib.a hardwareLib/libhardwareLib.a mc68k/lib68kEmu.a synthLib/libsynthLib.a baseLib/libbaseLib.a \
         libresample/libresample.a dsp56kEmu/libdsp56kEmu.a dsp56kBase/libdsp56kBase.a asmjit/libasmjit.a vtuneSdk/libvtuneSdk.a; do libs="$libs $B/$l"; done
T=build/test; mkdir -p "$T"
S="-fsanitize=address,undefined -fno-sanitize-recover=undefined -fno-omit-frame-pointer -O1 -g -std=c++17 -pthread"
N="${VAVRA_NAME:-Vavra}"
g++ $S -Wall -Wextra -DVAVRA_TEST -DVAVRA_NAME="\"$N\"" -I"$SDK/framework" -I"$MV/wrapper" -Isrc -c src/VavraPlugin.cpp -o "$T/plugin.o"
g++ $S -DVAVRA_EXPECT_NAME="\"$N\"" -I"$SDK/framework" -Isrc -c tests/host_test.cpp -o "$T/host_test.o"
g++ $S -o "$T/vavratest" "$T/plugin.o" "$T/host_test.o" -Wl,--start-group $libs -Wl,--end-group -ldl -lm
pf="$(mktemp -d)"; trap 'rm -rf "$pf"' EXIT
mkdir -p "$pf/vavra"; cp -r "$ROMS" "$pf/vavra/roms"; cp plugin.json "$pf/"
[ -f data/sounds.dat ] && cp data/sounds.dat "$pf/vavra/"             # the ROM's sound cache (made by a first boot): skips the harvest
[ -d "${VAVRA_BANKS:-data/banks}" ] && cp -r "${VAVRA_BANKS:-data/banks}" "$pf/vavra/banks"
set +e
VAVRA_REC="${VAVRA_REC:-}" MPC_PLUGIN_FOLDER="$pf" VAVRA_LOG="$T/engine.log" ASAN_OPTIONS=detect_leaks=1 "$T/vavratest" tests/data/legacy-0.1.0.chunk > "$T/log.txt" 2>&1
st=$?
grep -E '^(== |  ok   |  FAIL |OK$|FAILED|[A-DUW]: opened|    \(|    [A-Za-z0-9_]+ host )|ERROR: |runtime error' "$T/log.txt" | tail -${TAIL:-120}
exit $st
