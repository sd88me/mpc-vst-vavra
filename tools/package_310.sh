#!/usr/bin/env bash
# The plugin folder in the MPC OS plugin folder format (no MPC.settings entry, no root): copy the folder into "VST2 Plugins" at the root
# of a drive, turn on Preferences > Enhancements (Beta) > Enable Enhancements and VST2 Support, and it is listed under External VST
# Plugins. Format: the MPC plugin SDK's docs/plugin-folder-format.md (plugin.json, VST/<slug>-arm64.so, Plugin Skins/, version.xml).
#   tools/package_310.sh <version>     -> dist/VST2 Plugins/sd88me - VST - Vavra/ and dist/Vavra-<version>-VST2-Plugins.zip
# Run ./build.sh all first. Gen2 (arm64) only: the emulator's JIT has no 32-bit ARM backend, so there is no file32.
set -euo pipefail
cd "$(dirname "$0")/.."
VER="${1:?usage: tools/package_310.sh <version>}"
NAME="sd88me - VST - Vavra"
OUT="dist/VST2 Plugins/$NAME"
rm -rf "dist/VST2 Plugins"; mkdir -p "$OUT/VST"
cp -r "vst/build/skin/$NAME/." "$OUT/"
cp vst/build/aarch64/vavra.so "$OUT/VST/vavra-arm64.so"
cp -r release/vavra "$OUT/VST/vavra"           # the engine's data dir is <dir of the .so>/vavra (roms/, banks/)
cp LICENSE CREDITS.md "$OUT/"
cat > "$OUT/plugin.json" <<JSON
{
  "name": "Vavra",
  "manufacturer": "sd88me",
  "version": "$VER",
  "kind": "instrument",
  "uid": "VavQ",
  "category": "Synth",
  "numInputs": 0,
  "numOutputs": 2,
  "file64": "VST/vavra-arm64.so",
  "description": "Waldorf microQ emulation (gearmulator Vavra). Needs your own microQ ROM in VST/vavra/roms/.",
  "license": "GPL-3.0-only",
  "url": "https://github.com/sd88me/mpc-vst-vavra"
}
JSON
if find "$OUT" -iname "*.mid" -o -iname "*.bin" -o -iname "*.syx" -o -iname "*.dat" | grep -q .; then echo "refusing: a ROM-like file is in the folder" >&2; exit 1; fi
(cd dist && rm -f "Vavra-$VER-VST2-Plugins.zip" && python3 -m zipfile -c "Vavra-$VER-VST2-Plugins.zip" "VST2 Plugins")
echo "ok: $OUT, dist/Vavra-$VER-VST2-Plugins.zip"
