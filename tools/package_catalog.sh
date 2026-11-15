#!/usr/bin/env bash
# The release zips, from the release build (build/sdk/"sd88me - VST - Vavra", made by ./build-sdk.sh):
#   dist/Vavra-<ver>-mpc-aarch64.zip   install.sh / uninstall.sh (MPC.settings) for 64-bit MPCs, made by mpc-vst-plugins' tools/release.py;
#                                      it upgrades a 0.1.0 install in place
#   dist/Vavra-<ver>-mpc-sdk.zip       the plugin folder for "VST2 Plugins" (tools/sdk_zip.py)
#   dist/Vavra-<ver>-SHA256SUMS.txt
# As in 0.1.0 the .so is vavra.so at the folder root (plugin.json names it, so the plugin finds its folder and vavra/ beside it).
# User data, kept on upgrade and uninstall: vavra/roms (your ROM), vavra/banks (your sound sets), vavra/favourites.dat, vavra/sounds.dat
# (the ROM's sound names, read once), vavra-skin.txt (microQ / Dark Blue / Phoenix). No ROM or sound set is ever packed.
# MPC_VST: mpc-vst-plugins with tools/release.py and tools/sdk_zip.py.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
MPC_VST="${MPC_VST:-$HOME/mpc-vst-plugins-postlaunch}"
[ -f "$MPC_VST/tools/release.py" ] && [ -f "$MPC_VST/tools/sdk_zip.py" ] || { echo "need mpc-vst-plugins with tools/sdk_zip.py (MPC_VST)" >&2; exit 1; }
DIR="sd88me - VST - Vavra"; SRC="$here/build/sdk/$DIR"
[ -f "$SRC/VST/vavra-arm64.so" ] || { echo "missing $SRC: run ./build-sdk.sh first" >&2; exit 1; }
VER=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$SRC/plugin.json")
python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); sys.exit(0 if m["uid"]=="VavQ" and "Beta" not in m["name"] else "not the release identity")' "$SRC/plugin.json"
out="$here/dist"; mkdir -p "$out"
st="$here/build/catalog/aarch64"; rm -rf "$st"; mkdir -p "$st/$DIR" "$st/extra"
cp -r "$SRC/Plugin Skins" "$SRC/version.xml" "$st/$DIR/"
python3 - "$SRC/plugin.json" "$st/$DIR/plugin.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
m.pop("file32", None)
m["file64"] = "vavra.so"
json.dump(m, open(sys.argv[2], "w"), indent=2)
PY
cp "$SRC/VST/vavra-arm64.so" "$st/vavra.so"
cp -r "$here/release/vavra/." "$st/extra/"; cp "$here/LICENSE" "$here/CREDITS.md" "$st/extra/"
# nothing of the user's may ride along: only the placeholders
if find "$st" -type f | grep -v -E 'PUT_(MICROQ_ROM|SOUND_SETS)_HERE\.txt$' | grep -i -E '/(roms|banks)/|\.(bin|syx|mid)$|favourites|skin\.txt|sounds\.dat'; then
  echo "refusing: user files in the package" >&2; exit 1
fi
printf '<PLUGIN name="Vavra" descriptiveName="Vavra" format="VST" category="Synth" manufacturer="sd88me" version="%s" file="vavra.so" uid="56617651" isInstrument="1" fileTime="0" infoUpdateTime="0" numInputs="0" numOutputs="2" isShell="0"/>\n' "$VER" > "$st/entry.xml"
python3 "$MPC_VST/tools/release.py" --so "$st/vavra.so" --skin "$st/$DIR" --entry "$st/entry.xml" --version "$VER" --extra "$st/extra:vavra" \
  --user-data vavra/roms --user-data vavra/banks --user-data vavra/favourites.dat --user-data vavra/sounds.dat --user-data vavra-skin.txt \
  --user-files "$here/release/userfiles.json" \
  --repo sd88me/mpc-vst-vavra --license GPL-3.0-only --id vavra \
  --requires "64-bit MPC (Live III and others) and your own microQ ROM" \
  --about "Waldorf microQ emulation with a native MPC panel in three skins, 300 ROM sounds plus your own sound sets, RANDOM and named favourites." \
  -o "$st/dist"
z=$(ls "$st/dist"/*.zip); cp "$z" "$out/Vavra-$VER-mpc-aarch64.zip"
python3 "$here/tools/scrub_zip.py" "$out/Vavra-$VER-mpc-aarch64.zip"
python3 "$MPC_VST/tools/catalog_check.py" "$out/Vavra-$VER-mpc-aarch64.zip" --catalog --require-portable --expect-id vavra --expect-repo sd88me/mpc-vst-vavra
python3 "$MPC_VST/tools/sdk_zip.py" "$out/Vavra-$VER-mpc-sdk.zip" "$out/Vavra-$VER-mpc-aarch64.zip"
for f in "$out/Vavra-$VER-mpc-aarch64.zip" "$out/Vavra-$VER-mpc-sdk.zip"; do   # last guard: no ROM-like file in either zip
  if python3 -I -m zipfile -l "$f" | grep -i -E '\.(bin|syx|rom)\b|\.mid\b|sounds\.dat|favourites' | grep -v PUT_; then echo "refusing: a user or ROM-like file in $f" >&2; exit 1; fi
done
(cd "$out" && sha256sum "Vavra-$VER-mpc-aarch64.zip" "Vavra-$VER-mpc-sdk.zip" > "Vavra-$VER-SHA256SUMS.txt")
ls -la "$out"/Vavra-"$VER"-*
