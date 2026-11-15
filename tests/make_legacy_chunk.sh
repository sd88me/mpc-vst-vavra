#!/usr/bin/env bash
# Make tests/data/legacy-0.1.0.chunk: what a project saved with the released 0.1.0 build stores (effGetChunk), from that build's own code.
# Builds the v0.1.0 tree (engine + mpc-vst-plugins' wrapper) for x86 as a shared library, loads it like a host with your ROM, and saves
# the chunk. The wrapper is mpc-vst-plugins as of the release build's day. Not committed: it carries a ROM sound's bytes. VAVRA_ROMS: a folder with the ROM (default ./data/roms). MPC_VST: mpc-vst-plugins.
set -euo pipefail
cd "$(dirname "$0")/.."
MV="${MPC_VST:-$HOME/mpc-vst-plugins}"
ROMS="$(cd "${VAVRA_ROMS:-data/roms}" && pwd)"
W=build/legacy; rm -rf "$W"; mkdir -p "$W/src" "$W/mv" "$W/plug/vavra" tests/data
git archive v0.1.0 | tar -x -C "$W/src"
MVREV="$(git -C "$MV" rev-list -1 --before=2026-11-03T13:10+11:00 HEAD)"   # the wrapper of the released vavra.so (built 2026-11-03 13:10)
git -C "$MV" archive "$MVREV" wrapper tools | tar -x -C "$W/mv"
MV="$(pwd)/$W/mv"
ln -s "$ROMS" "$W/plug/vavra/roms"
[ -f data/sounds.dat ] && cp data/sounds.dat "$W/plug/vavra/"       # the ROM's sound cache: skips the first-boot name harvest
( cd "$W/src" && python3 "$MV/tools/gen_vst.py" vst/vst.json --params-h >/dev/null )
n=$(grep -c '^    {"' "$W/src/vst/build/params.h"); [ "$n" = 583 ] || { echo "the v0.1.0 table has $n params, not 583" >&2; exit 1; }
cmake -S "$W/src" -B "$W/eng" -G Ninja -DCMAKE_BUILD_TYPE=Release -DMPC_VST="$MV" >/dev/null
cmake --build "$W/eng" --target vavra_dsp -j"$(nproc)" >/dev/null
B="$W/eng"; libs=""
for l in libvavra_dsp.a mqLib/libmqLib.a wLib/libwLib.a hardwareLib/libhardwareLib.a mc68k/lib68kEmu.a synthLib/libsynthLib.a baseLib/libbaseLib.a \
         libresample/libresample.a dsp56kEmu/libdsp56kEmu.a dsp56kBase/libdsp56kBase.a asmjit/libasmjit.a vtuneSdk/libvtuneSdk.a; do libs="$libs $B/$l"; done
gcc -O1 -g -fPIC -std=gnu11 -I"$W/src/vst/build" -I"$MV/wrapper" -c "$MV/wrapper/vst2_wrap.c" -o "$W/vst2_wrap.o"
g++ -shared -o "$W/plug/vavra.so" "$W/vst2_wrap.o" -Wl,--start-group $libs -Wl,--end-group -lpthread -lm -ldl
g++ -O1 -g -std=c++17 -o "$W/dump" tests/legacy_dump.cpp -ldl -lpthread
at() { grep -n -x "$1" params.lock | cut -d: -f1 | awk '{print $1 - 1}'; }
"$W/dump" "$W/plug/vavra.so" tests/data/legacy-0.1.0.chunk "$(at F1Cutoff)" "$(at gain)"
