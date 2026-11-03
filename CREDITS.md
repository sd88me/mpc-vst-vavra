# Credits and licences

Vavra for MPC stands on the work of others. Each licence applies to its own part; the plugin as a whole is **GPL-3.0** (`LICENSE`).

- **[gearmulator](https://github.com/dsp56300/gearmulator)** by Dieter Mueller (dsp56300) and contributors, **GPL-3.0**: the Waldorf microQ emulation
  (`mqLib`, `wLib`: the microQ's 68k firmware host and its DSP56362 voice DSP) and the support libraries (`synthLib`, `baseLib`, `hardwareLib`). "Vavra" is
  gearmulator's name for its microQ plugin. Vendored from the [charlesvestal/gearmulator](https://github.com/charlesvestal/gearmulator) snapshot that
  Xenia for MPC uses.
- **[dsp56300](https://github.com/dsp56300/dsp56300)** (the DSP56300 emulator and its JIT: `dsp56kEmu`, `dsp56kBase`) and **[mc68k](https://github.com/dsp56300/mc68k)**
  (on Musashi), **GPL-3.0**; **[AsmJit](https://github.com/asmjit/asmjit)**, **zlib**; **libresample**, BSD / LGPL.
- **The "mqDefault" skin of Vavra by theusualsuspects**, **GPL-3.0** (shipped with gearmulator): the ring background, the "Vavra" logo, the encoder
  filmstrip and the panel look (`skin/mqDefault/`), and gearmulator's microQ parameter table (`skin/parameterDescriptions_mq.json`).
- **Liberation Sans** (Red Hat / Google, **SIL OFL 1.1**) for the page text and live text (`vst/fonts/`).
- **[mpc-vst-plugins](https://github.com/open-mpc/mpc-vst-plugins)**: the plugin wrapper (`wrapper/vst2_wrap.c`), `fast_cores.h` and the skin tools.

Vavra for MPC is an independent project, not affiliated with or endorsed by Waldorf. "microQ" is the name of the instrument it emulates.
No ROM is included, and none may be shared.
