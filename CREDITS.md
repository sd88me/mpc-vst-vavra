# Credits and licences

Vavra for MPC stands on the work of others. Each licence applies to its own part; the plugin as a whole is **GPL-3.0** (`LICENSE`).

- **[gearmulator](https://github.com/dsp56300/gearmulator)** by Dieter Mueller (dsp56300) and contributors, **GPL-3.0**: the Waldorf microQ emulation
  (`mqLib`, `wLib`: the microQ's 68k firmware host and its DSP56362 voice DSP) and the support libraries (`synthLib`, `baseLib`, `hardwareLib`). "Vavra" is
  gearmulator's name for its microQ plugin. Vendored from the [charlesvestal/gearmulator](https://github.com/charlesvestal/gearmulator) snapshot that
  Xenia for MPC uses.
- **[dsp56300](https://github.com/dsp56300/dsp56300)** (the DSP56300 emulator and its JIT: `dsp56kEmu`, `dsp56kBase`) and **[mc68k](https://github.com/dsp56300/mc68k)**
  (on Musashi), **GPL-3.0**; **[AsmJit](https://github.com/asmjit/asmjit)**, **zlib**; **libresample**, BSD / LGPL.
- **The "mqDefault" skin of Vavra by theusualsuspects**, **GPL-3.0** (shipped with gearmulator): the "Vavra" script of its logo (`skin/parts/logo.png`,
  recoloured per skin on MAIN), and gearmulator's microQ parameter table (`skin/parameterDescriptions_mq.json`). The rest of the screen is drawn by
  `tools/vavra_art.py`.
- **Titillium Web** (Accademia di Belle Arti di Urbino, **SIL OFL 1.1**, `tools/fonts/`) for the screen's text.
- **Akai's MPC Plugin SDK** (**MIT**): the plugin framework. **[mpc-vst-plugins](https://github.com/sd88me/mpc-vst-plugins)**: `fast_cores.h`, the engine
  interface (`wrapper/engine.h`) and the release tools.

Vavra for MPC is an independent project, not affiliated with or endorsed by Waldorf. "microQ" is the name of the instrument it emulates.
No ROM is included, and none may be shared.
