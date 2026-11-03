# Vendored source

- `gearmulator/` (framework/{baseLib,synthLib,hardwareLib}, 3rdparty/libresample, cpu/mc68k, cpu/dsp56300/{dsp56kBase,dsp56kEmu,asmjit,vtuneSdk},
  waldi/common/wLib, waldi/microq/mqLib): from https://github.com/charlesvestal/gearmulator commit `69981792efa44114aaafda91bed69faa4c96fc64`
  (a snapshot of dsp56300/gearmulator, "bump version to .20", the same snapshot as Xenia for MPC), with its submodules `source/cpu/dsp56300` at
  `848923e5f6faa481405d034072715a589e6b3326` (asmjit `3577608cab0bc509f856ebf6e41b2f9d9f71acc4`) and `source/cpu/mc68k` at
  `c0766a6b88f9bf6d3feae44fb0ec3da5b637065c`. GPL-3.0, unmodified. Only the microQ subset is vendored ("mqLib" is gearmulator's Vavra): no JUCE,
  no editor, no other synth. The layout is gearmulator's own, so a re-vendor is a plain copy.
- `skin/parameterDescriptions_mq.json`: gearmulator's `source/waldi/microq/mqJucePlugin/parameterDescriptions_mq.json` (the microQ parameter table
  the Vavra editor is built from, with its "singledump" packet that gives the bit fields), unmodified. `tools/gen_params.py` reads it.
- `skin/mqDefault/`: two images of the "mqDefault" skin of gearmulator's Vavra plugin (theusualsuspects): `mqDefaultBG.png` and
  `encoder_ranged_page0.png`, unmodified (see CREDITS.md). `tools/make_assets.py` cuts the background, logo, knob strip and tile from them.
- `src/dsp/fast_cores.h`: mpc-vst-plugins `wrapper/fast_cores.h`, copied 2026-11-03.
- `src/dsp/vavra_engine.cpp`: ours. It drives `mqLib::Device` through `synthLib::Plugin` on a thread of MPC's own process.
